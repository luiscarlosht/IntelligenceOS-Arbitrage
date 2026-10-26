"""Attempt 2 tests use synthetic credentials and mocked HTTP only."""
import base64
from email import policy
from email.parser import BytesParser
import io
import json
from unittest.mock import Mock
from urllib.request import ProxyHandler

import pytest
from app import gmail_api as gmail
from ops import gmail_api_demo_second as demo


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    directory = tmp_path/'var/demo'
    directory.mkdir(parents=True)
    (tmp_path/'var/diagnostics').mkdir()
    for name in ('DEMO.xlsx', 'DEMO.md'):
        (directory/name).write_bytes((name+' synthetic attachment').encode())
    token = tmp_path/'token.json'
    gmail.write_private(token, dict(client_id='synthetic-id', client_secret='synthetic-secret',
        refresh_token='synthetic-refresh', scopes=[gmail.SCOPE]))
    monkeypatch.setattr(demo, 'ROOT', tmp_path)
    monkeypatch.setattr(demo, 'TOKEN_FILE', token)
    monkeypatch.setattr(demo, 'MARKER', tmp_path/'var/diagnostics/gmail-api-demo-2.attempted')
    monkeypatch.setattr(demo, 'STAGES', tmp_path/'var/diagnostics/gmail-api-demo-2.stages.jsonl')
    return tmp_path, token


def test_second_attempt_exact_mime_requests_and_preserved_old_markers(prepared, monkeypatch):
    root, token = prepared
    old_markers = [root/'var/diagnostics/gmail-api-demo.attempted', root/'var/diagnostics/gmail-demo.attempted', root/'refresh-diagnostic.attempted']
    for marker in old_markers:
        marker.write_bytes(b'preserve historical evidence')
    original = token.read_bytes()
    post = Mock(side_effect=[dict(access_token='synthetic-access', token_type='Bearer', scope=gmail.SCOPE), dict(id='synthetic-accepted')])
    monkeypatch.setattr(gmail, 'post', post)
    tracker = demo.execute('fixture@gmail.com')
    assert tracker.acceptance_observed
    assert post.call_count == 2
    assert post.call_args_list[0].args[0] == gmail.TOKEN_URL
    url, body, headers = post.call_args_list[1].args
    assert url == gmail.SEND_URL
    assert headers == {'Content-Type':'application/json', 'Authorization':'Bearer synthetic-access'}
    message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(json.loads(body)['raw']))
    assert str(message['To']) == demo.RECIPIENT
    assert message.get_all('Cc') is None and message.get_all('Bcc') is None
    assert str(message['Subject']) == 'Arbitrage fictional DEMO — Gmail API attempt 2'
    assert [(p.get_filename(), p.get_payload(decode=True)) for p in message.iter_attachments()] == [(name, (name+' synthetic attachment').encode()) for name in ('DEMO.xlsx','DEMO.md')]
    assert token.read_bytes() == original
    assert all(p.read_bytes() == b'preserve historical evidence' for p in old_markers)
    assert 'synthetic-access' not in demo.STAGES.read_text()
    assert 'synthetic-secret' not in demo.STAGES.read_text()
    assert demo.MARKER.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        demo.execute('fixture@gmail.com')
    assert post.call_count == 2


@pytest.mark.parametrize('bad_response', [dict(access_token='x', scope=''),
    dict(access_token='x', token_type='MAC'), dict(access_token='x', error='invalid_grant'),
    dict(access_token='x', refresh_token=123)])
def test_invalid_refresh_response_stops_before_send(prepared, monkeypatch, bad_response):
    post = Mock(return_value=bad_response)
    monkeypatch.setattr(gmail, 'post', post)
    with pytest.raises(gmail.GmailError):
        demo.execute('fixture@gmail.com')
    assert post.call_count == 1
    last = json.loads(demo.STAGES.read_text().splitlines()[-1])
    assert last['stage'] == 'refresh_response_validation'
    assert last['status'] == 'failed'
    assert not last['submission_started']


@pytest.mark.parametrize('stage', ['refresh', 'submission'])
def test_timeout_no_retries_precise_stage(prepared, monkeypatch, stage):
    post = Mock(side_effect=[TimeoutError('secret')] if stage == 'refresh' else
        [dict(access_token='synthetic-access'), TimeoutError('secret')])
    monkeypatch.setattr(gmail, 'post', post)
    with pytest.raises(gmail.GmailError):
        demo.execute('fixture@gmail.com')
    last = json.loads(demo.STAGES.read_text().splitlines()[-1])
    assert last['stage'] == ('token_refresh' if stage == 'refresh' else 'message_submission')
    assert last['submission_started'] == (stage == 'submission')
    assert not last['acceptance_observed']
    assert post.call_count == (1 if stage == 'refresh' else 2)
    assert demo.MARKER.exists()


def test_post_disables_proxies_explicit_post_and_timeout(monkeypatch):
    response = io.BytesIO(b'{"id":"synthetic"}')
    opener = Mock()
    opener.open.return_value = response
    factory = Mock(return_value=opener)
    monkeypatch.setattr(gmail, 'build_opener', factory)
    assert gmail.post(gmail.SEND_URL, b'{}', {'Content-Type':'application/json'}) == dict(id='synthetic')
    handlers = factory.call_args.args
    assert any(isinstance(h, ProxyHandler) and h.proxies == {} for h in handlers)
    assert any(isinstance(h, gmail.NoRedirect) for h in handlers)
    assert opener.open.call_args.args[0].method == 'POST'
    assert opener.open.call_args.kwargs['timeout'] == 30


def test_missing_attachment_reserved_and_logged(prepared, monkeypatch):
    root, _ = prepared
    (root/'var/demo/DEMO.md').unlink()
    post = Mock()
    monkeypatch.setattr(gmail, 'post', post)
    with pytest.raises(ValueError):
        demo.execute('fixture@gmail.com')
    post.assert_not_called()
    assert demo.MARKER.exists()
    last = json.loads(demo.STAGES.read_text().splitlines()[-1])
    assert last['stage'] == 'message_construction' and last['status'] == 'failed'


def test_total_deadline(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['demo', '--sender','fixture@gmail.com','--send'])
    alarm = Mock()
    monkeypatch.setattr(demo.signal, 'alarm', alarm)
    monkeypatch.setattr(demo.signal, 'signal', Mock())
    monkeypatch.setattr(demo.resource, 'setrlimit', Mock())
    monkeypatch.setattr(demo, 'execute', Mock(side_effect=TimeoutError('secret')))
    assert demo.main() == 1
    assert [c.args[0] for c in alarm.call_args_list] == [90,0]
    assert 'secret' not in capsys.readouterr().out
