"""Offline append-only raw Browser Use evidence with validated existing lineage."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from app.observations import ObservationStore, canonical, fingerprint

TARGET = 'amazon:ATVPDKIKX0DER:B000I0TZO4'
JOB = 'search:0920dcc561b655f5f94117745c58e286d97aa4ba0547ef34fcb60211c062a394'
VERIFY = 'verify:v2:B000I0TZO4:02:identity'
MAX_BYTES = 262144


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON keys are unsupported')
        result[key] = value
    return result


def _constant(_):
    raise ValueError('Nonfinite JSON numbers are unsupported')


def _parse(raw):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Bounded UTF-8 JSON text required')
    result = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    if not isinstance(result, dict):
        raise ValueError('JSON object required')
    return result


def _statuses(record):
    location = record['location_context'].get('status', 'NOT_VERIFIED_FOR_OFFER')
    delivery = record.get('result_delivery_status', 'NOT_RECORDED')
    if location not in ('NOT_VERIFIED_FOR_OFFER', 'LOCATION_FAILURE', 'UNKNOWN'):
        raise ValueError('Unsupported location status')
    if delivery not in ('COMPLETE', 'PARTIAL', 'FAILED', 'NOT_RECORDED'):
        raise ValueError('Unsupported delivery status')
    return dict(identity_status='PENDING_APPLICATION_REVIEW', location_status=location,
                result_delivery_status=delivery)


def _check(record):
    if (record.get('verification_id') != VERIFY or record.get('original_target_id') != TARGET
            or record.get('original_job_id') != JOB):
        raise ValueError('Original target/job/verification lineage mismatch')
    observed = datetime.fromisoformat(record['observed_at_utc'].replace('Z', '+00:00'))
    if observed.utcoffset() is None:
        raise ValueError('Aware observation timestamp required')
    prior = record.get('prior_failed_verification', {})
    if (prior.get('verification_id') != 'verify:v2:B000I0TZO4:01'
            or prior.get('status') != 'LOCATION_FAILURE'
            or not isinstance(prior.get('run_id'), str) or not prior['run_id'].strip()):
        raise ValueError('Prior location failure reference required')
    identity = record['identity']
    for key, expected in (('sets', 2), ('markers_per_set', 5), ('total_markers', 10),
                          ('two_five_marker_sets_claimed', True),
                          ('separate_individual_packaging_evidenced', None)):
        actual = identity['retail_package'].get(key)
        if type(actual) is not type(expected) or actual != expected:
            raise ValueError('Preserve the unverified two-by-five package claim')
    if (identity.get('upc_gtin') is not None or record.get('splitting_approved') is not False
            or record.get('identity_browser_assessment') != 'PENDING_APPLICATION_REVIEW'
            or record.get('exact_match_approved', False) is not False):
        raise ValueError('Cannot approve barcode identity, exact match or splitting')
    if any(record.get(key) is not None for key in ('per_pack_acquisition_cost_usd', 'acquisition_cost_per_pack_usd')):
        raise ValueError('No acquisition cost is established')
    if not isinstance(record.get('verbatim_on_page_evidence'), list):
        raise ValueError('Literal evidence required')
    if record['location_context'].get('used_for_offer_verification') is not False:
        raise ValueError('Identity-only evidence cannot verify a local offer')
    _statuses(record)
    return prior


def _store(database):
    path = Path(database)
    if not path.exists():
        raise ValueError('Existing ObservationStore database required; no parent records are created')
    return ObservationStore(path)


def _linkage(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'amazon_search_jobs', 'amazon_target_versions'} <= tables:
        raise ValueError('Existing target and search-job tables required')
    row = db.execute('SELECT target_id,revision,payload FROM amazon_search_jobs WHERE job_id=?', (JOB,)).fetchone()
    if row is None or row[0] != TARGET:
        raise ValueError('Existing job is missing or linked to another target')
    job = json.loads(row[2])
    identity = {k: job[k] for k in ('target_id', 'retailer', 'location', 'query_version')}
    if (job.get('job_id') != JOB or job.get('target_id') != TARGET or job.get('target_revision') != row[1]
            or 'search:' + fingerprint(identity) != JOB or job.get('retailer') != 'Walmart'
            or job.get('location') != '76063'):
        raise ValueError('Search-job payload and stored linkage disagree')
    version = db.execute('SELECT payload FROM amazon_target_versions WHERE target_id=? AND revision=?',
                         (TARGET, row[1])).fetchone()
    if version is None:
        raise ValueError('Existing pinned target revision required')
    target = json.loads(version[0])
    if (fingerprint(target) != row[1]
            or f'amazon:{target.get("marketplace")}:{target.get("asin")}' != TARGET):
        raise ValueError('Target payload and revision disagree')
    return row[1], target


def _schema(db):
    # Additive extension of the draft table. No parent creation, rebuild or raw rewrite.
    db.execute("""CREATE TABLE IF NOT EXISTS browser_verification_evidence (
      id INTEGER PRIMARY KEY, verification_id TEXT NOT NULL,
      original_target_id TEXT NOT NULL, original_job_id TEXT NOT NULL,
      kind TEXT NOT NULL CHECK(kind IN ('identity','location_failure')),
      observed_at_utc TEXT, content_sha256 TEXT NOT NULL UNIQUE, raw_json TEXT NOT NULL,
      imported_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))""")
    db.execute('CREATE INDEX IF NOT EXISTS browser_evidence_lineage ON browser_verification_evidence(original_target_id,original_job_id,kind)')
    db.execute("""CREATE TABLE IF NOT EXISTS browser_evidence_links (
        evidence_id INTEGER PRIMARY KEY REFERENCES browser_verification_evidence(id),
        target_revision TEXT NOT NULL,
        record_scope TEXT NOT NULL CHECK(record_scope IN ('identity_observation','reference_only')),
        raw_representation TEXT NOT NULL CHECK(raw_representation IN ('original_json_text','canonical_object','generated_reference')),
        validated_at_utc TEXT NOT NULL)""")
    for table in ('browser_verification_evidence', 'browser_evidence_links'):
        for action in ('UPDATE', 'DELETE'):
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action.lower()}
                BEFORE {action} ON {table} BEGIN
                SELECT RAISE(ABORT, 'Browser evidence is append-only'); END""")


