from datetime import datetime, timedelta, timezone
import sqlite3

from app.backups import snapshot, restore
from app.healthcheck import check
from app.history import History


def test_health_and_restore_evidence(tmp_path):
    history = tmp_path / 'history.sqlite3'
    audit = History(history)
    for _ in range(2):
        audit.finish(audit.start(), 'succeeded')
    backups = tmp_path / 'backups'
    saved = snapshot(history, backups)
    now = datetime.now(timezone.utc)
    assert check(history, backups, now, minimum_free_bytes=0) == []
    recovered = tmp_path / 'recovered.sqlite3'
    restore(saved, recovered)
    with sqlite3.connect(history) as source, sqlite3.connect(recovered) as target:
        assert source.execute('SELECT * FROM runs').fetchall() == target.execute('SELECT * FROM runs').fetchall()
        assert target.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    issues = check(history, backups, now + timedelta(days=2), minimum_free_bytes=0)
    assert 'fresh_valid_backup_missing' in issues
    assert 'jobs_stale_or_future' in issues
    audit.finish(audit.start(), 'failed')
    assert 'latest_jobs_not_successful' in check(history, backups, now, minimum_free_bytes=0)
    (saved / 'database.sqlite3').write_bytes(b'corrupt')
    assert 'backup_invalid_or_unknown' in check(history, backups, now)


def test_missing_paths_never_created(tmp_path):
    history, backups = tmp_path / 'absent.db', tmp_path / 'absent'
    issues = check(history, backups, datetime.now(timezone.utc))
    assert 'history_unavailable' in issues and 'fresh_valid_backup_missing' in issues
    assert not history.exists() and not backups.exists()
