"""Mock transport only; fixtures never access real OAuth credentials."""
import io
import json
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
from ops import gmail_refresh_diagnostic as diagnostic


class Response(io.BytesIO):
    code = 200


@pytest.fixture
def setup(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    token = tmp_path/'token.json'
    token.write_text(json.dumps(dict(client_id='fake-client', client_secret='fake-secret',
        refresh_token='fake-refresh', scopes=[diagnostic.SCOPE])))
    token.chmod(0o600)
    marker = tmp_path/'refresh.attempted'
    monkeypatch.setattr(diagnostic, 'TOKEN_FILE', token)
    monkeypatch.setattr(diagnostic, 'RESERVATION', marker)
    opener = Mock()
    monkeypatch.setattr(diagnostic, 'build_opener', Mock(return_value=opener))
    return token, marker, opener


def test_one_request_success_no_token_write_or_second_request(setup):
    token, marker, opener = setup
    original = token.read_bytes()
    opener.open.return_value = Response(json.dumps(dict(access_token='secret-access',
        token_type='Bearer', refresh_token='secret-rotation', scope=diagnostic.SCOPE)).encode())
    assert diagnostic.run() == dict(success=True, http_status=200, oauth_error=None)
    request = opener.open.call_args.args[0]
    assert request.full_url == 'https://oauth2.googleapis.com/token'
    assert request.method == 'POST'
    assert opener.open.call_args.kwargs == dict(timeout=15)
    assert token.read_bytes() == original
    assert marker.stat().st_mode & 0o777 == 0o600
    assert diagnostic.run() == diagnostic.result()
    assert opener.open.call_count == 1


@pytest.mark.parametrize('error_name, expected', [('invalid_grant','invalid_grant'),
    ('invalid_client','invalid_client'), ('secret-unrecognized',None)])
def test_http_error_allowlist_no_raw_response(setup, error_name, expected, capsys):
    _, marker, opener = setup
    opener.open.side_effect = HTTPError('https://example.invalid/secret', 400, 'secret',
        {'secret':'secret'}, io.BytesIO(json.dumps(dict(error=error_name,
        error_description='secret-description', access_token='secret-token')).encode()))
    output = diagnostic.run()
    assert output == dict(success=False, http_status=400, oauth_error=expected)
    assert 'secret' not in json.dumps(output)
    assert capsys.readouterr().out == ''
    assert marker.exists() and opener.open.call_count == 1


@pytest.mark.parametrize('payload', [b'not-json-secret', b'[]', b'{}',
    b'x'*65537, b'{"access_token":"secret","token_type":"Bearer","scope":"broader"}'])
def test_bad_response_is_redacted(setup, payload):
    _, _, opener = setup
    opener.open.return_value = Response(payload)
    assert diagnostic.run() == diagnostic.result(http_status=200)
    assert opener.open.call_count == 1


def test_timeout_no_retry_and_reservation_preserved(setup):
    _, marker, opener = setup
    opener.open.side_effect = TimeoutError('secret')
    assert diagnostic.run() == diagnostic.result()
    assert marker.exists()
    assert opener.open.call_count == 1


@pytest.mark.parametrize('fault', ['permissions', 'symlink', 'fields', 'scope'])
def test_local_failures_do_not_connect(setup, fault):
    token, marker, opener = setup
    if fault == 'permissions':
        token.chmod(0o644)
    elif fault == 'symlink':
        token.unlink()
        token.symlink_to(token.parent/'absent')
    else:
        data = json.loads(token.read_text())
        if fault == 'fields':
            del data['refresh_token']
        else:
            data['scopes'] = ['broader']
        token.write_text(json.dumps(data))
    assert diagnostic.run() == diagnostic.result()
    opener.open.assert_not_called()
    assert not marker.exists()


def test_redirect_not_followed():
    assert diagnostic.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid') is None


def test_main_bounds_deadline_and_outputs_only_schema(monkeypatch, capsys):
    alarm, signal = Mock(), Mock()
    monkeypatch.setattr(diagnostic.signal, 'alarm', alarm)
    monkeypatch.setattr(diagnostic.signal, 'signal', signal)
    monkeypatch.setattr(diagnostic.resource, 'setrlimit', Mock())
    monkeypatch.setattr(diagnostic, 'run', Mock(return_value=diagnostic.result()))
    assert diagnostic.main() == 1
    assert json.loads(capsys.readouterr().out) == diagnostic.result()
    assert [call.args[0] for call in alarm.call_args_list] == [40, 0]
