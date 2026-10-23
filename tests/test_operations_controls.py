from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3
import subprocess
import sys

import pytest

from app import backups, storage_budget
from app.backups import snapshot, restore, verify_restore
from app.healthcheck import check
from app.ops_notifications import deliver, validate_config, read_config, NoRedirect
from app.ops_dispatch import unit_issues


def database(path):
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE t (id INTEGER PRIMARY KEY, value BLOB);'
                         'CREATE INDEX lookup ON t(value);'
                         'CREATE TABLE duplicates(x); INSERT INTO duplicates VALUES (1),(1);')
        db.execute('INSERT INTO t VALUES (?, ?)', (1, b'private\x00data'))


def test_budget_refusal_preserves_snapshots_and_unknown_entries(tmp_path):
    source, directory = tmp_path / 'source.db', tmp_path / 'backups'
    database(source)
    saved = snapshot(source, directory)
    unknown = directory / 'unknown'
    unknown.write_bytes(b'preserve')
    before = (saved / 'database.sqlite3').read_bytes()
    with pytest.raises(storage_budget.BudgetExceeded):
        snapshot(source, directory, keep=1, maximum_bytes=storage_budget.tree_bytes(directory) + 1)
    assert before == (saved / 'database.sqlite3').read_bytes()
    assert unknown.read_bytes() == b'preserve'
    assert not list(directory.glob('.pending-*'))


def test_low_space_admission_and_midcopy_cleanup(tmp_path, monkeypatch):
    source, directory = tmp_path / 'source.db', tmp_path / 'backups'
    database(source)
    saved = snapshot(source, directory)
    monkeypatch.setattr(storage_budget.shutil, 'disk_usage', lambda p: SimpleNamespace(free=0))
    with pytest.raises(storage_budget.BudgetExceeded): snapshot(source, directory)
    assert saved.exists()
    monkeypatch.undo()
    original = backups.copy_database
    def fill(source, target, **kwargs):
        target.write_bytes(b'x' * 100000)
        kwargs['guard']()
    monkeypatch.setattr(backups, 'copy_database', fill)
    with pytest.raises(storage_budget.BudgetExceeded):
        snapshot(source, directory, maximum_bytes=storage_budget.tree_bytes(directory) + 90000)
    assert saved.exists() and not list(directory.glob('.pending-*'))


def test_lock_serializes_manual_and_timer_and_refuses_symlinks(tmp_path):
    source, directory = tmp_path / 'source.db', tmp_path / 'backups'
    database(source)
    snapshot(source, directory)
    with storage_budget.exclusive_backup(directory):
        with pytest.raises(BlockingIOError): snapshot(source, directory)
    link = directory / 'unsafe'
    link.symlink_to(source)
    with pytest.raises(ValueError): snapshot(source, directory)
    assert source.exists()


def test_restore_proof_detects_logical_changes_and_preserves_source(tmp_path):
    source, directory = tmp_path / 'source.db', tmp_path / 'backups'
    database(source)
    saved = snapshot(source, directory)
    recovered = tmp_path / 'recovered.db'
    evidence = restore(saved, recovered)
    assert evidence['snapshot_sha256'] == backups.digest(saved / 'database.sqlite3')
    assert verify_restore(saved, recovered)['content_sha256'] == evidence['content_sha256']
    with sqlite3.connect(recovered) as db:
        db.execute('DELETE FROM duplicates WHERE rowid = 1')
    with pytest.raises(ValueError, match='differ'): verify_restore(saved, recovered)
    assert backups.validate_snapshot(saved)
    with sqlite3.connect(recovered) as db:
        db.execute('INSERT INTO duplicates VALUES (1)')
        db.execute('DROP INDEX lookup')
    with pytest.raises(ValueError, match='differ'): verify_restore(saved, recovered)


def test_bad_copy_not_published_and_restore_space_refused(tmp_path, monkeypatch):
    source = tmp_path / 'source.db'
    database(source)
    saved = snapshot(source, tmp_path / 'backups')
    def bad_copy(source, target):
        database(target)  # Valid database with a different row value.
        with sqlite3.connect(target) as db: db.execute('DELETE FROM t')
    monkeypatch.setattr(backups, 'copy_database', bad_copy)
    destination = tmp_path / 'restored.db'
    with pytest.raises(ValueError): restore(saved, destination)
    assert not destination.exists() and not list(tmp_path.glob('.restore-*'))
    monkeypatch.setattr(backups.shutil, 'disk_usage', lambda p: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match='reserve'): restore(saved, destination)
    assert not destination.exists()


