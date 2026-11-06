"""Synthetic-only descriptor storage. No production constructor or command.

Callers may open only isolated private fixtures beneath /tmp. No symlink or
cross-device descendant is accepted. Explicit fixture provisioning is separate
from every read/verification method. No credentials or network imports.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat


class Blocked(Exception):
    """Sanitized boundary diagnostic."""


def identity(info):
    return info.st_dev, info.st_ino


def snapshot(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
            info.st_nlink, info.st_size, info.st_atime_ns, info.st_mtime_ns, info.st_ctime_ns)


def metadata(info, uid, *, directory=False):
    if (info.st_uid != uid or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or (not directory and info.st_nlink != 1)):
        raise Blocked('STORAGE_BLOCKED')


class FixtureFS:
    def __init__(self, root: Path, *, fault=None):
        # Canonical lexical check before ANY filesystem access: never accept /var,
        # /etc, /root, caller TMPDIR, .., or production aliases through symlinks.
        if (type(root) is not Path and not isinstance(root, Path)) or (
                not root.is_absolute() or not root.is_relative_to('/tmp')
                or len(root.parts) < 3 or '..' in root.parts or str(root) != os.path.normpath(root)):
            raise Blocked('SYNTHETIC_FIXTURE_REQUIRED')
        self.root, self.uid, self.fault = root, os.getuid(), fault or (lambda _: None)
        self.dirs, self.edges, self.poisoned = {}, [], False
        try:
            # Ancestors are only traversed/stat'ed: O_PATH needs no ownership
            # privilege and cannot read entries or update directory atime.
            traversal = self.flags(directory=True, traversal=True)
            fd = os.open('/', traversal)
            self.dirs['/'] = fd
            path = Path('/')
            for part in root.parts[1:]:
                parent = fd
                before = os.stat(part, dir_fd=parent, follow_symlinks=False)
                path /= part
                flags = self.flags(directory=True) if path == root else traversal
                fd = os.open(part, flags, dir_fd=parent)
                self.dirs[str(path)] = fd
                self.edges.append((parent, part, fd, identity(os.fstat(fd)), path == root))
                if identity(before) != identity(os.fstat(fd)):
                    raise Blocked('STORAGE_BLOCKED')
            self.fd = fd
            self.device = os.fstat(fd).st_dev
            metadata(os.fstat(fd), self.uid, directory=True)
            self.check()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def flags(*, directory=False, traversal=False):
        if any(not getattr(os, name, 0) for name in ('O_NOATIME','O_NOFOLLOW','O_CLOEXEC','O_DIRECTORY','O_PATH')):
            raise Blocked('METADATA_SAFE_ACCESS_REQUIRED')
        if traversal:
            return os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_DIRECTORY
        return os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOATIME | os.O_NONBLOCK | (os.O_DIRECTORY if directory else 0)

    def close(self):
        for fd in reversed(tuple(self.dirs.values())):
            os.close(fd)
        self.dirs.clear()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def validate(self, info, *, directory=False):
        metadata(info, self.uid, directory=directory)

    def check(self):
        if self.poisoned: raise Blocked('DURABILITY_UNCERTAIN')
        for parent, name, fd, expected, protected in self.edges:
            actual = os.fstat(fd)
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if identity(actual) != expected or identity(named) != expected or not stat.S_ISDIR(named.st_mode):
                raise Blocked('STORAGE_BLOCKED')
            if protected:
                self.validate(actual, directory=True)
                if actual.st_dev != self.device: raise Blocked('CROSS_DEVICE_BLOCKED')

    def directory(self, relative=''):
        if type(relative) is not str or relative.startswith('/') or '..' in relative.split('/'):
            raise Blocked('STORAGE_BLOCKED')
        self.check()
        fd = self.fd
        current = ''
        for part in relative.split('/') if relative else ():
            if not part or part in ('.','..'): raise Blocked('STORAGE_BLOCKED')
            current = current+'/'+part if current else part
            key = '@'+current
            if key not in self.dirs:
                before = os.stat(part, dir_fd=fd, follow_symlinks=False)
                child = os.open(part, self.flags(directory=True), dir_fd=fd)
                try:
                    info = os.fstat(child)
                    self.validate(info, directory=True)
                    if identity(before) != identity(info) or info.st_dev != self.device:
                        raise Blocked('STORAGE_BLOCKED')
                except BaseException:
                    os.close(child)
                    self.poisoned = True
                    raise
                self.dirs[key] = child
                self.edges.append((fd, part, child, identity(info), True))
            fd = self.dirs[key]
        self.check()
        return fd

    @staticmethod
    def split(relative):
        if type(relative) is not str or relative.startswith('/') or any(x in ('','.','..') for x in relative.split('/')):
            raise Blocked('STORAGE_BLOCKED')
        parent, _, name = relative.rpartition('/')
        return parent, name

    def entries(self, relative=''):
        fd = self.directory(relative)
        result = sorted(os.listdir(fd))
        if len(result) > 2048: raise Blocked('BOUND_EXCEEDED')
        self.check()
        return result

    def mkdir(self, relative):
        parent, name = self.split(relative)
        fd = self.directory(parent)
        try:
            os.mkdir(name, 0o700, dir_fd=fd)
            os.fsync(fd)
            self.directory(relative)
        except BaseException:
            self.poisoned = True
            raise

    @contextmanager
    def opened(self, relative):
        parent, name = self.split(relative)
        directory = self.directory(parent)
        before = os.stat(name, dir_fd=directory, follow_symlinks=False)
        self.validate(before)
        fd = os.open(name, self.flags(), dir_fd=directory)
        try:
            initial = snapshot(os.fstat(fd))
            if snapshot(before) != initial or os.fstat(fd).st_dev != self.device:
                raise Blocked('STORAGE_BLOCKED')
            self.validate(os.fstat(fd))
            yield fd
            self.check()
            if (snapshot(os.fstat(fd)) != initial
                    or snapshot(os.stat(name, dir_fd=directory, follow_symlinks=False)) != initial):
                raise Blocked('STORAGE_BLOCKED')
        finally: os.close(fd)

    @staticmethod
    def read_fd(fd, maximum):
        if os.fstat(fd).st_size > maximum: raise Blocked('BOUND_EXCEEDED')
        chunks, size = [], 0
        while True:
            raw = os.read(fd, min(65536, maximum+1-size))
            if not raw: break
            chunks.append(raw); size += len(raw)
            if size > maximum: raise Blocked('BOUND_EXCEEDED')
        return b''.join(chunks)

    def read(self, relative, maximum=65536):
        with self.opened(relative) as fd: return self.read_fd(fd, maximum)

    @contextmanager
    def lock(self, relative, reviewed):
        with self.opened(relative) as fd:
            if identity(os.fstat(fd)) != reviewed: raise Blocked('LOCK_IDENTITY_BLOCKED')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def create(self, relative, raw, *, label='file'):
        if type(raw) is not bytes or len(raw) > 8*1024*1024: raise Blocked('BOUND_EXCEEDED')
        parent, name = self.split(relative)
        directory = self.directory(parent)
        self.fault(label+'.before_write')
        fd = os.open(name, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC, 0o600, dir_fd=directory)
        try:
            # Explicit partial-write point for process-kill and error injection.
            half = len(raw)//2
            for block in (raw[:half], raw[half:]):
                while block:
                    count = os.write(fd, block)
                    if count <= 0: raise OSError('WRITE_FAILED')
                    block = block[count:]
                if half >= 0:
                    self.fault(label+'.during_write'); half = -1
            os.fsync(fd)
            self.fault(label+'.after_file_fsync')
        except BaseException:
            self.poisoned = True
            raise
        finally: os.close(fd)
        try:
            self.check()
            self.fault(label+'.before_dir_fsync')
            os.fsync(directory)
            self.fault(label+'.after_dir_fsync')
            self.check()
        except BaseException:
            self.poisoned = True
            raise

    def publish(self, relative, raw, *, replace=False, label='manifest', guard=None):
        parent, name = self.split(relative)
        directory = self.directory(parent)
        pending = parent+'/'+name+'.pending' if parent else name+'.pending'
        # A stale pending artifact always blocks; never unlink or repair it.
        self.create(pending, raw, label=label)
        try:
            if os.fstat(directory).st_dev != self.device: raise Blocked('CROSS_DEVICE_BLOCKED')
            try:
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                metadata(info, self.uid)
                if not replace: raise Blocked('EXISTING_PUBLICATION')
            except FileNotFoundError: pass
            self.check()
            if guard is not None:guard()
            os.rename(name+'.pending', name, src_dir_fd=directory, dst_dir_fd=directory)
            self.fault(label+'.after_rename')
            self.fault(label+'.before_publish_dir_fsync')
            os.fsync(directory)
            self.fault(label+'.after_publish_dir_fsync')
            self.check()
            if guard is not None:guard()
        except BaseException:
            self.poisoned = True
            raise
