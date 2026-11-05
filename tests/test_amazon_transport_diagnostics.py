import errno
import json
from pathlib import Path
import socket
import ssl
from unittest.mock import Mock
from urllib.error import URLError

import pytest

from app import amazon_pilot as pilot
from app.amazon_diagnostics import AmazonFailure, failure_metadata
from app.amazon_transport_diagnostics import classify_transport, local_socket_readiness
from app.m89_auth_readiness import no_dispatch
from app.m89_auth_readiness import diagnose, file_hash
from app.m88_state import read, sha, write
from app.m89 import LEDGER

SECRET = 'synthetic-private-value-never-log'


@pytest.mark.parametrize('underlying,category', [
    (PermissionError(errno.EPERM, SECRET), 'network_permission_denied'),
    (PermissionError(errno.EACCES, SECRET), 'network_permission_denied'),
    (socket.gaierror(socket.EAI_AGAIN, SECRET), 'dns_resolution'),
    (ssl.SSLCertVerificationError(1, SECRET), 'tls_certificate_verification'),
    (ssl.SSLError(1, SECRET), 'tls_error'),
    (TimeoutError(SECRET), 'timeout'),
    (ConnectionRefusedError(errno.ECONNREFUSED, SECRET), 'connection_refused'),
    (OSError(errno.ENETUNREACH, SECRET), 'network_unreachable'),
    (ValueError(SECRET), 'unclassified_transport_error'),
])
def test_nested_transport_error_retains_category_without_secrets(monkeypatch, underlying, category):
    opener = Mock()
    opener.open.side_effect = URLError(underlying)
    monkeypatch.setattr(pilot, 'build_opener', lambda *args: opener)
    with pytest.raises(AmazonFailure) as raised:
        pilot._request_json(pilot.Request('https://example.invalid/' + SECRET))
    meta = failure_metadata(raised.value)
    assert meta['reason'] == 'transport_error'
    assert meta['http_status'] is None
    assert meta['transport']['category'] == category
    assert meta['transport']['stage'] == 'open'
    assert opener.open.call_count == 1
    assert SECRET not in json.dumps(meta)
    assert SECRET not in str(raised.value)


def test_tls_setup_failure_has_distinct_stage_and_no_dispatch(monkeypatch):
    opener = Mock()
    monkeypatch.setattr(pilot, 'build_opener', opener)
    def fail():
        raise ssl.SSLError(1, SECRET)
    monkeypatch.setattr(pilot.ssl, 'create_default_context', fail)
    with pytest.raises(AmazonFailure) as raised:
        pilot._request_json(pilot.Request('https://example.invalid'))
    assert failure_metadata(raised.value)['transport']['stage'] == 'tls_context'
    opener.assert_not_called()


def test_read_timeout_preserves_received_status_and_read_stage(monkeypatch):
    response = Mock(status=200, headers={})
    response.read.side_effect = TimeoutError(SECRET)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(pilot, 'build_opener', lambda *args: opener)
    with pytest.raises(AmazonFailure) as raised:
        pilot._request_json(pilot.Request('https://example.invalid'))
    safe = failure_metadata(raised.value)
    assert safe['http_status'] == 200
    assert safe['transport']['stage'] == 'read'
    assert safe['transport']['category'] == 'timeout'


def test_permission_denied_unconnected_socket_probe_never_resolves_or_connects(monkeypatch):
    factory = Mock(side_effect=PermissionError(errno.EPERM, SECRET))
    monkeypatch.setattr(socket, 'socket', factory)
    dns = Mock(side_effect=AssertionError('DNS forbidden'))
    monkeypatch.setattr(socket, 'getaddrinfo', dns)
    result = local_socket_readiness()
    assert factory.call_count == 2
    assert result['amazon_http_attempts'] == 0
    assert result['local_socket_ready'] is False
    assert all(v['errno'] == errno.EPERM for v in result['socket_checks'].values())
    assert SECRET not in json.dumps(result)
    dns.assert_not_called()


def test_constructible_sockets_do_not_claim_remote_readiness(monkeypatch):
    mock_socket = Mock()
    mock_socket.__enter__ = Mock(return_value=mock_socket)
    mock_socket.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(socket, 'socket', Mock(return_value=mock_socket))
    result = local_socket_readiness()
    assert result['local_socket_ready'] is True
    assert result['remote_connectivity'] == 'UNTESTED'
    mock_socket.connect.assert_not_called()
    mock_socket.send.assert_not_called()


