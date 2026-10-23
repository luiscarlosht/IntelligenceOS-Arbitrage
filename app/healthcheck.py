"""Proposed offline operational checks. No repairs, network requests or raw data logs."""
import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.backups import validate_snapshot
from app.storage_budget import DEFAULT_BUDGET, LOCK_NAME, tree_bytes


def check(history: Path, backups: Path, now: datetime, maximum_age_hours: int = 30,
          minimum_free_bytes: int = 256 * 1024 * 1024,
          maximum_backup_bytes: int = DEFAULT_BUDGET) -> list[str]:
    if maximum_age_hours <= 0 or minimum_free_bytes < 0 or maximum_backup_bytes <= 0:
        raise ValueError('Invalid monitoring policy')
    problems = []
    try:
        with sqlite3.connect(history.resolve().as_uri() + '?mode=ro', uri=True) as db:
            if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
                problems.append('history_integrity_failed')
            rows = db.execute('SELECT status, finished_at FROM runs ORDER BY id DESC LIMIT 2').fetchall()
        if len(rows) < 2 or any(status != 'succeeded' for status, _ in rows):
            problems.append('latest_jobs_not_successful')
        for _, finished in rows:
            stamp = datetime.fromisoformat(finished) if finished else None
            if not stamp or stamp.utcoffset() is None:
                problems.append('job_timestamp_missing')
            elif not 0 <= (now - stamp).total_seconds() <= maximum_age_hours * 3600:
                problems.append('jobs_stale_or_future')
        if shutil.disk_usage(history.parent).free < minimum_free_bytes:
            problems.append('disk_space_low')
    except (OSError, ValueError, sqlite3.Error):
        problems.append('history_unavailable')
    valid = []
    try:
        if tree_bytes(backups) >= maximum_backup_bytes:
            problems.append('backup_budget_exhausted')
        if shutil.disk_usage(backups).free < minimum_free_bytes:
            problems.append('backup_disk_space_low')
        for candidate in backups.iterdir():
            if candidate.name == LOCK_NAME and candidate.is_file() and not candidate.is_symlink():
                continue
            try:
                validate_snapshot(candidate)
                # Directory names and mtimes are not freshness evidence.
                manifest = json.loads((candidate / 'manifest.json').read_text())
                stamp = datetime.fromisoformat(manifest['created_at'])
                if 0 <= (now - stamp).total_seconds() <= maximum_age_hours * 3600:
                    valid.append(candidate)
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
                problems.append('backup_invalid_or_unknown')
    except (OSError, ValueError):
        problems.append('backups_unavailable')
    if not valid:
        problems.append('fresh_valid_backup_missing')
    return sorted(set(problems))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', type=Path, required=True)
    parser.add_argument('--backups', type=Path, required=True)
    parser.add_argument('--maximum-backup-bytes', type=int, default=DEFAULT_BUDGET)
    parser.add_argument('--minimum-free-bytes', type=int, default=256 * 1024 * 1024)
    parser.add_argument('--maximum-age-hours', type=int, default=30)
    args = parser.parse_args()
    issues = check(args.history, args.backups, datetime.now(timezone.utc),
                   args.maximum_age_hours, args.minimum_free_bytes, args.maximum_backup_bytes)
    print(json.dumps({'event': 'operational_health', 'issues': issues}))
    raise SystemExit(bool(issues))


if __name__ == '__main__':
    main()
