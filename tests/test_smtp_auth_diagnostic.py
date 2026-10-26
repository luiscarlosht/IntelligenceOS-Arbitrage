"""No live SMTP; strict mock exposes only the permitted operations."""
import smtplib
import ssl
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from ops import smtp_auth_diagnostic as diagnostic


@pytest.fixture
def setup(monkeypatch):
    client = Mock(spec_set=['ehlo', 'starttls', 'login', 'close', 'diagnostic_stage', 'esmtp_features'])
    client.ehlo.return_value = (250, b'ok')
    client.esmtp_features = {'auth': 'PLAIN LOGIN'}
    factory = Mock(return_value=client)
    prompt = Mock(return_value='secret-value')
    monkeypatch.setattr(diagnostic, 'TrackedSMTP', factory)
    monkeypatch.setattr(diagnostic, 'load_credential', prompt)
    monkeypatch.setattr(diagnostic, 'sys', SimpleNamespace(
        stdin=SimpleNamespace(isatty=lambda: True),
        stderr=SimpleNamespace(isatty=lambda: True)))
    monkeypatch.setattr(diagnostic.resource, 'setrlimit', Mock())
    return client, factory, prompt


def test_success_verified_tls_and_auth_only(setup, capsys):
    client, factory, _ = setup
    assert diagnostic.main() == 0
    factory.assert_called_once_with('smtp.sendgrid.net', 2525, timeout=30)
    assert [call[0] for call in client.mock_calls] == [
        'ehlo', 'starttls', 'ehlo', 'login', 'close']
    context = client.starttls.call_args.kwargs['context']
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED
    client.login.assert_called_once_with('apikey', 'secret-value')
    assert 'secret-value' not in capsys.readouterr().out


@pytest.mark.parametrize('operation', ['ehlo', 'starttls', 'login'])
def test_failures_are_redacted_without_retry(setup, capsys, operation):
    client, factory, _ = setup
    getattr(client, operation).side_effect = smtplib.SMTPException('secret-value')
    assert diagnostic.main() == 1
    assert 'secret-value' not in capsys.readouterr().out
    factory.assert_called_once()
    client.close.assert_called_once()
    if operation != 'login':
        client.login.assert_not_called()


def test_post_tls_ehlo_failure_blocks_auth(setup):
    client, _, _ = setup
    client.ehlo.side_effect = [(250, b'ok'), (500, b'private reply')]
    assert diagnostic.main() == 1
    client.login.assert_not_called()


def test_nonterminal_stops_before_prompt_or_connection(setup, monkeypatch):
    _, factory, prompt = setup
    monkeypatch.setattr(diagnostic.sys.stdin, 'isatty', lambda: False)
    assert diagnostic.main() == 1
    prompt.assert_not_called()
    factory.assert_not_called()



def test_loader_failure_never_connects(setup, capsys):
    _, factory, loader = setup
    loader.side_effect = ValueError('secret-value')
    assert diagnostic.main() == 1
    assert 'secret-value' not in capsys.readouterr().out
    factory.assert_not_called()


def test_ambiguity_reports_names_only(setup, capsys):
    _, factory, loader = setup
    loader.side_effect = diagnostic.AmbiguousCredential(['SMTP_PASSWORD', 'SMTP_APP_PASSWORD'])
    assert diagnostic.main() == 1
    output = capsys.readouterr().out
    assert 'SMTP_PASSWORD' in output and 'SMTP_APP_PASSWORD' in output
    factory.assert_not_called()


@pytest.mark.parametrize(('text', 'selection', 'expected'), [
    ('SMTP_APP_PASSWORD=first', None, 'first'),
    ('SMTP_PASSWORD=second', None, 'second'),
    ('SMTP_APP_PASSWORD=first\nSMTP_PASSWORD=second', 'SMTP_PASSWORD', 'second'),
    ('SMTP_APP_PASSWORD=first\nSMTP_PASSWORD=second', 'SMTP_APP_PASSWORD', 'first'),
    ("export SMTP_PASSWORD='quoted-value' # comment\nUNRELATED=$(ignored)", None, 'quoted-value'),
])
def test_loader_selection(tmp_path, monkeypatch, text, selection, expected):
    path = tmp_path / 'synthetic.env'
    path.write_text(text)
    monkeypatch.setattr(diagnostic, 'ENV_PATH', path)
    assert diagnostic.load_credential(selection) == expected
    assert path.read_text() == text


