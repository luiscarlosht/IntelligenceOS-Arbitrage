"""Versioned normalized SQLite evidence, exact-content dedup and run lineage.

No raw provider responses or credentials. Live-provider storage is not authorized
by this repository; the fixture pilot uses a separate owner-only database.
"""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

from app.history import History
from app.models import Match, RetailProduct
from app.provider_contracts import Evidence


def normalized(value):
    """JSON with exact decimal strings, explicit nulls and aware UTC timestamps."""
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError('Aware evidence timestamps required')
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError('Finite evidence decimals required')
        text = format(value, 'f')
        return text.rstrip('0').rstrip('.') if '.' in text else text
    if is_dataclass(value):
        return {field.name: normalized(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalized(item) for item in value]
    return value


def canonical(value) -> str:
    return json.dumps(normalized(value), sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


def fingerprint(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class ObservationStore:
    """Append-only evidence; run items preserve duplicate input rows and decisions."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('Evidence database must be owner-only and regular')
        else:
            os.close(fd)
        self.history = History(self.path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS evidence_schema (version INTEGER PRIMARY KEY)')
            versions = db.execute('SELECT version FROM evidence_schema').fetchall()
            if versions and versions != [(1,)]:
                raise ValueError('Unsupported evidence schema version')
            db.execute('INSERT OR IGNORE INTO evidence_schema VALUES (1)')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS source_observations (
                    id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                    retailer TEXT NOT NULL, gtin TEXT NOT NULL,
                    observed_at TEXT, provenance TEXT NOT NULL,
                    authorization_reference TEXT NOT NULL, purchase_price TEXT,
                    payload_json TEXT NOT NULL, first_seen_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS marketplace_matches (
                    id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                    observation_id INTEGER NOT NULL REFERENCES source_observations(id),
                    provider TEXT NOT NULL, asin TEXT, exact INTEGER NOT NULL CHECK(exact IN (0,1)),
                    observed_at TEXT, provenance TEXT NOT NULL, payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS enrichment_observations (
                    id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                    asin TEXT NOT NULL, kind TEXT NOT NULL, observed_at TEXT,
                    provenance TEXT NOT NULL, is_mock INTEGER NOT NULL CHECK(is_mock IN (0,1)),
                    payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pilot_run_items (
                    run_id INTEGER NOT NULL REFERENCES runs(id), ordinal INTEGER NOT NULL,
                    observation_id INTEGER NOT NULL REFERENCES source_observations(id),
                    match_id INTEGER NOT NULL REFERENCES marketplace_matches(id),
                    result_json TEXT NOT NULL, PRIMARY KEY(run_id, ordinal));
                CREATE TABLE IF NOT EXISTS pilot_runs (
                    run_id INTEGER PRIMARY KEY REFERENCES runs(id), evaluation_at TEXT NOT NULL,
                    label TEXT NOT NULL, manifest_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pilot_run_enrichment (
                    run_id INTEGER NOT NULL, ordinal INTEGER NOT NULL,
                    enrichment_id INTEGER NOT NULL REFERENCES enrichment_observations(id),
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, ordinal, enrichment_id),
                    FOREIGN KEY(run_id, ordinal) REFERENCES pilot_run_items(run_id, ordinal));
                CREATE INDEX IF NOT EXISTS matches_source ON marketplace_matches(observation_id);
                CREATE INDEX IF NOT EXISTS enrichment_asin ON enrichment_observations(asin, kind, observed_at);
                CREATE INDEX IF NOT EXISTS items_source ON pilot_run_items(observation_id);
            ''')

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def start_run(self, evaluation_at: datetime, manifest: dict) -> int:
        stamp = normalized(evaluation_at)
        if not isinstance(evaluation_at, datetime):
            raise ValueError('Aware evaluation timestamp required')
        run_id = self.history.start()
        with self.connect() as db:
            db.execute('INSERT INTO pilot_runs VALUES (?,?,?,?)',
                       (run_id, stamp, 'FIXTURE PILOT — no live evidence', canonical(manifest)))
        return run_id

    def record_item(self, run_id: int, ordinal: int, product: RetailProduct, match: Match,
                    row: dict, enrichments: list[tuple[str, str, Evidence, datetime]],
                    recorded_at: datetime) -> int:
        """Atomically store a row and all normalized evidence; failed rows never half-link."""
        stamp = normalized(recorded_at)
        if not isinstance(recorded_at, datetime):
            raise ValueError('Aware ingest timestamp required')
        source_key = fingerprint(product)
        listing = match.listing
        match_value = dict(source=source_key, provider='offline-mock-catalog', match=match)
        match_key = fingerprint(match_value)
        with self.connect() as db:
            db.execute('''INSERT OR IGNORE INTO source_observations
                (fingerprint,retailer,gtin,observed_at,provenance,authorization_reference,
                 purchase_price,payload_json,first_seen_at) VALUES (?,?,?,?,?,?,?,?,?)''',
                (source_key, product.retailer, product.gtin, normalized(product.retrieved_at),
                 product.provenance, product.authorization_reference, normalized(product.purchase_price),
                 canonical(product), stamp))
            source_id = db.execute('SELECT id FROM source_observations WHERE fingerprint=?', (source_key,)).fetchone()[0]
            db.execute('''INSERT OR IGNORE INTO marketplace_matches
                (fingerprint,observation_id,provider,asin,exact,observed_at,provenance,payload_json)
                VALUES (?,?,?,?,?,?,?,?)''', (match_key, source_id, 'offline-mock-catalog',
                    listing.asin if listing else None, int(match.exact),
                    normalized(listing.retrieved_at) if listing else None,
                    listing.provenance if listing else '', canonical(match)))
            match_id = db.execute('SELECT id FROM marketplace_matches WHERE fingerprint=?', (match_key,)).fetchone()[0]
            db.execute('INSERT INTO pilot_run_items VALUES (?,?,?,?,?)',
                       (run_id, ordinal, source_id, match_id, canonical(row)))
            for asin, kind, evidence, fetched_at in enrichments:
                # None has no observation timestamp: requested_at is not observation time.
                payload = dict(value=evidence.value, observed_at=evidence.observed_at if evidence.value is not None else None,
                               provenance=evidence.provenance, is_mock=evidence.is_mock)
                key = fingerprint(dict(asin=asin, kind=kind, **payload))
                db.execute('''INSERT OR IGNORE INTO enrichment_observations
                    (fingerprint,asin,kind,observed_at,provenance,is_mock,payload_json)
                    VALUES (?,?,?,?,?,?,?)''', (key, asin, kind, normalized(payload['observed_at']),
                        evidence.provenance, int(evidence.is_mock), canonical(payload)))
                evidence_id = db.execute('SELECT id FROM enrichment_observations WHERE fingerprint=?', (key,)).fetchone()[0]
                db.execute('INSERT INTO pilot_run_enrichment VALUES (?,?,?,?)',
                           (run_id, ordinal, evidence_id, normalized(fetched_at)))
        return source_id
