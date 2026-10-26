import json
import smtplib
import ssl
from unittest.mock import Mock
import pytest
from ops import gmail_demo_once as sender


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(sender, 'ROOT', tmp_path)
    directory = tmp_path/'var/demo'
    directory.mkdir(parents=True)
    for name in ('DEMO.xlsx', 'DEMO.md'):
        (directory/name).write_bytes(b'synthetic demo attachment')
    monkeypatch.setattr(sender, 'MARKER', tmp_path/'gmail.attempted')
    monkeypatch.setattr(sender, 'STAGES', tmp_path/'gmail.stages')
    monkeypatch.setattr(sender, 'load_bashrc_configuration', Mock(return_value=('test@gmail.com', 'synthetic-secret')))
    client = Mock()
    client.connect.return_value = (220, b'ok')
    client.ehlo.return_value = (250, b'ok')
    client.starttls.return_value = (220, b'ok')
    client.auth.return_value = (235, b'ok')
    client.mail.return_value = client.rcpt.return_value = client.data.return_value = (250, b'ok')
    client.esmtp_features = {'auth': 'PLAIN LOGIN'}
    factory = Mock(return_value=client)
    monkeypatch.setattr(sender.smtplib, 'SMTP', factory)
    return client, factory


def test_single_recipient_attachments_tls_and_once(runtime, capsys):
    client, factory = runtime
    assert sender.send_once() == 0
    factory.assert_called_once_with(timeout=15, local_hostname='arbitrage.local')
    client.connect.assert_called_once_with('smtp.gmail.com', 587)
    context = client.starttls.call_args.kwargs['context']
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    client.rcpt.assert_called_once_with('luiscarloshernandez@hotmail.com')
    client.auth.assert_called_once()
    message = sender.build_message('test@gmail.com')
    assert list(message.keys()) == ['From', 'To', 'Subject', 'MIME-Version', 'Content-Type']
    assert 'fictional DEMO' in message['Subject']
    assert 'not live opportunities' in message.get_body().get_content()
    assert {part.get_filename() for part in message.iter_attachments()} == {'DEMO.xlsx', 'DEMO.md'}
    assert sender.send_once() == 1
    assert factory.call_count == 1
    assert 'synthetic-secret' not in capsys.readouterr().out + sender.STAGES.read_text()


@pytest.mark.parametrize('stage', ['connect', 'starttls', 'auth', 'rcpt', 'data'])
def test_failure_no_retry_redaction_and_last_stage(runtime, stage, capsys):
    client, factory = runtime
    getattr(client, stage).side_effect = smtplib.SMTPServerDisconnected('synthetic-secret')
    assert sender.send_once() == 1
    result = json.loads(capsys.readouterr().out)
    assert result['submission_ambiguous'] == (stage == 'data')
    assert not result['smtp_acceptance_observed']
    assert sender.send_once() == 1
    assert factory.call_count == 1
    assert 'synthetic-secret' not in sender.STAGES.read_text()
    if stage != 'data': client.data.assert_not_called()


def test_connect_errno_and_existing_evidence(runtime, capsys):
    client, _ = runtime
    client.connect.side_effect = OSError(101, 'synthetic-secret')
    assert sender.send_once() == 1
    result = json.loads(capsys.readouterr().out)
    assert result['operation'] == 'connection_banner'
    assert result['errno'] == 101
    assert result['last_completed_stage'] == 'preflight'
    assert result['attempt_marker_exists']
    assert not result['submission_ambiguous']
    client.auth.assert_not_called()
    assert 'synthetic-secret' not in json.dumps(result)


@pytest.mark.parametrize('operation', ['credential_parse', 'attachment_read_DEMO.xlsx',
                                       'tls_context', 'attempt_marker_create'])
def test_preflight_failures(runtime, monkeypatch, capsys, operation):
    client, factory = runtime
    failure = OSError(13, 'synthetic-secret')
    if operation == 'credential_parse':
        sender.load_bashrc_configuration.side_effect = failure
    elif operation.startswith('attachment'):
        original = sender.Path.read_bytes
        def read(path):
            if path.name == 'DEMO.xlsx':
                raise failure
            return original(path)
        monkeypatch.setattr(sender.Path, 'read_bytes', read)
    elif operation == 'tls_context':
        monkeypatch.setattr(sender.ssl, 'create_default_context', Mock(side_effect=failure))
    else:
        monkeypatch.setattr(sender.os, 'open', Mock(side_effect=failure))
    assert sender.send_once() == 1
    result = json.loads(capsys.readouterr().out)
    assert result['operation'] == operation
    assert result['errno'] == 13
    assert not result['attempt_marker_exists']
    assert 'synthetic-secret' not in json.dumps(result)
    factory.assert_not_called()


@pytest.mark.parametrize('dns_error', [None, OSError(-3, 'synthetic-secret'), TimeoutError()])
def test_diagnose_never_smtp_or_marker_write(runtime, monkeypatch, capsys, dns_error):
    _, factory = runtime
    sender.MARKER.write_bytes(b'preserve this reservation')
    before = sender.MARKER.stat()
    dns = Mock(return_value=[object()], side_effect=dns_error)
    monkeypatch.setattr(sender.socket, 'getaddrinfo', dns)
    alarm = Mock()
    monkeypatch.setattr(sender.signal, 'alarm', alarm)
    assert sender.diagnose() == int(dns_error is not None)
    assert sender.MARKER.read_bytes() == b'preserve this reservation'
    assert sender.MARKER.stat().st_mtime_ns == before.st_mtime_ns
    factory.assert_not_called()
    dns.assert_called_once_with('smtp.gmail.com', 587, type=sender.socket.SOCK_STREAM)
    assert [c.args[0] for c in alarm.call_args_list] == [10, 0]
    assert 'synthetic-secret' not in capsys.readouterr().out
