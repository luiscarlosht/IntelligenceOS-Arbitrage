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


def copy_database(source: Path, target: Path, timeout_seconds: float = 30) -> None:
    deadline = time.monotonic() + timeout_seconds

    def progress(status: int, remaining: int, total: int) -> None:
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


def snapshot(source: Path, directory: Path, keep: int = 14) -> Path:
    if type(keep) is not int or keep < 1:
        raise ValueError('Keep at least one snapshot')
    # Validate before creating directories or files; never create a missing source.
    with closing(connect_readonly(source)):
        pass
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ValueError('Backup directory must be private (0700) and not a symlink')
    now = datetime.now(timezone.utc)
    final = directory / ('sqlite-' + now.strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex)
    temporary = Path(tempfile.mkdtemp(prefix='.pending-', dir=directory))
    try:
        copy_database(source, temporary / 'database.sqlite3')
        manifest = temporary / 'manifest.json'
        manifest.write_text(json.dumps({'kind': 'intelligenceos-arbitrage-sqlite',
                                       'format': 1, 'created_at': now.isoformat(),
                                       'sha256': digest(temporary / 'database.sqlite3')}) + '\n')
        os.chmod(manifest, 0o600)
        sync_file(manifest)
        sync_directory(temporary)
        temporary.rename(final)
        sync_directory(directory)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    validate_snapshot(final)
    # Only prune fully validated, tool-owned snapshots after publishing a valid new one.
    managed = []
    for candidate in sorted(directory.iterdir(), reverse=True):
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


def restore(snapshot_directory: Path, destination: Path) -> None:
    database = validate_snapshot(snapshot_directory)
    if any(path.exists() or path.is_symlink() for path in
           (destination, Path(str(destination) + '-wal'), Path(str(destination) + '-shm'),
            Path(str(destination) + '-journal'))):
        raise FileExistsError('Restore destination must not exist')
    if not destination.parent.is_dir():
        raise ValueError('Restore parent must already exist')
    descriptor, name = tempfile.mkstemp(prefix='.restore-', dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        copy_database(database, temporary)
        # Hard link atomically publishes without replacing a destination created meanwhile.
        os.link(temporary, destination)
        sync_directory(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    backup = commands.add_parser('backup')
    backup.add_argument('--source', type=Path, required=True)
    backup.add_argument('--directory', type=Path, required=True)
    backup.add_argument('--keep', type=int, default=14)
    recovery = commands.add_parser('restore')
    recovery.add_argument('--snapshot', type=Path, required=True)
    recovery.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'backup':
            result = snapshot(args.source, args.directory, args.keep)
            print(json.dumps({'event': 'sqlite_backup_succeeded', 'snapshot': result.name}))
        else:
            restore(args.snapshot, args.destination)
            print(json.dumps({'event': 'sqlite_restore_succeeded'}))
    except Exception as exc:
        print(json.dumps({'event': 'sqlite_' + args.command + '_failed', 'error_type': type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