def test_audit_guard_prohibits_even_local_dns_and_http_before_dispatch():
    import sys
    with no_dispatch():
        for event in ('socket.getaddrinfo', 'socket.connect', 'socket.sendto', 'http.client.connect', 'subprocess.Popen'):
            with pytest.raises(PermissionError, match='prohibits dispatch'):
                sys.audit(event)
    # Context resets rather than disabling future unrelated application work.
    sys.audit('socket.getaddrinfo')


def test_type_and_errno_are_bounded_not_arbitrary_strings():
    class PrivateException(Exception):
        errno = SECRET
    result = classify_transport(PrivateException(SECRET), SECRET)
    assert result == dict(category='unclassified_transport_error', stage='other', exception='OTHER', errno=None)


def test_readiness_report_preserves_ledger_and_evidence_without_dispatch(tmp_path, monkeypatch):
    root = tmp_path / 'var' / 'm88-real-six-pilot'
    root.mkdir(parents=True, mode=0o700)
    account_dir = tmp_path / 'private'
    account_dir.mkdir(mode=0o700)
    write(account_dir / 'credentials.json', dict(client_id=SECRET, client_secret=SECRET, refresh_token=SECRET))
    write(account_dir / 'm67-account-context.json', dict(credentials_sha256=sha(account_dir / 'credentials.json'),
                                                      marketplace_id='ATVPDKIKX0DER', condition='new_new', seller_id=SECRET))
    attempts = [dict(number=i, phase='search', status='COMPLETE', candidate_id='fixture') for i in range(1, 13)]
    for folder, number in (('m88-executor-v1-20261105T0301Z', 1), ('m88-targeted-verification-v1', 8)):
        directory = root / folder
        directory.mkdir(mode=0o700)
        write(directory / 'plan.json', dict(implementation_sha256={'amazon_pilot.py': 'same-historic-hash'}))
        write(directory / f'receipt-{number}.json', dict(observed_at='2026-11-05T00:00:00+00:00', evidence={'token_received': True}))
        attempts[number - 1].update(phase='authentication', plan_sha256=sha(directory / 'plan.json'),
                                    receipt_sha256=sha(directory / f'receipt-{number}.json'))
    directory = root.parent / 'm89-read-only-v1'
    directory.mkdir(mode=0o700)
    write(directory / 'plan.json', dict(implementation_sha256={'amazon_pilot.py': 'same-historic-hash'}))
    attempts[-1].update(phase='authentication', status='FAILED', plan_sha256=sha(directory / 'plan.json'),
                        failure=dict(reason='transport_error', exception='AmazonFailure', errno=None, http_status=None))
    ledger_path = root / LEDGER
    ledger_path.parent.mkdir(mode=0o700)
    write(ledger_path, dict(pilot='m88-real-six-pilot', ceiling=49, purchase_authorized=False,
                           includes_authentication_and_retries=True, attempts_used=12, attempts=attempts))
    inputs = tmp_path / 'inputs'
    inputs.mkdir(mode=0o700)
    inventory = {str(p): file_hash(p) for p in root.parent.rglob('*') if p.is_file()}
    inventory_path = inputs / 'inventory.json'
    write(inventory_path, inventory)
    monkeypatch.setattr(socket, 'socket', Mock(side_effect=PermissionError(errno.EPERM, SECRET)))
    live_transport = Mock(side_effect=AssertionError('live dispatch forbidden'))
    monkeypatch.setattr(pilot, '_request_json', live_transport)
    output = tmp_path / 'readiness'
    report = diagnose(root, account_dir, inventory_path, output)
    assert report['additional_amazon_http_attempts'] == 0
    assert report['cumulative_attempts'] == 12 and report['remaining_attempts'] == 37
    assert report['ledger_status_counts'] == dict(COMPLETE=11, FAILED=1, RESERVED=0)
    assert report['live_retry_now_justified'] is False
    assert report['original_root_cause_certainty'] == 'INFERRED_NOT_PROVEN'
    assert report['failed_authentication_receipt_present'] is False
    assert report['credentials']['remote_validity'] == 'UNTESTED'
    assert SECRET not in (output / 'authentication-readiness.json').read_text()
    assert all(file_hash(Path(p)) == digest for p, digest in inventory.items())
    live_transport.assert_not_called()
    assert read(ledger_path)['attempts_used'] == 12
