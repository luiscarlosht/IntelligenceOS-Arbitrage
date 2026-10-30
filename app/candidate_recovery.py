"""Hash-bound offline recovery preparation and explicit future execution."""
import argparse
import fcntl
import os
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import signal

from app import amazon_candidates as stage
from app.observations import canonical, fingerprint
from app.sheets_candidate_plan import audit_database, read_json
from app.stored_candidate_search import Reservations, sha


def prepare(proposal_path):
    proposal, _ = read_json(proposal_path)
    lock = Path(proposal['shared_ledger']).parent/'candidate-execution.lock'
    try:
        fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return _prepare(proposal_path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _prepare(proposal_path)
    finally:
        os.close(fd)


def _prepare(proposal_path):
    proposal, digest = read_json(proposal_path)
    parent, parent_sha = read_json(proposal['parent_manifest'])
    report_sha = sha(Path(proposal['original_report']))
    try:
        report, _ = read_json(proposal['original_report'])
    except json.JSONDecodeError:
        # A kill during presentation must not hide the authoritative SQL checkpoint.
        with closing(sqlite3.connect(Path(proposal['shared_ledger']).as_uri()+'?mode=ro', uri=True)) as db:
            row = db.execute('SELECT checkpoint_json FROM candidate_executions WHERE run_key=?',
                             (proposal['parent_run_key'],)).fetchone()
            if row is None:
                raise ValueError('Missing parent SQL checkpoint') from None
            report = json.loads(row[0])
    if (parent_sha != proposal['parent_manifest_sha256'] or report_sha != proposal['original_report_sha256']
            or report['manifest'] != parent or report['status'] not in ('failed_no_retry', 'succeeded', 'reserved')
            or parent['source_sha256'] != proposal['parent_run_key']
            or sha(Path(proposal['source_database'])) != proposal['source_database_sha256']):
        raise ValueError('Recovery parent/source binding changed')
    allowed = {Path(item['path']).resolve() for item in proposal['evidence']} | {Path(proposal['original_report']).resolve()}
    current = {p.resolve() for pattern in ('candidates-*.json', 'candidate-details-*.json')
               for p in Path(parent['private_directory']).glob(pattern)}
    if not current <= allowed:
        raise ValueError('New saved evidence requires a reviewed recovery proposal')
    for item in proposal['evidence']:
        if sha(Path(item['path'])) != item['sha256']:
            raise ValueError('Recovery evidence changed')
    sources = {}
    for binding in parent['batch_bindings']:
        audit, rows, products = audit_database(parent['source'], binding['batch_id'])
        if audit['batch_content_hash'] != binding['content_hash']:
            raise ValueError('Source batch changed')
        sources.update({r['record_id']: p for r, p in zip(rows, products)})
    requests, products = [], []
    ledger = Path(proposal['shared_ledger'])
    if ledger.resolve().parent != Path(parent['private_directory']).resolve():
        raise ValueError('Original shared ledger required')
    with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro', uri=True)) as db:
        parent_state = db.execute('SELECT status FROM candidate_executions WHERE run_key=?', (proposal['parent_run_key'],)).fetchone()
        if parent_state is None or parent_state[0] not in ('failed_no_retry', 'succeeded', 'reserved'):
            raise ValueError('Parent execution must be stopped')
        has_delegations = db.execute("SELECT 1 FROM sqlite_master WHERE name='candidate_delegations'").fetchone()
        for entry in proposal['requests']:
            spec = deepcopy(next(r for r in parent['requests'] if r['record_id'] == entry['record_id']))
            key = Reservations.search_key(spec)
            owner = db.execute('SELECT run_key,kind,state FROM candidate_operations WHERE request_key=?', (key,)).fetchone()
            delegate = db.execute('SELECT delegate_run_key FROM candidate_delegations WHERE request_key=?', (key,)).fetchone() if has_delegations else None
            if delegate and owner:
                owner = (delegate[0], *owner[1:])
            if (entry['search'] != spec['search'] or entry['detail'] != spec['detail']
                    or entry['existing_reservation']['request_key'] != key
                    or owner
                    != (proposal['parent_run_key'], 'search', 'claimed_not_attempted')):
                raise ValueError('Recovery must contain only original unattempted claims')
            if any(a.get('ordinal') == spec['ordinal'] for a in report['attempts']):
                raise ValueError('Attempted operation cannot be recovered')
            spec['original_ordinal'] = spec['ordinal']
            spec['ordinal'] = len(requests)+1
            requests.append(spec)
            products.append(sources[entry['record_id']])
    if not requests or len({r['record_id'] for r in requests}) != len(requests):
        raise ValueError('Distinct recovery records required')
    manifest = deepcopy(parent)
    manifest.update(mode='stored_candidate_recovery', requests=requests, evidence=proposal['evidence'],
        recovery=dict(proposal=str(Path(proposal_path).resolve()), proposal_sha256=digest,
                      parent_run_key=proposal['parent_run_key'], prior_not_before_utc=proposal['prior_not_before_utc']),
        limits=dict(authentication=1, search=len(requests), detail=len(requests), total=1+2*len(requests), retries=0))
    manifest['source_sha256'] = fingerprint(dict(parent=proposal['parent_run_key'], proposal_sha256=digest))
    return manifest, tuple(products)


def verify(path, digest, maximum):
    manifest, actual = read_json(path)
    if actual != digest or manifest.get('mode') != 'stored_candidate_recovery':
        raise ValueError('Recovery manifest hash/mode mismatch')
    expected, products = prepare(manifest['recovery']['proposal'])
    if manifest != expected or type(maximum) is not int or maximum != manifest['limits']['total']:
        raise ValueError('Recovery bindings or attempt cap mismatch')
    return manifest, products


def run(path, digest, maximum, **kwargs):
    from app.amazon_pacing import OperationPacer
    from app import amazon_pilot as pilot
    manifest, _ = verify(path, digest, maximum)
    pacer = OperationPacer(state_path=Path(manifest['private_directory'])/'candidate-executions.sqlite3',
                           **{k: kwargs[k] for k in ('sleep', 'monotonic') if k in kwargs})
    pacer.restore_cooldown('searchCatalogItems', manifest['recovery']['prior_not_before_utc'])
    transport = kwargs.pop('transport', None) or pilot._request_json
    deadline = pacer.monotonic()+manifest['deadline_seconds']
    return stage.execute(Path(manifest['source']), manifest, Path(manifest['private_directory']),
        source_binding=lambda: verify(path, digest, maximum), guard_factory=Reservations,
        transport=lambda request: pacer.call(request, transport, deadline=deadline), **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'check', 'run'))
    parser.add_argument('--proposal', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--expected-sha256')
    parser.add_argument('--max-attempts', type=int, default=37)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.execute != (args.action == 'run'):
        parser.error('Only run requires --execute')
    if args.action == 'prepare':
        manifest, _ = prepare(args.proposal)
        with args.manifest.open('x') as output:
            args.manifest.chmod(0o600)
            output.write(canonical(manifest)+'\n')
        print(json.dumps(dict(sha256=sha(args.manifest), records=len(manifest['requests']), limits=manifest['limits'])))
    elif args.action == 'check':
        verify(args.manifest, args.expected_sha256, args.max_attempts)
        print('offline_verified')
    else:
        from app import amazon_pilot as pilot
        previous = signal.signal(signal.SIGALRM, pilot.deadline)
        try:
            signal.alarm(300)
            result = run(args.manifest, args.expected_sha256, args.max_attempts)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
        print(result['status'])
        return int(result['status'] != 'succeeded')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
