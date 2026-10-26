import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app import amazon_pilot as pilot
from app.provider_runtime import ProviderFailure


CREDS = dict(client_id='fake-client', client_secret='fake-secret', refresh_token='fake-refresh')


def test_catalog_two_requests_and_unknowns():
    calls = []
    def transport(request):
        calls.append(request)
        if len(calls) == 1:
            assert request.get_method() == 'POST'
            assert b'grant_type=refresh_token' in request.data
            return dict(access_token='fake-access', token_type='bearer')
        assert request.get_method() == 'GET'
        assert request.get_header('X-amz-access-token') == 'fake-access'
        assert 'marketplaceIds=ATVPDKIKX0DER' in request.full_url
        return dict(asin=pilot.ASIN, summaries=[dict(marketplaceId=pilot.MARKETPLACE,
            manufacturer='fake-secret', modelNumber='model')])
    evidence = pilot.catalog_once(CREDS, transport)
    assert len(calls) == 2
    assert evidence.value.seller_eligible is None
    assert evidence.value.sale_price is None
    assert all(v is None for v in evidence.value.costs.values())
    assert evidence.value.package_quantity is None
    assert evidence.value.manufacturer == '[REDACTED]'
    assert not evidence.is_mock


def test_failure_no_retry():
    calls = []
    def transport(request):
        calls.append(request)
        raise ProviderFailure('throttled')
    with pytest.raises(ProviderFailure):
        pilot.catalog_once(CREDS, transport)
    assert len(calls) == 1


def test_invalid_token_no_catalog():
    with pytest.raises(ProviderFailure):
        pilot.catalog_once(CREDS, lambda request: dict(access_token='bad\nheader', token_type='bearer'))


def test_private_files_and_no_overwrite(tmp_path):
    directory = pilot.private_directory(tmp_path / 'amazon')
    try:
        with os.fdopen(pilot.create_file(directory, 'credentials.json'), 'w') as output:
            json.dump(CREDS, output)
        assert pilot.load_credentials(directory) == CREDS
        assert (tmp_path / 'amazon').stat().st_mode & 0o777 == 0o700
        assert (tmp_path / 'amazon/credentials.json').stat().st_mode & 0o777 == 0o600
        with pytest.raises(FileExistsError):
            pilot.create_file(directory, 'credentials.json')
        os.chmod(tmp_path / 'amazon/credentials.json', 0o644)
        with pytest.raises(ValueError):
            pilot.load_credentials(directory)
    finally:
        os.close(directory)


def test_symlink_directory_rejected(tmp_path):
    (tmp_path / 'link').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        pilot.private_directory(tmp_path / 'link')


def test_hidden_prompt_failure_writes_nothing(tmp_path):
    with patch('builtins.open', side_effect=OSError('no tty')):
        with pytest.raises(OSError):
            pilot.enter_credentials(tmp_path / 'amazon')
    assert not (tmp_path / 'amazon').exists()


def test_getpass_fallback_fails_closed(tmp_path):
    import warnings
    from unittest.mock import mock_open
    terminal = mock_open()
    terminal.return_value.isatty.return_value = True
    def fallback(*args, **kwargs):
        warnings.warn('no echo control', pilot.getpass.GetPassWarning)
        pytest.fail('Must not reach visible input')
    with patch('builtins.open', terminal), patch.object(pilot.getpass, 'getpass', fallback):
        with pytest.raises(pilot.getpass.GetPassWarning):
            pilot.enter_credentials(tmp_path / 'amazon')
    assert not (tmp_path / 'amazon/credentials.json').exists()


def test_existing_report_prevents_credentials_and_network(tmp_path):
    directory = pilot.private_directory(tmp_path / 'amazon')
    os.close(pilot.create_file(directory, 'catalog-pilot.json'))
    os.close(directory)
    with patch.object(pilot, 'load_credentials') as load, patch.object(pilot, 'catalog_once') as call:
        with pytest.raises(FileExistsError):
            pilot.run_pilot(tmp_path / 'amazon')
        load.assert_not_called()
        call.assert_not_called()


def test_http_rejection_redacted_and_no_retry():
    from urllib.error import HTTPError
    from unittest.mock import Mock
    opener = Mock()
    opener.open.side_effect = HTTPError('https://example.invalid', 403, 'fake-secret', {}, None)
    with patch.object(pilot, 'build_opener', return_value=opener):
        with pytest.raises(ProviderFailure, match='^forbidden$'):
            pilot.request_json(pilot.Request('https://example.invalid'))
    assert opener.open.call_count == 1
    assert opener.open.call_args.kwargs['timeout'] == 10


