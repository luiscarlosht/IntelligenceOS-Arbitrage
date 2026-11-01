"""Read-only frozen-cohort reporting and idempotent sanitized result import."""
import json
import fcntl
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app import m66_experiments, m66_discovery
from app.m65_intelligence import US, CONDITION, STATES, read_json
from app.m67_state import ReadOnlyStore, ledger_snapshot, secure
from app.observations import fingerprint
from app.m66_verification import verification_rows, verify


@contextmanager
def quiescent(ledger_path: Path):
    """Use an existing lock only; never create a real execution reservation."""
    path = ledger_path.parent/'candidate-execution.lock'
    fd = None
    try:
        if path.exists():
            secure(path)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield
    finally:
        if fd is not None:
            os.close(fd)


def records(snapshot: dict, digest: str) -> list[dict]:
    result = []
    for attempt in snapshot['attempts']:
        if attempt['digest'] != digest or attempt['kind'] != 'restrictions':
            continue
        row = snapshot['outcomes'].get(attempt['id'])
        # A committed dispatch slot without a response is uncertain, never retried.
        result.append(dict(asin=attempt['asin'], operation_status=row['operation_status'] if row else 'UNCERTAIN',
            api_state=row['api_state'] if row else 'UNKNOWN',
            observed_at=row['observed_at'] if row else attempt['observed_at'],
            source_sha256=fingerprint(dict(attempt=attempt, outcome=row))))
    return result


def validate_snapshot(snapshot: dict, manifest: dict, digest: str) -> None:
    inner = manifest['restrictions_proposal']
    if (manifest.get('mode') != 'M66_ELIGIBILITY_REVIEW_ONLY' or inner.get('marketplace_id') != US
            or inner.get('condition') != CONDITION or not 1 <= len(inner['asins']) <= 20):
        raise ValueError('Frozen US/New cohort required')
    if digest in snapshot['batches'] and snapshot['batch_scope_sha256'].get(digest) != fingerprint(inner):
        raise ValueError('Global reservation differs from frozen cohort')
    attempts = [r for r in snapshot['attempts'] if r['digest'] == digest]
    if attempts and digest not in snapshot['batches']:
        raise ValueError('Missing immutable global reservation')
    restrictions = [r['asin'] for r in attempts if r['kind']=='restrictions']
    if (len(attempts) > inner['budget']['maximum_requests'] or restrictions != inner['asins'][:len(restrictions)]
            or any(r['kind'] not in ('authentication','restrictions') for r in attempts)
            or sum(r['kind']=='authentication' for r in attempts)>1):
        raise ValueError('Corrupt request accounting')


class ReportView:
    def __init__(self, store, rows):
        self.store, self.rows, self.db = store, rows, store.db

    def events(self, kind=None):
        events = self.store.events(kind)
        if kind in (None, 'eligibility'):
            events += [dict(asin=r['asin'],marketplace=US,condition=CONDITION,observed_at=r['observed_at'],
                operation_status=r['operation_status'],eligibility=r['api_state'],
                source_reference='sha256:'+r['source_sha256']) for r in self.rows]
        return events


def report(path: Path, digest: str, store_path: Path, ledger_path: Path) -> dict:
    with quiescent(ledger_path):
        return _report(path, digest, store_path, ledger_path)