def import_record(database, record, *, raw_json=None):
    """File imports retain exact UTF-8 JSON text; dict-only imports are canonical objects."""
    raw = canonical(record) if raw_json is None else raw_json
    parsed = _parse(raw)
    if canonical(parsed) != canonical(record):
        raise ValueError('Raw JSON and parsed record disagree')
    prior = _check(parsed)
    store = _store(database)
    reference = dict(verification_id=prior['verification_id'], status='LOCATION_FAILURE',
                     run_id=prior['run_id'], raw_observation_available=False)
    events = [('location_failure', prior['verification_id'], None, canonical(reference), 'reference_only', 'generated_reference'),
              ('identity', parsed['verification_id'], parsed['observed_at_utc'], raw, 'identity_observation',
               'canonical_object' if raw_json is None else 'original_json_text')]
    inserted, conflicts = 0, set()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        revision, _ = _linkage(db)
        _schema(db)
        for kind, verification_id, observed, payload, scope, representation in events:
            digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
            old = db.execute('SELECT raw_json FROM browser_verification_evidence WHERE verification_id=?', (verification_id,)).fetchall()
            meanings = {canonical(_parse(r[0])) for r in old} | {canonical(_parse(payload))}
            if len(meanings) > 1:
                conflicts.add(verification_id)
            cursor = db.execute('''INSERT OR IGNORE INTO browser_verification_evidence
                (verification_id,original_target_id,original_job_id,kind,observed_at_utc,content_sha256,raw_json)
                VALUES (?,?,?,?,?,?,?)''', (verification_id, TARGET, JOB, kind, observed, digest, payload))
            inserted += cursor.rowcount
            stored = db.execute('SELECT id,verification_id,original_target_id,original_job_id,kind,raw_json FROM browser_verification_evidence WHERE content_sha256=?', (digest,)).fetchone()
            if stored[1:] != (verification_id, TARGET, JOB, kind, payload):
                raise ValueError('Stored raw evidence/hash linkage mismatch')
            link = db.execute('SELECT target_revision,record_scope FROM browser_evidence_links WHERE evidence_id=?', (stored[0],)).fetchone()
            if link is not None and link != (revision, scope):
                raise ValueError('Existing evidence links another target revision')
            db.execute('INSERT OR IGNORE INTO browser_evidence_links VALUES (?,?,?,?,?)',
                       (stored[0], revision, scope, representation, datetime.now(timezone.utc).isoformat()))
    return dict(inserted=inserted, duplicate=inserted == 0, conflicting_verification_ids=sorted(conflicts),
        **_statuses(parsed), exact_match_approved=False, splitting_approved=False,
        per_pack_acquisition_cost_usd=None, prior_location_failure_scope='reference_only',
        full_location_failure_record_preserved=False, target_revision=revision,
        lineage_status='VALIDATED_EXISTING_RECORDS', identity_raw_representation=events[1][-1])