def test_failure_report_contains_no_secrets(tmp_path):
    path = tmp_path / 'amazon'
    directory = pilot.private_directory(path)
    with os.fdopen(pilot.create_file(directory, 'credentials.json'), 'w') as output:
        json.dump(CREDS, output)
    os.close(directory)
    with patch.object(pilot, 'catalog_once', side_effect=RuntimeError('fake-secret')):
        with pytest.raises(RuntimeError):
            pilot.run_pilot(path)
    report = (path / 'catalog-pilot.json').read_text()
    assert 'fake-secret' not in report
    assert json.loads(report)['status'] == 'failed'
    assert (path / 'catalog-pilot.json').stat().st_mode & 0o777 == 0o600


def test_terminal_output_mode_accepts_real_nonseekable_tty():
    import pty
    master, slave = pty.openpty()
    try:
        with pytest.raises(OSError):
            open(os.ttyname(slave), 'r+')
        with open(os.ttyname(slave), 'w') as terminal:
            assert terminal.isatty()
    finally:
        os.close(master)
        os.close(slave)


def test_entry_uses_output_only_terminal_and_exclusive_file(tmp_path):
    from unittest.mock import mock_open
    terminal = mock_open()
    terminal.return_value.isatty.return_value = True
    path = tmp_path / 'amazon'
    with patch('builtins.open', terminal), patch.object(pilot.getpass, 'getpass', side_effect=CREDS.values()):
        pilot.enter_credentials(path)
    terminal.assert_called_once_with('/dev/tty', 'w')
    assert json.loads((path / 'credentials.json').read_text()) == CREDS
    assert (path / 'credentials.json').stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('mode,wrong_owner', [(0o755, False), (0o700, True)])
def test_directory_security_diagnostics(tmp_path, mode, wrong_owner):
    from types import SimpleNamespace
    path = tmp_path / 'amazon'
    path.mkdir(mode=mode)
    info = SimpleNamespace(st_uid=os.geteuid() + int(wrong_owner), st_mode=mode)
    with patch.object(pilot.os, 'fstat', return_value=info):
        with pytest.raises(ValueError) as failure:
            pilot.private_directory(path)
    assert 'operation=directory_security_check exception=ValueError errno=none' in pilot.failure_diagnostic(failure.value)


def test_existing_credentials_preserved_without_open_or_prompt(tmp_path):
    from unittest.mock import mock_open
    path = tmp_path / 'amazon'
    path.mkdir(mode=0o700)
    target = path / 'credentials.json'
    target.write_text('synthetic sentinel')
    before = target.stat()
    terminal = mock_open()
    terminal.return_value.isatty.return_value = True
    with patch('builtins.open', terminal), patch.object(pilot.getpass, 'getpass') as prompt:
        with pytest.raises(FileExistsError) as failure:
            pilot.enter_credentials(path)
        prompt.assert_not_called()
    assert target.read_text() == 'synthetic sentinel'
    assert target.stat().st_ino == before.st_ino
    assert 'operation=credential_existence_check exception=FileExistsError errno=17' in pilot.failure_diagnostic(failure.value)


def test_cli_diagnostic_excludes_exception_text(capsys):
    error = PermissionError(13, 'fake-secret fake-refresh')
    with patch('sys.argv', ['amazon_pilot', 'credentials']), patch('builtins.open', side_effect=error):
        assert pilot.main() == 1
    output = capsys.readouterr().out
    assert 'operation=terminal_open exception=PermissionError errno=13' in output
    assert 'fake-secret' not in output
    assert 'fake-refresh' not in output


def test_hidden_input_failure_operation(tmp_path):
    from unittest.mock import mock_open
    terminal = mock_open()
    terminal.return_value.isatty.return_value = True
    with patch('builtins.open', terminal), patch.object(pilot.getpass, 'getpass', side_effect=pilot.getpass.GetPassWarning('synthetic secret')):
        with pytest.raises(pilot.getpass.GetPassWarning) as failure:
            pilot.enter_credentials(tmp_path / 'amazon')
    assert 'operation=hidden_prompt exception=GetPassWarning errno=none' in pilot.failure_diagnostic(failure.value)
    assert 'synthetic secret' not in pilot.failure_diagnostic(failure.value)
    assert not (tmp_path / 'amazon/credentials.json').exists()
