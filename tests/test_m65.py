"""Synthetic evidence only. No Amazon, retailer, credential or browser access."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

import pytest

from app import m65
from app import m65_batch as batch
from app import m65_intelligence as intel
from app import m65_ranking as ranking
from app.m65_readiness import readiness
from app.observations import canonical, fingerprint

DATE='2026-01-01T12:00:00+00:00'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args,**kwargs):pytest.fail('Network forbidden in M65 tests')
    monkeypatch.setattr(socket,'create_connection',forbidden)
    monkeypatch.setattr(socket,'getaddrinfo',forbidden)
    from app import amazon_pilot
    monkeypatch.setattr(amazon_pilot,'load_credentials',forbidden)
    monkeypatch.setattr(amazon_pilot,'_request_json',forbidden)


def normalized(state='APPROVAL_REQUIRED',asin='B000000001'):
    codes=[] if state=='NO_REPORTED_RESTRICTIONS' else [state]
    return dict(asin=asin,marketplace_id=intel.US,condition='new_new',seller_reference='PRIVATESELLER',
        restrictions=dict(status='succeeded',data=dict(restriction_count=0 if not codes else 1,
            listing_permission=dict(value=not codes,observed_at=DATE),reason_codes=codes,
            reasons=[] if not codes else [dict(reasonCode=state,message='PRIVATESELLER',links=[dict(resource='https://example.com/PRIVATESELLER')])],
            approval_required=state=='APPROVAL_REQUIRED')))


def report(tmp_path,rows=None):
    path=tmp_path/'report.json'
    value=dict(is_mock=False,status='partial',finished_at=DATE,rows=rows or [normalized()],
        seller_id='PRIVATESELLER',client_secret='PRIVATEKEY',access_token='PRIVATETOKEN',
        source_bound_manifest=dict(marketplace_id=intel.US,condition='new_new',requests=[]))
    path.write_text(json.dumps(value))
    return path


@pytest.fixture
def store(tmp_path):
    value=intel.IntelligenceStore(tmp_path/'private/intelligence.sqlite3')
    yield value
    value.close()


@pytest.mark.parametrize('state',intel.STATES[:-1])
def test_normalized_m63_classifications_and_private_allowlist(tmp_path,state):
    path=report(tmp_path,[normalized(state)])
    events=intel.import_report(path)
    e=events[0]
    assert e['eligibility']==state and e['operation_status']=='SUCCEEDED'
    assert e['observed_at']==DATE and e['marketplace']==intel.US and e['condition']=='new_new'
    assert e['fba_eligibility'] is None and e['purchase_authorized'] is False
    assert not any(secret in canonical(events) for secret in ('PRIVATESELLER','PRIVATEKEY','PRIVATETOKEN'))
    assert e['source_reference'].startswith('sha256:')


@pytest.mark.parametrize('changes',[
    dict(restrictions=None),dict(restrictions=dict(status='succeeded')),
    dict(restrictions=dict(status='failed',data=dict(restriction_count=0,listing_permission=dict(value=True),reason_codes=[]))),
    dict(restrictions=dict(status='succeeded',http_status=429,response=dict(restrictions=[]))),
    dict(marketplace_id='WRONG'),dict(condition='used'),
    dict(restrictions=dict(status='succeeded',data=dict(restriction_count=0,listing_permission=dict(value=False),reason_codes=[]))),
    dict(restrictions=dict(status='succeeded',data=dict(restriction_count=True,listing_permission=dict(value=True),reason_codes=[]))),
    dict(restrictions=dict(status='succeeded',data=dict(restriction_count=0,listing_permission=[],reason_codes=[]))),
])
def test_missing_malformed_and_wrong_scope_are_unknown(tmp_path,changes):
    row=normalized()
    row.update(changes)
    e=intel.import_report(report(tmp_path,[row]))[0]
    assert e['eligibility']=='UNKNOWN'


@pytest.mark.parametrize('codes,state',[([], 'NO_REPORTED_RESTRICTIONS'),(['APPROVAL_REQUIRED'],'APPROVAL_REQUIRED'),
    (['NOT_ELIGIBLE'],'NOT_ELIGIBLE'),(['UNRECOGNIZED_SECRET'],'OTHER_RESTRICTED')])
def test_raw_response_parse_is_allowlisted(tmp_path,codes,state):
    row=normalized()
    rows=[] if not codes else [dict(marketplaceId=intel.US,conditionType='new_new',
                                    reasons=[dict(reasonCode=c,message='PRIVATESELLER') for c in codes])]
    row['restrictions']=dict(status='succeeded',response=dict(restrictions=rows))
    e=intel.import_report(report(tmp_path,[row]))[0]
    assert e['eligibility']==state and 'UNRECOGNIZED_SECRET' not in canonical(e)


def test_missing_timestamp_does_not_imply_current_permission(tmp_path):
    row=normalized('NO_REPORTED_RESTRICTIONS')
    row['restrictions']['data']['listing_permission'].pop('observed_at')
    p=report(tmp_path,[row]);d=json.loads(p.read_text());d.pop('finished_at');p.write_text(json.dumps(d))
    assert intel.import_report(p)[0]['eligibility']=='UNKNOWN'


def test_import_never_uses_overall_partial_as_failed_eligibility(tmp_path,store):
    rows=[normalized('APPROVAL_REQUIRED',f'B{i:09d}') for i in range(18)]+[normalized('NOT_ELIGIBLE',f'B{i:09d}') for i in range(18,20)]
    events=intel.import_report(report(tmp_path,rows))
    assert Counter(e['eligibility'] for e in events)==dict(APPROVAL_REQUIRED=18,NOT_ELIGIBLE=2)
    assert all(e['operation_status']=='SUCCEEDED' for e in events)
    assert store.append(events)==dict(added=20,duplicates=0)
    assert store.append(events)==dict(added=0,duplicates=20)
    assert len(store.excluded())==20


def test_malformed_document_and_mock_intake_rejected(tmp_path):
    path=tmp_path/'report.json';path.write_text('[]')
    with pytest.raises(ValueError):intel.import_report(path)
    path.write_text(json.dumps(dict(is_mock=True,rows=[normalized()])))
    with pytest.raises(ValueError):intel.import_report(path)
    path=tmp_path/'credentials.json';path.write_text('PRIVATE')
    with pytest.raises(ValueError):intel.read_json(path)


def test_four_manual_seeds_and_duplicate_handling(store):
    assert m65.manual_import(m65.SEEDS,store)==dict(added=4,duplicates=0)
    assert m65.manual_import(m65.SEEDS,store)==dict(added=0,duplicates=4)
    rows={m['brand']:m for m in store.events('manual_approval')}
    assert set(rows)=={'OXO','Avery','Command','Whitmor'}
    for brand,row in rows.items():
        assert row['minimum_invoiced_units']==(200 if brand=='OXO' else 100)
        assert row['minimum_invoice_count']==1 and row['invoice_required'] is True
        assert row['application_scope']=='BRAND' and row['immediate_approval_offered'] is False
        assert row['supplier_documentation_requirements']==['MANUFACTURER_OR_DISTRIBUTOR_PURCHASE_INVOICE']
        assert row['review_date'] is None and row['additional_requirements'] is None


def test_manual_observations_append_corrections_without_overwrite(store):
    m65.manual_import(m65.SEEDS,store)
    row=deepcopy(store.events('manual_approval')[0]);row.pop('kind')
    row['minimum_invoiced_units']=300;row['source_reference']='manual:later-review'
    store.append([intel.manual_observation(row)])
    assert len(store.events('manual_approval'))==5
    with pytest.raises(sqlite3.IntegrityError):store.db.execute('DELETE FROM intelligence_events')
    with pytest.raises(sqlite3.IntegrityError):store.db.execute("UPDATE intelligence_events SET payload='{}'")


@pytest.mark.parametrize('update',[dict(invoice_required='yes'),dict(minimum_invoiced_units=-1),
    dict(review_date='missing timezone'),dict(immediate_approval_offered='false'),
    dict(seller_id='PRIVATE'),dict(supplier_documentation_requirements=['PRIVATE INVOICE TEXT'])])
def test_manual_schema_rejects_ambiguous_or_private_inputs(update):
    doc,_=intel.read_json(m65.SEEDS);row=deepcopy(doc['observations'][0]);row.update(update)
    with pytest.raises(ValueError):intel.manual_observation(row)


def test_manual_coverage_is_exact_asin_not_entire_brand(tmp_path,store):
    m65.manual_import(m65.SEEDS,store)
    store.append(intel.import_report(report(tmp_path,[normalized(asin='B00L9X2CWQ'),normalized(asin='B000000001')])))
    result={r['asin']:r for r in intel.coverage(store)}
    assert result['B00L9X2CWQ']['manual_review_status']=='REVIEWED'
    assert result['B000000001']['manual_review_status']=='NOT_REVIEWED'


def catalog_row(i,brand=None,category='office',product_type='PENS'):
    return dict(asin=f'B{i:09d}',brand=brand or 'Independent '+str(i),category=category,
        product_type=product_type,marketplace=intel.US,observed_at=DATE,provenance='synthetic:test',
        catalog=dict(asin=f'B{i:09d}',title='Synthetic example '+str(i),model='M'+str(i),
            package_quantity=1,variation='blue',identifiers=[dict(identifier_type='UPC',value='012345678905')]),
        summary_fields=dict(size='small'))


def catalog_file(tmp_path,rows):
    path=tmp_path/'catalog.json';path.write_text(json.dumps(rows));return path


def test_candidate_identity_parser_and_duplicate_conflicts(tmp_path):
    row=catalog_row(1);duplicate=deepcopy(row);duplicate['catalog']['model']='DIFFERENT'
    parsed=ranking.candidates(catalog_file(tmp_path,[row,duplicate]))
    assert len(parsed)==1 and parsed[0]['identity_conflict'] is True
    result=ranking.rank(parsed,[],[],set())
    assert not result['selected_asins'] and result['rows'][0]['eligibility']=='UNKNOWN'


def test_ranking_determinism_diversity_and_historical_exclusion(tmp_path):
    rows=[catalog_row(i,brand='Brand '+str(i//3),category='cat '+str(i%3),product_type='type '+str(i%2)) for i in range(30)]
    parsed=ranking.candidates(catalog_file(tmp_path,rows))
    a=ranking.rank(parsed,[],[],{'B000000000'},maximum=12,max_per_brand=2)
    b=ranking.rank(list(reversed(parsed)),[],[],{'B000000000'},maximum=12,max_per_brand=2)
    assert a==b
    selected=[r for r in a['rows'] if r['selected']]
    assert len(selected)==12 and 'B000000000' not in a['selected_asins']
    assert max(Counter(r['brand'] for r in selected).values())<=2
    assert len({r['category'] for r in selected})==3 and len({r['product_type'] for r in selected})==2
    assert all(r['eligibility']=='UNKNOWN' for r in a['rows'])


def test_invoice_heavy_penalty_is_soft_not_eligibility_inference(tmp_path,store):
    m65.manual_import(m65.SEEDS,store)
    rows=[catalog_row(1,'OXO'),catalog_row(2,'Independent Maker')]
    result=ranking.rank(ranking.candidates(catalog_file(tmp_path,rows)),[],store.events('manual_approval'),set(),maximum=1,max_per_brand=1)
    assert result['selected_asins']==['B000000002']
    oxo=next(r for r in result['rows'] if r['brand']=='OXO')
    assert oxo['score_components']['invoice_heavy_observation']==-35
    assert oxo['eligibility']=='UNKNOWN' and not oxo['exclusion_reasons']


def batch_case(tmp_path,store):
    private=tmp_path/'legacy';private.mkdir(exist_ok=True)
    h=intel.build_audit(private,store)
    parsed=ranking.candidates(catalog_file(tmp_path,[catalog_row(i) for i in range(5)]))
    ranked=ranking.rank(parsed,[],[],set(h['excluded_asins']),maximum=3,max_per_brand=2)
    m=batch.proposal(ranked,h,'a'*64)
    digest='b'*64
    now=datetime.now(timezone.utc)
    auth=dict(approved=True,manifest_sha256=digest,asins=m['asins'],marketplace_id=intel.US,
        condition='new_new',budget=m['budget'],review_reference='manual:test-review',
        reviewed_at=(now-timedelta(minutes=1)).isoformat(),expires_at=(now+timedelta(hours=1)).isoformat())
    return m,digest,h,auth


@pytest.mark.parametrize('failure',['no_auth','no_flag','digest','scope','budget','expired','history'])
def test_separate_authorization_digest_budget_and_flag_required(tmp_path,store,failure):
    m,digest,h,auth=batch_case(tmp_path,store)
    flag=True;actual=digest
    if failure=='no_auth':auth=None
    if failure=='no_flag':flag=False
    if failure=='digest':actual='c'*64
    if failure=='scope':auth['condition']='used'
    if failure=='budget':auth=deepcopy(auth);auth['budget']['restrictions']+=1
    if failure=='expired':auth['expires_at']=DATE
    if failure=='history':h=deepcopy(h);h['excluded_asins'].append(m['asins'][0])
    with pytest.raises(ValueError):batch.reserve_future(store,m,digest,auth,actual_file_sha256=actual,execute=flag,audit=h)
    assert store.db.execute('SELECT count(*) FROM batch_claims').fetchone()[0]==0


def test_permanent_reservation_request_limit_and_no_retries(tmp_path,store):
    m,digest,h,auth=batch_case(tmp_path,store)
    batch.reserve_future(store,m,digest,auth,actual_file_sha256=digest,execute=True,audit=h)
    batch.consume_attempt(store,digest,'authentication')
    for asin in m['asins']:batch.consume_attempt(store,digest,'restrictions',asin)
    assert store.db.execute('SELECT count(*) FROM request_attempts').fetchone()[0]==4
    with pytest.raises(ValueError):batch.consume_attempt(store,digest,'authentication')
    with pytest.raises(ValueError):batch.consume_attempt(store,digest,'pricing',m['asins'][0])
    with pytest.raises((ValueError,sqlite3.IntegrityError)):batch.consume_attempt(store,digest,'restrictions',m['asins'][0])
    assert set(m['asins'])<=store.excluded()
    with pytest.raises(ValueError):batch.reserve_future(store,m,digest,auth,actual_file_sha256=digest,execute=True,audit=h)


def test_ambiguous_outcome_stops_without_followup(tmp_path,store):
    m,digest,h,auth=batch_case(tmp_path,store)
    batch.reserve_future(store,m,digest,auth,actual_file_sha256=digest,execute=True,audit=h)
    batch.consume_attempt(store,digest,'authentication')
    batch.consume_attempt(store,digest,'restrictions',m['asins'][0])
    batch.stop_ambiguous(store,digest,'UNKNOWN')
    with pytest.raises(ValueError):batch.consume_attempt(store,digest,'restrictions',m['asins'][1])
    assert store.db.execute('SELECT count(*) FROM request_attempts').fetchone()[0]==2


def test_budget_tampering_and_manifest_duplicates_rejected(tmp_path,store):
    m,*_=batch_case(tmp_path,store)
    for edit in ('budget','duplicates','retry','path'):
        value=deepcopy(m)
        if edit=='budget':value['budget']['maximum_requests']+=1
        if edit=='duplicates':value['asins'].append(value['asins'][0])
        if edit=='retry':value['no_retry']=False
        if edit=='path':value['requests'][0]['path']='/products/pricing/v0/items'
        with pytest.raises(ValueError):batch.validate_manifest(value)


def test_legacy_exclusions_unchanged_and_preparation_dry_only(tmp_path,store):
    private=tmp_path/'legacy';private.mkdir()
    path=private/'m63-eligibility-authorization-01.json'
    path.write_text(json.dumps(dict(asins=['B000000001'])))
    before=intel.sha256(path)
    rows=[catalog_row(i) for i in range(5)]
    out=tmp_path/'dry'
    summary=m65.prepare(store,catalog_file(tmp_path,rows),private,out,3,2)
    assert summary['live_requests']==0 and summary['execution_authorized'] is False
    assert 'B000000001' not in summary['selected_asins']
    assert intel.sha256(path)==before and not store.excluded()
    assert store.db.execute('SELECT count(*) FROM batch_claims').fetchone()[0]==0
    m=json.loads((out/'M65_proposed_manifest.json').read_text());batch.validate_manifest(m)
    assert summary['manifest_sha256']==intel.sha256(out/'M65_proposed_manifest.json')


def test_readiness_never_calculates_missing_economics():
    value=readiness()
    assert value['enabled'] is False and value['expected_net_profit'] is None and value['roi'] is None
    assert value['seller_listing_permission'] is None and value['fba_fulfillment_eligibility'] is None
    assert value['purchase_authorized'] is False and value['listing_creation_authorized'] is False
    assert value['thresholds']==dict(minimum_roi_percent=50,minimum_net_profit_usd=5,maximum_inventory_budget_usd=500)


def test_cli_has_no_execution_or_commercial_action(tmp_path):
    for action in ('execute','run','purchase','apply','listing','upload'):
        result=subprocess.run([sys.executable,'-m','app.m65',action,'--store',str(tmp_path/'store.sqlite3')],capture_output=True)
        assert result.returncode!=0
    assert not (tmp_path/'store.sqlite3').exists()


def test_store_rejects_private_field_injection(tmp_path,store):
    event=intel.import_report(report(tmp_path))[0]
    event['seller_id']='PRIVATESELLER'
    with pytest.raises(ValueError):store.append([event])
    assert not store.events()


def test_low_priority_shortfall_is_not_padded_with_invoice_heavy_brand(tmp_path,store):
    m65.manual_import(m65.SEEDS,store)
    rows=[catalog_row(1,'OXO'),catalog_row(2,'Independent Maker')]
    result=ranking.rank(ranking.candidates(catalog_file(tmp_path,rows)),[],store.events('manual_approval'),set(),maximum=2,max_per_brand=2)
    assert result['selected_asins']==['B000000002'] and result['actual_selected']==1
    oxo=next(r for r in result['rows'] if r['brand']=='OXO')
    assert oxo['priority_review_required'] is True and oxo['eligibility']=='UNKNOWN'


def test_attempt_accounting_is_sql_append_only(tmp_path,store):
    m,digest,h,auth=batch_case(tmp_path,store)
    batch.reserve_future(store,m,digest,auth,actual_file_sha256=digest,execute=True,audit=h)
    batch.consume_attempt(store,digest,'authentication')
    for table in ('batch_claims','asin_claims','request_attempts'):
        with pytest.raises(sqlite3.IntegrityError):store.db.execute('DELETE FROM '+table)


def test_cli_manual_export_roundtrip_and_no_overwrite(tmp_path):
    path=tmp_path/'state.sqlite3';out=tmp_path/'manual.json'
    def cli(*args):
        return subprocess.run([sys.executable,'-m','app.m65',*map(str,args),'--store',str(path)],capture_output=True)
    assert cli('init').returncode==0
    assert cli('export-manual','--output',out).returncode==0
    data=json.loads(out.read_bytes())
    assert len(data['observations'])==4
    assert cli('import-manual','--input',out).returncode==0
    assert cli('export-manual','--output',out).returncode!=0