def test_monitor_backup_mount_and_budget(tmp_path, monkeypatch):
    from app.history import History
    history = tmp_path / 'history.db'
    audit = History(history)
    for _ in range(2): audit.finish(audit.start(), 'succeeded')
    directory = tmp_path / 'backups'
    snapshot(history, directory)
    monkeypatch.setattr(storage_budget.shutil, 'disk_usage',
                        lambda p: SimpleNamespace(free=0 if p == directory else 10 ** 10))
    issues = check(history, directory, datetime.now(timezone.utc), maximum_backup_bytes=1)
    assert 'backup_budget_exhausted' in issues
    assert 'backup_disk_space_low' in issues
    assert 'disk_space_low' not in issues


CONFIG = {'enabled': True, 'allowed_hosts': ['heartbeat.example', 'notify.example'],
          'heartbeat_url': 'https://heartbeat.example/private-check',
          'notification_url': 'https://notify.example/private-topic'}


def test_notification_transition_reminder_recovery_and_retry():
    sent = []
    def sender(*args): sent.append(args)
    result = deliver(CONFIG, True, 100000, {}, sender)
    assert len(sent) == 2 and sent[0][0].endswith('/fail')
    state = result['state']
    deliver(CONFIG, True, 100001, state, sender)
    assert len(sent) == 3  # Heartbeat only; duplicate failure suppressed.
    state = deliver(CONFIG, True, 121600, state, sender)['state']
    assert len(sent) == 5
    state = deliver(CONFIG, False, 121601, state, sender)['state']
    assert sent[-1][1].endswith(b'recovered.') and state['failed'] is False
    assert not deliver(CONFIG, False, 121602, state, sender)['issues']
    def broken(*args): raise RuntimeError('secret-url-must-not-escape')
    failed = deliver(CONFIG, True, 200000, state, broken)
    assert failed['state'] == state and len(failed['issues']) == 2
    assert 'secret' not in json.dumps(failed)


@pytest.mark.parametrize('url', ['http://heartbeat.example/x', 'https://bad.example/x',
    'https://user:secret@heartbeat.example/x', 'https://heartbeat.example/x?secret=x',
    'https://heartbeat.example:8443/x', 'https://heartbeat.example/x#fragment'])
def test_notification_destination_validation(url):
    with pytest.raises(ValueError): validate_config({**CONFIG, 'heartbeat_url': url})


def test_no_redirect_and_private_configuration(tmp_path):
    with pytest.raises(ValueError): NoRedirect().redirect_request(None, None, 302, '', {}, 'https://bad.example')
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(CONFIG)); path.chmod(0o644)
    with pytest.raises(ValueError): read_config(path)
    path.chmod(0o600)
    assert read_config(path) == CONFIG
    with pytest.raises(ValueError): validate_config({**CONFIG, 'enabled': False})


def test_systemd_fail_closed_and_dryrun_never_reads_credentials(tmp_path, monkeypatch):
    def missing(*args, **kwargs): raise subprocess.CalledProcessError(1, 'systemctl')
    assert unit_issues(missing) == ['unit_failed_or_unavailable']
    # CI uses setup-python without a repository-local .venv. Exercise that layout
    # even when pytest itself was started from the developer's local environment.
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).resolve().parents[1]))
    assert not (tmp_path / '.venv').exists()
    result = subprocess.run([sys.executable, '-m', 'app.ops_dispatch',
        '--history', str(tmp_path / 'missing.db'), '--backups', str(tmp_path / 'missing'),
        '--state-directory', str(tmp_path / 'state'), '--config', str(tmp_path / 'no-secret-file')],
        cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1
    assert '"send_enabled": false' in result.stdout
    assert not (tmp_path / 'state').exists() and not (tmp_path / 'missing.db').exists()


def test_post_uses_verified_tls_bounded_request_and_no_proxy(monkeypatch):
    from app import ops_notifications as notifications
    recorded = {}
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): recorded['limit'] = limit
    class Opener:
        def open(self, request, timeout):
            recorded.update(request=request, timeout=timeout)
            return Response()
    def build(*handlers):
        recorded['handlers'] = handlers
        return Opener()
    monkeypatch.setattr(notifications, 'build_opener', build)
    notifications.post('https://notify.example/private', b'fixed message', 'private-token')
    assert recorded['timeout'] == 10 and recorded['limit'] == 1024
    assert recorded['request'].get_header('Authorization') == 'Bearer private-token'
    assert any(isinstance(h, notifications.NoRedirect) for h in recorded['handlers'])
    tls = next(h for h in recorded['handlers'] if isinstance(h, notifications.HTTPSHandler))
    assert tls._context.check_hostname
    assert tls._context.verify_mode == notifications.ssl.CERT_REQUIRED


