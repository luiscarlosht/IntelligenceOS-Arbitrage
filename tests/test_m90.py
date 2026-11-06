"""Synthetic ledgers and mock HTTP only; no production credentials or network."""
from copy import deepcopy
import json
import os
import signal

import pytest

from app import m90
from app.m88_state import read, sha, write


@pytest.fixture
def state(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    prior = dict(pilot='m88-real-six-pilot', ceiling=49, purchase_authorized=False,
                 includes_authentication_and_retries=True, attempts_used=12,
                 attempts=[dict(number=i, status='COMPLETE' if i != 12 else 'FAILED',
                                phase='detail', candidate_id='synthetic') for i in range(1, 13)])
    monkeypatch.setattr(m90, 'BASELINE', m90.canonical_hash(prior))
    value = deepcopy(prior)
    value['m89_authentication_only'] = 'CLAIMED_NO_REPLAY'
    value['attempts_used'] = 13
    value['attempts'].append(dict(number=13, status='COMPLETE', phase='authentication',
        candidate_id=None, operation='m89-authentication-only', token_received=True,
        reserved_at='2026-11-05T01:00:00+00:00', completed_at='2026-11-05T01:00:01+00:00'))
    path = tmp_path / 'ledger.json'
    write(path, value)
    monkeypatch.setattr(m90, 'seller_context', lambda _: None)
    monkeypatch.setattr(m90, 'configuration', lambda _: {'LWA_REFRESH_TOKEN': 'fixture-secret'})
    monkeypatch.setattr(m90, 'token_from_pipe', lambda _: 'fixture-token')
    return path, sha(path), tmp_path / 'candidate-execution.lock', value


def run(state, transport, approval=m90.APPROVAL):
    path, digest, account_lock, _ = state
    return m90.execute(path, digest, path.parent / 'env', account_lock, 3, path.parent / 'context.json',
                       approval=approval, transport=transport)


def success(token):
    assert token == 'fixture-token'
    return 200, json.dumps(dict(asin=m90.ASIN, summaries=[dict(marketplaceId=m90.MARKETPLACE,
                                                            itemName='Synthetic item')])).encode()


def test_success_reservation_and_replay(state):
    def transport(token):
        value = read(state[0])
        assert value['attempts_used'] == 14
        assert value['attempts'][-1]['status'] == 'RESERVED'
        return success(token)
    assert run(state, transport)['purchase_authorized'] is False
    value = read(state[0])
    assert value['attempts'][:13] == state[3]['attempts']
    assert value['attempts'][-1]['status'] == 'COMPLETE'
    with pytest.raises(ValueError):
        run(state, lambda _: pytest.fail('replay dispatched'))
    assert 'fixture-token' not in state[0].read_text()


@pytest.mark.parametrize('status', [301, 302, 307, 308, 401, 403, 429, 500, 503])
def test_http_failure_charged(state, status):
    calls = []
    def transport(token):
        calls.append(token)
        return status, b'fixture-token fixture-secret'
    with pytest.raises(RuntimeError):
        run(state, transport)
    assert len(calls) == 1
    assert read(state[0])['attempts'][-1]['status'] == 'FAILED'
    assert read(state[0])['attempts_used'] == 14
    assert 'fixture-secret' not in state[0].read_text()


@pytest.mark.parametrize('error', [TimeoutError(), OSError(), KeyboardInterrupt(), SystemExit()])
def test_timeout_and_catchable_crash(state, error):
    def transport(_):
        raise error
    with pytest.raises(RuntimeError):
        run(state, transport)
    assert read(state[0])['attempts_used'] == 14
    with pytest.raises(ValueError):
        run(state, lambda _: pytest.fail('retry'))


def test_uncatchable_crash_preserves_charge(state):
    pid = os.fork()
    if pid == 0:
        run(state, lambda _: os._exit(77))
        os._exit(78)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 77
    assert read(state[0])['attempts'][-1]['status'] == 'RESERVED'
    with pytest.raises(ValueError):
        run(state, lambda _: pytest.fail('crash replay'))


@pytest.mark.parametrize('change', ['prefix', 'success', 'count', 'purchase', 'chronology'])
def test_corruption_even_if_rehashed(state, change):
    value = read(state[0])
    if change == 'prefix': value['attempts'][0]['candidate_id'] = 'changed'
    if change == 'success': value['attempts'][-1]['token_received'] = False
    if change == 'count': value['attempts_used'] = 12
    if change == 'purchase': value['purchase_authorized'] = True
    if change == 'chronology': value['attempts'][-1]['completed_at'] = '2026-11-04T00:00:00+00:00'
    write(state[0], value, replace=True)
    changed = (state[0], sha(state[0]), state[2], state[3])
    with pytest.raises(ValueError):
        run(changed, lambda _: pytest.fail('corrupt ledger dispatched'))


def test_approval_and_offline_preflight(state):
    before = state[0].read_bytes()
    with pytest.raises(PermissionError):
        run(state, lambda _: pytest.fail('unapproved dispatch'), approval='')
    assert m90.preflight(state[0], state[1])['network'] == 'NOT_TESTED'
    assert state[0].read_bytes() == before


@pytest.mark.parametrize('raw', [b'{}', b'not json', b'x' * (m90.MAX_RESPONSE + 1),
    b'{"asin":"B001BE12BA","asin":"B001BE12BA"}',
    b'{"asin":"B001BE12BA","summaries":[]}',
    b'{"asin":"B001BE12BA","summaries":[{"marketplaceId":"wrong","itemName":"x"}]}'])
def test_invalid_response_charged(state, raw):
    with pytest.raises(RuntimeError):
        run(state, lambda _: (200, raw))
    assert read(state[0])['attempts_used'] == 14


def test_endpoint_write_rejection():
    with pytest.raises(PermissionError):
        m90.send('synthetic', url='https://unapproved.invalid')
    with pytest.raises(PermissionError):
        m90.send('synthetic', method='POST')


def test_real_transport_mocked(monkeypatch):
    calls = []
    class Response:
        status = 302
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            assert size == m90.MAX_RESPONSE + 1
            return b''
    class Connection:
        def __init__(self, host, **kwargs):
            assert host == m90.HOST and kwargs['timeout'] == 10
        def request(self, method, target, headers):
            calls.append((method, target))
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(m90.http.client, 'HTTPSConnection', Connection)
    assert m90.send('synthetic') == (302, b'')
    assert calls == [('GET', m90.TARGET)]


def test_durable_reservation_failure_never_sends(state, monkeypatch):
    def fail(*args, **kwargs): raise OSError('disk full')
    monkeypatch.setattr(m90, 'write', fail)
    with pytest.raises(OSError):
        run(state, lambda _: pytest.fail('undurable dispatch'))


def test_pipe_is_bounded(tmp_path):
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b'synthetic-token')
        assert m90.token_from_pipe(read_fd) == 'synthetic-token'
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_seller_prerequisites(tmp_path):
    from datetime import datetime, timedelta, timezone
    tmp_path.chmod(0o700)
    path = tmp_path / 'context.json'
    value = dict(seller_id='SYNTHETIC', marketplace_id=m90.MARKETPLACE,
                 product_listing_role_confirmed=True, application_authorized_for_seller=True,
                 us_marketplace_participation_confirmed=True, token_matches_protected_source=True,
                 token_expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
    write(path, value)
    m90.seller_context(path)
    for key in ('product_listing_role_confirmed', 'application_authorized_for_seller',
                'us_marketplace_participation_confirmed', 'token_matches_protected_source'):
        invalid = dict(value, **{key: False})
        write(path, invalid, replace=True)
        with pytest.raises(ValueError): m90.seller_context(path)
    write(path, dict(value, token_expires_at='2000-01-01T00:00:00+00:00'), replace=True)
    with pytest.raises(ValueError): m90.seller_context(path)


def test_no_network_import_or_preflight(state):
    from app.m89_auth_readiness import no_dispatch
    import importlib
    # Audit hook rejects DNS, connect, sends, subprocess and HTTP, not only urlopen.
    with no_dispatch():
        importlib.import_module('app.m90')
        m90.preflight(state[0], state[1])


def test_account_lock_contention(state):
    from app.m88_state import lock
    with lock(state[2]):
        with pytest.raises(BlockingIOError):
            run(state, lambda _: pytest.fail('concurrent dispatch'))
    assert read(state[0])['attempts_used'] == 13


def test_pinned_bytes_reject_drift(state):
    state[0].write_text(state[0].read_text() + ' ')
    with pytest.raises(ValueError):
        run(state, lambda _: pytest.fail('unpinned dispatch'))
