"""Local SQLite snapshots with manifests, conservative retention and no overwrite restore."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
from uuid import uuid4
from itertools import zip_longest
from app.storage_budget import (DEFAULT_BUDGET, DEFAULT_RESERVE, LOCK_NAME,
                                enforce, exclusive_backup)

NAME = re.compile(r'sqlite-\d{8}T\d{12}Z-[0-9a-f]{32}')


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file() or path.is_symlink():
        raise ValueError('SQLite source must be an existing regular file')
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)


def check(db: sqlite3.Connection) -> None:
    if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise ValueError('SQLite integrity check failed')


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sync_file(path: Path) -> None:
    with path.open('rb') as stream:
        os.fsync(stream.fileno())


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def copy_database(source: Path, target: Path, timeout_seconds: float = 30, guard=None) -> None:
    deadline = time.monotonic() + timeout_seconds

    def progress(status: int, remaining: int, total: int) -> None:
        if guard:
            guard()
        if time.monotonic() > deadline:
            raise TimeoutError('SQLite snapshot deadline exceeded')

    with closing(connect_readonly(source)) as original, closing(sqlite3.connect(target)) as copied:
        original.backup(copied, pages=128, progress=progress, sleep=0.05)
        copied.execute('PRAGMA journal_mode=DELETE')
        check(copied)
    os.chmod(target, 0o600)
    sync_file(target)


def validate_snapshot(snapshot: Path) -> Path:
    if snapshot.is_symlink() or not snapshot.is_dir() or not NAME.fullmatch(snapshot.name):
        raise ValueError('Not a managed snapshot directory')
    if {item.name for item in snapshot.iterdir()} != {'database.sqlite3', 'manifest.json'}:
        raise ValueError('Unexpected snapshot contents; refusing retention/restore')
    database, manifest = snapshot / 'database.sqlite3', snapshot / 'manifest.json'
    if database.is_symlink() or manifest.is_symlink() or not database.is_file() or not manifest.is_file():
        raise ValueError('Snapshot files must be regular files')
    metadata = json.loads(manifest.read_text())
    if not isinstance(metadata, dict):
        raise ValueError('Invalid snapshot manifest')
    if metadata.get('kind') != 'intelligenceos-arbitrage-sqlite' or metadata.get('format') != 1 or metadata.get('sha256') != digest(database):
        raise ValueError('Snapshot checksum mismatch')
    if datetime.fromisoformat(metadata['created_at']).utcoffset() is None:
        raise ValueError('Snapshot clock must be timezone aware')
    with closing(connect_readonly(database)) as db:
        check(db)
    return database


def snapshot(source: Path, directory: Path, keep: int = 14,
             maximum_bytes: int = DEFAULT_BUDGET, minimum_free_bytes: int = DEFAULT_RESERVE) -> Path:
    if maximum_bytes <= 0 or minimum_free_bytes < 0:
        raise ValueError('Invalid disk policy')
    if type(keep) is not int or keep < 1:
        raise ValueError('Keep at least one snapshot')
    # Validate before creating directories or files; never create a missing source.
    with closing(connect_readonly(source)):
        pass
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ValueError('Backup directory must be private (0700) and not a symlink')
    with exclusive_backup(directory):
        with closing(connect_readonly(source)) as db:
            logical = db.execute('PRAGMA page_count').fetchone()[0] * db.execute('PRAGMA page_size').fetchone()[0]
        # Reserve growth/metadata headroom before copying; never prune to make room.
        allowance = (logical * 6 + 4) // 5 + 65536
        enforce(directory, allowance, maximum_bytes, minimum_free_bytes)
        if shutil.disk_usage(source.parent).free < minimum_free_bytes:
            raise ValueError('Source filesystem reserve insufficient')
        now = datetime.now(timezone.utc)
        final = directory / ('sqlite-' + now.strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex)
        temporary = Path(tempfile.mkdtemp(prefix='.pending-', dir=directory))
        try:
            copy_database(source, temporary / 'database.sqlite3', guard=lambda:
                    enforce(directory, 0, maximum_bytes, minimum_free_bytes))
            manifest = temporary / 'manifest.json'
            manifest.write_text(json.dumps({'kind': 'intelligenceos-arbitrage-sqlite',
                                           'format': 1, 'created_at': now.isoformat(),
                                           'sha256': digest(temporary / 'database.sqlite3')}) + '\n')
            os.chmod(manifest, 0o600)
            sync_file(manifest)
            sync_directory(temporary)
            enforce(directory, 0, maximum_bytes, minimum_free_bytes)
            temporary.rename(final)
            sync_directory(directory)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        validate_snapshot(final)
        # Only prune fully validated, tool-owned snapshots after publishing a valid new one.
        managed = []
        for candidate in sorted(directory.iterdir(), reverse=True):
            if candidate.name == LOCK_NAME:
                continue
            try:
                validate_snapshot(candidate)
            except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
                continue
            managed.append(candidate)
        for expired in managed[keep:]:
            # Revalidate immediately before touching files. Unknown/corrupt items are retained.
            validate_snapshot(expired)
            (expired / 'database.sqlite3').unlink()
            (expired / 'manifest.json').unlink()
            expired.rmdir()
        sync_directory(directory)
        return final


def _verify_restore(snapshot_directory: Path, destination: Path) -> dict:
    """Verify schema and every typed row, including duplicates, NUL text and blobs."""
    database = validate_snapshot(snapshot_directory)
    with closing(connect_readonly(database)) as source, closing(connect_readonly(destination)) as recovered:
        check(recovered)
        if source.execute('PRAGMA foreign_key_check').fetchone() or recovered.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Foreign key validation failed')
        content = hashlib.sha256()
        schema_sql = "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"
        schema = source.execute(schema_sql).fetchall()
        if schema != recovered.execute(schema_sql).fetchall():
            raise ValueError('Restored schema differs from snapshot')
        content.update(repr(schema).encode('utf-8'))
        table_count = 0
        row_count = 0
        # Compare typed values directly: SQL quote()/iterdump can truncate NUL text.
        for (table,) in source.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name"):
            table_count += 1
            content.update(repr(('table', table)).encode('utf-8') + b'\n')
            quoted = '"' + table.replace('"', '""') + '"'
            expected_rows = source.execute('SELECT * FROM ' + quoted)
            actual_rows = recovered.execute('SELECT * FROM ' + quoted)
            sentinel = object()
            for expected, actual in zip_longest(expected_rows, actual_rows, fillvalue=sentinel):
                if expected is sentinel or actual is sentinel:
                    raise ValueError('Restored contents differ from snapshot')
                row_count += 1
                typed_expected = tuple((type(value).__name__, value) for value in expected)
                typed_actual = tuple((type(value).__name__, value) for value in actual)
                if typed_expected != typed_actual:
                    raise ValueError('Restored contents differ from snapshot')
                content.update(repr(typed_expected).encode('utf-8') + b'\n')
    return {'snapshot': snapshot_directory.name, 'snapshot_sha256': digest(database),
            'content_sha256': content.hexdigest(), 'tables_verified': table_count, 'rows_verified': row_count,
            'verified_at': datetime.now(timezone.utc).isoformat()}


def verify_restore(snapshot_directory: Path, destination: Path) -> dict:
    with exclusive_backup(snapshot_directory.parent):
        return _verify_restore(snapshot_directory, destination)


def restore(snapshot_directory: Path, destination: Path,
            minimum_free_bytes: int = DEFAULT_RESERVE) -> dict:
    with exclusive_backup(snapshot_directory.parent):
        return _restore(snapshot_directory, destination, minimum_free_bytes)


def _restore(snapshot_directory: Path, destination: Path,
             minimum_free_bytes: int) -> dict:
    database = validate_snapshot(snapshot_directory)
    if any(path.exists() or path.is_symlink() for path in
           (destination, Path(str(destination) + '-wal'), Path(str(destination) + '-shm'),
            Path(str(destination) + '-journal'))):
        raise FileExistsError('Restore destination must not exist')
    if not destination.parent.is_dir():
        raise ValueError('Restore parent must already exist')
    if minimum_free_bytes < 0:
        raise ValueError('Invalid free space reserve')
    if shutil.disk_usage(destination.parent).free < database.stat().st_size * 2 + 65536 + minimum_free_bytes:
        raise ValueError('Restore filesystem reserve insufficient')
    descriptor, name = tempfile.mkstemp(prefix='.restore-', dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        copy_database(database, temporary)
        evidence = _verify_restore(snapshot_directory, temporary)
        # Hard link atomically publishes without replacing a destination created meanwhile.
        if any(Path(str(destination) + suffix).exists() or Path(str(destination) + suffix).is_symlink()
               for suffix in ('-wal', '-shm', '-journal')):
            raise FileExistsError('Restore sidecar appeared before publication')
        os.link(temporary, destination)
        sync_directory(destination.parent)
        return evidence
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    backup = commands.add_parser('backup')
    backup.add_argument('--source', type=Path, required=True)
    backup.add_argument('--directory', type=Path, required=True)
    backup.add_argument('--keep', type=int, default=14)
    backup.add_argument('--maximum-bytes', type=int, default=DEFAULT_BUDGET)
    backup.add_argument('--minimum-free-bytes', type=int, default=DEFAULT_RESERVE)
    recovery = commands.add_parser('restore')
    recovery.add_argument('--snapshot', type=Path, required=True)
    recovery.add_argument('--destination', type=Path, required=True)
    recovery.add_argument('--minimum-free-bytes', type=int, default=DEFAULT_RESERVE)
    verification = commands.add_parser('verify-restore')
    verification.add_argument('--snapshot', type=Path, required=True)
    verification.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'backup':
            result = snapshot(args.source, args.directory, args.keep, args.maximum_bytes, args.minimum_free_bytes)
            print(json.dumps({'event': 'sqlite_backup_succeeded', 'snapshot': result.name}))
        else:
            evidence = (restore(args.snapshot, args.destination, args.minimum_free_bytes)
                        if args.command == 'restore' else verify_restore(args.snapshot, args.destination))
            print(json.dumps({'event': 'sqlite_restore_verified', **evidence}))
    except Exception as exc:
        print(json.dumps({'event': 'sqlite_' + args.command + '_failed', 'error_type': type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
