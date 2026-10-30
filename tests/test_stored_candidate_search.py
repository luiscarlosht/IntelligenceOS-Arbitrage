"""Synthetic database, credentials and transport only; no real evidence or network."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

import pytest

from app import stored_candidate_search as stored
from app.observations import canonical, fingerprint, normalized
from app.sheets_intake import FIELDS, BATCH_FIELDS, IntakeStore, product

ASIN = 'B012345678'
CREDS = dict(client_id='synthetic-client', client_secret='synthetic-secret', refresh_token='synthetic-refresh')


def case(tmp_path, count=3):
    database = tmp_path/'intake.sqlite3'
    store = IntakeStore(database)
    rows = []
    for i in range(count):
        row = dict.fromkeys(FIELDS, '')
        row.update(schema_version='1', batch_id='b1', record_id='r'+str(i), source='walmart_browser',
            walmart_item_id=str(900000+i), product_url='https://www.walmart.com/ip/widget/'+str(900000+i),
            title='Example widget', item_price_usd='6.71', currency='USD', displayed_zip='76063',
            observed_at_utc='2026-01-01T00:00:00Z', exported_at_utc='2026-01-01T00:01:00Z')
        row['raw_record_json'] = json.dumps({k:v for k,v in row.items() if k != 'raw_record_json'})
        rows.append(row)
    batch = dict(zip(BATCH_FIELDS, ['b1',str(count),str(count),'COMPLETE','2026-01-01T00:02:00Z','','']))
    products = tuple(product(r) for r in rows)
    store.store(batch, rows, products)
    with store.connect() as db:
        db.execute("UPDATE sheets_batches SET acknowledged_at='2026-01-01T00:03:00Z'")
    private = tmp_path/'private'; private.mkdir(mode=0o700)
    inventory = tmp_path/'inventory.json'; inventory.write_text('{"reports":[]}')
    specs = []
    for ordinal, (row, p) in enumerate(zip(rows, products), 1):
        specs.append(dict(ordinal=ordinal, batch_id='b1', record_id=row['record_id'],
            walmart_item_id=row['walmart_item_id'], original_row_sha256=fingerprint(row),
            original_raw_sha256=hashlib.sha256(row['raw_record_json'].encode()).hexdigest(),
            source_fingerprint=fingerprint(p), source=normalized(p), observed_at_utc=row['observed_at_utc'],
            exported_at_utc=row['exported_at_utc'],
            search=dict(method='GET', path=stored.stage.CATALOG_PATH, params=dict(marketplaceIds=stored.MARKETPLACE,
                keywords='Example widget', keywordsLocale='en_US', locale='en_US', includedData='summaries', pageSize=10)),
            detail=dict(method='GET', path=stored.stage.CATALOG_PATH+'/{reviewed_asin}',
                params=dict(marketplaceIds=stored.MARKETPLACE, includedData=stored.DETAIL_DATA, locale='en_US'),
                conditional=True, maximum=1,
                selection='Review returned candidates; skip rejected or insufficient candidates; never infer exact identity from title',
                saved_evidence_policy='Before any detail, reuse compatible completed scoped ASIN evidence; block every prior attempted or uncertain ASIN, including B0000AQOAB')))
    plan = dict(schema=1, action='offline_missing_candidate_evidence_plan', execution_authorized=False,
        live_requests=0, database=str(database), database_signature=dict(sha256=stored.sha(database)),
        new_records=count, new_batches=1, requests=specs, marketplace_id=stored.MARKETPLACE,
        evidence_inventory=inventory.name, limits=dict(authentication=1, search=count, detail_at_most=count,
            total_at_most=1+2*count, pricing=0, fees=0, restrictions=0, retries=0, automatic_refresh=0, pagination=0))
    path = tmp_path/'plan.json'; path.write_text(canonical(plan))
    return database, private, path


def executable(tmp_path, count=3):
    database, private, plan = case(tmp_path, count)
    manifest, _ = stored.prepare(plan, private)
    path = tmp_path/'execution.json'; path.write_text(canonical(manifest)+'\n')
    return database, private, plan, path


def search(asin=ASIN):
    return dict(numberOfResults=1, items=[dict(asin=asin, summaries=[dict(marketplaceId=stored.MARKETPLACE,
        itemName='Example widget')])])


def catalog(asin=ASIN):
    return dict(asin=asin, summaries=[dict(marketplaceId=stored.MARKETPLACE, itemName='Example widget')],
        identifiers=[], relationships=[], attributes={})


def simulate(path, *, detail=False, fail=False):
    calls = []
    def transport(request):
        calls.append(request)
        if len(calls) == 1:
            return dict(access_token='synthetic-access', token_type='bearer')
        if fail:
            raise TimeoutError('synthetic-secret')
        if detail:
            asin = urlsplit(request.full_url).path.rsplit('/',1)[-1]
            return catalog(asin) if asin.startswith('B0') else search('B0'+str(len(calls)).zfill(8))
        return dict(numberOfResults=0, items=[])
    result = stored.run(path, stored.sha(path), transport=transport, credential_loader=lambda _:CREDS,
                        is_mock=True, sleep=lambda _:None)
    return result, calls


def test_38_source_bindings_77_attempt_ceiling_and_replay(tmp_path, monkeypatch):
    database, private, plan, path = executable(tmp_path, 38)
    before = (database.read_bytes(), database.stat().st_mtime_ns)
    manifest, products = stored.verify(path, stored.sha(path))
    assert len(products) == 38 and manifest['limits']['total'] == 77
    # Selection is injected to exercise every conditional detail and the hard ceiling.
    monkeypatch.setattr(stored.Reservations, 'select', staticmethod(lambda _,s:s['selected_asin']))
    result, calls = simulate(path, detail=True)
    assert len(calls) == 77 and result['status'] == 'succeeded'
    assert len(result['rows']) == 38 and not any(r['exact'] for r in result['rows'])
    assert (database.read_bytes(), database.stat().st_mtime_ns) == before
    assert all(secret not in canonical(result) for secret in (*CREDS.values(), 'synthetic-access'))
    for request in calls[1:]:
        assert request.get_method() == 'GET' and '/catalog/2022-04-01/items' in request.full_url
        assert 'pageToken' not in request.full_url
    with pytest.raises(ValueError):
        stored.run(path, stored.sha(path), credential_loader=lambda _:pytest.fail('Replay credentials'))
    # Renaming output and preparing again cannot bypass source-row claims.
    with pytest.raises(ValueError):
        stored.prepare(plan, private)


def test_empty_searches_make_no_details(tmp_path):
    _, _, _, path = executable(tmp_path)
    result, calls = simulate(path)
    assert result['status'] == 'succeeded' and len(calls) == 4


@pytest.mark.parametrize('change', ['query','row','raw','price','ordinal','limits','duplicate','database','evidence'])
def test_tampering_rejects_before_credentials(tmp_path, change):
    database, private, plan, path = executable(tmp_path)
    payload = json.loads(plan.read_text())
    if change == 'query': payload['requests'][0]['search']['params']['keywords'] = 'changed'
    elif change == 'row': payload['requests'][0]['source_fingerprint'] = '0'*64
    elif change == 'raw': payload['requests'][0]['original_raw_sha256'] = '0'*64
    elif change == 'price': payload['requests'][0]['source']['purchase_price'] = '0'
    elif change == 'ordinal': payload['requests'][0]['ordinal'] = 2
    elif change == 'limits': payload['limits']['total_at_most'] = 78
    elif change == 'duplicate': payload['requests'][1] = payload['requests'][0]
    elif change == 'database': payload['database_signature']['sha256'] = '0'*64
    elif change == 'evidence': (private/'candidates-new.json').write_text('{}')
    plan.write_text(canonical(payload))
    with pytest.raises(ValueError):
        stored.run(path, stored.sha(path), credential_loader=lambda _:pytest.fail('Credential access'))


def test_wrong_hash_mode_and_cap_reject(tmp_path):
    _, _, plan, path = executable(tmp_path)
    for digest, cap in [('0'*64,77),(stored.sha(path),78),(stored.sha(path),6)]:
        with pytest.raises(ValueError): stored.verify(path,digest,cap)
    with pytest.raises(ValueError): stored.verify(plan,stored.sha(plan))


def test_failure_consumes_reservations_without_retry(tmp_path):
    _, private, _, path = executable(tmp_path)
    result, calls = simulate(path, fail=True)
    assert len(calls) == 2 and result['status'] == 'failed_no_retry'
    assert result['attempts'][-1]['outcome'] == 'uncertain'
    with sqlite3.connect(private/'candidate-executions.sqlite3') as db:
        assert db.execute("SELECT count(*) FROM candidate_operations WHERE kind='search'").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM candidate_operations WHERE state='reserved'").fetchone()[0] == 1
    with pytest.raises(ValueError): stored.verify(path,stored.sha(path))


def test_same_run_asin_deduplicates_and_existing_reservation_blocks(tmp_path, monkeypatch):
    _, private, _, path = executable(tmp_path)
    monkeypatch.setattr(stored.Reservations, 'select', staticmethod(lambda _,s:s['selected_asin']))
    calls=[]
    def transport(request):
        calls.append(request)
        if len(calls)==1:return dict(access_token='synthetic-access',token_type='bearer')
        return catalog() if urlsplit(request.full_url).path.endswith('/'+ASIN) else search()
    result=stored.run(path,stored.sha(path),transport=transport,credential_loader=lambda _:CREDS,is_mock=True,sleep=lambda _:None)
    assert result['status']=='succeeded' and len(calls)==5
    assert result['rows'][1]['detail_origin']=='reused_same_run_us_catalog_asin'


def test_prior_uncertain_asin_blocks_detail_without_changing_old_reservation(tmp_path, monkeypatch):
    _, private, plan = case(tmp_path)
    # A historical source is unrelated, but its selected ASIN remains uncertain.
    source=dict(retailer='Walmart',url='https://www.walmart.com/ip/old/1',source_context=dict(retailer_item_id='1'))
    prior=dict(is_mock=False,manifest=dict(marketplace_id=stored.MARKETPLACE,requests=[]),rows=[dict(ordinal=1,source=source,search=dict(selected_asin=ASIN))],attempts=[dict(kind='detail',ordinal=1,status='failed_or_parser_rejected')])
    evidence=private/'candidates-prior.json';evidence.write_text(canonical(prior));before=evidence.read_bytes()
    (tmp_path/'inventory.json').write_text(canonical(dict(reports=[dict(path=str(evidence),sha256=stored.sha(evidence))])))
    manifest,_=stored.prepare(plan,private);path=tmp_path/'execution.json';path.write_text(canonical(manifest))
    monkeypatch.setattr(stored.Reservations,'select',staticmethod(lambda _,s:ASIN))
    calls=[]
    def transport(req):
        calls.append(req)
        return dict(access_token='synthetic-access',token_type='bearer') if len(calls)==1 else search()
    result=stored.run(path,stored.sha(path),transport=transport,credential_loader=lambda _:CREDS,is_mock=True,sleep=lambda _:None)
    assert len(calls)==2 and result['status']=='failed_no_retry' and evidence.read_bytes()==before


@pytest.mark.parametrize('stored_details', [False, True])
def test_scoped_completed_detail_reuses_original_timestamp(tmp_path, monkeypatch, stored_details):
    _, private, plan = case(tmp_path)
    source=dict(retailer='Walmart',url='https://www.walmart.com/ip/old/1',source_context=dict(retailer_item_id='1'))
    detail=normalized(stored.stage.detail_evidence(catalog(),ASIN,is_mock=False,secrets=()))
    prior=dict(is_mock=False,manifest=dict(marketplace_id=stored.MARKETPLACE,requests=[dict(ordinal=1,
        source_fingerprint=fingerprint(source),detail=dict(params=dict(marketplaceIds=stored.MARKETPLACE)))]),
        rows=[dict(ordinal=1,source=source,search=dict(selected_asin=ASIN),detail=detail)],
        attempts=[dict(kind='detail',ordinal=1,status='response_received')])
    if stored_details:
        prior['manifest']=dict(mode='stored_missing_catalog_details',requests=[dict(kind='catalog_detail',
            asin=ASIN,source_record_ids=['old'],params=dict(marketplaceIds=stored.MARKETPLACE))])
        prior['rows'][0].update(record_id='old',source_fingerprint=fingerprint(source))
        prior['attempts']=[dict(kind='detail',asin=ASIN,status='response_received')]
    evidence=private/'candidates-completed.json';evidence.write_text(canonical(prior));before=evidence.read_bytes()
    (tmp_path/'inventory.json').write_text(canonical(dict(reports=[dict(path=str(evidence),sha256=stored.sha(evidence))])))
    manifest,_=stored.prepare(plan,private);path=tmp_path/'execution.json';path.write_text(canonical(manifest))
    monkeypatch.setattr(stored.Reservations,'select',staticmethod(lambda _,s:ASIN))
    calls=[]
    def transport(req):
        calls.append(req)
        return dict(access_token='synthetic-access',token_type='bearer') if len(calls)==1 else search()
    result=stored.run(path,stored.sha(path),transport=transport,credential_loader=lambda _:CREDS,is_mock=False,sleep=lambda _:None)
    assert len(calls)==4 and result['status']=='succeeded'
    assert all(row['detail']['observed_at']==detail['observed_at'] for row in result['rows'])
    assert evidence.read_bytes()==before


def test_changed_manifest_with_existing_search_claim_refuses_before_credentials(tmp_path):
    _,private,plan,path=executable(tmp_path)
    manifest,_=stored.verify(path,stored.sha(path))
    # Simulate a concurrent run claiming one source row after preparation.
    directory=stored.pilot.private_directory(private)
    report=dict(status='reserved',attempts=[])
    guard=stored.Reservations(directory,manifest,report);guard.close()
    stored.os.close(directory)
    # Regenerate to include the new ledger hash; stable row keys still reject.
    altered,_=stored.prepare(plan,private);path.write_text(canonical(altered))
    with pytest.raises(ValueError,match='Prior source search reservation'):
        stored.run(path,stored.sha(path),credential_loader=lambda _:pytest.fail('Credentials'))


def test_real_selection_skips_insufficient_candidates(tmp_path):
    _,_,_,path=executable(tmp_path)
    calls=[]
    def transport(req):
        calls.append(req)
        return dict(access_token='synthetic-access',token_type='bearer') if len(calls)==1 else dict(numberOfResults=1,items=[dict(asin=ASIN,summaries=[dict(marketplaceId=stored.MARKETPLACE,itemName='Different product')])])
    result=stored.run(path,stored.sha(path),transport=transport,credential_loader=lambda _:CREDS,is_mock=True,sleep=lambda _:None)
    assert len(calls)==4 and result['status']=='succeeded'
    assert all(row['detail'] is None for row in result['rows'])
