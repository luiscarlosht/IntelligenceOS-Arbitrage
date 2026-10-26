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
    monkeypatch.setattr(diagnostic, 'load_configuration', Mock(return_value='operator@gmail.com'))
    monkeypatch.setattr(diagnostic, 'sys', SimpleNamespace(
        stdin=SimpleNamespace(isatty=lambda: True),
        stderr=SimpleNamespace(isatty=lambda: True)))
    monkeypatch.setattr(diagnostic.resource, 'setrlimit', Mock())
    return client, factory, prompt


def test_success_verified_tls_and_auth_only(setup, capsys):
    client, factory, _ = setup
    assert diagnostic.main() == 0
    factory.assert_called_once_with('smtp.gmail.com', 587, timeout=30)
    assert [call[0] for call in client.mock_calls] == [
        'ehlo', 'starttls', 'ehlo', 'login', 'close']
    context = client.starttls.call_args.kwargs['context']
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED
    client.login.assert_called_once_with('operator@gmail.com', 'secret-value')
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


@pytest.mark.parametrize('text', [
    'SMTP_HOST=smtp.sendgrid.net',
    'SMTP_HOST=$(command)',
    'SMTP_HOST=smtp.gmail.com\nSMTP_HOST=smtp.gmail.com',
    'SMTP_PASSWORD=synthetic',
    'UNRELATED=synthetic',
    'SMTP_HOST="unterminated',
])
def test_configuration_fails_closed(tmp_path, text):
    path = tmp_path / 'isolated.env'
    path.write_text(text)
    with pytest.raises(ValueError):
        diagnostic.load_configuration(path)


def test_configuration_valid_literal(tmp_path):
    path = tmp_path / 'isolated.env'
    path.write_text('SMTP_HOST=smtp.gmail.com\nSMTP_PORT=587\n'
                    'SMTP_SECURITY=starttls\nSMTP_USER=operator@gmail.com\nEMAIL_TO=')
    assert diagnostic.load_configuration(path) == 'operator@gmail.com'


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


def test_invalid_configuration_never_prompts_or_connects(setup, monkeypatch, capsys):
    _, factory, prompt = setup
    monkeypatch.setattr(diagnostic, 'load_configuration', Mock(side_effect=ValueError('private')))
    assert diagnostic.main() == 1
    factory.assert_not_called()
    prompt.assert_not_called()
    assert 'private' not in capsys.readouterr().out


@pytest.mark.parametrize('entered', ['SG.synthetic-key', '', 'short', '$(command)'])
def test_hidden_entry_rejects_non_app_password(monkeypatch, entered):
    prompt = Mock(return_value=entered)
    monkeypatch.setattr(diagnostic.getpass, 'getpass', prompt)
    monkeypatch.setattr(diagnostic.getpass, 'unix_getpass', prompt)
    with pytest.raises(ValueError):
        diagnostic.load_credential()
    prompt.assert_called_once()


def test_hidden_entry_accepts_google_grouped_password(monkeypatch):
    prompt = Mock(return_value='abcd efgh ijkl mnop')
    monkeypatch.setattr(diagnostic.getpass, 'getpass', prompt)
    monkeypatch.setattr(diagnostic.getpass, 'unix_getpass', prompt)
    assert diagnostic.load_credential() == 'abcdefghijklmnop'


@pytest.mark.parametrize('failure', ['no_fd', 'echo_control'])
def test_real_getpass_fails_before_visible_read(monkeypatch, failure):
    import io
    import termios

    visible_read = Mock(side_effect=AssertionError('visible input attempted'))
    stdin = io.StringIO('synthetic-only\n')  # fileno() raises UnsupportedOperation.
    monkeypatch.setattr(stdin, 'readline', visible_read)
    monkeypatch.setattr(diagnostic.getpass.sys, 'stdin', stdin)
    monkeypatch.setattr(diagnostic.getpass.os, 'open', Mock(side_effect=OSError()))
    if failure == 'echo_control':
        monkeypatch.setattr(stdin, 'fileno', lambda: 0)
        monkeypatch.setattr(termios, 'tcgetattr', Mock(return_value=[0, 0, 0, termios.ECHO, 0, 0, []]))
        monkeypatch.setattr(termios, 'tcsetattr', Mock(side_effect=termios.error()))
    with pytest.raises((diagnostic.getpass.GetPassWarning, io.UnsupportedOperation)):
        diagnostic.load_credential()
    visible_read.assert_not_called()


