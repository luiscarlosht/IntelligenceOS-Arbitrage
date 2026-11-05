import json
from pathlib import Path
import pytest
from app import m89_deployment as m
from app.m88_state import write, ledger


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    path = tmp_path / 'ledger.json'
    value = dict(pilot='m88-real-six-pilot', ceiling=49, purchase_authorized=False,
        includes_authentication_and_retries=True, attempts_used=12,
        attempts=[dict(number=i, status='COMPLETE' if i < 12 else 'FAILED', phase='authentication') for i in range(1,13)])
    write(path, value)
    monkeypatch.setattr(m, 'BASELINE', m.sha(path))
    env = tmp_path / 'live.env'
    env.write_text('LWA_CLIENT_ID=synthetic\nLWA_CLIENT_SECRET=synthetic\nLWA_REFRESH_TOKEN=synthetic\nPURCHASE_AUTHORIZED=false\n')
    env.chmod(0o600)
    monkeypatch.setattr(m, 'dependencies', lambda: None)
    return path, env


def test_offline_and_transfer(prepared, tmp_path, monkeypatch):
    path, env = prepared
    monkeypatch.setattr(m, 'network', lambda: pytest.fail('offline network'))
    original = path.read_bytes()
    assert m.preflight(path, env, offline=True)['dns_tcp_tls'] == 'NOT_TESTED'
    copy = tmp_path / 'copy.json'
    m.transfer(path, copy)
    assert copy.read_bytes() == original == path.read_bytes()
    with pytest.raises(FileExistsError):
        m.transfer(path, copy)


@pytest.mark.parametrize('outcome', ['success', 'rejected', 'exception', 'interrupt'])
def test_single_attempt(prepared, monkeypatch, outcome):
    path, env = prepared
    prior = ledger(path)['attempts']
    calls = []
    def send(_):
        calls.append(1)
        assert ledger(path)['attempts_used'] == 13
        assert ledger(path)['attempts'][-1]['status'] == 'RESERVED'
        if outcome == 'exception':
            raise OSError('secret diagnostic')
        if outcome == 'interrupt':
            raise KeyboardInterrupt()
        return outcome == 'success'
    monkeypatch.setattr(m, 'send', send)
    if outcome == 'success':
        m.authenticate(path, env, opt_in=True)
    else:
        with pytest.raises(RuntimeError):
            m.authenticate(path, env, opt_in=True)
    assert ledger(path)['attempts'][:12] == prior
    assert ledger(path)['attempts_used'] == 13
    with pytest.raises(ValueError):
        m.authenticate(path, env, opt_in=True)
    assert calls == [1]


def test_fail_closed(prepared, monkeypatch):
    path, env = prepared
    monkeypatch.setattr(m, 'send', lambda _: pytest.fail('dispatch'))
    with pytest.raises(PermissionError):
        m.authenticate(path, env)
    env.chmod(0o644)
    with pytest.raises(ValueError):
        m.authenticate(path, env, opt_in=True)
    assert ledger(path)['attempts_used'] == 12


def test_no_redirect():
    assert m.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com') is None


def test_preflight_network_is_tls_only(monkeypatch):
    calls = []
    class Channel:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Context:
        def wrap_socket(self, sock, server_hostname):
            calls.append(('tls', server_hostname))
            return Channel()
    monkeypatch.setattr(m.ssl, 'create_default_context', lambda: Context())
    monkeypatch.setattr(m.socket, 'getaddrinfo', lambda host, *a, **kw: calls.append(('dns', host)))
    monkeypatch.setattr(m.socket, 'create_connection', lambda address, **kw: Channel())
    m.network()
    assert calls == [(kind, host) for host in m.HOSTS for kind in ('dns', 'tls')]


def test_tampered_baseline_and_lock(prepared):
    path, env = prepared
    with m.lock(path.with_suffix('.lock')):
        with pytest.raises(BlockingIOError):
            m.preflight(path, env, offline=True)
    value = ledger(path)
    value['attempts'][0]['extra'] = 'tampered'
    write(path, value, replace=True)
    with pytest.raises(ValueError):
        m.authenticate(path, env, opt_in=True)
    assert ledger(path)['attempts_used'] == 12


def test_transport_request_is_single_fixed_post(monkeypatch):
    seen = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            assert size == 65537
            return b'{"access_token":"synthetic-token"}'
    class Opener:
        def open(self, request, timeout):
            seen.append(request)
            assert timeout == 20
            assert request.full_url == 'https://api.amazon.com/auth/o2/token'
            assert request.method == 'POST'
            assert b'grant_type=refresh_token' in request.data
            return Response()
    def build(*handlers):
        assert any(isinstance(h, m.NoRedirect) for h in handlers)
        assert any(isinstance(h, m.ProxyHandler) and h.proxies == {} for h in handlers)
        return Opener()
    monkeypatch.setattr(m, 'build_opener', build)
    assert m.send(dict(LWA_CLIENT_ID='synthetic', LWA_CLIENT_SECRET='synthetic', LWA_REFRESH_TOKEN='synthetic'))
    assert len(seen) == 1


def test_dependency_gate(monkeypatch):
    monkeypatch.setattr(m.sys, 'version_info', (3, 12))
    monkeypatch.setattr(m, 'version', lambda name: {'openpyxl':'3.1.5', 'pytest':'8.3.5'}[name])
    with pytest.raises(ValueError, match='Pinned dependencies'):
        m.dependencies()
    monkeypatch.setattr(m, 'version', lambda name: {'openpyxl':'3.1.5', 'pytest':'9.0.3'}[name])
    m.dependencies()
    monkeypatch.setattr(m.sys, 'version_info', (3, 11))
    with pytest.raises(ValueError, match='Python 3.12'):
        m.dependencies()
