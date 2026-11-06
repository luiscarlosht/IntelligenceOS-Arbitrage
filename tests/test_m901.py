"""Synthetic state only; no production credential reads or network."""
import os
import pytest
from app import m901, m90
from app.m88_state import read, write
from test_m90 import state, success


@pytest.fixture
def controlled(state, monkeypatch):
    path, pin, account_lock, _ = state
    write(account_lock, {})
    release = path.parent / 'release'
    release.mkdir()
    current = path.parent / 'current'
    current.symlink_to(release)
    monkeypatch.setattr(m901, 'CURRENT', current)
    monkeypatch.setattr(m901, 'CURRENT_RELEASE', release)
    monkeypatch.setattr(m901, 'PIN', pin)
    monkeypatch.setattr(m901, 'LEDGER', path)
    monkeypatch.setattr(m901, 'ACCOUNT_LOCK', account_lock)
    monkeypatch.setattr(m901, 'account_context', lambda _: None)
    return state


def run(state, auth=lambda _: 'fixture-token', catalog=success):
    return m901.execute(state[0], state[0].parent / 'env', state[0].parent / 'context',
                        approval=m901.APPROVAL, auth=auth, catalog=catalog)


def test_success_and_rollback(controlled):
    original = controlled[0].read_bytes()
    def auth(credentials):
        assert read(controlled[0])['attempts_used'] == 14
        return 'fixture-token'
    def catalog(token):
        assert read(controlled[0])['attempts_used'] == 15
        return success(token)
    assert run(controlled, auth, catalog)['purchase_authorized'] is False
    value = read(controlled[0])
    assert value['attempts'][:13] == controlled[3]['attempts']
    assert 'fixture-token' not in controlled[0].read_text()
    with pytest.raises(ValueError): run(controlled)
    controlled[0].write_bytes(original)
    with pytest.raises(FileExistsError): run(controlled)


@pytest.mark.parametrize('phase', [14, 15])
@pytest.mark.parametrize('error', [TimeoutError, OSError, KeyboardInterrupt, SystemExit])
def test_failures(controlled, phase, error):
    def fail(_): raise error('fixture-token')
    with pytest.raises(RuntimeError):
        run(controlled, auth=fail if phase == 14 else lambda _: 'fixture-token',
            catalog=fail if phase == 15 else success)
    assert read(controlled[0])['attempts_used'] == phase
    assert 'fixture-token' not in controlled[0].read_text()


@pytest.mark.parametrize('status', [301, 401, 403, 429, 500, 503])
def test_status(controlled, status):
    with pytest.raises(RuntimeError): run(controlled, catalog=lambda _: (status, b''))
    assert read(controlled[0])['attempts_used'] == 15


@pytest.mark.parametrize('failure_write', [1, 2, 3, 4, 5])
def test_storage(controlled, monkeypatch, failure_write):
    calls = []
    real_write = m901.write
    count = 0
    def fail(*args, **kwargs):
        nonlocal count
        count += 1
        if count == failure_write: raise OSError('disk full')
        return real_write(*args, **kwargs)
    monkeypatch.setattr(m901, 'write', fail)
    def auth(_): calls.append(14); return 'fixture-token'
    def catalog(token): calls.append(15); return success(token)
    with pytest.raises(OSError): run(controlled, auth, catalog)
    assert calls == {1: [], 2: [], 3: [14], 4: [14], 5: [14, 15]}[failure_write]


@pytest.mark.parametrize('phase', [14, 15])
def test_crash(controlled, phase):
    pid = os.fork()
    if pid == 0:
        run(controlled, auth=(lambda _: os._exit(77)) if phase == 14 else lambda _: 'fixture-token',
            catalog=lambda _: os._exit(77))
        os._exit(78)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 77
    assert read(controlled[0])['attempts_used'] == phase
    assert read(controlled[0])['attempts'][-1]['status'] == 'RESERVED'


def test_lock(controlled):
    with m901.existing_lock(controlled[2]):
        with pytest.raises(BlockingIOError): run(controlled)
    assert read(controlled[0])['attempts_used'] == 13


def test_disposal(controlled):
    held = []
    def auth(credentials): held.append(credentials); return 'fixture-token'
    def catalog(token):
        assert held == [{}]
        return success(token)
    run(controlled, auth, catalog)
    assert held == [{}]
    # Python cannot promise secure erasure of immutable strings; only reference disposal.


def test_release_drift(controlled, monkeypatch, tmp_path):
    monkeypatch.setattr(m901, 'CURRENT', tmp_path / 'missing')
    with pytest.raises(PermissionError): run(controlled)
    assert read(controlled[0])['attempts_used'] == 13


def test_missing_lock(controlled):
    controlled[2].unlink()
    with pytest.raises(FileNotFoundError): run(controlled)
    assert not controlled[2].exists()


def test_auth_transport(monkeypatch):
    calls = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            assert size == 65537
            return b'{"access_token":"synthetic","expires_in":3600,"token_type":"bearer"}'
    class Connection:
        def __init__(self, host, **kwargs):
            assert host == 'api.amazon.com'
            assert kwargs['context'].check_hostname
        def request(self, method, target, **kwargs): calls.append((method, target))
        def getresponse(self): return Response()
        def close(self): calls.append('closed')
    monkeypatch.setattr(m901.http.client, 'HTTPSConnection', Connection)
    assert m901.authenticate(dict(LWA_CLIENT_ID='x', LWA_CLIENT_SECRET='y', LWA_REFRESH_TOKEN='z')) == 'synthetic'
    assert calls == [('POST', '/auth/o2/token'), 'closed']


@pytest.mark.parametrize('status', [302, 401, 403, 429, 500, 503])
def test_auth_http_failure(controlled, monkeypatch, status):
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return b'fixture-secret'
    Response.status = status
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): calls.append('POST')
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(m901.http.client, 'HTTPSConnection', Connection)
    monkeypatch.setattr(m90, 'configuration', lambda _: dict(LWA_CLIENT_ID='x', LWA_CLIENT_SECRET='y', LWA_REFRESH_TOKEN='z'))
    with pytest.raises(RuntimeError):
        run(controlled, auth=m901.authenticate, catalog=lambda _: pytest.fail('Catalog after auth failure'))
    assert calls == ['POST']
    assert read(controlled[0])['attempts_used'] == 14


def test_token_reference_dropped_before_completion(controlled, monkeypatch):
    import inspect
    real_write = m901.write
    def check(path, value, **kwargs):
        if value.get('attempts_used') == 15 and value['attempts'][-1]['status'] == 'COMPLETE':
            assert inspect.currentframe().f_back.f_locals['token'] is None
        return real_write(path, value, **kwargs)
    monkeypatch.setattr(m901, 'write', check)
    run(controlled)


def test_account_evidence_required(tmp_path):
    from datetime import datetime, timezone
    tmp_path.chmod(0o700)
    path = tmp_path / 'context.json'
    value = dict(seller_id='SYNTHETIC', marketplace_id=m90.MARKETPLACE,
                 reviewer='fixture-reviewer', reviewed_at=datetime.now(timezone.utc).isoformat())
    keys = ('seller_authorization', 'application_product_listing_role',
            'us_marketplace_participation', 'protected_credentials_binding')
    for key in keys:
        value[key] = dict(confirmed=True, reference='fixture-only')
    write(path, value)
    m901.account_context(path)
    for key in keys:
        missing = dict(value, **{key: dict(confirmed=False, reference='fixture-only')})
        write(path, missing, replace=True)
        with pytest.raises(ValueError): m901.account_context(path)