def _report(path: Path, digest: str, store_path: Path, ledger_path: Path) -> dict:
    snapshot = ledger_snapshot(ledger_path)
    manifest, actual = read_json(path)
    if actual != digest:
        raise ValueError('Frozen manifest digest mismatch')
    validate_snapshot(snapshot, manifest, digest)
    store = ReadOnlyStore(store_path)
    try:
        view = ReportView(store, records(snapshot,digest))
        result = m66_experiments.load(path, digest, view)
        api = view.events('eligibility')
        for (payload,) in store.db.execute('SELECT payload FROM m66_results WHERE digest=?', (digest,)):
            saved = json.loads(payload)
            api.append(dict(saved,eligibility=saved['api_state'],source_reference='sha256:'+saved['source_sha256']))
        manual = verification_rows(store)
        now = datetime.now(timezone.utc)
        for row in result['rows']:
            separate = verify(row['asin'],api,manual,as_of=now)
            row.update(seller_central_states=separate['seller_central_states'],fba_state=separate['fba_state'],
                seller_verification_conflict_requires_review=separate['conflict_requires_review'],
                fba_conflict_requires_review=separate['fba_conflict_requires_review'],
                listing_review_gate_complete=separate['listing_review_gate_complete'])
        attempts = [r for r in snapshot['attempts'] if r['digest'] == digest]
        result['request_accounting'] = dict(authentication=sum(r['kind']=='authentication' for r in attempts),
            restrictions=sum(r['kind']=='restrictions' for r in attempts), total=len(attempts),
            uncertain_response_records=sum(r['id'] not in snapshot['outcomes'] for r in attempts),
            retries=0, meaning='Durably consumed dispatch slots; a crash may precede actual transport')
        succeeded = sum(snapshot['outcomes'].get(r['id'],{}).get('operation_status')=='SUCCEEDED' for r in attempts)
        result['request_accounting'].update(successful_requests=succeeded,failed_or_uncertain_requests=len(attempts)-succeeded,
                                           reviewed_budget=manifest['restrictions_proposal']['budget'])
        return result
    finally:
        store.db.close()


def import_results(path: Path, digest: str, store, ledger_path: Path) -> dict:
    """Offline: never reserves attempts or fabricates missing local proof."""
    with quiescent(ledger_path):
        return _import_results(path, digest, store, ledger_path)


def _import_results(path: Path, digest: str, store, ledger_path: Path) -> dict:
    manifest, actual = read_json(path)
    if actual != digest:
        raise ValueError('Frozen manifest digest mismatch')
    ranking, _ = read_json(path.parent/'M66_candidate_ranking.json')
    if fingerprint(ranking) != manifest['restrictions_proposal']['ranking_sha256']:
        raise ValueError('Frozen ranking digest mismatch')
    labels = {r['asin']:r for r in ranking['rows']}
    snapshot = ledger_snapshot(ledger_path)
    validate_snapshot(snapshot, manifest, digest)
    rows = records(snapshot, digest)
    imported = duplicate = unreconciled = 0
    for row in rows:
        if row['asin'] not in manifest['restrictions_proposal']['asins'] or row['api_state'] not in STATES:
            raise ValueError('Result outside frozen scope')
        old = store.db.execute('SELECT payload FROM m66_results WHERE digest=? AND asin=?', (digest,row['asin'])).fetchone()
        if old:
            saved = json.loads(old[0])
            if any(saved[k] != row[k] for k in ('operation_status','api_state','source_sha256','observed_at')):
                raise ValueError('Immutable result conflict; manual review required')
            duplicate += 1
        elif not store.db.execute('SELECT 1 FROM request_attempts WHERE request_id=? AND digest=? AND kind=?',
                (digest+':'+row['asin'],digest,'restrictions')).fetchone():
            unreconciled += 1
            continue
        else:
            m66_discovery.record_result(store,digest,row['asin'],row['operation_status'],row['api_state'],
                                       row['source_sha256'],row['observed_at'])
            imported += 1
        # Populate M65's independent API-evidence projection as well. A crash
        # between inserts is recoverable by this idempotent offline import.
        store.append([dict(kind='eligibility',asin=row['asin'],marketplace=US,condition=CONDITION,
            observed_at=row['observed_at'],operation_status=row['operation_status'],eligibility=row['api_state'],
            reason_codes=[],brand=labels[row['asin']]['brand'],category=labels[row['asin']]['category'],
            brand_approval_requirement=None,fba_eligibility=None,purchase_authorized=False,
            source_reference='sha256:'+row['source_sha256']+':row:0',source_sha256=row['source_sha256'])])
    return dict(imported=imported,duplicates=duplicate,missing_local_attempt_proof=unreconciled,
                additional_requests=0)
