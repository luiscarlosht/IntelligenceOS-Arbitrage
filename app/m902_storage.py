"""Descriptor-relative broker storage. No lock creation or recovery API.

Pinned directory descriptors prevent substitution from redirecting reads/writes.
The complete chain is revalidated at each boundary; privileged hostile writers
remain outside the advisory-lock trust model. Synthetic tests use a private anchor.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat


def identity(info):
    return info.st_dev, info.st_ino


def metadata(info, uid, *, directory=False, private=False):
    if info.st_uid != uid:
        raise ValueError('Untrusted owner')
    mode = stat.S_IMODE(info.st_mode)
    if directory:
        if not stat.S_ISDIR(info.st_mode) or mode & 0o022 or (private and mode != 0o700):
            raise ValueError('Untrusted directory')
    elif not stat.S_ISREG(info.st_mode) or mode != 0o600 or info.st_nlink != 1:
        raise ValueError('Untrusted file')


class Directory:
    def __init__(self, path, policy):
        self.path, self.policy, self.chain = path, policy, []
        if (not path.is_absolute() or '..' in path.parts or not policy.root.is_absolute()
                or '..' in policy.root.parts or not path.is_relative_to(policy.root)):
            raise ValueError('Protected absolute path required')
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            fd = os.open('/', flags)
            self.chain.append((None, '/', fd, policy.root == Path('/')))
            current = Path('/')
            for part in path.parts[1:]:
                current /= part
                parent = self.chain[-1][2]
                before = os.stat(part, dir_fd=parent, follow_symlinks=False)
                fd = os.open(part, flags, dir_fd=parent)
                self.chain.append((parent, part, fd, current.is_relative_to(policy.root)))
                if identity(before) != identity(os.fstat(fd)):
                    raise ValueError('Directory changed during open')
            self.fd = self.chain[-1][2]
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        for parent, name, fd, protected in self.chain:
            actual = os.fstat(fd)
            if parent is not None:
                named = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if identity(named) != identity(actual) or not stat.S_ISDIR(named.st_mode):
                    raise ValueError('Directory identity changed')
            if protected:
                metadata(actual, self.policy.uid, directory=True, private=fd == self.fd)

    def close(self):
        for _, _, fd, _ in reversed(self.chain):
            os.close(fd)
        self.chain.clear()

    def open(self, name, flags=os.O_RDONLY):
        if not name or Path(name).name != name or name in ('.', '..'):
            raise ValueError('Single filename required')
        self.check()
        before = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        metadata(before, self.policy.uid)
        fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOATIME,
                     dir_fd=self.fd)
        try:
            actual = os.fstat(fd)
            metadata(actual, self.policy.uid)
            after = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            if identity(before) != identity(actual) or identity(after) != identity(actual):
                raise ValueError('File changed during open')
            self.check()
            return fd
        except BaseException:
            os.close(fd)
            raise


class Store:
    def __init__(self, policy):
        self.policy, self.directories, self.versions = policy, {}, {}
        self.locked = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        for directory in self.directories.values():
            directory.close()

    def directory(self, path):
        if (not path.is_absolute() or '..' in path.parts or not path.is_relative_to(self.policy.root)):
            raise ValueError('Protected path required')
        if path.parent not in self.directories:
            self.directories[path.parent] = Directory(path.parent, self.policy)
        return self.directories[path.parent]

    def check(self):
        for directory in self.directories.values():
            directory.check()
        for directory, name, fd in self.locked:
            named = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
            metadata(named, self.policy.uid)
            if identity(named) != identity(os.fstat(fd)):
                raise ValueError('Held lock replaced')

    def read(self, path, maximum=65536):
        directory = self.directory(path)
        fd = directory.open(path.name)
        try:
            before = os.fstat(fd)
            if before.st_size > maximum:
                raise ValueError('Bound exceeded')
            chunks, size = [], 0
            while True:
                raw = os.read(fd, min(65536, maximum + 1 - size))
                if not raw:
                    break
                chunks.append(raw)
                size += len(raw)
                if size > maximum:
                    raise ValueError('Bound exceeded')
            after = os.fstat(fd)
            named = os.stat(path.name, dir_fd=directory.fd, follow_symlinks=False)
            if (identity(named) != identity(before) or before != after):
                raise ValueError('File changed during read')
            self.check()
            raw = b''.join(chunks)
            self.versions[path] = hashlib.sha256(raw).digest()
            return raw
        finally:
            os.close(fd)

    @contextmanager
    def lock(self, path, expected):
        directory = self.directory(path)
        fd = directory.open(path.name, os.O_RDWR)
        try:
            if identity(os.fstat(fd)) != (expected.device, expected.inode):
                raise ValueError('Lock identity mismatch')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.check()
            if identity(os.stat(path.name, dir_fd=directory.fd, follow_symlinks=False)) != identity(os.fstat(fd)):
                raise ValueError('Lock changed')
            held = (directory, path.name, fd)
            self.locked.append(held)
            try:
                yield
            finally:
                self.locked.remove(held)
        finally:
            os.close(fd)

    def write(self, path, value, *, replace=False):
        directory = self.directory(path)
        self.check()
        if replace:
            expected = self.versions.get(path)
            if expected is None or hashlib.sha256(self.read(path, 8*1024*1024)).digest() != expected:
                raise ValueError('Unreviewed ledger change')
        raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
        name = '.m902-'+secrets.token_hex(16) if replace else path.name
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=directory.fd)
        temporary = replace
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self.check()
            if replace:
                os.replace(name, path.name, src_dir_fd=directory.fd, dst_dir_fd=directory.fd)
                temporary = False
            os.fsync(directory.fd)
            self.check()
            self.versions[path] = hashlib.sha256(raw).digest()
        finally:
            if temporary:
                os.unlink(name, dir_fd=directory.fd)
