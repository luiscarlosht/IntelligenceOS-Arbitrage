"""Read-only, network-free verifier. Production use requires separate approval.

Fixed invocation: python -I -B -m app.m902b_verify verify
No path, ownership, baseline or lock-identity arguments/environment overrides.
Only a fixed root-protected policy supplies independently reviewed lock identities.
"""
from contextlib import ExitStack, contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import sys

from app.m902_history import BASELINE_13, MAX_LEDGER, unique, validate_snapshot

ACCOUNT_LOCK = Path('/root/.intelligenceos-arbitrage-amazon/candidate-execution.lock')
LEDGER = Path('/var/lib/intelligenceos-arbitrage/m89/ledger.json')
LEDGER_LOCK = LEDGER.with_suffix('.lock')
POLICY = Path('/etc/intelligenceos-arbitrage/m902b/verification-policy.json')
# Fixed independent claim scope. Future broker launch policy must use this scope.
CLAIM_ROOT = Path('/var/lib/intelligenceos-arbitrage-protected')
# Existing m901 claim is detected by the strict ledger-directory entry allowlist.
ANCHOR = Path('/')
OWNER = 0


class VerificationError(Exception):
    """Fixed diagnostic only; never return protected paths or document content."""


def _identity(info) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _snapshot(info) -> tuple:
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
            info.st_nlink, info.st_size, info.st_atime_ns, info.st_mtime_ns, info.st_ctime_ns)


def _metadata(info, *, directory=False, private=False):
    if info.st_uid != OWNER:
        raise ValueError('Untrusted owner')
    mode = stat.S_IMODE(info.st_mode)
    if directory:
        if not stat.S_ISDIR(info.st_mode) or mode & 0o022 or (private and mode != 0o700):
            raise ValueError('Untrusted directory')
    elif not stat.S_ISREG(info.st_mode) or mode != 0o600 or info.st_nlink != 1:
        raise ValueError('Untrusted file')


def _flags(*, directory=False, traversal=False) -> int:
    required = ('O_NOFOLLOW', 'O_CLOEXEC', 'O_NOATIME', 'O_NONBLOCK', 'O_DIRECTORY', 'O_PATH')
    if any(not getattr(os, name, 0) for name in required):
        raise ValueError('Metadata-safe access unavailable')
    if traversal:
        return os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_DIRECTORY
    return (os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOATIME | os.O_NONBLOCK
            | (os.O_DIRECTORY if directory else 0))


class _Directory:
    """Pinned component chain; no creation, pathname reads or writable descriptors."""
    def __init__(self, path: Path, *, private=True):
        self.chain = []
        self.private = private
        if not path.is_absolute() or '..' in path.parts or not path.is_relative_to(ANCHOR):
            raise ValueError('Fixed absolute path required')
        try:
            # O_PATH only outside the protected anchor (synthetic test seam).
            # Production ANCHOR='/' retains strict O_NOATIME on every component.
            fd = os.open('/', _flags(directory=True, traversal=ANCHOR != Path('/')))
            self.chain.append((None, '/', fd, ANCHOR == Path('/'), _snapshot(os.fstat(fd))))
            current = Path('/')
            for name in path.parts[1:]:
                current /= name
                parent = self.chain[-1][2]
                before = os.stat(name, dir_fd=parent, follow_symlinks=False)
                fd = os.open(name, _flags(directory=True, traversal=not current.is_relative_to(ANCHOR)), dir_fd=parent)
                self.chain.append((parent, name, fd, current.is_relative_to(ANCHOR), _snapshot(os.fstat(fd))))
                if _identity(before) != _identity(os.fstat(fd)):
                    raise ValueError('Directory replaced')
            self.fd = self.chain[-1][2]
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        for parent, name, fd, protected, initial in self.chain:
            actual = os.fstat(fd)
            if _snapshot(actual) != initial:
                raise ValueError('Directory metadata changed')
            if parent is not None:
                named = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if _identity(named) != _identity(actual) or not stat.S_ISDIR(named.st_mode):
                    raise ValueError('Directory replaced')
            if protected:
                _metadata(actual, directory=True, private=fd == self.fd and self.private)

    def close(self):
        for _, _, fd, _, _ in reversed(self.chain):
            os.close(fd)
        self.chain.clear()

    @contextmanager
    def file(self, name: str):
        self.check()
        before = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        _metadata(before)
        fd = os.open(name, _flags(), dir_fd=self.fd)
        try:
            initial = _snapshot(os.fstat(fd))
            if _snapshot(before) != initial:
                raise ValueError('File replaced during open')
            _metadata(os.fstat(fd))
            yield fd, initial
            self.file_check(name, fd, initial)
        finally:
            os.close(fd)

    def file_check(self, name, fd, initial):
        self.check()
        if (_snapshot(os.fstat(fd)) != initial
                or _snapshot(os.stat(name, dir_fd=self.fd, follow_symlinks=False)) != initial):
            raise ValueError('Persistent file or metadata changed')

    def read(self, name: str, maximum: int) -> bytes:
        with self.file(name) as (fd, _):
            return _read(fd, maximum)

    def entries(self, expected: set[str]):
        self.check()
        if set(os.listdir(self.fd)) != expected:
            raise ValueError('Unexpected state or claim')
        self.check()


