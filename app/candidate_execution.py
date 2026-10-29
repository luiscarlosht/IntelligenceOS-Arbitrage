"""Stored-source mode for the candidate stage: validated, missing catalog details only."""
import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import os
from pathlib import Path
import signal
import sqlite3
import stat
import time

from app import amazon_pilot as pilot
from app.models import Match
from app.normalization import timestamp
from app.observations import canonical, fingerprint, normalized
from app.sheets_candidate_plan import audit_database, compatible_search, plan, read_json, MARKETPLACE

DETAIL_DATA = 'summaries,identifiers,relationships,attributes'


def prepare_details(database, reviewed_plan):
    """Validate unchanged original preview; build a separate execution authorization manifest."""
    reviewed, plan_sha = read_json(reviewed_plan)
    if (reviewed.get('schema') != 1 or reviewed.get('action') != 'offline_stored_batch_candidate_plan'
            or reviewed.get('live_requests') != 0 or reviewed.get('execution_authorized') is not False):
        raise ValueError('Original offline candidate preview required')
    batch_id = reviewed['audit']['batch_id']
    audit, original_rows, products = audit_database(database, batch_id)
    if audit['batch_content_hash'] != reviewed['audit']['batch_content_hash']:
        raise ValueError('Batch content differs from reviewed source')
    selections = {r['walmart_item_id']: dict(asin=r['candidate_asin'], reason=r['selection_reason'],
                  previous_selection_disposition=r['previous_selection_disposition']) for r in reviewed['rows']}
    reports = sorted({r['search_reuse']['report'] for r in reviewed['rows']} |
                     {d['report'] for r in reviewed['rows'] for d in r['catalog_detail_reuse']})
    expected = plan(database, batch_id, reports, selections, evaluated_at=timestamp(reviewed['evaluated_at']))
    for field in ('rows', 'requests', 'budget', 'selections_sha256', 'reused_searches'):
        if expected[field] != reviewed[field]:
            raise ValueError('Reviewed plan/source/evidence mismatch')
    cache = {str(p): read_json(p)[0] for p in reports}
    rows = []
    for ordinal, (original, product, reviewed_row) in enumerate(zip(original_rows, products, reviewed['rows']), 1):
        saved = compatible_search(cache[reviewed_row['search_reuse']['report']], original, product)
        if not saved:
            raise ValueError('Saved search binding missing')
        original_search = deepcopy(saved['search'])
        search = deepcopy(original_search)
        search['selected_asin'] = reviewed_row['candidate_asin']
        search['selection_origin'] = 'explicit_reviewed_plan; historical search unchanged in original_search'
        rows.append(dict(ordinal=ordinal, record_id=original['record_id'], batch_id=batch_id,
            source_fingerprint=fingerprint(product), original_intake_row=original, source=normalized(product),
            original_search=original_search, search=search, search_reuse=reviewed_row['search_reuse'],
            candidate_asin=reviewed_row['candidate_asin'], selection_reason=reviewed_row['selection_reason'],
            catalog_detail_reuse=reviewed_row['catalog_detail_reuse']))
    requests = []
    for request in expected['requests']:
        asin = request['asin']
        scope = dict(kind='catalog_detail', marketplace_id=MARKETPLACE, asin=asin, included_data=DETAIL_DATA)
        requests.append(dict(**request, request_key=fingerprint(scope)))
    run_key = fingerprint(dict(batch_content_hash=audit['batch_content_hash'],
        bindings=[(r['record_id'], r['source_fingerprint'], r['candidate_asin']) for r in rows],
        marketplace_id=MARKETPLACE, included_data=DETAIL_DATA))
    count = len(requests)
    return dict(schema=1, mode='stored_missing_catalog_details', database=str(Path(database)),
        reviewed_plan=str(Path(reviewed_plan)), reviewed_plan_sha256=plan_sha, batch_id=batch_id,
        batch_content_hash=audit['batch_content_hash'], run_key=run_key, rows=rows, requests=requests,
        source=str(Path(database)), limits=dict(authentication=1 if count else 0, search=0, detail=count,
            total=count+(1 if count else 0)), retries=0, pagination=False,
        pricing=False, fees=False, restrictions=False, deadline_seconds=300,
        minimum_interval_seconds=0.5, live_requests=0, execution_authorized=False)


