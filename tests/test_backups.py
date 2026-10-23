import sqlite3

import pytest

from app.backups import restore, snapshot, validate_snapshot


def database(path):
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE evidence (value TEXT)')
    db.execute('INSERT INTO evidence VALUES (?)', ('illustrative history',))
    db.commit()
    return db


def test_wal_backup_and_restore_roundtrip(tmp_path):
    source = tmp_path / 'source.sqlite3'
    with database(source) as live:
        # Remain connected while backup runs; committed WAL is included.
        saved = snapshot(source, tmp_path / 'backups')
        live.execute("INSERT INTO evidence VALUES ('later run')")
        live.commit()
        restored = tmp_path / 'restored.sqlite3'
        restore(saved, restored)
        with sqlite3.connect(restored) as db:
            assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
            assert db.execute('SELECT * FROM evidence').fetchall() == [('illustrative history',)]
        assert live.execute('SELECT COUNT(*) FROM evidence').fetchone()[0] == 2
    assert restored.stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        restore(saved, restored)


def test_retention_only_removes_owned_valid_snapshots(tmp_path):
    source = tmp_path / 's.db'
    database(source).close()
    directory = tmp_path / 'backups'
    first = snapshot(source, directory, 2)
    second = snapshot(source, directory, 2)
    unrelated = directory / 'keep-me.sqlite3'
    unrelated.write_text('unrelated')
    malformed = directory / ('sqlite-20200101T000000000000Z-' + 'a' * 32)
    malformed.mkdir()
    (malformed / 'private.txt').write_text('preserve')
    third = snapshot(source, directory, 2)
    assert not first.exists() and second.exists() and third.exists()
    assert unrelated.exists() and (malformed / 'private.txt').exists()


def test_corruption_missing_source_and_unsafe_paths(tmp_path):
    missing = tmp_path / 'missing.db'
    with pytest.raises(ValueError):
        snapshot(missing, tmp_path / 'backups')
    assert not missing.exists() and not (tmp_path / 'backups').exists()
    source = tmp_path / 's.db'
    database(source).close()
    saved = snapshot(source, tmp_path / 'backups')
    (saved / 'database.sqlite3').write_bytes(b'corrupt')
    with pytest.raises(ValueError):
        restore(saved, tmp_path / 'restore.db')
    assert not (tmp_path / 'restore.db').exists()
    # A failed new backup cannot prune a prior snapshot.
    source.write_bytes(b'not sqlite')
    with pytest.raises(sqlite3.DatabaseError):
        snapshot(source, tmp_path / 'backups', 1)
    assert saved.exists()
    assert not list((tmp_path / 'backups').glob('.pending-*'))


def test_symlinks_and_nonprivate_directories_refused(tmp_path):
    source = tmp_path / 's.db'
    database(source).close()
    link = tmp_path / 'link.db'
    link.symlink_to(source)
    with pytest.raises(ValueError):
        snapshot(link, tmp_path / 'backups')
    directory = tmp_path / 'public'
    directory.mkdir(mode=0o755)
    with pytest.raises(ValueError):
        snapshot(source, directory)
    with pytest.raises(ValueError):
        snapshot(source, tmp_path / 'backups', 0)


def test_restore_refuses_orphan_sidecars_and_preserves_them(tmp_path):
    source = tmp_path / 's.db'
    database(source).close()
    saved = snapshot(source, tmp_path / 'backups')
    sidecar = tmp_path / 'restored.db-wal'
    sidecar.write_bytes(b'preserve orphan for investigation')
    with pytest.raises(FileExistsError):
        restore(saved, tmp_path / 'restored.db')
    assert sidecar.read_bytes() == b'preserve orphan for investigation'
    assert not (tmp_path / 'restored.db').exists()
