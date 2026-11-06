"""Controlled M90.1 core. No live CLI: broker/lock review remains mandatory."""
from contextlib import contextmanager
import fcntl
import http.client
import json
import os
from pathlib import Path
import resource
import signal
import ssl
from urllib.parse import urlencode

from app import m90
from app.m67_state import secure
from app.m88_state import lock, stamp, write

PIN = 'c79e2a7788c3b99ee75a17dc3150b9e2a609818ad2de3cce82f082e36c9b79f1'
ACCOUNT_LOCK = Path('/root/.intelligenceos-arbitrage-amazon/candidate-execution.lock')
LEDGER = Path('/var/lib/intelligenceos-arbitrage/m89/ledger.json')
APPROVAL = 'APPROVE_M901_AUTH14_CATALOG15'
CURRENT = Path('/opt/intelligenceos-arbitrage/current')
CURRENT_RELEASE = Path('/opt/intelligenceos-arbitrage/releases/68230d3fdaef588bb7ba5c8340f49a473e8386b7')


@contextmanager
def existing_lock(path):
    """Never create a substitute lock; compare opened inode to reviewed pathname."""
    secure(path.parent, directory=True)
    secure(path)
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        actual, expected = os.fstat(fd), path.stat()
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise PermissionError('Shared lock changed')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def authenticate(credentials):
    """Exactly one POST, verified TLS, no proxies, redirects or retry machinery."""
    connection = http.client.HTTPSConnection('api.amazon.com', timeout=10,
                                            context=ssl.create_default_context())
    raw = None
    document = {}
    payload = None
    try:
        payload = urlencode(dict(grant_type='refresh_token',
            client_id=credentials['LWA_CLIENT_ID'], client_secret=credentials['LWA_CLIENT_SECRET'],
            refresh_token=credentials['LWA_REFRESH_TOKEN'])).encode()
        connection.request('POST', '/auth/o2/token', body=payload,
                           headers={'Content-Type': 'application/x-www-form-urlencoded'})
        with connection.getresponse() as response:
            raw = response.read(65537)
            if response.status != 200 or len(raw) > 65536:
                raise ValueError('Authentication rejected')
        from app.m80_contract import unique
        document = json.loads(raw, object_pairs_hook=unique)
        token = document.get('access_token')
        if (not isinstance(token, str) or not 1 <= len(token) <= 2048
                or any(c.isspace() or not c.isascii() or not c.isprintable() for c in token)
                or document.get('token_type', '').lower() != 'bearer'
                or type(document.get('expires_in')) is not int or document['expires_in'] < 60):
            raise ValueError('Invalid authentication response')
        return token
    finally:
        connection.close()
        payload = raw = None
        if isinstance(document, dict):
            document.clear()


def account_context(path):
    """Require operator-reviewed evidence, never synthesize confirmation flags."""
    from app.m88_state import read
    from datetime import datetime, timezone
    secure(path.parent, directory=True)
    if path.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError('Evidence must be outside repository')
    value = read(path)
    if (value.get('marketplace_id') != m90.MARKETPLACE
            or not isinstance(value.get('seller_id'), str) or not value['seller_id']
            or not isinstance(value.get('reviewer'), str) or not value['reviewer']):
        raise ValueError('Reviewed seller evidence required')
    for key in ('seller_authorization', 'application_product_listing_role', 'us_marketplace_participation',
                'protected_credentials_binding'):
        evidence = value.get(key, {})
        if evidence.get('confirmed') is not True or not evidence.get('reference'):
            raise ValueError('Missing authorization evidence')
    reviewed = datetime.fromisoformat(value['reviewed_at'])
    age = (datetime.now(timezone.utc) - reviewed).total_seconds()
    if reviewed.tzinfo is None or not 0 <= age <= 86400:
        raise ValueError('Current aware review required')


def execute(path, env, context, *, approval='', auth=authenticate, catalog=m90.send):
    """Broker integration seam; callers must obtain separate live authorization."""
    if approval != APPROVAL:
        raise PermissionError('Separate explicit two-request approval required')
    if path != LEDGER:
        raise ValueError('Authoritative ledger required')
    if not CURRENT.is_symlink() or CURRENT.resolve(strict=True) != CURRENT_RELEASE:
        raise PermissionError('Production release drift; review required')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    token = None
    credentials = {}
    with existing_lock(ACCOUNT_LOCK), lock(path.with_suffix('.lock')):
        value = m90.history(path, PIN)
        account_context(context)
        old_handler = signal.getsignal(signal.SIGALRM)
        def deadline(*_):
            raise TimeoutError('Absolute workflow deadline')
        signal.signal(signal.SIGALRM, deadline)
        try:
            credentials = m90.configuration(env)
            # Persistent independent claim rejects restoring the 13-attempt ledger.
            # Must live on the authoritative ledger filesystem and is never removed.
            claim = path.parent / 'm901-no-replay.json'
            write(claim, dict(baseline_sha256=PIN, claimed_at=stamp()))
            for number, phase in ((14, 'authentication'), (15, 'catalog_read_only')):
                attempt = dict(number=number, phase=phase, candidate_id=None if number == 14 else m90.ASIN,
                               status='RESERVED', reserved_at=stamp(), operation='m901', baseline_sha256=PIN)
                value['attempts'].append(attempt)
                value['attempts_used'] = number
                write(path, value, replace=True)
                try:
                    signal.alarm(20)
                    if number == 14:
                        token = auth(credentials)
                        if not isinstance(token, str) or not token:
                            raise ValueError('Authentication failed')
                        credentials.clear()
                        attempt.update(token_received=True)
                    else:
                        try:
                            status, raw = catalog(token)
                        finally:
                            token = None
                        if type(status) is int and 100 <= status <= 599:
                            attempt['http_status'] = status
                        if status != 200:
                            raise ValueError('Catalog rejected')
                        result = m90.parse_response(raw)
                        raw = None
                        attempt['result'] = result
                    attempt.update(status='COMPLETE', completed_at=stamp())
                except BaseException:
                    attempt.update(status='FAILED', completed_at=stamp(), outcome='FAILED_OR_UNCERTAIN_NO_RETRY')
                    write(path, value, replace=True)
                    raise RuntimeError('M90.1 stopped; charged; no retry') from None
                finally:
                    signal.alarm(0)
                write(path, value, replace=True)
            return result
        finally:
            token = None
            credentials.clear()
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