def test_dispatch_saves_only_acknowledged_alert_state_and_redacts(tmp_path, monkeypatch):
    from app import ops_dispatch
    config = tmp_path / 'credentials.json'
    config.write_text(json.dumps(CONFIG)); config.chmod(0o600)
    state_dir = tmp_path / 'state'; state_dir.mkdir(mode=0o700)
    monkeypatch.setattr(ops_dispatch, 'check', lambda *args: ['disk_space_low'])
    monkeypatch.setattr(ops_dispatch, 'unit_issues', lambda: [])
    def delivery(config, failed, now, state):
        assert failed is True
        return {'state': {'failed': True, 'sent_at': now}, 'issues': []}
    monkeypatch.setattr(ops_dispatch, 'deliver', delivery)
    assert ops_dispatch.dispatch(tmp_path/'history',tmp_path/'backups',state_dir,config) == ['disk_space_low']
    saved = state_dir / 'delivery.json'
    assert saved.stat().st_mode & 0o077 == 0
    assert 'private-check' not in saved.read_text()


def test_restore_late_sidecar_refuses_publication(tmp_path, monkeypatch):
    source = tmp_path / 'source.db'; database(source)
    saved = snapshot(source, tmp_path/'backups')
    destination = tmp_path/'restore.db'
    original = backups.copy_database
    def copy_with_sidecar(source, target):
        original(source,target)
        Path(str(destination)+'-wal').write_bytes(b'preserve')
    monkeypatch.setattr(backups,'copy_database',copy_with_sidecar)
    with pytest.raises(FileExistsError): restore(saved,destination)
    assert not destination.exists()
    assert Path(str(destination)+'-wal').read_bytes() == b'preserve'


def test_restore_detects_text_after_nul_and_value_types(tmp_path):
    source = tmp_path/'source.db'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE evidence (value)')
        db.execute('INSERT INTO evidence VALUES (?)', ('before\x00original',))
        db.execute('INSERT INTO evidence VALUES (?)', (1,))
    saved = snapshot(source,tmp_path/'backups')
    recovered = tmp_path/'restore.db';restore(saved,recovered)
    with sqlite3.connect(recovered) as db:
        db.execute('UPDATE evidence SET value=? WHERE rowid=1',('before\x00altered',))
    with pytest.raises(ValueError): verify_restore(saved,recovered)
    with sqlite3.connect(recovered) as db:
        db.execute('UPDATE evidence SET value=? WHERE rowid=1',('before\x00original',))
        db.execute('UPDATE evidence SET value=1.0 WHERE rowid=2')
    with pytest.raises(ValueError): verify_restore(saved,recovered)


def test_restore_lock_blocks_retention_and_invalid_state_never_sends(tmp_path):
    source = tmp_path/'source.db';database(source)
    directory=tmp_path/'backups';saved=snapshot(source,directory)
    with storage_budget.exclusive_backup(directory):
        with pytest.raises(BlockingIOError): restore(saved,tmp_path/'restore.db')
        with pytest.raises(BlockingIOError): verify_restore(saved,source)
    sent=[]
    with pytest.raises(ValueError):
        deliver(CONFIG,False,100,{'failed':True,'sent_at':None},lambda *args:sent.append(args))
    assert sent==[]
