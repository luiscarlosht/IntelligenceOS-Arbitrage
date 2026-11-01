"""Read-only preflight and separate, expiring human authorization validation."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from app import m65_batch, m66_discovery
from app.m65_intelligence import US, CONDITION, build_audit, read_json, sha256, observed
from app.m66_verification import ACCOUNT
from app.m67_state import ReadOnlyStore, secure, ledger_snapshot, readonly
from app.observations import fingerprint

LEDGER = 'm67-executions.sqlite3'
CONTEXT = 'm67-account-context.json'


def implementation() -> dict:
    root = Path(__file__).parent
    names = ('m67.py','m67_policy.py','m67_state.py','m67_transport.py','m67_execution.py',
             'm67_reporting.py','amazon_pilot.py','amazon_pacing.py','amazon_diagnostics.py','ops_notifications.py',
             'observations.py','normalization.py','provider_runtime.py')
    return {name: sha256(root/name) for name in names}


def private_json(path: Path) -> tuple[dict, str]:
    secure(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise ValueError('Owner-only pinned private object required')
        raw = os.read(fd, 32769)
        if len(raw) > 32768:
            raise ValueError('Private binding too large')
        doc = json.loads(raw)
        if not isinstance(doc, dict):
            raise ValueError('Private object required')
        return doc, hashlib.sha256(raw).hexdigest()
    finally:
        os.close(fd)


def scope(inner: dict) -> None:
    m65_batch.validate_manifest(inner)
    if not 1 <= len(inner['asins']) <= 20 or inner['maximum_checks'] > 20:
        raise ValueError('M67 maximum is 20')
    if inner['budget']['maximum_requests'] != len(inner['asins'])+1:
        raise ValueError('Exact authentication plus restrictions budget required')
    if any(type(v) is not int for v in inner['budget'].values()):
        raise ValueError('Integer request budgets required')


def preflight(path: Path, digest: str, sources: list[Path], store_path: Path, private: Path) -> dict:
    """No writes, reservations, secret-value reads or transport construction."""
    secure(private, directory=True)
    store = ReadOnlyStore(store_path)
    try:
        manifest = m66_discovery.validate(path, digest, sources, store, private)
        inner = manifest['restrictions_proposal']; scope(inner)
        audit = build_audit(private, store)
        for table in ('intelligence_events','batch_claims','asin_claims','request_attempts','batch_stops','m66_verifications','m66_results'):
            triggers = [r[0].upper() for r in store.db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))]
            if not all(any('BEFORE '+op in sql and 'RAISE(ABORT' in sql for sql in triggers) for op in ('UPDATE','DELETE')):
                raise ValueError('Immutable derived store protections missing')
        proof, proof_sha = read_json(private/'m63-eligibility-authorization-01.json')
        if (proof.get('state') != 'claimed_no_replay' or proof.get('maximum_checks') != 20
                or len(set(proof.get('asins', []))) != 20
                or not set(proof['asins']) <= set(audit['excluded_asins'])):
            raise ValueError('Original permanent M63 reservation required')
        # The legacy SQLite audit is mandatory even when all M63 claims live in
        # its separate immutable reservation file. Read it, never migrate it.
        legacy = readonly(private/'candidate-executions.sqlite3'); legacy.close()
        saved = ledger_snapshot(private/LEDGER)
        if digest in saved['batches'] or set(inner['asins']) & set(saved['claims']):
            raise ValueError('Permanently reserved cohort; replay forbidden')
        if store.db.execute('SELECT 1 FROM batch_claims WHERE digest=?', (digest,)).fetchone():
            raise ValueError('Existing execution reservation')
        secure(private/'credentials.json')  # metadata only, deliberately not parsed
        binding_path = private/CONTEXT
        checks = []
        binding_sha = None
        if binding_path.exists():
            context, binding_sha = private_json(binding_path)
            if (set(context) != {'account_reference','marketplace_id','condition','seller_id','credentials_sha256'}
                    or context['account_reference'] != ACCOUNT or context['marketplace_id'] != US
                    or context['condition'] != CONDITION or not isinstance(context['seller_id'], str)
                    or not re.fullmatch('[A-Z0-9]{1,32}', context['seller_id'])
                    or not re.fullmatch('[a-f0-9]{64}', context['credentials_sha256'])):
                raise ValueError('Private account binding invalid')
            checks.append('ACCOUNT_BINDING_PRESENT_CREDENTIAL_CONTENT_UNREAD')
        else:
            checks.append('BLOCKED_PRIVATE_ACCOUNT_BINDING_MISSING')
        if not os.access(private, os.W_OK) or os.statvfs(private).f_bavail * os.statvfs(private).f_frsize < 1024*1024:
            raise ValueError('Immutable storage unavailable')
        return dict(schema=1, mode='M67_OFFLINE_PREFLIGHT', ready=bool(binding_sha),
            manifest_sha256=digest, asins=inner['asins'], account_reference=ACCOUNT,
            marketplace_id=US, condition=CONDITION, budget=inner['budget'],
            audit_sha256=fingerprint(audit), original_reservation_sha256=proof_sha,
            historical_exclusions=len(audit['excluded_asins']),
            account_binding_sha256=binding_sha, implementation_sha256=implementation(),
            checks=checks+['MANIFEST_SOURCE_CODE_HISTORY_ORDER_VALID','NO_RESERVATION_OR_NETWORK'],
            execution_authorized=False)
    finally:
        store.db.close()


def authorize(manifest: dict, digest: str, authorization: dict | None, *, execute: bool,
              audit: dict, preflight_report: dict, now: datetime | None = None) -> None:
    """In-memory validation; never generates a review artifact."""
    inner = manifest['restrictions_proposal']; scope(inner)
    m65_batch.validate_authorization(inner, digest, authorization, actual_file_sha256=sha256_from_report(preflight_report),
                                    execute=execute, audit=audit, now=now)
    a = authorization
    required = {'schema','approved','execution_permission','manifest_sha256','asins','account_reference',
                'account_binding_sha256','marketplace_id','condition','budget','review_reference',
                'reviewed_at','expires_at','implementation_sha256','preflight_sha256','no_retry'}
    if (not isinstance(a, dict) or set(a) != required or type(a['schema']) is not int or a['schema'] != 1
            or a['execution_permission'] is not True or a['no_retry'] is not True
            or a['account_reference'] != ACCOUNT or not preflight_report['ready']
            or a['account_binding_sha256'] != preflight_report['account_binding_sha256']
            or a['implementation_sha256'] != implementation()
            or a['preflight_sha256'] != fingerprint(preflight_report)
            or any(type(v) is not int for v in a['budget'].values())):
        raise ValueError('Separate exact account/code/preflight authorization required')


def sha256_from_report(report: dict) -> str:
    return report['manifest_sha256']


def not_expired(authorization: dict) -> None:
    expiry = observed(authorization.get('expires_at'))
    if not expiry or datetime.now(timezone.utc) >= datetime.fromisoformat(expiry):
        raise ValueError('Authorization expired')