class ExecutionJournal:
    """Durable run/operation claims; SQL checkpoints remain authoritative after a crash."""
    def __init__(self, directory, manifest, manifest_sha, report):
        self.directory, self.report, self.run_key = directory, report, manifest['run_key']
        fd = os.open('candidate-executions.sqlite3', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_nlink != 1):
                raise ValueError('Private execution ledger required')
        finally:
            os.close(fd)
        self.db = sqlite3.connect(f'/proc/self/fd/{directory}/candidate-executions.sqlite3', timeout=5)
        self.stream = self.report_file = None
        try:
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS candidate_executions (
                  run_key TEXT PRIMARY KEY, manifest_sha256 TEXT NOT NULL, plan_sha256 TEXT NOT NULL,
                  batch_id TEXT NOT NULL, batch_content_hash TEXT NOT NULL, status TEXT NOT NULL,
                  checkpoint_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS candidate_operations (
                  request_key TEXT PRIMARY KEY, run_key TEXT NOT NULL REFERENCES candidate_executions(run_key),
                  kind TEXT NOT NULL, asin TEXT, state TEXT NOT NULL);
            ''')
            # All target operations are claimed together BEFORE credentials or HTTP.
            # Changing output names, plan paths/times or source batch cannot bypass an ASIN claim.
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                self.db.execute('INSERT INTO candidate_executions VALUES (?,?,?,?,?,?,?)',
                    (self.run_key, manifest_sha, manifest['reviewed_plan_sha256'], manifest['batch_id'],
                     manifest['batch_content_hash'], report['status'], canonical(report)))
                for request in manifest['requests']:
                    self.db.execute('INSERT INTO candidate_operations VALUES (?,?,?,?,?)',
                        (request['request_key'], self.run_key, 'detail', request['asin'], 'claimed_not_attempted'))
            stem = 'candidate-details-'+self.run_key
            self.report_file = os.fdopen(pilot.create_file(directory, stem+'.json'), 'w')
            self.stream = os.fdopen(pilot.create_file(directory, stem+'.checkpoints.jsonl'), 'w')
            os.fsync(directory)
            self.checkpoint()
        except BaseException:
            self.close()
            raise

    def checkpoint(self):
        body = canonical(self.report)
        with self.db:
            self.db.execute('UPDATE candidate_executions SET status=?,checkpoint_json=? WHERE run_key=?',
                            (self.report['status'], body, self.run_key))
        # SQL snapshot is committed before either presentation can be interrupted.
        self.report_file.seek(0); self.report_file.write(body+'\n'); self.report_file.truncate()
        self.report_file.flush(); os.fsync(self.report_file.fileno())
        self.stream.write(body+'\n'); self.stream.flush(); os.fsync(self.stream.fileno())

    def reserve(self, kind, asin, key, limits):
        attempts = self.report['attempts']
        if kind not in ('authentication', 'detail') or len(attempts) >= limits['total']:
            raise ValueError('Candidate attempt ceiling reached')
        if sum(a['kind'] == kind for a in attempts) >= limits[kind]:
            raise ValueError('Candidate operation ceiling reached')
        attempt = dict(kind=kind, asin=asin, request_key=key, status='reserved',
                       reserved_at=normalized(datetime.now(timezone.utc)))
        attempts.append(attempt)
        self.report['live_requests'] = 0 if self.report['is_mock'] else len(attempts)
        with self.db:
            if kind == 'authentication':
                self.db.execute('INSERT INTO candidate_operations VALUES (?,?,?,?,?)',
                                (key, self.run_key, kind, None, 'reserved'))
            else:
                changed = self.db.execute('''UPDATE candidate_operations SET state='reserved'
                    WHERE request_key=? AND run_key=? AND state='claimed_not_attempted' ''',
                    (key, self.run_key)).rowcount
                if changed != 1:
                    raise ValueError('Catalog operation already reserved or attempted')
            self.db.execute('UPDATE candidate_executions SET checkpoint_json=? WHERE run_key=?',
                            (canonical(self.report), self.run_key))
        self.checkpoint()  # Durable consumed attempt before I/O, including uncertain outcomes.

    def received(self, key):
        self.report['attempts'][-1]['status'] = 'response_received'
        with self.db:
            self.db.execute("UPDATE candidate_operations SET state='response_received' WHERE request_key=?", (key,))
        self.checkpoint()

    def close(self):
        for stream in (self.stream, self.report_file):
            if stream is not None:
                stream.close()
        self.db.close()


def execute_details(manifest_path, expected_sha256, max_attempts, private_path=pilot.DIRECTORY, *,
                    transport=None, credential_loader=None, is_mock=False,
                    sleep=time.sleep, monotonic=time.monotonic):
    """Generic stored-batch entrypoint; same transport/parser/persistence as CSV candidate runs."""
    from app import amazon_candidates as candidates
    manifest, digest = read_json(manifest_path)
    if digest != expected_sha256 or manifest.get('mode') != 'stored_missing_catalog_details':
        raise ValueError('Execution manifest hash/mode mismatch')
    expected = prepare_details(Path(manifest['database']), Path(manifest['reviewed_plan']))
    if manifest != expected:
        raise ValueError('Execution manifest no longer matches reviewed evidence/source')
    if type(max_attempts) is not int or not 0 <= manifest['limits']['total'] <= max_attempts <= 1001:
        raise ValueError('Explicit HTTP attempt cap exceeded')
    _, _, products = audit_database(manifest['database'], manifest['batch_id'])
    now = datetime.now(timezone.utc)
    results = [dict(**deepcopy(r), status='not_attempted', exact=False, detail=None,
                    reasons=['Missing catalog detail not attempted']) for r in manifest['rows']]
    report = dict(label=candidates.LABEL, manifest=manifest, manifest_sha256=digest,
                  reviewed_plan_sha256=manifest['reviewed_plan_sha256'], run_key=manifest['run_key'],
                  batch_id=manifest['batch_id'], batch_content_hash=manifest['batch_content_hash'],
                  rows=results, attempts=[], live_requests=0, is_mock=is_mock,
                  status='reserved', purchase_approved=False)
    matches = [Match(None, False, Decimal('0'), ('Candidate identity unverified',)) for _ in results]
    directory = pilot.private_directory(private_path)
    journal = None
    start, last = monotonic(), None
    try:
        journal = ExecutionJournal(directory, manifest, digest, report)
        def call(kind, asin, request, key):
            nonlocal last
            if last is not None:
                sleep(max(0, manifest['minimum_interval_seconds']-(monotonic()-last)))
            if monotonic()-start >= manifest['deadline_seconds']:
                raise TimeoutError('Candidate deadline')
            journal.reserve(kind, asin, key, manifest['limits'])
            last = monotonic()
            value = (transport or pilot.request_json)(request)
            if not isinstance(value, dict):
                raise ValueError('Candidate response object required')
            journal.received(key)
            return value
        try:
            # Reused evidence is copied as-is and never assigned a new observation time.
            for row in results:
                if row['catalog_detail_reuse']:
                    row['detail'] = deepcopy(row['catalog_detail_reuse'][0]['evidence'])
                    if row['detail']['is_mock'] is not is_mock:
                        raise ValueError('Mixed catalog mock/live evidence')
                    row.update(status='candidate_unverified', detail_origin='reused_saved_catalog',
                               reasons=['Historical catalog retained; independent identity still unverified'])
            journal.checkpoint()
            if manifest['requests']:
                credentials = (credential_loader or pilot.load_credentials)(directory)
                access = pilot.exchange_token(credentials, lambda req: call('authentication', None, req,
                    fingerprint(dict(run_key=manifest['run_key'], kind='authentication'))))
                secrets = (*credentials.values(), access)
                for request in manifest['requests']:
                    affected = [r for r in results if r['record_id'] in request['source_record_ids']]
                    for row in affected: row['status'] = 'detail_pending'
                    journal.checkpoint()
                    detail = candidates.detail_evidence(call('detail', request['asin'], pilot.amazon_request(
                        access, request['path'], request['params']), request['request_key']),
                        request['asin'], is_mock=is_mock, secrets=secrets)
                    for row in affected:
                        row['detail'], row['detail_origin'] = normalized(detail), 'collected_missing_detail'
                        _, match = candidates.decide(products[row['ordinal']-1], row['search'], detail)
                        matches[row['ordinal']-1] = replace(match, exact=False, confidence=Decimal('0'))
                        row.update(status='candidate_unverified', exact=False,
                            reasons=list(dict.fromkeys((*match.reasons, 'Reviewed candidate only; no purchase approval'))))
                    journal.checkpoint()
            report['status'] = 'succeeded'
        except (Exception, KeyboardInterrupt):
            report['status'] = 'failed_no_retry'
            if report['attempts']:
                report['attempts'][-1]['status'] = 'failed_or_parser_rejected'
            for row in results:
                if row['status'] == 'detail_pending':
                    row.update(status='failed', reasons=['Catalog detail failed or interrupted; no retry'])
            # No exceptions, tokens, credentials or raw provider responses are serialized.
        finally:
            journal.checkpoint()
        # Existing per-run ObservationStore, history and workbook retain every outcome.
        # Run ledger and source database are separate; presentation failure never releases claims.
        report['presentation_status'] = 'pending'
        journal.checkpoint()
        try:
            candidates.persist(private_path, 'candidate-details-'+manifest['run_key'],
                               tuple(products), report, now, matches)
            report['presentation_status'] = 'succeeded'
        except BaseException:
            report['presentation_status'] = 'failed; durable SQL/checkpoint outcomes retained'
            raise
        finally:
            journal.checkpoint()
        return report
    finally:
        if journal is not None:
            journal.close()
        os.close(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare-details', 'run-details'))
    parser.add_argument('--database', type=Path)
    parser.add_argument('--reviewed-plan', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--max-attempts', type=int)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.action == 'prepare-details' and (args.execute or not args.database or not args.reviewed_plan):
        parser.error('Preparation requires local database and reviewed plan; no --execute')
    if args.action == 'run-details' and (not args.execute or not args.manifest_sha256 or args.max_attempts is None
                                       or args.database or args.reviewed_plan):
        parser.error('run-details requires --execute, --manifest-sha256 and --max-attempts')
    try:
        if args.action == 'prepare-details':
            manifest = prepare_details(args.database, args.reviewed_plan)
            fd = os.open(args.manifest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w') as output:
                output.write(canonical(manifest)+'\n')
            print(canonical(dict(manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
                                 source_rows=len(manifest['rows']), limits=manifest['limits'], live_requests=0)))
            return 0
        previous = signal.signal(signal.SIGALRM, pilot.deadline)
        try:
            signal.alarm(300)
            report = execute_details(args.manifest, args.manifest_sha256, args.max_attempts)
        finally:
            signal.alarm(0); signal.signal(signal.SIGALRM, previous)
        print(canonical(dict(status=report['status'], attempts=len(report['attempts']),
                             source_rows=len(report['rows']), purchase_approved=False)))
        return 0 if report['status'] == 'succeeded' else 1
    except (Exception, KeyboardInterrupt):
        print('Candidate execution stopped; no retry. Inspect the separate execution ledger/checkpoints.')
        return 1
