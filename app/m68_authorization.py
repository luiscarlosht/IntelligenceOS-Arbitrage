"""Local-only M67 review preparation. No execution, transport or reservation imports."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import termios

from app import m67_policy
from app.m65_intelligence import build_audit, read_json
from app.m66_verification import ACCOUNT
from app.m67_state import ReadOnlyStore, secure
from app.observations import canonical, fingerprint

PRIVATE = Path.home()/'.intelligenceos-arbitrage-amazon'
MANIFEST_SHA256 = '8983bef70ce5cfd79d15b7611e4b5646784f37bfce1a88bd220286394303ee55'
VALIDITY_SECONDS = 900
CONFIRMATION = 'I VERIFIED THE ACCOUNT; PREPARE ONLY'
BUDGET = dict(authentication=1, restrictions=20, maximum_requests=21, retries=0,
              catalog=0, pricing=0, fees=0, retailer=0)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def implementation() -> dict:
    root = Path(__file__).parent
    return {name: hashlib.sha256((root/name).read_bytes()).hexdigest()
            for name in ('m68.py', 'm68_authorization.py')}


def private_bytes(path: Path) -> bytes:
    """Bounded, pinned owner-only input; values never enter diagnostics."""
    secure(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise ValueError('Unsafe private input')
        raw = os.read(fd, 32769)
        if len(raw) > 32768:
            raise ValueError('Private input exceeds bound')
        return raw
    finally:
        os.close(fd)


def load_private(path: Path) -> tuple[dict, str]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Ambiguous duplicate JSON key')
            result[key] = value
        return result
    raw = private_bytes(path)
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    if not isinstance(value, dict):
        raise ValueError('Private JSON object required')
    return value, hashlib.sha256(raw).hexdigest()


def paths(private: Path, name: str) -> tuple[Path, Path]:
    # CLI cannot redirect an authorization into the repository or another account.
    if private.absolute() != PRIVATE.absolute():
        raise ValueError('Existing account private directory required')
    secure(private, directory=True)
    repository = Path(__file__).resolve().parent.parent
    if private.resolve().is_relative_to(repository):
        raise ValueError('Private artifacts must be outside repository')
    if not re.fullmatch(r'm68-authorization-[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.json', name):
        raise ValueError('Dedicated nonsecret authorization filename required')
    artifact = private/name
    receipt = private/(name[:-5]+'.review.json')
    return artifact, receipt


@contextmanager
def existing_lock(private: Path):
    """Read-lock an existing cross-version lock, never create one."""
    fd = None
    try:
        path = private/'candidate-execution.lock'
        if path.exists() or path.is_symlink():
            secure(path)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield
    finally:
        if fd is not None:
            os.close(fd)


def snapshot(manifest_path: Path, digest: str, sources: list[Path], store_path: Path,
             private: Path, preflight_path: Path) -> tuple[dict, dict, str]:
    if digest != MANIFEST_SHA256:
        raise ValueError('Only original reviewed M66 digest supported')
    if (private/m67_policy.LEDGER).is_symlink():
        raise ValueError('Ambiguous permanent execution evidence')
    saved, _ = load_private(preflight_path)
    fresh = m67_policy.preflight(manifest_path, digest, sources, store_path, private)
    if not fresh['ready'] or fingerprint(saved) != fingerprint(fresh):
        raise ValueError('Fresh ready identical M67 preflight required')
    manifest, actual = read_json(manifest_path)
    inner = manifest['restrictions_proposal']
    if (actual != digest or len(inner['asins']) != 20 or len(set(inner['asins'])) != 20
            or inner['asins'] != fresh['asins'] or inner['budget'] != BUDGET
            or any(type(v) is not int for v in inner['budget'].values())
            or fresh['account_reference'] != ACCOUNT):
        raise ValueError('Exact frozen 20-ASIN scope required')
    binding, binding_sha = load_private(private/m67_policy.CONTEXT)
    if binding_sha != fresh['account_binding_sha256']:
        raise ValueError('Private account binding drift')
    # Hash credential bytes locally; never parse, print or export their contents.
    credential_sha = hashlib.sha256(private_bytes(private/'credentials.json')).hexdigest()
    if not hmac.compare_digest(credential_sha, binding['credentials_sha256']):
        raise ValueError('Credential/account association drift')
    return manifest, fresh, binding['seller_id']


def _hidden_terminal_line(terminal, prompt: str) -> str:
    """Read only the pinned controlling TTY; restore echo on every exit."""
    fd = terminal.fileno()
    previous = termios.tcgetattr(fd)
    hidden = previous[:]
    hidden[3] &= ~(termios.ECHO | termios.ECHONL)
    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, hidden)
        terminal.write(prompt)
        terminal.flush()
        line = terminal.readline()
        if not line:
            raise EOFError('Private terminal input unavailable')
        return line.removesuffix('\n')
    finally:
        termios.tcsetattr(fd, termios.TCSAFLUSH, previous)
        terminal.write('\n')
        terminal.flush()


def confirm_account(expected_seller: str) -> bool:
    """No argv/env/stdin bypass or echoed-input fallback."""
    fd = os.open('/dev/tty', os.O_RDWR | os.O_NOCTTY | os.O_CLOEXEC)
    with os.fdopen(fd, 'r+b', buffering=0) as raw:
        if not raw.isatty():
            raise ValueError('Private interactive terminal required')
        # Buffered r+ requires seeking, which Linux PTYs do not support.
        with io.TextIOWrapper(raw, encoding='utf-8', write_through=True) as terminal:
            supplied = _hidden_terminal_line(terminal, 'Privately verified seller ID (hidden): ')
            phrase = _hidden_terminal_line(terminal, 'Type I VERIFIED THE ACCOUNT; PREPARE ONLY (hidden): ')
    return hmac.compare_digest(supplied, expected_seller) and hmac.compare_digest(phrase, CONFIRMATION)


def check_authorization(manifest: dict, digest: str, artifact: dict, fresh: dict,
                        store_path: Path, private: Path, now: datetime) -> None:
    store = ReadOnlyStore(store_path)
    try:
        # execute=True models the flag in the PURE policy validator only. No
        # executor, token loader, transport or reservation is imported/called.
        m67_policy.authorize(manifest, digest, artifact, execute=True,
            audit=build_audit(private, store), preflight_report=fresh, now=now)
    finally:
        store.db.close()
    reviewed = datetime.fromisoformat(artifact['reviewed_at'])
    expires = datetime.fromisoformat(artifact['expires_at'])
    if expires-reviewed != timedelta(seconds=VALIDITY_SECONDS) or not reviewed <= now < expires:
        raise ValueError('Exact current 15-minute validity required')


def publish(private: Path, artifact_path: Path, receipt_path: Path,
            artifact: dict, receipt: dict) -> None:
    """Durable no-replace publication; receipt first, authorization last."""
    temporary = []
    try:
        for destination, value in ((receipt_path, receipt), (artifact_path, artifact)):
            fd, name = tempfile.mkstemp(prefix='.m68-pending-', dir=private)
            temporary.append(Path(name))
            with os.fdopen(fd, 'wb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write((canonical(value)+'\n').encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.link(name, destination, follow_symlinks=False)  # atomic NOREPLACE
            os.unlink(name)
            temporary.remove(Path(name))
            directory = os.open(private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)


def prepare(manifest_path: Path, digest: str, sources: list[Path], store_path: Path,
            private: Path, preflight_path: Path, name: str, review_reference: str) -> dict:
    artifact_path, receipt_path = paths(private, name)
    if artifact_path.exists() or artifact_path.is_symlink() or receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError('Never overwrite a review artifact')
    if not re.fullmatch(r'manual:[A-Za-z0-9._-]{1,80}', review_reference):
        raise ValueError('Nonsecret manual review reference required')
    with existing_lock(private):
        manifest, fresh, seller = snapshot(manifest_path,digest,sources,store_path,private,preflight_path)
        if confirm_account(seller) is not True:
            raise ValueError('Private human association confirmation required')
        # Terminal review can take time: reconstruct evidence again before writing.
        manifest, fresh, current_seller = snapshot(manifest_path,digest,sources,store_path,private,preflight_path)
        if not hmac.compare_digest(seller,current_seller):
            raise ValueError('Account changed during review')
        now = utcnow()
        artifact = dict(schema=1,approved=True,execution_permission=True,no_retry=True,
            manifest_sha256=digest,asins=manifest['restrictions_proposal']['asins'],account_reference=ACCOUNT,
            account_binding_sha256=fresh['account_binding_sha256'],marketplace_id=fresh['marketplace_id'],
            condition=fresh['condition'],budget=fresh['budget'],review_reference=review_reference,
            reviewed_at=now.isoformat(),expires_at=(now+timedelta(seconds=VALIDITY_SECONDS)).isoformat(),
            implementation_sha256=fresh['implementation_sha256'],preflight_sha256=fingerprint(fresh))
        check_authorization(manifest,digest,artifact,fresh,store_path,private,now)
        raw = (canonical(artifact)+'\n').encode(); artifact_sha = hashlib.sha256(raw).hexdigest()
        receipt = dict(schema=1,authorization_sha256=artifact_sha,
            preparation_implementation_sha256=implementation(),account_binding_sha256=fresh['account_binding_sha256'],
            preflight_sha256=fingerprint(fresh),reviewed_at=artifact['reviewed_at'],expires_at=artifact['expires_at'],
            confirmation_method='HIDDEN_TTY_SELLER_REENTRY_AND_PREPARE_ONLY_PHRASE',human_account_confirmed=True)
        publish(private,artifact_path,receipt_path,artifact,receipt)
    return dict(status='PREPARED_OFFLINE_ONLY',authorization_sha256=artifact_sha,
        receipt_sha256=hashlib.sha256((canonical(receipt)+'\n').encode()).hexdigest(),
        expires_at=artifact['expires_at'],live_requests=0,reservations_created=0,execution_performed=False)


def validate(manifest_path: Path, digest: str, sources: list[Path], store_path: Path,
             private: Path, preflight_path: Path, name: str, artifact_sha256: str,
             receipt_sha256: str) -> dict:
    artifact_path, receipt_path = paths(private,name)
    with existing_lock(private):
        artifact, actual = load_private(artifact_path)
        receipt, receipt_actual = load_private(receipt_path)
        if actual != artifact_sha256 or receipt_actual != receipt_sha256:
            raise ValueError('Exact artifact and receipt digests required')
        manifest, fresh, _ = snapshot(manifest_path,digest,sources,store_path,private,preflight_path)
        check_authorization(manifest,digest,artifact,fresh,store_path,private,utcnow())
        expected = dict(schema=1,authorization_sha256=actual,preparation_implementation_sha256=implementation(),
            account_binding_sha256=fresh['account_binding_sha256'],preflight_sha256=fingerprint(fresh),
            reviewed_at=artifact['reviewed_at'],expires_at=artifact['expires_at'],
            confirmation_method='HIDDEN_TTY_SELLER_REENTRY_AND_PREPARE_ONLY_PHRASE',human_account_confirmed=True)
        if fingerprint(receipt) != fingerprint(expected):
            raise ValueError('Preparation code or human review receipt drift')
    return dict(status='VALID_M67_POLICY_OFFLINE_ONLY',authorization_sha256=actual,
        receipt_sha256=receipt_actual,expires_at=artifact['expires_at'],live_requests=0,
        reservations_created=0,execution_performed=False)
