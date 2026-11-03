"""Offline input pins and exclusive private output; never reads credential artifacts."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import urlsplit, unquote, parse_qs
from app.m70_sources import strict_json
from app.m78 import atomic_publish, _rename
from app.m78_reporting import write, encoded

SENSITIVE=re.compile(r'credential|authorization|account.context|token|secret|\.env|\.aws|\.ssh',re.I)
ACTIVE=ContextVar('decision_offline',default=None)
INSTALLED=False


def safe(path:Path) -> Path:
    path=Path(path).absolute()
    if SENSITIVE.search(str(path)) or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('Nonsymlink noncredential evidence paths required')
    return path.resolve()


def digest(path:Path) -> str:
    path=safe(path)
    info=path.stat()
    if not path.is_file() or info.st_nlink!=1 or info.st_size>64*1024*1024: raise ValueError('Bounded single-link evidence required')
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def pinned(path:Path,expected:str) -> dict:
    if not isinstance(expected,str) or not re.fullmatch('[a-f0-9]{64}',expected) or digest(path)!=expected:
        raise ValueError('Reviewed evidence SHA-256 mismatch')
    data=strict_json(path)
    if not isinstance(data,dict) or digest(path)!=expected: raise ValueError('Evidence object/drift')
    return data


@contextmanager
def offline(reads=(),writes=()):
    global INSTALLED
    if not INSTALLED:
        def audit(event,args):
            scope=ACTIVE.get()
            if scope is None:return
            read_paths,write_roots=scope
            if event.startswith(('socket.','subprocess.','os.exec','os.spawn','os.posix_spawn','os.system')):
                raise PermissionError('Offline decision pipeline forbids network/processes')
            if event=='sqlite3.connect' and args and str(args[0])!=':memory:':
                value=str(args[0]);parsed=urlsplit(value)
                path=Path(unquote(parsed.path) if value.startswith('file:') else value).resolve()
                readonly=value.startswith('file:') and parse_qs(parsed.query).get('mode')==['ro'] and path in read_paths
                if not readonly and not any(path.is_relative_to(root) for root in write_roots):
                    raise PermissionError('SQLite writes outside owned history forbidden')
            if event in ('os.symlink','os.link'):raise PermissionError('Offline outputs forbid symlinks/hardlinks')
            if event=='os.rename':
                destination=Path(os.fsdecode(args[1])).resolve()
                if not any(destination.is_relative_to(root) for root in write_roots):raise PermissionError('Rename outside owned outputs forbidden')
            if event in ('open','os.mkdir','os.remove','os.rename','os.rmdir','os.chmod','os.utime','os.truncate') and args and isinstance(args[0],(str,bytes,os.PathLike)):
                path=Path(os.fsdecode(args[0])).resolve()
                is_code=path.suffix in ('.py','.pyc') and path.is_relative_to(Path(__file__).resolve().parent)
                if SENSITIVE.search(str(path)) and not is_code:raise PermissionError('Private authority access forbidden')
                writing=event!='open' or len(args)>2 and isinstance(args[2],int) and bool(args[2]&(os.O_WRONLY|os.O_RDWR))
                if writing and not any(path.is_relative_to(root) for root in write_roots):
                    raise PermissionError('Writes outside new report/history forbidden')
        sys.addaudithook(audit);INSTALLED=True
    token=ACTIVE.set(({safe(p) for p in reads},tuple(safe(p) for p in writes)))
    try:yield
    finally:ACTIVE.reset(token)


@contextmanager
def publication(output:Path, protected:list[Path], *, archived_roots=()):
    output=safe(output); roots=[safe(p) for p in protected]
    frozen=[Path(p) for p in archived_roots]
    if any(not p.is_absolute() or '..' in p.parts for p in frozen):raise ValueError('Canonical archived boundaries required')
    if (output.exists() or not output.parent.is_dir() or output.is_relative_to('/mnt')
            or any(output.is_relative_to(p if p.is_dir() else p.parent) or p.is_relative_to(output) for p in roots)
            or any(output.is_relative_to(p) or p.is_relative_to(output) for p in frozen)):
        raise ValueError('Fresh local output outside protected evidence required')
    stage=Path(tempfile.mkdtemp(prefix='.decision-stage-',dir=output.parent));stage.chmod(0o700)
    try:
        yield stage
        atomic_publish(stage,output,_rename)
    finally:
        if stage.exists():shutil.rmtree(stage)


def json_write(path:Path,value:dict) -> None:write(path,encoded(value).encode())