@pytest.mark.parametrize('text', [
    'SMTP_PASSWORD=one\nSMTP_APP_PASSWORD=two',
    'SMTP_PASSWORD=same\nSMTP_APP_PASSWORD=same',
    'SMTP_PASSWORD=one\nSMTP_PASSWORD=two',
    'SMTP_PASSWORD=$SMTP_APP_PASSWORD',
    'SMTP_PASSWORD=$(command)',
    'SMTP_PASSWORD=`command`',
    'SMTP_PASSWORD="bad key"',
    'SMTP_PASSWORD=',
    'UNRELATED=value',
    "SMTP_PASSWORD='unterminated",
])
def test_loader_fails_closed(tmp_path, monkeypatch, text):
    path = tmp_path / 'synthetic.env'
    path.write_text(text)
    monkeypatch.setattr(diagnostic, 'ENV_PATH', path)
    with pytest.raises((ValueError, diagnostic.AmbiguousCredential)):
        diagnostic.load_credential()


def test_explicit_missing_variable_does_not_fallback(tmp_path, monkeypatch):
    path = tmp_path / 'synthetic.env'
    path.write_text('SMTP_PASSWORD=synthetic')
    monkeypatch.setattr(diagnostic, 'ENV_PATH', path)
    with pytest.raises(ValueError):
        diagnostic.load_credential('SMTP_APP_PASSWORD')


def test_advertised_mechanisms_never_echo_unknown_tokens(capsys):
    diagnostic.report_auth_mechanisms({'auth': 'PLAIN LOGIN secret-value c2VjcmV0'})
    output = capsys.readouterr().out
    assert 'PLAIN, LOGIN' in output
    assert 'unrecognized_count=2' in output
    assert 'secret-value' not in output and 'c2VjcmV0' not in output


def scripted_client(monkeypatch, advertised, responses):
    # An empty host constructs the SMTP object without connecting.
    client = diagnostic.TrackedSMTP()
    client.ehlo_resp = b'fixture'
    client.esmtp_features = {'auth': advertised}
    client.diagnostic_stage = 'authenticate'
    # Replaces every protocol exchange. Real login/auth selection stays intact.
    exchange = Mock(side_effect=responses)
    monkeypatch.setattr(client, 'docmd', exchange)
    return client, exchange


def test_real_login_prefers_cram_md5_then_plain_then_login(monkeypatch, capsys):
    client, exchange = scripted_client(monkeypatch, 'LOGIN PLAIN CRAM-MD5', [
        (535, b'secret-value'), (535, b'secret-value'), (235, b'secret-value')])
    assert client.debuglevel == 0
    assert client.login('apikey', 'synthetic-key')[0] == 235
    assert exchange.call_count == 3
    output = capsys.readouterr().out
    assert output.splitlines() == [
        'Authentication mechanism attempted: CRAM-MD5',
        'Authentication mechanism attempted: PLAIN',
        'Authentication mechanism attempted: LOGIN']


def test_real_login_selects_plain_before_login(monkeypatch, capsys):
    client, exchange = scripted_client(monkeypatch, 'LOGIN PLAIN', [(235, b'secret-value')])
    assert client.login('apikey', 'synthetic-key')[0] == 235
    assert exchange.call_count == 1
    assert capsys.readouterr().out.strip() == 'Authentication mechanism attempted: PLAIN'


def test_real_login_disconnect_does_not_fallback(monkeypatch, capsys):
    client, exchange = scripted_client(monkeypatch, 'PLAIN LOGIN', [
        smtplib.SMTPServerDisconnected('secret-value')])
    with pytest.raises(smtplib.SMTPServerDisconnected):
        client.login('apikey', 'synthetic-key')
    assert exchange.call_count == 1
    assert capsys.readouterr().out.strip() == 'Authentication mechanism attempted: PLAIN'


