"""Synthetic credentials and mocked HTTP only; no live authorization or send."""
from email.message import EmailMessage
import io
import json
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
from app import gmail_api as gmail
from ops.gmail_stage_tracking import StageTracker


@pytest.mark.parametrize('failure_stage', ['token_refresh', 'message_submission', None])
def test_stage_evidence_and_redaction(tmp_path, monkeypatch, failure_stage):
    secret = 'DO-NOT-LOG-SYNTHETIC-SECRET'
    token = tmp_path / 'token.json'
    tmp_path.chmod(0o700)
    gmail.write_private(token, dict(client_id=secret, client_secret=secret,
        refresh_token=secret, scopes=[gmail.SCOPE]))
    error = HTTPError('https://example.invalid/'+secret, 400, secret,
        {'Authorization': secret}, io.BytesIO(secret.encode()))
    replies = ([error] if failure_stage == 'token_refresh' else
        [{'access_token': secret}, error] if failure_stage else
        [{'access_token': secret}, {'id': secret}])
    post = Mock(side_effect=replies)
    monkeypatch.setattr(gmail, 'post', post)
    log = tmp_path / 'stages.jsonl'
    tracker = StageTracker(log)
    if failure_stage:
        with pytest.raises(gmail.GmailError):
            gmail.send_message(EmailMessage(), token, observe=tracker)
    else:
        gmail.send_message(EmailMessage(), token, observe=tracker)
    rendered = log.read_text()
    assert secret not in rendered
    assert log.stat().st_mode & 0o777 == 0o600
    records = [json.loads(line) for line in rendered.splitlines()]
    if failure_stage:
        assert records[-1]['stage'] == failure_stage
        assert records[-1]['status'] == 'failed'
        assert records[-1]['http_status'] == 400
        assert not tracker.acceptance_observed
        assert tracker.submission_started == (failure_stage == 'message_submission')
        assert post.call_count == (1 if failure_stage == 'token_refresh' else 2)
    else:
        assert tracker.acceptance_observed
        assert tracker.last_completed == 'acceptance_validation'


def test_tracker_filters_untrusted_details(tmp_path):
    tracker = StageTracker(tmp_path/'stages')
    tracker('token_refresh', 'failed', error_category='secret', errno='secret', body='secret')
    assert 'secret' not in tracker.path.read_text()


def test_missing_acknowledgement_does_not_claim_acceptance(tmp_path, monkeypatch):
    monkeypatch.setattr(gmail, 'read_private', lambda _: dict(client_id='x', client_secret='x', refresh_token='x', scopes=[gmail.SCOPE]))
    monkeypatch.setattr(gmail, 'post', Mock(side_effect=[{'access_token':'x'}, {}]))
    tracker = StageTracker(tmp_path/'stages')
    with pytest.raises(gmail.GmailError):
        gmail.send_message(EmailMessage(), tmp_path/'unused', observe=tracker)
    assert tracker.last_completed == 'message_submission'
    assert tracker.submission_started and not tracker.acceptance_observed


def test_existing_marker_prevents_any_token_or_network_operation(tmp_path, monkeypatch):
    from ops import gmail_api_demo_third as demo
    marker = tmp_path/'api.attempted'
    marker.write_bytes(b'preserve this existing evidence')
    monkeypatch.setattr(demo, 'MARKER', marker)
    monkeypatch.setattr(demo, 'build_message', lambda _: EmailMessage())
    reader, sender = Mock(), Mock()
    monkeypatch.setattr(gmail, 'read_private', reader)
    monkeypatch.setattr(demo, 'send_message', sender)
    with pytest.raises(FileExistsError):
        demo.execute('fixture@gmail.com')
    reader.assert_not_called()
    sender.assert_not_called()
    assert marker.read_bytes() == b'preserve this existing evidence'


@pytest.mark.parametrize('body, expected', [
    ({'error': {'code':403, 'message':'SECRET', 'status':'PERMISSION_DENIED',
      'errors':[{'reason':'accessNotConfigured', 'message':'SECRET'}],
      'details':[{'reason':'SERVICE_DISABLED', 'metadata':{'secret':'SECRET'}}]}},
     ['PERMISSION_DENIED', 'SERVICE_DISABLED', 'accessNotConfigured']),
    ({'error':'invalid_grant', 'error_description':'SECRET'}, ['invalid_grant']),
    ({'error':{'errors':[{'reason':'SECRET'}], 'status':'SECRET'}}, []),
    ([], []),
])
def test_safe_reason_reporting(tmp_path, monkeypatch, body, expected):
    monkeypatch.setattr(gmail, 'read_private', lambda _: dict(client_id='x', client_secret='x', refresh_token='x', scopes=[gmail.SCOPE]))
    error = HTTPError('https://example.invalid/SECRET',403,'SECRET',{},io.BytesIO(json.dumps(body).encode()))
    post = Mock(side_effect=[{'access_token':'SECRET'}, error])
    monkeypatch.setattr(gmail, 'post', post)
    tracker = StageTracker(tmp_path/'stages')
    with pytest.raises(gmail.GmailError) as caught:
        gmail.send_message(EmailMessage(), tmp_path/'unused', observe=tracker)
    assert post.call_count == 2
    assert 'SECRET' not in tracker.path.read_text()
    assert 'SECRET' not in str(caught.value)
    last = json.loads(tracker.path.read_text().splitlines()[-1])
    assert last['google_reasons'] == expected
    assert last['http_status'] == 403
    assert last['stage'] == 'message_submission'


@pytest.mark.parametrize('raw', [b'not json SECRET', b'x'*16385])
def test_malformed_or_oversized_error_omits_reasons(raw):
    stream = io.BytesIO(raw)
    error = HTTPError('https://example.invalid',400,'SECRET',{},stream)
    assert gmail.safe_google_reasons(error) == []
    assert stream.tell() <= 16385
