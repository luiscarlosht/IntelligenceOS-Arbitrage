"""Private, append-only global accounting. Construction is execution-only."""
import json
import os
from pathlib import Path
import sqlite3
import stat
from urllib.parse import quote
from datetime import datetime, timezone

from app.m66_verification import VerificationStore
from app.observations import canonical, fingerprint


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def secure(path: Path, *, directory: bool = False) -> None:
    """Metadata only: no credential reads, creation, chmod or symlink traversal."""
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('Unsafe private path')
    info = path.stat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (not expected(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
            or (not directory and info.st_nlink != 1)):
        raise ValueError('Owner-only private storage required')


def readonly(path: Path) -> sqlite3.Connection:
    secure(path)
    with path.open('rb') as stream:
        header = stream.read(20)
    if header[:16] != b'SQLite format 3\x00' or header[18:20] != b'\x01\x01':
        raise ValueError('Rollback-journal database required; no WAL side effects')
    # A live WAL must be handled by an operator, never ignored as stale history.
    for suffix in ('-wal', '-journal'):
        sidecar = Path(str(path)+suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise ValueError('Quiescent durable database required')
    db = sqlite3.connect('file:'+quote(str(path.resolve()), safe='/')+'?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    return db


class ReadOnlyStore(VerificationStore):
    def __init__(self, path: Path):
        self.db = readonly(path)
        self.db.execute('BEGIN')


class Ledger:
    """Global claims survive derived-store restoration. There is no resume API."""
    def __init__(self, path: Path):
        secure(path.parent, directory=True)
        if path.exists():
            ledger_snapshot(path)  # Never silently repair an existing ledger.
        else:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.fsync(fd)
            os.close(fd)
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            os.fsync(fd)
            os.close(fd)
        secure(path)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS m67_batches(digest TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS m67_claims(asin TEXT PRIMARY KEY,digest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS m67_attempts(id TEXT PRIMARY KEY,digest TEXT NOT NULL,kind TEXT NOT NULL,asin TEXT,observed_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS m67_outcomes(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS m67_stops(digest TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS m67_reviews(digest TEXT PRIMARY KEY,payload TEXT NOT NULL);
        ''')
        for table in ('batches', 'claims', 'attempts', 'outcomes', 'stops', 'reviews'):
            for op in ('UPDATE', 'DELETE'):
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_m67_{table}_{op} BEFORE {op} ON m67_{table} BEGIN SELECT RAISE(ABORT,'immutable accounting'); END")
        self.db.commit()

    def reserve(self, digest: str, manifest: dict, review: dict | None = None) -> None:
        from app.m67_policy import scope
        import re
        scope(manifest)
        if review is not None and (set(review) != {'authorization_sha256','account_binding_sha256','preflight_sha256','implementation_sha256'}
                or any(not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v) for v in review.values())):
            raise ValueError('Only review evidence hashes may be stored')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute('INSERT INTO m67_batches VALUES (?,?)', (digest, canonical(manifest)))
            if review is not None:
                self.db.execute('INSERT INTO m67_reviews VALUES (?,?)', (digest, canonical(review)))
            for asin in manifest['asins']:
                self.db.execute('INSERT INTO m67_claims VALUES (?,?)', (asin, digest))

    def consume(self, digest: str, kind: str, asin: str | None = None) -> str:
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT payload FROM m67_batches WHERE digest=?', (digest,)).fetchone()
            if not row or self.db.execute('SELECT 1 FROM m67_stops WHERE digest=?', (digest,)).fetchone():
                raise ValueError('Unclaimed or stopped execution')
            m = json.loads(row[0]); key = digest+':'+(asin or 'authentication')
            if not ((kind == 'authentication' and asin is None) or
                    (kind == 'restrictions' and asin in m['asins'])):
                raise ValueError('Operation outside reviewed scope')
            previous = list(self.db.execute('SELECT id,kind,asin FROM m67_attempts WHERE digest=? ORDER BY rowid', (digest,)))
            # Require an immutable successful outcome for every preceding call.
            for request_id, previous_kind, _ in previous:
                outcome = self.db.execute('SELECT payload FROM m67_outcomes WHERE id=?', (request_id,)).fetchone()
                saved = json.loads(outcome[0]) if outcome else None
                if not saved or saved['operation_status'] != 'SUCCEEDED' or (previous_kind == 'restrictions' and saved['api_state'] == 'UNKNOWN'):
                    raise ValueError('Uncertain previous request; no continuation')
            restrictions = [v[2] for v in previous if v[1] == 'restrictions']
            if kind == 'restrictions' and (not previous or previous[0][1] != 'authentication'
                    or restrictions != m['asins'][:len(restrictions)]
                    or len(restrictions) >= len(m['asins']) or asin != m['asins'][len(restrictions)]):
                raise ValueError('Exact ordered requests required')
            if len(previous) >= m['budget']['maximum_requests'] or sum(v[1] == kind for v in previous) >= m['budget'][kind]:
                raise ValueError('Budget exhausted')
            self.db.execute('INSERT INTO m67_attempts VALUES (?,?,?,?,?)', (key, digest, kind, asin, stamp()))
        return key

    def finish(self, key: str, record: dict) -> None:
        allowed = {'operation_status', 'api_state', 'http_status', 'reason_codes', 'observed_at', 'source_sha256', 'failure'}
        from app.m65_intelligence import STATES, REASONS, observed
        import re
        if (set(record) != allowed or record['operation_status'] not in ('SUCCEEDED','FAILED','UNCERTAIN')
                or record['api_state'] not in STATES or record['http_status'] not in (None, 200, 400, 401, 403, 404, 408, 429, 500, 502, 503, 504)
                or not isinstance(record['reason_codes'], list) or set(record['reason_codes'])-REASONS
                or not observed(record['observed_at']) or not re.fullmatch('[a-f0-9]{64}', record['source_sha256'])
                or record['failure'] not in (None,'HTTP_FAILURE','TRANSPORT_UNCERTAIN','INVALID_RESPONSE','INTERRUPTED')
                or (record['operation_status'] != 'SUCCEEDED' and record['api_state'] != 'UNKNOWN')):
            raise ValueError('Allowlisted immutable outcome required')
        with self.db:
            attempt = self.db.execute('SELECT kind FROM m67_attempts WHERE id=?', (key,)).fetchone()
            if not attempt:
                raise ValueError('Consumed request required')
            if ((attempt[0] == 'authentication' and record['api_state'] != 'UNKNOWN')
                    or (attempt[0] == 'restrictions' and record['operation_status'] == 'SUCCEEDED' and record['api_state'] == 'UNKNOWN')):
                raise ValueError('Uncertainty cannot authorize continuation')
            self.db.execute('INSERT INTO m67_outcomes VALUES (?,?)', (key, canonical(record)))

    def stop(self, digest: str) -> None:
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO m67_stops VALUES (?)', (digest,))


def ledger_snapshot(path: Path) -> dict:
    if not path.exists():
        return dict(claims=[], batches=[], batch_scope_sha256={}, attempts=[], outcomes={})
    db = readonly(path)
    try:
        for table in ('batches','claims','attempts','outcomes','stops','reviews'):
            for op in ('UPDATE','DELETE'):
                trigger = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (f'immutable_m67_{table}_{op}',)).fetchone()
                if not trigger or 'RAISE(ABORT' not in trigger[0].upper():
                    raise ValueError('Immutable global protections missing')
        db.execute('BEGIN')
        return dict(claims=[r[0] for r in db.execute('SELECT asin FROM m67_claims ORDER BY asin')],
                    batches=[r[0] for r in db.execute('SELECT digest FROM m67_batches ORDER BY digest')],
                    batch_scope_sha256={r[0]:fingerprint(json.loads(r[1])) for r in db.execute('SELECT digest,payload FROM m67_batches')},
                    attempts=[dict(id=r[0],digest=r[1],kind=r[2],asin=r[3],observed_at=r[4]) for r in db.execute('SELECT * FROM m67_attempts ORDER BY rowid')],
                    outcomes={r[0]:json.loads(r[1]) for r in db.execute('SELECT * FROM m67_outcomes')})
    finally:
        db.close()
