"""All OAuth and HTTPS calls are mocked; never submit email."""
import base64
import json
import traceback
from dataclasses import replace
from email import policy
from email.parser import BytesParser
from unittest.mock import Mock

import pytest
from app import gmail_api as gmail
from app.config import Config
from app.mailer import send_report


@pytest.fixture
def token(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / 'token.json'
    gmail.write_private(path, dict(client_id='id', client_secret='secret', refresh_token='refresh', scopes=[gmail.SCOPE]))
    return path


def test_attachment_and_routing(token, tmp_path, monkeypatch):
    post = Mock(side_effect=[{'access_token': 'access'}, {'id': 'accepted'}])
    monkeypatch.setattr(gmail, 'post', post)
    smtp = Mock(side_effect=AssertionError('SMTP must not be used'))
    monkeypatch.setattr('app.mailer.smtplib.SMTP', smtp)
    report = tmp_path / 'report.xlsx'
    report.write_bytes(b'xlsx-bytes')
    config = Config(tmp_path/'in', report, tmp_path/'db', email_transport='gmail_api',
                    gmail_token_file=token, email_from='sender@gmail.com', email_to=('receiver@example.com',))
    assert send_report(config, report, 'demo')
    assert post.call_args_list[0].args[0] == gmail.TOKEN_URL
    assert b'refresh_token=refresh' in post.call_args_list[0].args[1]
    url, body, headers = post.call_args.args
    assert url == gmail.SEND_URL
    assert headers['Authorization'] == 'Bearer access'
    message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(json.loads(body)['raw']))
    attachment, = message.iter_attachments()
    assert attachment.get_filename() == 'report.xlsx'
    assert attachment.get_payload(decode=True) == b'xlsx-bytes'
    assert message['To'] == 'receiver@example.com'
    assert replace(config, email_to=()).email_transport == 'gmail_api'


@pytest.mark.parametrize('stage', ['refresh', 'send'])
def test_redacted_no_retries(token, monkeypatch, stage):
    post = Mock(side_effect=[RuntimeError('secret refresh access')] if stage == 'refresh' else
                [{'access_token': 'access'}, RuntimeError('secret refresh access')])
    monkeypatch.setattr(gmail, 'post', post)
    from email.message import EmailMessage
    with pytest.raises(gmail.GmailError) as caught:
        gmail.send_message(EmailMessage(), token)
    rendered = ''.join(traceback.format_exception(caught.value))
    assert 'secret refresh access' not in rendered
    assert caught.value.__context__ is None
    assert post.call_count == (1 if stage == 'refresh' else 2)


def test_private_files(token, tmp_path):
    assert token.stat().st_mode & 0o777 == 0o600
    token.chmod(0o644)
    with pytest.raises(gmail.GmailError):
        gmail.read_private(token)
    link = tmp_path/'link'
    link.symlink_to(token)
    with pytest.raises(OSError):
        gmail.read_private(link)
    tmp_path.chmod(0o755)
    with pytest.raises(gmail.GmailError):
        gmail.write_private(token, {})


def test_broad_scope_rejected(token, monkeypatch):
    data = gmail.read_private(token)
    data['scopes'].append('https://mail.google.com/')
    gmail.write_private(token, data)
    post = Mock()
    monkeypatch.setattr(gmail, 'post', post)
    with pytest.raises(gmail.GmailError):
        gmail.send_message(None, token)
    post.assert_not_called()


def test_redirects_denied():
    assert gmail.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com') is None


def test_authorization_only(token, tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from ops.gmail_authorize import authorize
    client = tmp_path/'client.json'
    gmail.write_private(client, {'installed': {'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                                             'token_uri': gmail.TOKEN_URL}})
    creds = SimpleNamespace(refresh_token='refresh', client_id='id', client_secret='secret',
                            scopes=[gmail.SCOPE], granted_scopes=[gmail.SCOPE])
    flow = Mock()
    flow.run_local_server.return_value = creds
    factory = Mock(return_value=flow)
    monkeypatch.setitem(sys.modules, 'google_auth_oauthlib', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'google_auth_oauthlib.flow',
                        SimpleNamespace(InstalledAppFlow=SimpleNamespace(from_client_config=factory)))
    post = Mock(side_effect=AssertionError('no sending during consent'))
    monkeypatch.setattr(gmail, 'post', post)
    target = tmp_path/'new-token.json'
    authorize(client, target)
    assert gmail.read_private(target)['scopes'] == [gmail.SCOPE]
    factory.assert_called_once_with(gmail.read_private(client), scopes=[gmail.SCOPE], autogenerate_code_verifier=True)
    args = flow.run_local_server.call_args.kwargs
    assert args['host'] == '127.0.0.1'
    assert args['access_type'] == 'offline'
    assert args['prompt'] == 'consent'
    post.assert_not_called()
    with pytest.raises(gmail.GmailError):
        authorize(client, target)
    assert factory.call_count == 1


def test_rotated_refresh_saved(token, monkeypatch):
    from email.message import EmailMessage
    monkeypatch.setattr(gmail, 'post', Mock(side_effect=[
        {'access_token': 'access', 'refresh_token': 'rotated'}, {'id': 'ok'}]))
    gmail.send_message(EmailMessage(), token)
    assert gmail.read_private(token)['refresh_token'] == 'rotated'
    assert 'access_token' not in gmail.read_private(token)
