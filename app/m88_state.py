"""M88 durable cumulative accounting; no network and no automatic replay."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from app.m67_state import secure
from app.m80_contract import unique


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def read(path: Path) -> dict:
    secure(path)
    if path.stat().st_size > 8*1024*1024:
        raise ValueError('Bounded M88 state required')
    value = json.loads(path.read_bytes(), object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    if not isinstance(value, dict):
        raise ValueError('M88 state object required')
    return value


def sha(path: Path) -> str:
    secure(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict, *, replace: bool = False) -> None:
    secure(path.parent, directory=True)
    if path.exists():
        secure(path)
        if not replace:
            raise FileExistsError('M88 artifacts are exclusive')
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str)+'\n').encode()
    if replace:
        fd, temporary = tempfile.mkstemp(prefix='.m88-', dir=path.parent)
    else:
        fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
        temporary = None
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        if temporary:
            os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if temporary and os.path.exists(temporary): os.unlink(temporary)


@contextmanager
def lock(path: Path):
    secure(path.parent, directory=True)
    fd = os.open(path, os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
    try:
        secure(path)
        fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def ledger(path: Path) -> dict:
    value = read(path)
    attempts = value.get('attempts')
    if (value.get('pilot') != 'm88-real-six-pilot' or value.get('ceiling') != 49
            or value.get('purchase_authorized') is not False
            or value.get('includes_authentication_and_retries') is not True
            or not isinstance(attempts, list) or type(value.get('attempts_used')) is not int
            or not 0 <= value['attempts_used'] <= 49 or value['attempts_used'] != len(attempts)):
        raise ValueError('Invalid cumulative M88 ledger; never reset or repair automatically')
    if any(not isinstance(a,dict) or type(a.get('number')) is not int or a['number'] != i or a.get('status') not in ('RESERVED','COMPLETE','FAILED')
           for i,a in enumerate(attempts, 1)):
        raise ValueError('Invalid cumulative M88 attempt sequence')
    return value


class Journal:
    """Caller holds account and ledger locks throughout a one-shot run."""
    def __init__(self, path: Path, plan_sha: str):
        self.path, self.plan_sha = path, plan_sha

    def start(self) -> None:
        value = ledger(self.path)
        if value.get('m88_operation') is not None:
            raise PermissionError('M88 already claimed; recovery is report-only, never replay')
        if value['attempts_used'] + 31 > 49:
            raise PermissionError('Insufficient cumulative budget for bounded M88 operation')

    def reserve(self, phase: str, candidate_id: str | None) -> int:
        if (phase not in ('authentication','search','detail','offers','fees_FBA','fees_FBM')
                or (candidate_id is not None if phase=='authentication' else not isinstance(candidate_id,str) or not candidate_id)):
            raise ValueError('Fixed M88 request phases required')
        value = ledger(self.path)
        operation = value.get('m88_operation')
        if operation is not None and operation != self.plan_sha:
            raise PermissionError('M88 operation binding drift')
        if value['attempts_used'] >= 49:
            raise PermissionError('Cumulative Amazon attempt ceiling reached')
        own = [a for a in value['attempts'] if a.get('plan_sha256') == self.plan_sha]
        if len(own) >= 31 or any(a['status'] != 'COMPLETE' for a in own):
            raise PermissionError('Attempt ceiling or unresolved prior attempt')
        if (sum(a['phase']==phase for a in own)>=(1 if phase=='authentication' else 6)
                or any(a['phase']==phase and a['candidate_id']==candidate_id for a in own)):
            raise PermissionError('No repeated or exploratory request permitted')
        value['m88_operation'] = self.plan_sha
        number = value['attempts_used'] + 1
        value['attempts'].append(dict(number=number, phase=phase, candidate_id=candidate_id,
            plan_sha256=self.plan_sha, status='RESERVED', reserved_at=stamp()))
        value['attempts_used'] = number
        write(self.path, value, replace=True)  # fsync file + parent BEFORE possible send.
        return number

    def finish(self, number: int, status: str, **metadata) -> None:
        value = ledger(self.path)
        attempt = value['attempts'][number-1]
        if (status not in ('COMPLETE','FAILED') or attempt['status'] != 'RESERVED'
                or attempt['plan_sha256'] != self.plan_sha):
            raise ValueError('Invalid M88 completion')
        attempt.update(status=status, completed_at=stamp(), **metadata)
        write(self.path, value, replace=True)
