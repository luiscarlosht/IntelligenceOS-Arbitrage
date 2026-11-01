"""Explicit, one-shot execution; only the CLI entry validates production inputs."""
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import signal
import time

from app import m65_batch
from app.m65_intelligence import US, CONDITION, classify, build_audit, read_json, sha256
from app.m66_verification import VerificationStore
from app.m67_policy import (preflight, authorize, private_json, CONTEXT, LEDGER,
                            not_expired)
from app.m67_state import Ledger, ReadOnlyStore, secure, stamp
from app.m67_transport import AmazonTransport
from app.observations import fingerprint


def outcome(operation='UNCERTAIN', state='UNKNOWN', status=None, codes=None, failure=None, source=None) -> dict:
    return dict(operation_status=operation, api_state=state, http_status=status, reason_codes=codes or [],
                failure=failure, observed_at=stamp(), source_sha256=source or fingerprint(dict(operation=operation,state=state,status=status,failure=failure)))


def run_reserved(store, ledger: Ledger, manifest: dict, digest: str, adapter,
                 *, before_request, pacer, deadline: float) -> dict:
    """Internal runner for an already-authorized reservation. Never resumes.

    Every invocation must come from a fresh atomic reserve in execute(). Tests
    inject only synthetic in-memory transports and temporary reservations.
    """
    current = None
    try:
        for kind, asin in [('authentication', None)]+[('restrictions', a) for a in manifest['asins']]:
            current = None
            before_request()
            if time.monotonic() >= deadline:
                raise TimeoutError
            operation = None if kind == 'authentication' else 'getListingsRestrictions'
            pacer.acquire(operation, deadline)
            dispatched = False
            response_status = None
            response_source = None
            def dispatch(req):
                nonlocal current, dispatched, response_status, response_source
                if dispatched:
                    raise ValueError('Second dispatch forbidden')
                before_request()
                adapter.validate(req, kind, asin)
                current = ledger.consume(digest, kind, asin)
                m65_batch.consume_attempt(store, digest, kind, asin)
                dispatched = True
                try:
                    reply = adapter.send(req, kind, asin)
                except BaseException as error:
                    from app.amazon_diagnostics import AmazonFailure
                    if isinstance(error, AmazonFailure):
                        pacer.observe(operation,error.http_status,getattr(error,'rate_headers',{}))
                    raise
                response_status = getattr(reply, 'http_status', None)
                headers = getattr(reply, 'rate_headers', {})
                pacer.observe(operation, response_status, headers)
                if response_status != 200:
                    raise ValueError('Explicit successful HTTP response required')
                if any(k.lower() == 'retry-after' for k in headers):
                    raise ValueError('Server deferral; no continuation')
                # Hash private data in memory; neither body nor headers are persisted.
                response_source = fingerprint(reply)
                return reply
            reply = adapter.request(kind, asin, dispatch)
            if not dispatched or current is None:
                raise ValueError('Exactly one accounted dispatch required')
            if kind == 'authentication':
                record = outcome('SUCCEEDED', source=response_source, status=response_status)
            else:
                _, state, codes = classify(dict(status='succeeded', http_status=response_status, response=reply), US, CONDITION, stamp())
                record = outcome('SUCCEEDED' if state != 'UNKNOWN' else 'UNCERTAIN', state,
                    response_status, codes, None if state != 'UNKNOWN' else 'INVALID_RESPONSE', response_source)
            ledger.finish(current, record)
            if record['operation_status'] != 'SUCCEEDED':
                raise ValueError('Ambiguous response')
        return dict(status='COMPLETED', requests_consumed=1+len(manifest['asins']))
    except BaseException as error:
        # Never serialize exception text, URLs, headers, bodies or arbitrary types.
        if current and not ledger.db.execute('SELECT 1 FROM m67_outcomes WHERE id=?', (current,)).fetchone():
            from app.amazon_diagnostics import AmazonFailure
            status = error.http_status if isinstance(error, AmazonFailure) else None
            safe_status = status if type(status) is int and status in (400,401,403,404,408,429,500,502,503,504) else None
            failed = safe_status is not None
            ledger.finish(current, outcome('FAILED' if failed else 'UNCERTAIN', status=safe_status,
                failure='HTTP_FAILURE' if failed else 'INTERRUPTED' if isinstance(error, (KeyboardInterrupt,SystemExit)) else 'TRANSPORT_UNCERTAIN'))
        ledger.stop(digest)
        m65_batch.stop_ambiguous(store, digest, 'UNCERTAIN')
        return dict(status='STOPPED_NO_REPLAY', requests_consumed=ledger.db.execute(
            'SELECT count(*) FROM m67_attempts WHERE digest=?', (digest,)).fetchone()[0])


