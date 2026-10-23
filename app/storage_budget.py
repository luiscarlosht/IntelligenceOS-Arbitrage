"""Application disk admission controls; not a filesystem quota."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import shutil
import stat

DEFAULT_BUDGET = 1024 ** 3
DEFAULT_RESERVE = 256 * 1024 ** 2
LOCK_NAME = '.backup.lock'


class BudgetExceeded(ValueError):
    pass


def tree_bytes(path: Path) -> int:
    """Count all entries, including unknown/pending data; never follow symlinks."""
    info = path.lstat()
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError('Unsafe backup directory entry')
    used = max(info.st_size, info.st_blocks * 512)
    if stat.S_ISDIR(info.st_mode):
        used += sum(tree_bytes(child) for child in path.iterdir())
    return used


def enforce(directory: Path, additional: int, maximum: int, reserve: int) -> None:
    if maximum <= 0 or reserve < 0 or additional < 0:
        raise ValueError('Invalid disk policy')
    if tree_bytes(directory) + additional > maximum:
        raise BudgetExceeded('Backup byte budget exceeded')
    if shutil.disk_usage(directory).free < reserve + additional:
        raise BudgetExceeded('Backup filesystem reserve insufficient')


@contextmanager
def exclusive_backup(directory: Path):
    descriptor = os.open(directory / LOCK_NAME, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('Invalid backup lock')
        # Fail promptly rather than queue manual backups behind the timer.
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)
