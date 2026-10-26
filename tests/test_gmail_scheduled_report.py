"""No network: scheduled entrypoint gates and synthetic nonroot token rotation."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import tempfile
from unittest.mock import Mock

import pytest

from app.config import Config
from app import gmail_api as gmail
from app.mailer import send_report
from ops import gmail_scheduled_report as scheduled


@pytest.fixture
def setup(tmp_path, monkeypatch):
    config = Config(tmp_path/'input', tmp_path/'report.xlsx', tmp_path/'history',
                    email_transport='gmail_api', gmail_token_file=tmp_path/'token.json',
                    gmail_stage_file=tmp_path/'delivery.stages.jsonl',
                    email_from='synthetic@gmail.com', email_to=('synthetic@example.com',))
    monkeypatch.setattr(scheduled.Config, 'from_env', lambda: config)
    monkeypatch.delenv('ARBITRAGE_GMAIL_SCHEDULE_ENABLED', raising=False)
    monkeypatch.delenv('ARBITRAGE_GMAIL_OAUTH_READY', raising=False)
    job = Mock()
    monkeypatch.setattr(scheduled, 'report_main', job)
    return config, job


@pytest.mark.parametrize('enabled,ready', [(None,None), ('false','true'), ('true','false'), ('true',None)])
def test_inactive_or_testing_not_ready_never_runs(setup, monkeypatch, enabled, ready):
    _, job = setup
    for key, value in [('ARBITRAGE_GMAIL_SCHEDULE_ENABLED', enabled), ('ARBITRAGE_GMAIL_OAUTH_READY', ready)]:
        if value is not None:
            monkeypatch.setenv(key, value)
    assert scheduled.main() == 1
    job.assert_not_called()


def test_explicit_ready_configuration_runs_one_job(setup, monkeypatch):
    _, job = setup
    monkeypatch.setenv('ARBITRAGE_GMAIL_SCHEDULE_ENABLED', 'true')
    monkeypatch.setenv('ARBITRAGE_GMAIL_OAUTH_READY', 'true')
    assert scheduled.main() == 0
    job.assert_called_once_with()


@pytest.mark.parametrize('changes', [dict(email_to=()), dict(interval=10),
                                    dict(gmail_stage_file=None), dict(email_transport='smtp')])
def test_bad_schedule_configuration_never_runs(setup, monkeypatch, changes):
    config, job = setup
    # Supply SMTP prerequisites so its rejection specifically tests Gmail routing.
    config = replace(config, smtp_host='smtp.example.com', **changes)
    monkeypatch.setattr(scheduled.Config, 'from_env', lambda: config)
    monkeypatch.setenv('ARBITRAGE_GMAIL_SCHEDULE_ENABLED', 'true')
    monkeypatch.setenv('ARBITRAGE_GMAIL_OAUTH_READY', 'true')
    assert scheduled.main() == 1
    job.assert_not_called()


def test_scheduled_delivery_retains_safe_stage_reasons(setup, monkeypatch):
    import io
    from urllib.error import HTTPError
    config, _ = setup
    config.output.write_bytes(b'synthetic workbook')
    monkeypatch.setattr(gmail, 'read_private', lambda _: dict(client_id='x', client_secret='x',
                        refresh_token='x', scopes=[gmail.SCOPE]))
    post = Mock(side_effect=HTTPError('https://example.invalid/SECRET', 400, 'SECRET', {},
        io.BytesIO(b'{"error":"invalid_grant","error_description":"SECRET"}')))
    monkeypatch.setattr(gmail, 'post', post)
    with pytest.raises(gmail.GmailError):
        send_report(config, config.output, 'synthetic')
    post.assert_called_once()
    rendered = config.gmail_stage_file.read_text()
    assert 'SECRET' not in rendered
    last = json.loads(rendered.splitlines()[-1])
    assert last['google_reasons'] == ['invalid_grant']
    assert last['stage'] == 'token_refresh' and not last['submission_started']


def test_service_owned_token_can_be_read_and_rotated_without_root_home(monkeypatch):
    """Synthetic private state works for its owner and rejects a different UID."""
    directory = Path(tempfile.mkdtemp(prefix='arbitrage-service-token-', dir='/tmp'))
    token = directory/'token.json'
    data = dict(client_id='fixture', client_secret='fixture', refresh_token='fixture', scopes=[gmail.SCOPE])
    gmail.write_private(token, data)
    try:
        owner = os.getuid()
        with monkeypatch.context() as patch:
            patch.setattr(gmail.os, 'getuid', lambda: owner + 1)
            with pytest.raises(gmail.GmailError):
                gmail.read_private(token)
            with pytest.raises(gmail.GmailError):
                gmail.write_private(token, data)
        assert gmail.read_private(token) == data
        gmail.write_private(token, dict(data, refresh_token='rotated'))
        assert gmail.read_private(token)['refresh_token'] == 'rotated'
        assert token.stat().st_mode & 0o777 == 0o600
        assert directory.stat().st_mode & 0o777 == 0o700
    finally:
        shutil.rmtree(directory)
