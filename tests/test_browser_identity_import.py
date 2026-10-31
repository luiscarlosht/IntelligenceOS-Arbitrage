"""Integration coverage against real ObservationStore/TargetStore and temporary SQLite."""
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

from app.amazon_targets import AmazonTarget, TargetStore, browser_jobs
from app.browser_identity_import import (JOB, TARGET, VERIFY, _schema,
    comparison, import_file, import_record)
from app.models import Match, RetailProduct
from app.observations import ObservationStore, canonical

FIXTURE = Path(__file__).resolve().parents[1] / 'sample_data/browser_identity_B000I0TZO4.json'
NOW = datetime(2026, 10, 31, 13, 20, tzinfo=timezone.utc)
CORE_TABLES = ('runs', 'source_observations', 'marketplace_matches', 'enrichment_observations',
               'pilot_runs', 'pilot_run_items', 'pilot_run_enrichment', 'evidence_schema',
               'amazon_target_versions', 'amazon_search_jobs', 'amazon_search_events', 'amazon_search_evaluations')


@pytest.fixture
def evidence():
    return json.loads(FIXTURE.read_bytes())


def core_rows(store):
    with store.connect() as db:
        return {name: db.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall() for name in CORE_TABLES}


@pytest.fixture
def existing(tmp_path):
    path = tmp_path / 'observations.sqlite3'
    store = TargetStore(path)
    assert isinstance(store, ObservationStore)
    # Parents are explicitly created with the real public API, never by the importer.
    target = AmazonTarget('B000I0TZO4', NOW, NOW, NOW, 'Synthetic integration target',
        brand='Sharpie', manufacturer='Synthetic manufacturer', model='30665PP',
        exact_package_evidence={'size': {'value': '5 Count (Pack of 1)'},
                                'package_quantity': {'value': 1}, 'unit_count': {'value': '5.0'}})
    job = browser_jobs([target], query_version='sp-api-v1')[0]
    assert target.target_id == TARGET and job['job_id'] == JOB
    store.save_target(target)
    store.save_job(job)
    run = store.start_run(NOW, {'fixture': 'unrelated existing observation'})
    product = RetailProduct('Walmart', 'Unrelated stored source', 'https://www.walmart.com/ip/fixture/123',
        '', '', '', None, None, 'unknown', NOW, 'Synthetic source evidence')
    store.record_item(run, 1, product, Match(None, False, 0, ('Unverified',)),
                      {'status': 'REJECT'}, [], NOW)
    # Leave that existing run unresolved: import must not mark it complete.
    return path, store, core_rows(store)


def rows(store):
    with store.connect() as db:
        return db.execute('SELECT kind,raw_json,content_sha256,observed_at_utc,imported_at_utc FROM browser_verification_evidence ORDER BY id').fetchall()


