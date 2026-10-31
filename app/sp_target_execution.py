"""Future explicit catalog-only runner using existing SP-API transport/pacing/ledger."""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import time

from app import amazon_pilot as pilot
from app.amazon_diagnostics import failure_metadata
from app.amazon_pacing import OperationPacer
from app.observations import canonical, fingerprint, normalized
from app.sp_catalog_targets import (aggregate_targets, audit_saved, parse_target_item,
                                   read_report, select_targets)
from app.sp_api_targets import make_plan


def run_prepared(manifest_path, expected_sha256, maximum, *, transport=None,
                 credential_loader=None, private_path=pilot.DIRECTORY,
                 sleep=time.sleep, monotonic=time.monotonic):
    """Only an explicit future CLI invocation may reach credentials or transport.

    Every HTTP attempt is durable before I/O. No retry, paid provider, enrichment,
    pagination or default orchestration registration. Existing claims are never released.
    """
    plan, digest = read_report(manifest_path)
    if digest != expected_sha256 or type(maximum) is not int or maximum != 11:
        raise ValueError('Reviewed hash and exact eleven-request ceiling required')
    if Path(plan.get('evidence_directory', '')).resolve() != Path(private_path).resolve():
        raise ValueError('Shared private evidence/ledger directory required')
    snapshots, audit = audit_saved(private_path)
    seeds = select_targets(aggregate_targets(snapshots, now=datetime.now(timezone.utc)))
    if plan != normalized(make_plan(audit, seeds, evidence_directory=private_path)):
        raise ValueError('Manifest/evidence changed; prepare and review again')
    if len(seeds) >= 20:
        return dict(status='saved_target_cap_satisfied', selected_targets=20,
                    live_requests=0, authentication_attempts=0, credential_files_read=0)
    if transport is None:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    directory = pilot.private_directory(Path(private_path))
    lock = db = stream = None
    old_handler = None
    old_timer = None
    report = dict(schema_version=1, mode=plan['mode'], manifest=plan, is_mock=transport is not None,
        attempts=[], catalog_snapshots=[], status='reserved', live_requests=0,
        purchase_approved=False, selected_target_ids=[t.target_id for t in seeds])
    run_key = 'amazon-first:' + fingerprint(plan)
    name = 'amazon-first-catalog-' + fingerprint(plan) + '.json'
    try:
        lock = os.open('candidate-execution.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        lock_info = os.fstat(lock)
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_mode & 0o077 or lock_info.st_uid != os.getuid():
            raise ValueError('Private regular shared lock required')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = os.open('candidate-executions.sqlite3', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise ValueError('Private regular shared ledger required')
        finally:
            os.close(fd)
        db = sqlite3.connect(f'/proc/self/fd/{directory}/candidate-executions.sqlite3', timeout=5)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript('''CREATE TABLE IF NOT EXISTS candidate_executions (
            run_key TEXT PRIMARY KEY, manifest_sha256 TEXT NOT NULL, plan_sha256 TEXT NOT NULL,
            batch_id TEXT NOT NULL, batch_content_hash TEXT NOT NULL, status TEXT NOT NULL, checkpoint_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS candidate_operations (
            request_key TEXT PRIMARY KEY, run_key TEXT NOT NULL REFERENCES candidate_executions(run_key),
            kind TEXT NOT NULL, asin TEXT, state TEXT NOT NULL);''')
        with db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO candidate_executions VALUES (?,?,?,?,?,?,?)',
                (run_key, digest, fingerprint(plan), plan['mode'], fingerprint(plan['evidence_inventory']), 'reserved', canonical(report)))
            for spec in plan['requests']:
                db.execute('INSERT INTO candidate_operations VALUES (?,?,?,?,?)',
                    ('amazon-first-query:' + spec['query_id'], run_key, 'amazon_target_search', None, 'claimed_not_attempted'))
        stream = os.fdopen(pilot.create_file(directory, name), 'w')
        pacer = OperationPacer(state_path=f'/proc/self/fd/{directory}/candidate-executions.sqlite3',
                               sleep=sleep, monotonic=monotonic)
        end = monotonic() + 120
        old_handler = signal.signal(signal.SIGALRM, pilot.deadline)
        old_timer = signal.setitimer(signal.ITIMER_REAL, 120)

        def checkpoint():
            payload = canonical(report)
            with db:
                db.execute('UPDATE candidate_executions SET status=?,checkpoint_json=? WHERE run_key=?',
                           (report['status'], payload, run_key))
            stream.seek(0)
            stream.truncate()
            stream.write(payload + '\n')
            stream.flush()
            os.fsync(stream.fileno())

        def call(request, kind, query_id=None):
            if len(report['attempts']) >= maximum:
                raise ValueError('Attempt ceiling reached')
            operation = 'searchCatalogItems' if kind == 'search' else None
            # An existing extended cooldown defers the stage; no refill/cooldown retry loop.
            if pacer.not_before.get(operation, 0) - monotonic() > 2:
                raise ValueError('Existing quota cooldown; no request')
            key = 'amazon-first-query:' + query_id if query_id else run_key + ':authentication'
            with db:
                if query_id:
                    updated = db.execute("UPDATE candidate_operations SET state='reserved' WHERE request_key=? AND run_key=? AND state='claimed_not_attempted'",
                                         (key, run_key)).rowcount
                    if updated != 1:
                        raise ValueError('Operation already attempted')
                else:
                    db.execute('INSERT INTO candidate_operations VALUES (?,?,?,?,?)',
                               (key, run_key, 'authentication', None, 'reserved'))
            report['attempts'].append(dict(kind=kind, query_id=query_id, status='reserved'))
            report['live_requests'] = 0 if report['is_mock'] else len(report['attempts'])
            checkpoint()
            reply = pacer.call(request, transport or pilot._request_json, deadline=end)
            with db:
                db.execute("UPDATE candidate_operations SET state='response_received' WHERE request_key=?", (key,))
            report['attempts'][-1]['status'] = 'response_received'
            metadata = getattr(reply, 'pacing', {})
            report['attempts'][-1]['pacing'] = metadata
            report['stop_after_response'] = metadata.get('retry_after_seconds') is not None
            checkpoint()
            return reply

        checkpoint()
        if pacer.not_before.get('searchCatalogItems', 0) - monotonic() > 2:
            raise ValueError('Existing quota cooldown; credentials not loaded')
        credentials = (credential_loader or pilot.load_credentials)(directory)
        access = pilot.exchange_token(credentials, lambda request: call(request, 'authentication'))
        secrets = (*credentials.values(), access)
        for spec in plan['requests']:
            if len(report['selected_target_ids']) >= 20 or report.get('stop_after_response'):
                break
            reply = call(pilot.amazon_request(access, spec['path'], spec['params']), 'search', spec['query_id'])
            items = reply.get('items')
            count = reply.get('numberOfResults')
            if (reply.get('errors') or not isinstance(items, list) or len(items) > 2
                    or type(count) is not int or count < len(items)):
                raise ValueError('Invalid bounded search response')
            report['attempts'][-1].update(returned_items=len(items),
                more_results=bool(reply.get('pagination', {}).get('nextToken')) or count > len(items))
            observed_at = datetime.now(timezone.utc)
            for item in items:
                snapshot = parse_target_item(item, observed_at=observed_at,
                    provenance=name + ':query=' + spec['query_id'], is_mock=report['is_mock'], secrets=secrets)
                snapshot['query_id'] = spec['query_id']
                report['catalog_snapshots'].append(snapshot)
            combined = aggregate_targets(snapshots + report['catalog_snapshots'], now=datetime.now(timezone.utc))
            report['selected_target_ids'] = [t.target_id for t in select_targets(combined)]
            checkpoint()
        report['status'] = 'stopped_retry_after' if report.get('stop_after_response') else 'completed_bounded'
        checkpoint()
        return dict(status=report['status'], selected_targets=len(report['selected_target_ids']),
                    live_requests=report['live_requests'], attempts=len(report['attempts']), report=name)
    except BaseException as error:
        report['status'] = 'stopped_no_retry'
        report['failure'] = failure_metadata(error)
        if db is not None and stream is not None:
            payload = canonical(report)
            with db:
                db.execute('UPDATE candidate_executions SET status=?,checkpoint_json=? WHERE run_key=?',
                           (report['status'], payload, run_key))
            stream.seek(0)
            stream.truncate()
            stream.write(payload + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        raise
    finally:
        if old_handler is not None:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
            if old_timer and old_timer[0]:
                signal.setitimer(signal.ITIMER_REAL, *old_timer)
        for handle in (stream, db):
            if handle is not None:
                handle.close()
        if lock is not None:
            os.close(lock)
        os.close(directory)
