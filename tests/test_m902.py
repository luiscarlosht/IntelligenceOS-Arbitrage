"""Only synthetic files, identities and transports. Never open production paths."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
import signal

import pytest

from app import m902, m902_requester
from app.m88_state import read, sha, write
from test_m90 import state, success


def fake_owner(monkeypatch, target):
    from pathlib import Path
    from types import SimpleNamespace
    real = Path.lstat
    def altered(path):
        info = real(path)
        if path != target:
            return info
        return SimpleNamespace(st_uid=12345, st_mode=info.st_mode, st_nlink=info.st_nlink,
                               st_dev=info.st_dev, st_ino=info.st_ino)
    monkeypatch.setattr(Path, 'lstat', altered)
    from app import m902_storage
    target_info = real(target)
    original_metadata = m902_storage.metadata
    def metadata(info, uid, **kwargs):
        if (info.st_dev, info.st_ino) == (target_info.st_dev, target_info.st_ino):
            raise ValueError('Synthetic ownership mismatch')
        return original_metadata(info, uid, **kwargs)
    monkeypatch.setattr(m902_storage, 'metadata', metadata)


@pytest.fixture
def broker(state, monkeypatch):
    path, pin, account, _ = state
    root = path.parent
    write(account, {})
    ledger_lock = root / 'ledger.lock'
    write(ledger_lock, {})
    credentials = root / 'env'
    credentials.write_text('LWA_CLIENT_ID=synthetic\nLWA_CLIENT_SECRET=fixture-secret\n'
                           'LWA_REFRESH_TOKEN=fixture-refresh\nPURCHASE_AUTHORIZED=false\n')
    credentials.chmod(0o600)
    evidence_path = root / 'evidence'
    evidence = dict(seller_id='SYNTHETIC', application_id='fixture-app', marketplace_id='ATVPDKIKX0DER',
                    credential_sha256=sha(credentials), reviewer='fixture-operator',
                    reviewed_at=datetime.now(timezone.utc).isoformat())
    for key in ('seller_authorization', 'application_product_listing_role',
                'us_marketplace_participation', 'protected_credentials_binding'):
        evidence[key] = dict(confirmed=True, reference='synthetic-reference')
    write(evidence_path, evidence)
    policy = m902.Policy(root=root, uid=os.geteuid(), requester_uid=12345,
                        release_commit='a'*40, baseline_sha256=pin, seller_id='SYNTHETIC',
                        application_id='fixture-app', ledger=path, account_lock=account,
                        account_identity=m902.Identity.of(account), ledger_lock=ledger_lock,
                        ledger_identity=m902.Identity.of(ledger_lock), credentials=credentials,
                        credential_sha256=sha(credentials), evidence=evidence_path,
                        evidence_sha256=sha(evidence_path), approval=root/'approval', claim=root/'claim')
    approval = dict(binding=policy.binding(), approved_by='fixture-operator', nonce='b'*64,
                    approved_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),
                    expires_at=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat())
    write(policy.approval, approval)
    return policy


def run(policy, **kwargs):
    return m902.execute(kwargs.pop('raw', m902_requester.request()),
                        kwargs.pop('peer_uid', policy.requester_uid), policy,
                        auth=kwargs.pop('auth', lambda _: 'fixture-token'),
                        catalog=kwargs.pop('catalog', success), **kwargs)


def test_success(broker):
    before = read(broker.ledger)['attempts']
    held = []
    def auth(credentials):
        held.append(credentials)
        assert read(broker.ledger)['attempts_used'] == 14
        assert read(broker.ledger)['attempts'][-1]['status'] == 'RESERVED'
        assert broker.claim.exists()
        return 'fixture-token'
    def catalog(token):
        assert held == [{}]
        value = read(broker.ledger)
        assert value['attempts_used'] == 15
        assert value['attempts'][-2]['status'] == 'COMPLETE'
        return success(token)
    assert run(broker, auth=auth, catalog=catalog) == dict(asin='B001BE12BA', marketplace_id='ATVPDKIKX0DER',
        summary_present=True, seller_eligibility='UNKNOWN', profitability='UNKNOWN', purchase_authorized=False)
    assert read(broker.ledger)['attempts'][:13] == before
    assert held == [{}]
    for path in (broker.ledger, broker.claim):
        assert 'fixture-token' not in path.read_text()
        assert 'fixture-secret' not in path.read_text()
    assert signal.getsignal(signal.SIGALRM) == signal.SIG_DFL


@pytest.mark.parametrize('field,value', [
    ('release_commit', 'c'*40), ('baseline_sha256', 'c'*64), ('seller_id', 'OTHER'),
    ('marketplace_id', 'OTHER'), ('credential_sha256', 'c'*64), ('credential_path', '/tmp/injected'),
    ('account_inode', 0), ('account_device', 0), ('application_id', 'OTHER'), ('requester_uid', 0),
    ('operation', m902.OPERATION+'OTHER'), ('ledger', '/tmp/injected')])
def test_altered_authorization(broker, field, value):
    approval = read(broker.approval)
    approval['binding'][field] = value
    write(broker.approval, approval, replace=True)
    with pytest.raises(m902.BrokerError): run(broker)
    assert read(broker.ledger)['attempts_used'] == 13
    assert not broker.claim.exists()


@pytest.mark.parametrize('problem', ['missing', 'expired', 'future', 'naive', 'extra', 'nonce', 'owner', 'mode', 'symlink'])
def test_bad_approval(broker, problem, monkeypatch):
    approval = read(broker.approval)
    if problem == 'missing': broker.approval.unlink()
    elif problem == 'expired':
        approval['expires_at'] = (datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat()
    elif problem == 'future':
        approval['approved_at'] = (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
    elif problem == 'naive': approval['expires_at'] = '2026-11-06T23:59:00'
    elif problem == 'extra': approval['command'] = 'echo injected'
    elif problem == 'nonce': approval['nonce'] = 'not-a-nonce'
    elif problem == 'owner': fake_owner(monkeypatch, broker.approval)
    elif problem == 'mode': broker.approval.chmod(0o644)
    elif problem == 'symlink':
        target = broker.approval.with_name('target')
        broker.approval.rename(target)
        broker.approval.symlink_to(target)
    if problem in ('expired', 'future', 'naive', 'extra', 'nonce'):
        write(broker.approval, approval, replace=True)
    with pytest.raises(m902.BrokerError): run(broker)
    assert read(broker.ledger)['attempts_used'] == 13


@pytest.mark.parametrize('raw', [b'', b'[]', b'{', b'x'*257, b'{"operation":"shell","version":1}',
    b'{"operation":"M902_AUTH14_CATALOG15","version":true}',
    b'{"operation":"M902_AUTH14_CATALOG15","version":1,"url":"https://evil"}',
    b'{"operation":"M902_AUTH14_CATALOG15","version":1,"command":"touch /tmp/pwned"}',
    b'{"operation":"M902_AUTH14_CATALOG15","version":1,"version":1}'])
def test_protocol(broker, raw):
    with pytest.raises(m902.BrokerError): run(broker, raw=raw)
    assert not broker.claim.exists()


def test_unauthorized_identity(broker):
    with pytest.raises(m902.BrokerError): run(broker, peer_uid=9999)
    with pytest.raises(m902.BrokerError): run(replace(broker, uid=9999))
    assert not broker.claim.exists()


@pytest.mark.parametrize('which', ['account_lock', 'ledger_lock'])
@pytest.mark.parametrize('problem', ['missing', 'inode', 'symlink', 'mode', 'owner', 'hardlink'])
def test_lock_metadata(broker, which, problem, monkeypatch):
    path = getattr(broker, which)
    if problem == 'missing': path.unlink()
    if problem in ('inode', 'symlink'):
        other = path.with_name(path.name+'-old')
        path.rename(other)
        if problem == 'inode': write(path, {})
        else: path.symlink_to(other)
    if problem == 'mode': path.chmod(0o644)
    if problem == 'owner': fake_owner(monkeypatch, path)
    if problem == 'hardlink': os.link(path, path.with_name(path.name+'-hardlink'))
    with pytest.raises(m902.BrokerError): run(broker)
    assert read(broker.ledger)['attempts_used'] == 13


@pytest.mark.parametrize('which', ['account', 'ledger'])
def test_contention_and_exception_cleanup(broker, which):
    path, identity = ((broker.account_lock, broker.account_identity) if which == 'account'
                      else (broker.ledger_lock, broker.ledger_identity))
    with m902.existing(path, identity, broker):
        with pytest.raises(m902.BrokerError): run(broker)
    # Both locks were released after a failed acquisition of the second lock.
    assert run(broker)['purchase_authorized'] is False


@pytest.mark.parametrize('problem', ['missing', 'malformed', 'purchase', 'binding', 'path'])
def test_credentials(broker, problem):
    policy = broker
    if problem == 'missing': broker.credentials.unlink()
    elif problem in ('malformed', 'purchase'):
        broker.credentials.write_text('secret' if problem == 'malformed' else
            'LWA_CLIENT_ID=x\nLWA_CLIENT_SECRET=y\nLWA_REFRESH_TOKEN=z\nPURCHASE_AUTHORIZED=true\n')
        # Re-approve digest to reach the strict configuration parser.
        policy = replace(broker, credential_sha256=sha(broker.credentials))
        evidence = read(policy.evidence)
        evidence['credential_sha256'] = policy.credential_sha256
        write(policy.evidence, evidence, replace=True)
        policy = replace(policy, evidence_sha256=sha(policy.evidence))
        approval = read(policy.approval)
        approval['binding'] = policy.binding()
        write(policy.approval, approval, replace=True)
    elif problem == 'binding': broker.credentials.write_text('changed-secret')
    else: policy = replace(broker, credentials=broker.root/'arbitrary')
    with pytest.raises(m902.BrokerError) as exc: run(policy)
    assert 'secret' not in str(exc.value)
    assert read(broker.ledger)['attempts_used'] == 13


@pytest.mark.parametrize('key', ['seller_id', 'application_id', 'marketplace_id', 'credential_sha256',
    'reviewer', 'reviewed_at', 'seller_authorization', 'application_product_listing_role',
    'us_marketplace_participation', 'protected_credentials_binding'])
def test_evidence(broker, key):
    evidence = read(broker.evidence)
    evidence.pop(key)
    write(broker.evidence, evidence, replace=True)
    policy = replace(broker, evidence_sha256=sha(broker.evidence))
    approval = read(policy.approval)
    approval['binding'] = policy.binding()
    write(policy.approval, approval, replace=True)
    with pytest.raises(m902.BrokerError): run(policy)
    assert not policy.claim.exists()


@pytest.mark.parametrize('phase', [14, 15])
@pytest.mark.parametrize('error', [TimeoutError, ConnectionError, KeyboardInterrupt, SystemExit])
def test_failed_dispatch(broker, phase, error):
    calls = []
    def fail(_):
        calls.append(phase)
        raise error('fixture-secret fixture-token')
    with pytest.raises(m902.BrokerError) as exc:
        run(broker, **{'auth' if phase == 14 else 'catalog': fail})
    assert calls == [phase]
    assert str(exc.value) == 'STOPPED_NO_RETRY_OPERATOR_REVIEW_REQUIRED'
    assert read(broker.ledger)['attempts_used'] == phase
    assert read(broker.ledger)['attempts'][-1]['status'] == 'FAILED'
    assert 'fixture-secret' not in broker.ledger.read_text()
    with pytest.raises(m902.BrokerError): run(broker)


@pytest.mark.parametrize('status', [301, 401, 403, 429, 500, 503])
def test_catalog_status(broker, status):
    calls = []
    def fail(_): calls.append(status); return status, b'fixture-secret'
    with pytest.raises(m902.BrokerError): run(broker, catalog=fail)
    assert calls == [status]
    assert read(broker.ledger)['attempts_used'] == 15


@pytest.mark.parametrize('number', [1, 2, 3, 4, 5])
def test_storage_failure(broker, monkeypatch, number):
    real = m902.write
    count = 0
    calls = []
    def fail(*args, **kwargs):
        nonlocal count
        count += 1
        if count == number: raise OSError('fixture-secret')
        return real(*args, **kwargs)
    monkeypatch.setattr(m902, 'write', fail)
    def auth(_): calls.append(14); return 'fixture-token'
    def catalog(token): calls.append(15); return success(token)
    with pytest.raises(m902.BrokerError): run(broker, auth=auth, catalog=catalog)
    assert calls == {1: [], 2: [], 3: [14], 4: [14], 5: [14, 15]}[number]


@pytest.mark.parametrize('phase', [14, 15])
def test_process_crash_and_rollback(broker, phase):
    baseline = broker.ledger.read_bytes()
    pid = os.fork()
    if pid == 0:
        run(broker, auth=(lambda _: os._exit(77)) if phase == 14 else lambda _: 'fixture-token',
            catalog=lambda _: os._exit(77))
        os._exit(78)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 77
    assert read(broker.ledger)['attempts_used'] == phase
    assert read(broker.ledger)['attempts'][-1]['status'] == 'RESERVED'
    broker.ledger.write_bytes(baseline)
    # Independent claim survives ledger-only rollback, even a new approval nonce.
    approval = read(broker.approval)
    approval['nonce'] = 'c'*64
    write(broker.approval, approval, replace=True)
    with pytest.raises(m902.BrokerError): run(broker)
    assert read(broker.ledger)['attempts_used'] == 13


def test_ledger_tampering_and_ceiling(broker):
    value = read(broker.ledger)
    value['attempts'][0]['candidate_id'] = 'tampered'
    write(broker.ledger, value, replace=True)
    with pytest.raises(m902.BrokerError): run(broker)
    value['attempts_used'] = 49
    write(broker.ledger, value, replace=True)
    with pytest.raises(m902.BrokerError): run(broker)
    assert not broker.claim.exists()


def test_claim_before_reservation_failure_blocks_replay(broker):
    def fail(_): raise AssertionError('Must not dispatch')
    broker.credentials.unlink()
    with pytest.raises(m902.BrokerError): run(broker, auth=fail)
    assert broker.claim.exists()
    assert read(broker.ledger)['attempts_used'] == 13
    with pytest.raises(m902.BrokerError): run(broker, auth=fail)


def test_token_reference_disposal(broker, monkeypatch):
    import inspect
    real = m902.write
    def check(path, value, **kwargs):
        if value.get('attempts_used') == 15 and value['attempts'][-1]['status'] == 'COMPLETE':
            assert inspect.currentframe().f_back.f_locals['token'] is None
            assert inspect.currentframe().f_back.f_locals['response'] is None
        return real(path, value, **kwargs)
    monkeypatch.setattr(m902, 'write', check)
    run(broker)


def test_absolute_deadline(broker, monkeypatch):
    calls = []
    real = signal.alarm
    def alarm(seconds): calls.append(seconds); return real(seconds)
    monkeypatch.setattr(signal, 'alarm', alarm)
    run(broker)
    assert calls == [40, 0]


def test_offline_entrypoint(capsys, monkeypatch):
    monkeypatch.setattr(m902, 'execute', lambda *a, **kw: pytest.fail('execution in preflight'))
    assert m902.main() == 0
    assert json.loads(capsys.readouterr().out)['live_enabled'] is False


def test_success_replay_and_new_approval(broker):
    baseline = broker.ledger.read_bytes()
    run(broker)
    with pytest.raises(m902.BrokerError): run(broker)
    broker.ledger.write_bytes(baseline)
    with pytest.raises(m902.BrokerError): run(broker)


def test_concurrent_process(broker):
    ready_r, ready_w = os.pipe()
    done_r, done_w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(ready_r)
        os.close(done_w)
        with m902.existing(broker.account_lock, broker.account_identity, broker):
            os.write(ready_w, b'1')
            os.read(done_r, 1)
        os._exit(0)
    os.close(ready_w)
    os.close(done_r)
    try:
        assert os.read(ready_r, 1) == b'1'
        with pytest.raises(m902.BrokerError): run(broker)
        assert read(broker.ledger)['attempts_used'] == 13
    finally:
        os.write(done_w, b'1')
        os.waitpid(pid, 0)
        os.close(ready_r)
        os.close(done_w)
    run(broker)


@pytest.mark.parametrize('failure', ['claim_file', 'claim_directory', 'reservation_file', 'reservation_directory'])
def test_fsync_failure(broker, monkeypatch, failure):
    real = os.fsync
    calls = []
    count = 0
    target = {'claim_file': 1, 'claim_directory': 2, 'reservation_file': 3, 'reservation_directory': 4}[failure]
    def fsync(fd):
        nonlocal count
        count += 1
        if count == target: raise OSError('synthetic-fsync')
        return real(fd)
    monkeypatch.setattr(os, 'fsync', fsync)
    def auth(_): calls.append(14); return 'fixture-token'
    with pytest.raises(m902.BrokerError): run(broker, auth=auth)
    assert calls == []
    assert broker.claim.exists()


@pytest.mark.parametrize('status', [301, 401, 403, 429, 500, 503])
def test_auth_http_status(broker, monkeypatch, status):
    from app import m901
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, maximum):
            assert maximum == 65537
            return b'fixture-secret'
    Response.status = status
    class Connection:
        def __init__(self, host, **kwargs):
            assert host == 'api.amazon.com'
            assert kwargs['timeout'] == 10
            assert kwargs['context'].check_hostname
        def request(self, method, path, **kwargs):
            assert (method, path) == ('POST', '/auth/o2/token')
            calls.append(14)
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(m901.http.client, 'HTTPSConnection', Connection)
    with pytest.raises(m902.BrokerError): run(broker, auth=m901.authenticate)
    assert calls == [14]
    assert read(broker.ledger)['attempts_used'] == 14


def test_mocked_fixed_two_http_operations(broker, monkeypatch):
    from app import m901, m90
    calls = []
    class Response:
        status = 200
        def __init__(self, host): self.host = host
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, maximum):
            if self.host == 'api.amazon.com':
                return b'{"access_token":"fixture-token","expires_in":3600,"token_type":"bearer"}'
            return success('fixture-token')[1]
    class Connection:
        def __init__(self, host, **kwargs):
            self.host = host
            assert kwargs['context'].check_hostname
            assert kwargs['context'].verify_mode != 0
        def request(self, method, path, **kwargs): calls.append((self.host, method, path))
        def getresponse(self): return Response(self.host)
        def close(self): pass
    monkeypatch.setenv('HTTPS_PROXY', 'http://forbidden-proxy.invalid')
    monkeypatch.setattr(m901.http.client, 'HTTPSConnection', Connection)
    run(broker, auth=m901.authenticate, catalog=m90.send)
    assert calls == [('api.amazon.com', 'POST', '/auth/o2/token'),
                     ('sellingpartnerapi-na.amazon.com', 'GET', m90.TARGET)]


@pytest.mark.parametrize('checkpoint,used', [(1, 13), (2, 14), (3, 14), (4, 15), (5, 15)])
def test_crash_after_each_durable_write(broker, checkpoint, used):
    baseline = broker.ledger.read_bytes()
    pid = os.fork()
    if pid == 0:
        real = m902.write
        count = 0
        def crash(*args, **kwargs):
            nonlocal count
            real(*args, **kwargs)
            count += 1
            if count == checkpoint: os._exit(77)
        m902.write = crash
        run(broker)
        os._exit(78)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 77
    assert read(broker.ledger)['attempts_used'] == used
    broker.ledger.write_bytes(baseline)
    with pytest.raises(m902.BrokerError): run(broker)


def test_alarm_exception_charged(broker):
    def timeout(_):
        os.kill(os.getpid(), signal.SIGALRM)
        pytest.fail('Alarm ignored')
    with pytest.raises(m902.BrokerError): run(broker, auth=timeout)
    assert read(broker.ledger)['attempts_used'] == 14
    assert read(broker.ledger)['attempts'][-1]['status'] == 'FAILED'


def test_required_explicit_transports():
    # An internal core call cannot accidentally choose a live default transport.
    import inspect
    parameters = inspect.signature(m902.execute).parameters
    assert parameters['auth'].default is inspect.Parameter.empty
    assert parameters['catalog'].default is inspect.Parameter.empty


def test_replacement_during_open(broker, monkeypatch):
    real = os.open
    descriptors = []
    def replaced(path, flags, *args, **kwargs):
        fd = real(path, flags, *args, **kwargs)
        if path == broker.account_lock.name and flags & os.O_RDWR:
            descriptors.append(fd)
            broker.account_lock.rename(broker.root/'old-lock')
            write(broker.account_lock, {})
        return fd
    monkeypatch.setattr(os, 'open', replaced)
    with pytest.raises(m902.BrokerError): run(broker)
    assert len(descriptors) == 1
    with pytest.raises(OSError): os.fstat(descriptors[0])
    assert not broker.claim.exists()


@pytest.mark.parametrize('token', ['', 'x'*2049, 'has space', 'tab\t', '\u00e9'])
def test_invalid_auth_token(broker, token):
    with pytest.raises(m902.BrokerError): run(broker, auth=lambda _: token)
    assert read(broker.ledger)['attempts_used'] == 14
    assert read(broker.ledger)['attempts'][-1]['status'] == 'FAILED'


@pytest.mark.parametrize('raw', [b'x'*262145, b'{"asin":"OTHER"}', b'not-json'])
def test_bad_catalog_response(broker, raw):
    with pytest.raises(m902.BrokerError): run(broker, catalog=lambda _: (200, raw))
    assert read(broker.ledger)['attempts_used'] == 15
    assert read(broker.ledger)['attempts'][-1]['status'] == 'FAILED'


def test_expiration_between_requests(broker, monkeypatch):
    real = m902.authorize
    def short(*args):
        digest, _ = real(*args)
        return digest, datetime.now(timezone.utc)+timedelta(seconds=10)
    monkeypatch.setattr(m902, 'authorize', short)
    def auth(_):
        class ExpiredClock:
            @staticmethod
            def now(_): return datetime.now(timezone.utc)+timedelta(minutes=1)
        monkeypatch.setattr(m902, 'datetime', ExpiredClock)
        return 'fixture-token'
    with pytest.raises(m902.BrokerError): run(broker, auth=auth)
    assert read(broker.ledger)['attempts_used'] == 14
    assert read(broker.ledger)['attempts'][-1]['status'] == 'COMPLETE'


def test_inherited_alarm_rejected(broker):
    signal.alarm(60)
    try:
        with pytest.raises(m902.BrokerError): run(broker)
        assert not broker.claim.exists()
        assert signal.getitimer(signal.ITIMER_REAL)[0] > 0
    finally:
        signal.alarm(0)


def test_thread_rejected(broker):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as executor:
        with pytest.raises(m902.BrokerError): executor.submit(run, broker).result()
    assert not broker.claim.exists()


@pytest.mark.parametrize('problem', ['owner', 'writable'])
def test_untrusted_ancestor_rejected(broker, monkeypatch, problem):
    if problem == 'owner': fake_owner(monkeypatch, broker.root)
    else: broker.root.chmod(0o777)
    with pytest.raises(m902.BrokerError): run(broker)
    assert not broker.claim.exists()