def execute(path: Path, digest: str, sources: list[Path], store_path: Path, private: Path,
            authorization_path: Path, authorization_sha256: str, *, execution_flag: bool) -> dict:
    """Production Stage B; never called by validation, import, help or preflight."""
    if not execution_flag:
        raise ValueError('Explicit execution flag required')
    # Validate before even opening/creating an execution lock or ledger.
    report = preflight(path, digest, sources, store_path, private)
    manifest, actual = read_json(path)
    if actual != digest:
        raise ValueError('Manifest changed')
    auth, auth_sha = private_json(authorization_path)
    if auth_sha != authorization_sha256:
        raise ValueError('Authorization artifact digest mismatch')
    ro = ReadOnlyStore(store_path)
    try:
        authorize(manifest, digest, auth, execute=True, audit=build_audit(private, ro), preflight_report=report)
    finally:
        ro.db.close()
    lock_path = private/'candidate-execution.lock'
    if lock_path.exists():
        secure(lock_path)
    lock = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    ledger = store = None
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Re-read all bound evidence while holding the existing cross-version lock.
        report = preflight(path, digest, sources, store_path, private)
        ro = ReadOnlyStore(store_path)
        try:
            authorize(manifest, digest, auth, execute=True, audit=build_audit(private, ro), preflight_report=report)
        finally:
            ro.db.close()
        context, context_sha = private_json(private/CONTEXT)
        if context_sha != auth['account_binding_sha256']:
            raise ValueError('Private account binding changed')
        # Credentials are loaded only after separate authorization, without any request.
        from app.amazon_pilot import load_credentials
        directory = os.open(private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            credentials = load_credentials(directory)
        finally:
            os.close(directory)
        credential_copy, credential_sha = private_json(private/'credentials.json')
        if credential_sha != context['credentials_sha256'] or credential_copy != credentials:
            raise ValueError('Credential binding changed')
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if signal.getsignal(signal.SIGALRM) != signal.SIG_DFL or signal.getitimer(signal.ITIMER_REAL)[0]:
            raise ValueError('Exclusive execution deadline unavailable')
        from app.amazon_pacing import OperationPacer
        ledger = Ledger(private/LEDGER)
        pacer = OperationPacer(headroom=.5,state_path=private/LEDGER)
        # Preserve legacy server cooldowns without writing the original ledger.
        from app.m67_state import readonly
        old = readonly(private/'candidate-executions.sqlite3')
        try:
            for name, until in old.execute('SELECT operation,not_before_utc FROM amazon_cooldowns'):
                pacer.restore_cooldown(name, until)
        finally:
            old.close()
        store = VerificationStore(store_path)
        audit = build_audit(private, store)
        authorize(manifest, digest, auth, execute=True, audit=audit, preflight_report=report)
        not_expired(auth)
        # Global-first, then the existing M65 permanent mirror. A crash between
        # transactions burns the whole cohort; there is deliberately no resume.
        ledger.reserve(digest, manifest['restrictions_proposal'],dict(authorization_sha256=auth_sha,
            account_binding_sha256=context_sha,preflight_sha256=fingerprint(report),
            implementation_sha256=fingerprint(report['implementation_sha256'])))
        m65_batch.reserve_future(store, manifest['restrictions_proposal'], digest, auth,
            actual_file_sha256=actual, execute=True, audit=audit)
        def timeout(_signum, _frame):
            raise TimeoutError
        previous = signal.signal(signal.SIGALRM, timeout)
        signal.setitimer(signal.ITIMER_REAL, 120)
        try:
            result = run_reserved(store, ledger, manifest['restrictions_proposal'], digest,
                AmazonTransport(credentials, context['seller_id']), before_request=lambda:not_expired(auth),
                pacer=pacer, deadline=time.monotonic()+120)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
        return result
    finally:
        if store is not None:
            store.db.close()
        if ledger is not None:
            ledger.db.close()
        os.close(lock)
