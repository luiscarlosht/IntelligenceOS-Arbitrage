"""Privileged one-shot broker core; intentionally no live launcher in M90.2.

Policy and transports are trusted constructor inputs, never protocol fields.
Only an independently reviewed future launcher may construct a production policy.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat
import threading

from app import m90
from app.m80_contract import unique
from app.m88_state import write, stamp
from app.m89_deployment import configuration

OPERATION = 'M902_AUTH14_CATALOG15'


class BrokerError(Exception):
    """Contains only a fixed diagnostic; never underlying exception text."""


def message(raw: bytes) -> None:
    if not isinstance(raw, bytes) or len(raw) > 256:
        raise BrokerError('INVALID_REQUEST')
    try:
        value = json.loads(raw, object_pairs_hook=unique)
        if (not isinstance(value, dict) or set(value) != {'version', 'operation'}
                or type(value['version']) is not int or value['version'] != 1
                or value['operation'] != OPERATION):
            raise ValueError()
    except Exception:
        raise BrokerError('INVALID_REQUEST') from None


@dataclass(frozen=True)
class Identity:
    device: int
    inode: int

    @classmethod
    def of(cls, path: Path):
        info = path.lstat()
        return cls(info.st_dev, info.st_ino)


@dataclass(frozen=True)
class Policy:
    """Privileged launcher's immutable reviewed configuration, not requester data.

    Test policies use synthetic paths. No API deserializes Policy from requests.
    root: trusted ancestor; production must use / to inspect the full chain.
    """
    root: Path
    uid: int
    requester_uid: int
    release_commit: str
    baseline_sha256: str
    seller_id: str
    application_id: str
    ledger: Path
    account_lock: Path
    account_identity: Identity
    ledger_lock: Path
    ledger_identity: Identity
    credentials: Path
    credential_sha256: str
    evidence: Path
    evidence_sha256: str
    approval: Path
    claim: Path

    def binding(self):
        return dict(operation=OPERATION, release_commit=self.release_commit,
                    baseline_sha256=self.baseline_sha256, seller_id=self.seller_id,
                    marketplace_id=m90.MARKETPLACE, application_id=self.application_id,
                    requester_uid=self.requester_uid,
                    account_lock=str(self.account_lock),
                    account_device=self.account_identity.device, account_inode=self.account_identity.inode,
                    ledger=str(self.ledger), ledger_lock=str(self.ledger_lock),
                    ledger_device=self.ledger_identity.device, ledger_inode=self.ledger_identity.inode,
                    credential_path=str(self.credentials), credential_sha256=self.credential_sha256,
                    evidence_sha256=self.evidence_sha256)


def private(path: Path, policy: Policy, *, directory=False):
    """No links, hardlinks, group writers or requester-writable ancestor chain."""
    if not path.is_absolute() or '..' in path.parts or not path.is_relative_to(policy.root):
        raise ValueError('Protected path required')
    if not directory and stat.S_IMODE(path.parent.lstat().st_mode) != 0o700:
        raise ValueError('Owner-only containing directory required')
    for parent in (path, *path.parents):
        info = parent.lstat()
        is_dir = directory if parent == path else True
        if (info.st_uid != policy.uid
                or (bool(stat.S_IMODE(info.st_mode) & 0o022) if is_dir
                    else stat.S_IMODE(info.st_mode) != 0o600)
                or not (stat.S_ISDIR(info.st_mode) if is_dir else stat.S_ISREG(info.st_mode))
                or (not is_dir and info.st_nlink != 1)):
            raise ValueError('Protected metadata required')
        if parent == policy.root:
            break


def protected_bytes(path, policy, maximum=65536):
    private(path, policy)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = path.lstat()
        actual = os.fstat(fd)
        if (actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError('Protected file changed')
        raw = os.read(fd, maximum + 1)
        if len(raw) > maximum:
            raise ValueError('Bound exceeded')
        return raw
    finally:
        os.close(fd)


def document(raw):
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if not isinstance(value, dict):
        raise ValueError('Object required')
    return value


@contextmanager
def existing(path, identity, policy):
    private(path, policy)
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (Identity(info.st_dev, info.st_ino) != identity or Identity.of(path) != identity
                or info.st_uid != policy.uid or stat.S_IMODE(info.st_mode) != 0o600
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError('Lock identity mismatch')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # A protected ancestor prevents unprivileged replacement after this check.
        if Identity.of(path) != identity:
            raise ValueError('Lock replaced')
        yield
    finally:
        os.close(fd)


def aware(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Aware timestamp required')
    return result


def authorize(policy, now):
    if (not re.fullmatch('[0-9a-f]{40}', policy.release_commit)
            or not re.fullmatch('[0-9a-f]{64}', policy.baseline_sha256)
            or type(policy.uid) is not int or type(policy.requester_uid) is not int
            or policy.requester_uid < 0 or policy.uid == policy.requester_uid):
        raise ValueError('Invalid trusted policy')
    raw = protected_bytes(policy.approval, policy)
    approval = document(raw)
    if set(approval) != {'binding', 'approved_by', 'approved_at', 'expires_at', 'nonce'}:
        raise ValueError('Exact approval schema required')
    if (json.dumps(approval['binding'], sort_keys=True) != json.dumps(policy.binding(), sort_keys=True)
            or not isinstance(approval['approved_by'], str)
            or not approval['approved_by'] or not isinstance(approval['nonce'], str)
            or not re.fullmatch('[0-9a-f]{64}', approval['nonce'])):
        raise ValueError('Approval mismatch')
    start, end = aware(approval['approved_at']), aware(approval['expires_at'])
    if not start <= now < end or not 0 < (end-start).total_seconds() <= 3600:
        raise ValueError('Expired or invalid approval')
    evidence_raw = protected_bytes(policy.evidence, policy)
    if hashlib.sha256(evidence_raw).hexdigest() != policy.evidence_sha256:
        raise ValueError('Evidence drift')
    evidence = document(evidence_raw)
    if (evidence.get('seller_id') != policy.seller_id
            or evidence.get('application_id') != policy.application_id
            or evidence.get('marketplace_id') != m90.MARKETPLACE
            or evidence.get('credential_sha256') != policy.credential_sha256
            or not isinstance(evidence.get('reviewer'), str) or not evidence['reviewer']
            or not 0 <= (now-aware(evidence['reviewed_at'])).total_seconds() <= 86400):
        raise ValueError('Reviewed evidence required')
    for key in ('seller_authorization', 'application_product_listing_role',
                'us_marketplace_participation', 'protected_credentials_binding'):
        item = evidence.get(key, {})
        if item.get('confirmed') is not True or not isinstance(item.get('reference'), str) or not item['reference']:
            raise ValueError('Evidence reference required')
    return hashlib.sha256(raw).hexdigest(), end


def _execute(raw, peer_uid, policy, auth, catalog):
    message(raw)
    # peer_uid must come from kernel credentials in a future launcher, never JSON.
    if os.geteuid() != policy.uid or peer_uid != policy.requester_uid:
        raise PermissionError('Unauthorized identity')
    if (threading.current_thread() is not threading.main_thread()
            or signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0)):
        raise PermissionError('Dedicated main process required')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    credentials = {}
    token = response = None
    with existing(policy.account_lock, policy.account_identity, policy), existing(
            policy.ledger_lock, policy.ledger_identity, policy):
        private(policy.ledger, policy)
        value = m90.history(policy.ledger, policy.baseline_sha256)
        digest, expires_at = authorize(policy, datetime.now(timezone.utc))
        private(policy.claim.parent, policy, directory=True)
        # One fixed claim per operation, independent of approval nonce and ledger.
        # Exclusive creation + file and directory fsync is the approval consumption.
        write(policy.claim, dict(operation=OPERATION, approval_sha256=digest,
                                 binding=policy.binding(), claimed_at=stamp()))
        previous = signal.getsignal(signal.SIGALRM)
        def deadline(*_):
            raise TimeoutError('Workflow deadline')
        signal.signal(signal.SIGALRM, deadline)
        try:
            signal.alarm(40)  # one absolute deadline, never reset between requests
            raw_credentials = protected_bytes(policy.credentials, policy, 16384)
            try:
                if hashlib.sha256(raw_credentials).hexdigest() != policy.credential_sha256:
                    raise ValueError('Credential binding mismatch')
            finally:
                raw_credentials = None
            # Reuses strict fixed-key configuration and PURCHASE_AUTHORIZED=false.
            credentials = configuration(policy.credentials)
            for number, phase in ((14, 'authentication'), (15, 'catalog_read_only')):
                if datetime.now(timezone.utc) >= expires_at:
                    raise PermissionError('Approval expired')
                attempt = dict(number=number, phase=phase, candidate_id=None if number == 14 else m90.ASIN,
                               operation=OPERATION, status='RESERVED', reserved_at=stamp(),
                               baseline_sha256=policy.baseline_sha256)
                value['attempts'].append(attempt)
                value['attempts_used'] = number
                write(policy.ledger, value, replace=True)
                try:
                    if datetime.now(timezone.utc) >= expires_at:
                        raise PermissionError('Approval expired before dispatch')
                    if number == 14:
                        token = auth(credentials)
                        credentials.clear()
                        if (not isinstance(token, str) or not 1 <= len(token) <= 2048
                                or any(not c.isascii() or not c.isprintable() or c.isspace() for c in token)):
                            raise ValueError('Invalid token')
                        attempt['token_received'] = True
                    else:
                        try:
                            status, response = catalog(token)
                        finally:
                            token = None
                        if type(status) is int and 100 <= status <= 599:
                            attempt['http_status'] = status
                        if type(status) is not int or status != 200:
                            raise ValueError('Catalog rejected')
                        result = m90.parse_response(response)
                        response = None
                        attempt['result'] = result
                    attempt.update(status='COMPLETE', completed_at=stamp())
                except BaseException:
                    attempt.update(status='FAILED', completed_at=stamp(), outcome='FAILED_OR_UNCERTAIN_NO_RETRY')
                    write(policy.ledger, value, replace=True)
                    raise
                # Auth completion MUST be durable before next reservation.
                write(policy.ledger, value, replace=True)
            return result
        finally:
            credentials.clear()
            token = response = None
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)


def execute(raw: bytes, peer_uid: int, policy: Policy, *, auth, catalog) -> dict:
    """Trusted broker core. No transport defaults: M90.2 tests inject mocks only.

    Not an unprivileged Python API security boundary. Deployment must protect
    imports/policy/transports and authenticate peer_uid outside this function.
    """
    try:
        return _execute(raw, peer_uid, policy, auth, catalog)
    except BaseException:
        raise BrokerError('STOPPED_NO_RETRY_OPERATOR_REVIEW_REQUIRED') from None


def main():
    # Deliberately no production file reads, socket, sudo, or live execute command.
    print(json.dumps(dict(operation=OPERATION, live_enabled=False, network='NOT_TESTED',
                         blocker='Separate launcher and legacy-writer coordination review required',
                         purchase_authorized=False), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