def _read(fd: int, maximum: int) -> bytes:
    if os.fstat(fd).st_size > maximum:
        raise ValueError('Bound exceeded')
    chunks, size = [], 0
    while True:
        block = os.read(fd, min(65536, maximum + 1 - size))
        if not block:
            break
        chunks.append(block)
        size += len(block)
        if size > maximum:
            raise ValueError('Bound exceeded')
    return b''.join(chunks)


def _policy(directory: _Directory) -> dict:
    raw = directory.read(POLICY.name, 4096)
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if type(value) is not dict or set(value) != {'version', 'account_lock', 'ledger_lock'}:
        raise ValueError('Invalid verification policy')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Invalid verification policy')
    for key in ('account_lock', 'ledger_lock'):
        item = value[key]
        if type(item) is not dict or set(item) != {'device', 'inode'}:
            raise ValueError('Invalid reviewed identity')
        if any(type(item[k]) is not int or not 0 <= item[k] <= 2**64-1 for k in item):
            raise ValueError('Invalid reviewed identity')
        if item['inode'] == 0:
            raise ValueError('Invalid reviewed identity')
    return value


def _claims(stack: ExitStack):
    # The dedicated future protected root must be absent or empty. No state is
    # provisioned by verification. Fail on even an empty claim or unexplained file.
    parent = _Directory(CLAIM_ROOT.parent, private=False)
    stack.callback(parent.close)
    try:
        os.stat(CLAIM_ROOT.name, dir_fd=parent.fd, follow_symlinks=False)
    except FileNotFoundError:
        parent.check()
        return lambda: _assert_absent(parent)
    child = _Directory(CLAIM_ROOT)
    stack.callback(child.close)
    child.entries(set())
    return lambda: child.entries(set())


def _assert_absent(parent):
    parent.check()
    try:
        os.stat(CLAIM_ROOT.name, dir_fd=parent.fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise ValueError('Unexpected protected state')


def _verify() -> dict:
    if os.geteuid() != OWNER or os.getuid() != OWNER:
        raise ValueError('Dedicated trusted identity required')
    with ExitStack() as stack:
        policy_directory = _Directory(POLICY.parent)
        stack.callback(policy_directory.close)
        policy = _policy(policy_directory)
        checkers = []
        # Linux flock on read-only descriptors is intentional: no O_RDWR needed.
        for path, key in ((ACCOUNT_LOCK, 'account_lock'), (LEDGER_LOCK, 'ledger_lock')):
            directory = _Directory(path.parent)
            stack.callback(directory.close)
            fd, initial = stack.enter_context(directory.file(path.name))
            if _identity(os.fstat(fd)) != (policy[key]['device'], policy[key]['inode']):
                raise ValueError('Reviewed lock identity mismatch')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            checkers.append((directory, path.name, fd, initial))
        ledger_directory = _Directory(LEDGER.parent)
        stack.callback(ledger_directory.close)
        ledger_directory.entries({LEDGER.name, LEDGER_LOCK.name})
        claims_check = _claims(stack)
        ledger_fd, ledger_initial = stack.enter_context(ledger_directory.file(LEDGER.name))
        raw = _read(ledger_fd, MAX_LEDGER)
        validate_snapshot(raw, BASELINE_13)
        ledger_directory.file_check(LEDGER.name, ledger_fd, ledger_initial)
        ledger_directory.entries({LEDGER.name, LEDGER_LOCK.name})
        claims_check()
        for directory, name, fd, initial in checkers:
            directory.file_check(name, fd, initial)
        policy_directory.check()
    # Success is emitted only after descriptors close and both kernel locks release.
    return dict(status='VERIFIED', baseline_match=True, attempts_used=13, ceiling=49,
                remaining=36, purchase_authorized=False, claims='ABSENT_IN_FIXED_SCOPE',
                persistent_changes=False)


def verify() -> dict:
    """Fixed-path public API. Internal seams exist solely for synthetic testing."""
    try:
        return _verify()
    except BaseException:
        raise VerificationError('VERIFICATION_BLOCKED') from None


def main(argv=None) -> int:
    # Validate invocation before touching any path, including for --help.
    args = sys.argv[1:] if argv is None else argv
    if args != ['verify']:
        print('{"code":"INVALID_INVOCATION","status":"BLOCKED"}')
        return 2
    try:
        result = verify()
    except VerificationError:
        print('{"code":"VERIFICATION_BLOCKED","status":"BLOCKED"}')
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