def test_exact_raw_file_preservation_and_reference_only_failure(existing):
    path, store, before = existing
    result = import_file(path, FIXTURE)
    assert result['inserted'] == 2
    identity = next(r for r in rows(store) if r[0] == 'identity')
    assert identity[1].encode('utf-8') == FIXTURE.read_bytes()
    assert identity[2] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert identity[3] == json.loads(FIXTURE.read_bytes())['observed_at_utc']
    failure = next(r for r in rows(store) if r[0] == 'location_failure')
    reference = json.loads(failure[1])
    assert reference == dict(verification_id='verify:v2:B000I0TZO4:01', status='LOCATION_FAILURE',
        run_id='11f73237-0b70-4b27-94c8-fe1062a71256', raw_observation_available=False)
    assert failure[3] is None  # no invented failure timestamp
    assert result['prior_location_failure_scope'] == 'reference_only'
    assert result['full_location_failure_record_preserved'] is False
    assert result['result_delivery_status'] == 'NOT_RECORDED'
    assert core_rows(store) == before
    with store.connect() as db:
        assert db.execute('PRAGMA foreign_keys').fetchone() == (1,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert set(db.execute('SELECT record_scope,raw_representation FROM browser_evidence_links')) == {
            ('identity_observation', 'original_json_text'), ('reference_only', 'generated_reference')}


def test_duplicate_import_keeps_rows_timestamps_and_parent_records(existing):
    path, store, before = existing
    import_file(path, FIXTURE)
    saved = rows(store)
    repeated = import_file(path, FIXTURE)
    assert repeated['inserted'] == 0 and repeated['duplicate']
    assert rows(store) == saved
    assert repeated['lineage_status'] == 'VALIDATED_EXISTING_RECORDS'
    assert core_rows(store) == before
    assert path.stat().st_mode & 0o777 == 0o600


def test_conflicts_are_distinct_immutable_observations(existing, evidence):
    path, store, before = existing
    import_file(path, FIXTURE)
    original = rows(store)
    changed = copy.deepcopy(evidence)
    changed['identity']['model'] = 'CONFLICTING_VISIBLE_MODEL'
    result = import_record(path, changed)
    assert result['inserted'] == 1 and result['conflicting_verification_ids'] == [VERIFY]
    assert rows(store)[:2] == original
    assert {json.loads(r[1])['identity']['model'] for r in rows(store) if r[0] == 'identity'} == {
        '30665PP', 'CONFLICTING_VISIBLE_MODEL'}
    assert comparison(path)['observed_models'] == ['30665PP', 'CONFLICTING_VISIBLE_MODEL']
    repeated = import_file(path, FIXTURE)
    assert repeated['inserted'] == 0 and repeated['conflicting_verification_ids'] == [VERIFY]
    assert core_rows(store) == before


def test_formatting_variants_retained_without_inventing_semantic_conflict(existing, evidence):
    path, store, _ = existing
    raw = '\n' + json.dumps(evidence, ensure_ascii=False, indent=3) + '\n\n'
    import_record(path, evidence, raw_json=raw)
    result = import_record(path, evidence)
    assert result['inserted'] == 1 and result['conflicting_verification_ids'] == []
    assert {r[1] for r in rows(store) if r[0] == 'identity'} == {raw, canonical(evidence)}


@pytest.mark.parametrize('table', ['browser_verification_evidence', 'browser_evidence_links'])
@pytest.mark.parametrize('action', ['UPDATE', 'DELETE'])
def test_database_guards_append_only_records(existing, table, action):
    path, store, _ = existing
    import_file(path, FIXTURE)
    with pytest.raises(sqlite3.IntegrityError, match='append-only'), store.connect() as db:
        db.execute(f'UPDATE {table} SET rowid=rowid' if action == 'UPDATE' else f'DELETE FROM {table}')
    assert len(rows(store)) == 2


@pytest.mark.parametrize('fault', ['missing_job', 'missing_revision', 'wrong_target_column',
                                  'wrong_job_payload', 'wrong_target_payload'])
def test_actual_existing_linkage_is_checked_before_any_evidence_insert(existing, evidence, fault):
    path, store, _ = existing
    with store.connect() as db:
        if fault == 'missing_job':
            db.execute('DELETE FROM amazon_search_jobs')
        elif fault == 'missing_revision':
            db.execute('DELETE FROM amazon_target_versions')
        elif fault == 'wrong_target_column':
            db.execute("UPDATE amazon_search_jobs SET target_id='different target'")
        elif fault == 'wrong_job_payload':
            job = json.loads(db.execute('SELECT payload FROM amazon_search_jobs').fetchone()[0])
            job['query_version'] = 'changed behind the API'
            db.execute('UPDATE amazon_search_jobs SET payload=?', (canonical(job),))
        else:
            target = json.loads(db.execute('SELECT payload FROM amazon_target_versions').fetchone()[0])
            target['model'] = 'tampered'
            db.execute('UPDATE amazon_target_versions SET payload=?', (canonical(target),))
    before = core_rows(store)
    with pytest.raises(ValueError):
        import_record(path, evidence)
    with store.connect() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='browser_verification_evidence'").fetchall()
    assert core_rows(store) == before


def test_no_database_or_missing_parent_tables_are_not_invented(tmp_path, evidence):
    path = tmp_path / 'missing.sqlite3'
    with pytest.raises(ValueError, match='Existing ObservationStore'):
        import_record(path, evidence)
    assert not path.exists()
    store = ObservationStore(path)
    with pytest.raises(ValueError, match='Existing target'):
        import_record(path, evidence)
    with store.connect() as db:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert 'amazon_target_versions' not in names and 'amazon_search_jobs' not in names
        assert 'browser_verification_evidence' not in names


@pytest.mark.parametrize('delivery', ['COMPLETE', 'PARTIAL', 'FAILED'])
@pytest.mark.parametrize('location', ['NOT_VERIFIED_FOR_OFFER', 'LOCATION_FAILURE'])
def test_identity_location_and_delivery_are_independent(existing, evidence, delivery, location):
    path, _, _ = existing
    evidence['result_delivery_status'] = delivery
    evidence['location_context']['status'] = location
    evidence['historical_displayed_price_usd'] = '13.99'  # cannot divide by two to infer a buy cost
    result = import_record(path, evidence)
    summary = comparison(path)
    for output in (result, summary):
        assert output['identity_status'] == 'PENDING_APPLICATION_REVIEW'
        assert output['location_status'] == location
        assert output['result_delivery_status'] == delivery
        assert output['exact_match_approved'] is False and output['splitting_approved'] is False
    assert result['per_pack_acquisition_cost_usd'] is None
    assert summary['acquisition_cost_per_pack_usd'] is None
    assert summary['mansfield_offer_verified'] is False and summary['source_barcode'] is None
    assert summary['amazon_sale_unit_evidence']['size']['value'] == '5 Count (Pack of 1)'
    assert summary['walmart_claimed_package'] == dict(packs=2, markers_per_pack=5, total=10, individually_packaged=None)


def test_status_conflicts_are_not_silently_overwritten(existing, evidence):
    path, _, _ = existing
    import_file(path, FIXTURE)
    evidence['result_delivery_status'] = 'FAILED'
    evidence['location_context']['status'] = 'LOCATION_FAILURE'
    import_record(path, evidence)
    result = comparison(path)
    assert result['identity_status'] == 'PENDING_APPLICATION_REVIEW'
    assert result['location_status'] == result['result_delivery_status'] == 'CONFLICTING_OBSERVATIONS'
    assert len(result['status_observations']) == 2
    assert result['location_failure_references'] == 1
    assert not result['full_location_failure_record_preserved']


@pytest.mark.parametrize('field', ['barcode', 'splitting', 'packaging', 'exact', 'cost', 'offer'])
def test_unsupported_claims_fail_without_storage_side_effects(existing, evidence, field):
    path, store, before = existing
    if field == 'barcode':
        evidence['identity']['upc_gtin'] = '012899877137'
    elif field == 'splitting':
        evidence['splitting_approved'] = True
    elif field == 'packaging':
        evidence['identity']['retail_package']['separate_individual_packaging_evidenced'] = True
    elif field == 'exact':
        evidence['exact_match_approved'] = True
    elif field == 'cost':
        evidence['per_pack_acquisition_cost_usd'] = '6.995'
    else:
        evidence['location_context']['used_for_offer_verification'] = True
    with pytest.raises(ValueError):
        import_record(path, evidence)
    assert core_rows(store) == before


def test_raw_mismatch_and_ambiguous_json_rejected(existing, evidence):
    path, store, before = existing
    with pytest.raises(ValueError, match='disagree'):
        import_record(path, evidence, raw_json='{}')
    with pytest.raises(ValueError, match='Duplicate JSON'):
        import_record(path, evidence, raw_json='{"x":1,"x":2}')
    with pytest.raises(ValueError, match='Nonfinite JSON'):
        import_record(path, evidence, raw_json='{"x":NaN}')
    assert core_rows(store) == before


def test_legacy_draft_schema_is_extended_without_rewriting_raw(existing, evidence):
    path, store, before = existing
    # Original PR #45 schema, alongside the actual repository store and parents.
    with store.connect() as db:
        db.execute('''CREATE TABLE browser_verification_evidence (
            id INTEGER PRIMARY KEY,verification_id TEXT NOT NULL,original_target_id TEXT NOT NULL,
            original_job_id TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('identity','location_failure')),
            observed_at_utc TEXT,content_sha256 TEXT NOT NULL UNIQUE,raw_json TEXT NOT NULL,
            imported_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))''')
        payload = canonical(evidence)
        db.execute('''INSERT INTO browser_verification_evidence
            (verification_id,original_target_id,original_job_id,kind,observed_at_utc,content_sha256,raw_json)
            VALUES (?,?,?,?,?,?,?)''', (VERIFY, TARGET, JOB, 'identity', evidence['observed_at_utc'],
                                      hashlib.sha256(payload.encode()).hexdigest(), payload))
    original = rows(store)
    assert comparison(path)['unvalidated_evidence_records'] == 1
    result = import_record(path, evidence)
    assert result['inserted'] == 1  # only the missing reference is added
    assert rows(store)[0] == original[0]
    assert comparison(path)['unvalidated_evidence_records'] == 0
    assert core_rows(store) == before
    with store.connect() as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert len(db.execute('PRAGMA table_info(browser_verification_evidence)').fetchall()) == 9


def test_atomic_rollback_and_compatible_child_foreign_key(existing, evidence):
    path, store, before = existing
    with store.connect() as db:
        _schema(db)
        db.execute("""CREATE TRIGGER reject_identity BEFORE INSERT ON browser_verification_evidence
            WHEN NEW.kind='identity' BEGIN SELECT RAISE(ABORT, 'test rollback'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='test rollback'):
        import_record(path, evidence)
    assert rows(store) == []  # the earlier reference insert rolls back, too
    with pytest.raises(sqlite3.IntegrityError, match='FOREIGN KEY'), store.connect() as db:
        db.execute('INSERT INTO browser_evidence_links VALUES (?,?,?,?,?)',
                   (999, 'absent', 'reference_only', 'generated_reference', NOW.isoformat()))
    assert core_rows(store) == before


def test_owner_only_store_security_is_not_bypassed(existing, evidence):
    path, _, _ = existing
    path.chmod(0o644)
    with pytest.raises(ValueError, match='owner-only'):
        import_record(path, evidence)


def aliased_record(evidence):
    record = copy.deepcopy(evidence)
    record['identity']['browser_assessment'] = record.pop('identity_browser_assessment')
    record['identity']['splitting_approved'] = record.pop('splitting_approved')
    record['delivery_status'] = 'COMPLETE'
    return record


ALIASES = [('identity_browser_assessment', 'browser_assessment', 'PENDING_APPLICATION_REVIEW'),
           ('splitting_approved', 'splitting_approved', False),
           ('result_delivery_status', None, 'COMPLETE')]


def test_alias_file_raw_preservation_and_duplicate_import(existing, evidence, tmp_path):
    path, store, before = existing
    # Local compatibility runs explicitly select the actual saved observation.
    # CI uses a synthetic schema variant; runtime evidence is never committed.
    selected = os.environ.get('BROWSER_IDENTITY_ALIAS_INPUT')
    if selected:
        source = Path(selected)
    else:
        source = tmp_path / 'alias-observation.json'
        source.write_bytes(json.dumps(aliased_record(evidence), indent=2).encode())
    original = source.read_bytes()
    result = import_file(path, source)
    saved = rows(store)
    identity = next(r for r in saved if r[0] == 'identity')
    assert identity[1].encode() == original
    assert identity[2] == hashlib.sha256(original).hexdigest()
    parsed = json.loads(identity[1])
    assert parsed['identity']['browser_assessment'] == 'PENDING_APPLICATION_REVIEW'
    assert parsed['identity']['splitting_approved'] is False
    assert 'identity_browser_assessment' not in parsed and 'splitting_approved' not in parsed
    assert result['identity_status'] == 'PENDING_APPLICATION_REVIEW'
    assert result['location_status'] == 'NOT_VERIFIED_FOR_OFFER'
    assert result['result_delivery_status'] == 'COMPLETE'
    assert result['exact_match_approved'] is result['splitting_approved'] is False
    assert result['per_pack_acquisition_cost_usd'] is None
    assert result['prior_location_failure_scope'] == 'reference_only'
    assert result['inserted'] == 2
    again = import_file(path, source)
    assert again['duplicate'] and again['inserted'] == 0
    assert rows(store) == saved and source.read_bytes() == original
    summary = comparison(path)
    assert summary['result_delivery_status'] == 'COMPLETE'
    assert summary['identity_evidence_events'] == 1
    assert summary['location_failure_references'] == 1
    assert not summary['full_location_failure_record_preserved']
    assert summary['acquisition_cost_per_pack_usd'] is None
    assert core_rows(store) == before
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM browser_evidence_links').fetchone() == (2,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('primary,nested,value', ALIASES)
def test_agreeing_aliases_are_accepted_without_removing_either(existing, evidence, primary, nested, value):
    path, store, _ = existing
    record = aliased_record(evidence)
    record[primary] = value
    raw = json.dumps(record, indent=3)
    import_record(path, record, raw_json=raw)
    assert next(r[1] for r in rows(store) if r[0] == 'identity') == raw
    assert comparison(path)['result_delivery_status'] == 'COMPLETE'


@pytest.mark.parametrize('primary,value', [
    ('identity_browser_assessment', 'EXACT_MATCH_APPROVED'),
    ('splitting_approved', True), ('splitting_approved', 0),
    ('result_delivery_status', 'FAILED'), ('result_delivery_status', None)])
def test_conflicting_aliases_rejected_before_storage(existing, evidence, primary, value):
    path, store, before = existing
    record = aliased_record(evidence)
    record[primary] = value
    with pytest.raises(ValueError, match='Conflicting aliases: ' + primary):
        import_record(path, record)
    assert core_rows(store) == before
    with store.connect() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='browser_verification_evidence'").fetchall()


@pytest.mark.parametrize('primary,nested', [('identity_browser_assessment', 'browser_assessment'),
                                         ('splitting_approved', 'splitting_approved')])
def test_missing_both_required_representations_does_not_imply_approval(existing, evidence, primary, nested):
    path, store, before = existing
    record = aliased_record(evidence)
    del record['identity'][nested]
    assert primary not in record
    with pytest.raises(ValueError):
        import_record(path, record)
    assert core_rows(store) == before


def test_missing_both_delivery_fields_stays_not_recorded(existing, evidence):
    path, _, _ = existing
    record = aliased_record(evidence)
    del record['delivery_status']
    result = import_record(path, record)
    assert result['result_delivery_status'] == comparison(path)['result_delivery_status'] == 'NOT_RECORDED'


@pytest.mark.parametrize('primary,nested,value', ALIASES)
def test_explicit_null_is_not_a_successful_default(existing, evidence, primary, nested, value):
    path, store, before = existing
    record = aliased_record(evidence)
    record[primary] = None
    if nested:
        record['identity'][nested] = None
    else:
        record['delivery_status'] = None
    with pytest.raises(ValueError):
        import_record(path, record)
    assert core_rows(store) == before