def test_real_getpass_pty_hides_input_and_restores_echo():
    """Exercise the actual terminal wrappers, never main() or SMTP."""
    import os
    import pty
    import select
    import signal
    import termios
    import time
    import io

    pid, fd = pty.fork()
    if pid == 0:
        try:
            # A wrapper without fileno must not matter when /dev/tty works.
            diagnostic.getpass.sys.stdin = io.StringIO()
            value = diagnostic.load_credential()
            os.write(1, b'VALID\n' if value == 'abcdefghijklmnop' else b'INVALID\n')
            os._exit(0)
        except BaseException:
            os._exit(1)
    output = b''
    sent = False
    try:
        deadline = time.monotonic() + 5
        while b'VALID\r\n' not in output:
            remaining = deadline - time.monotonic()
            assert remaining > 0, output
            assert select.select([fd], [], [], remaining)[0], output
            output += os.read(fd, 4096)
            if not sent and b'(hidden): ' in output:
                assert not termios.tcgetattr(fd)[3] & termios.ECHO
                os.write(fd, b'abcd efgh ijkl mnop\n')
                sent = True
        assert sent
        assert b'abcd' not in output
        assert termios.tcgetattr(fd)[3] & termios.ECHO
        _, status = os.waitpid(pid, 0)
        pid = None
        assert os.waitstatus_to_exitcode(status) == 0
    finally:
        os.close(fd)
        if pid is not None:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)


def test_hidden_entry_rejects_non_unix_getpass(monkeypatch):
    prompt = Mock()
    monkeypatch.setattr(diagnostic.getpass, 'getpass', prompt)
    with pytest.raises(ValueError):
        diagnostic.load_credential()
    prompt.assert_not_called()


def bashrc_fixture(tmp_path, extra=''):
    path = tmp_path / 'bashrc'
    path.write_text('unrelated=$(never-execute)\nreturn\n'
                    'export SMTP_USERNAME="operator@gmail.com"\n'
                    "SMTP_APP_PASSWORD='abcd efgh ijkl mnop'\n" + extra)
    return path


def test_bashrc_aliases_literal_only(tmp_path):
    assert diagnostic.load_bashrc_configuration(bashrc_fixture(tmp_path)) == (
        'operator@gmail.com', 'abcdefghijklmnop')


@pytest.mark.parametrize('extra', [
    'SMTP_USERNAME=operator@gmail.com\n',
    'SMTP_USER=operator@gmail.com\n',
    'SMTP_PASSWORD=abcdefghijklmnop\n',
    'SMTP_HOST=smtp.sendgrid.net\n', 'SMTP_PORT=2525\n', 'SMTP_SECURITY=ssl\n',
    'EMAIL_FROM=$(never-execute)\n', 'SMTP_HOST="unterminated\n',
    'EMAIL_TO=one\nEMAIL_TO=two\n',
])
def test_bashrc_rejects_ambiguity_and_shell_expressions(tmp_path, extra):
    with pytest.raises(ValueError):
        diagnostic.load_bashrc_configuration(bashrc_fixture(tmp_path, extra))


@pytest.mark.parametrize('password', ['', 'SG.synthetic', 'short'])
def test_bashrc_rejects_missing_or_wrong_password_shape(tmp_path, password):
    path = tmp_path / 'bashrc'
    path.write_text(f'SMTP_USER=operator@gmail.com\nSMTP_PASSWORD={password}\n')
    with pytest.raises(ValueError):
        diagnostic.load_bashrc_configuration(path)


def test_bashrc_main_auth_only(setup, tmp_path, capsys):
    client, factory, prompt = setup
    assert diagnostic.main(bashrc_path=bashrc_fixture(tmp_path)) == 0
    prompt.assert_not_called()
    factory.assert_called_once_with('smtp.gmail.com', 587, timeout=30)
    client.login.assert_called_once_with('operator@gmail.com', 'abcdefghijklmnop')
    assert [call[0] for call in client.mock_calls] == ['ehlo', 'starttls', 'ehlo', 'login', 'close']
    context = client.starttls.call_args.kwargs['context']
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert 'abcdefghijklmnop' not in capsys.readouterr().out


def test_bashrc_failure_never_connects(setup, tmp_path, capsys):
    _, factory, prompt = setup
    assert diagnostic.main(bashrc_path=bashrc_fixture(tmp_path, 'SMTP_PASSWORD=SG.synthetic\n')) == 1
    factory.assert_not_called()
    prompt.assert_not_called()
    assert 'SG.synthetic' not in capsys.readouterr().out