def import_file(database, path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('Bounded nonsymlink JSON file required')
    raw = path.read_bytes().decode('utf-8')
    return import_record(database, _parse(raw), raw_json=raw)


def comparison(database):
    store = _store(database)
    with store.connect() as db:
        db.execute('BEGIN')
        revision, target = _linkage(db)
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        stored = db.execute('SELECT id,kind,raw_json,content_sha256 FROM browser_verification_evidence WHERE original_target_id=? AND original_job_id=? ORDER BY id', (TARGET, JOB)).fetchall() if 'browser_verification_evidence' in tables else []
        links = dict(db.execute('SELECT evidence_id,target_revision FROM browser_evidence_links')) if 'browser_evidence_links' in tables else {}
        if any(links[r[0]] != revision for r in stored if r[0] in links):
            raise ValueError('Evidence is pinned to another target revision')
        unvalidated = sum(r[0] not in links for r in stored)
        rows = [r[1:] for r in stored]
    identities = [_parse(raw) for kind, raw, _ in rows if kind == 'identity']
    statuses = [dict(content_sha256=digest, **_statuses(_parse(raw))) for kind, raw, digest in rows if kind == 'identity']
    def consensus(key):
        values = {s[key] for s in statuses}
        return next(iter(values)) if len(values) == 1 else ('CONFLICTING_OBSERVATIONS' if values else 'NOT_RECORDED')
    package = target.get('exact_package_evidence', {})
    return dict(amazon_sale_unit_evidence={k: package.get(k) for k in ('size', 'package_quantity', 'unit_count')},
        walmart_claimed_package={'packs': 2, 'markers_per_pack': 5, 'total': 10, 'individually_packaged': None} if identities else None,
        observed_models=sorted({r['identity']['model'] for r in identities if r['identity'].get('model')}),
        source_barcode=None, exact_match_approved=False, splitting_approved=False,
        mansfield_offer_verified=False, acquisition_cost_per_pack_usd=None,
        identity_status=consensus('identity_status'), location_status=consensus('location_status'),
        result_delivery_status=consensus('result_delivery_status'), status_observations=statuses,
        location_failure_references=sum(kind == 'location_failure' for kind, _, _ in rows),
        prior_location_failure_scope='reference_only', full_location_failure_record_preserved=False,
        identity_evidence_events=len(identities), target_revision=revision, unvalidated_evidence_records=unvalidated,
        gaps=['Independent packaging evidence', 'UPC/GTIN corroboration', 'Application identity review',
              'ZIP 76063 offer', 'Verified acquisition cost', 'Splitting approval', 'Complete prior failure raw record'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    print(canonical({'import': import_file(args.database, args.input), 'comparison': comparison(args.database)}))


if __name__ == '__main__':
    main()