def test_real_login_can_exchange_challenges_without_logging_payloads(monkeypatch, capsys):
    client, exchange = scripted_client(monkeypatch, 'LOGIN', [
        (334, b'UGFzc3dvcmQ6'), (235, b'secret-value')])
    assert client.login('apikey', 'synthetic-key')[0] == 235
    assert exchange.call_count == 2
    assert capsys.readouterr().out.strip() == 'Authentication mechanism attempted: LOGIN'


@pytest.mark.parametrize('code', [220, 250, 334, 235, 503, 535, 454, 421])
def test_response_tracking_codes_only(monkeypatch, capsys, code):
    client = diagnostic.TrackedSMTP()
    client.diagnostic_stage = 'authenticate'
    monkeypatch.setattr(smtplib.SMTP, 'getreply', Mock(return_value=(code, b'secret-value')))
    assert client.getreply()[0] == code
    assert capsys.readouterr().out.strip() == f'SMTP response: stage=authenticate; code={code}'


def test_response_tracking_disconnect_without_raw_message(monkeypatch, capsys):
    client = diagnostic.TrackedSMTP()
    client.diagnostic_stage = 'authenticate'
    monkeypatch.setattr(smtplib.SMTP, 'getreply', Mock(
        side_effect=smtplib.SMTPServerDisconnected('secret-value')))
    with pytest.raises(smtplib.SMTPServerDisconnected):
        client.getreply()
    assert capsys.readouterr().out.strip() == (
        'SMTP response: stage=authenticate; code=unavailable; disconnected=True')


def test_unknown_mechanism_label_is_redacted(monkeypatch, capsys):
    client = diagnostic.TrackedSMTP()
    monkeypatch.setattr(smtplib.SMTP, 'auth', Mock(return_value=(235, b'secret-value')))
    client.auth('secret-value', lambda: 'synthetic')
    assert capsys.readouterr().out.strip() == 'Authentication mechanism attempted: unrecognized'


@pytest.mark.parametrize('code', [400, 421, 432, 450, 451, 454, 499])
@pytest.mark.parametrize('after_challenge', [False, True])
def test_temporary_auth_failure_stops_all_mechanism_fallback(
        monkeypatch, capsys, code, after_challenge):
    responses = [(334, b'UGFzc3dvcmQ6')] if after_challenge else []
    responses += [(code, b'secret-value'), (235, b'unused')]
    client, exchange = scripted_client(monkeypatch, 'PLAIN LOGIN', responses)
    with pytest.raises(diagnostic.TemporaryAuthenticationError) as caught:
        client.login('apikey', 'synthetic-key')
    assert caught.value.smtp_code == code
    assert not isinstance(caught.value, smtplib.SMTPAuthenticationError)
    assert 'secret-value' not in str(caught.value)
    assert exchange.call_count == (2 if after_challenge else 1)
    assert capsys.readouterr().out.strip() == 'Authentication mechanism attempted: PLAIN'


def test_temporary_failure_on_later_mechanism_stops_remaining_fallback(monkeypatch, capsys):
    client, exchange = scripted_client(monkeypatch, 'CRAM-MD5 PLAIN LOGIN', [
        (535, b'secret-value'), (454, b'secret-value'), (235, b'unused')])
    with pytest.raises(diagnostic.TemporaryAuthenticationError):
        client.login('apikey', 'synthetic-key')
    assert exchange.call_count == 2
    assert capsys.readouterr().out.splitlines() == [
        'Authentication mechanism attempted: CRAM-MD5',
        'Authentication mechanism attempted: PLAIN']


def test_main_closes_after_temporary_failure_without_reconnect(setup, capsys):
    client, factory, _ = setup
    client.login.side_effect = diagnostic.TemporaryAuthenticationError(454)
    assert diagnostic.main() == 1
    factory.assert_called_once()
    client.close.assert_called_once()
    output = capsys.readouterr().out
    assert 'error_type=TemporaryAuthenticationError' in output
    assert 'secret-value' not in output
