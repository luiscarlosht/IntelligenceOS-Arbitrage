"""Synthetic offline fixtures; production credentials, network and claims forbidden."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import csv
import json
import os
from pathlib import Path
import socket
import sqlite3

import pytest

from app import m69,m69_discovery as discovery,m69_history as history_api
from app import m69_workflow as workflow
from app.m65_intelligence import US,CONDITION,sha256,read_json
from app.m67_state import Ledger
from app.m65_batch import validate_manifest
from app.observations import canonical,fingerprint
from test_m67 import cohort
from test_m66 import catalog_row,opportunity,positive_sc

NOW=datetime.now(timezone.utc).replace(microsecond=0)
DATE='2026-01-02T12:00:00+00:00'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*a,**k):pytest.fail('Live operations and execution reservations forbidden')
    for name in ('create_connection','getaddrinfo','gethostbyname'):
        monkeypatch.setattr(socket,name,blocked)
    monkeypatch.setattr(socket.socket,'connect',blocked)
    monkeypatch.setattr(socket.socket,'connect_ex',blocked)
    from app import amazon_pilot,m65_batch,m67_execution,m67_transport
    for name in ('load_credentials','exchange_token','_request_json'):monkeypatch.setattr(amazon_pilot,name,blocked)
    monkeypatch.setattr(Ledger,'__init__',blocked)
    monkeypatch.setattr(m65_batch,'reserve_future',blocked)
    monkeypatch.setattr(m65_batch,'consume_attempt',blocked)
    monkeypatch.setattr(m67_execution,'execute',blocked)
    monkeypatch.setattr(m67_transport.AmazonTransport,'send',blocked)


def write(path,value):
    path.write_text(canonical(value)+'\n');path.chmod(0o600)


@pytest.fixture
def fixture(cohort):
    c=cohort
    rows=[catalog_row(i,brand='Brand'+str(i%18)) for i in range(160)]
    write(c['source'],rows)
    from app.m66_discovery import build
    manifest,ranking,_=build([c['source']],c['store'],c['private'],as_of=datetime.fromisoformat(DATE))
    write(c['path'],manifest);write(c['path'].parent/'M66_candidate_ranking.json',ranking)
    c.update(manifest=manifest,inner=manifest['restrictions_proposal'],digest=sha256(c['path']))
    m63=[]
    for i in range(20):
        state='NOT_ELIGIBLE' if i>=18 else 'APPROVAL_REQUIRED'
        m63.append(dict(asin=f'B{i:09d}',marketplace_id=US,condition=CONDITION,observed_at=DATE,
            restrictions=dict(status='succeeded',http_status=200,response=dict(restrictions=[dict(marketplaceId=US,
                reasons=[dict(reasonCode=state,message='PRIVATESELLER PRIVATESECRET')])]))))
    write(c['private']/'m63-eligibility-results.json',dict(is_mock=False,status='partial',finished_at=DATE,
        source_bound_manifest=dict(marketplace_id=US,condition=CONDITION),rows=m63,
        seller_id='PRIVATESELLER',client_secret='PRIVATESECRET'))
    p=c['private']/'m67-executions.sqlite3'
    db=sqlite3.connect(p)
    db.executescript('''
        CREATE TABLE m67_batches(digest TEXT PRIMARY KEY,payload TEXT);
        CREATE TABLE m67_claims(asin TEXT PRIMARY KEY,digest TEXT);
        CREATE TABLE m67_attempts(id TEXT PRIMARY KEY,digest TEXT,kind TEXT,asin TEXT,observed_at TEXT);
        CREATE TABLE m67_outcomes(id TEXT PRIMARY KEY,payload TEXT);
        CREATE TABLE m67_stops(digest TEXT PRIMARY KEY);
        CREATE TABLE m67_reviews(digest TEXT PRIMARY KEY,payload TEXT);
    ''')
    db.execute('INSERT INTO m67_batches VALUES (?,?)',(c['digest'],canonical(c['inner'])))
    for index,(kind,asin) in enumerate([('authentication',None)]+[('restrictions',a) for a in c['inner']['asins']]):
        key=c['digest']+':'+(asin or 'authentication')
        state='UNKNOWN' if kind=='authentication' else 'NOT_ELIGIBLE' if index>18 else 'APPROVAL_REQUIRED'
        db.execute('INSERT INTO m67_attempts VALUES (?,?,?,?,?)',(key,c['digest'],kind,asin,DATE))
        db.execute('INSERT INTO m67_outcomes VALUES (?,?)',(key,canonical(dict(operation_status='SUCCEEDED',api_state=state,
            http_status=200,reason_codes=[] if kind=='authentication' else [state],observed_at=DATE,
            source_sha256=fingerprint(dict(key=key)),failure=None))))
        if asin:db.execute('INSERT INTO m67_claims VALUES (?,?)',(asin,c['digest']))
    for table in ('batches','claims','attempts','outcomes','stops','reviews'):
        for op in ('UPDATE','DELETE'):
            db.execute(f"CREATE TRIGGER immutable_m67_{table}_{op} BEFORE {op} ON m67_{table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
    db.commit();db.close();p.chmod(0o600)
    c['ledger']=p
    return c


def analyze(c,**kwargs):
    return discovery.analyze([c['source']],c['store_path'],c['private'],c['path'],c['digest'],as_of=NOW,**kwargs)


def protected(c):
    paths=[c['ledger'],c['store_path'],c['path'],c['source'],c['private']/'m63-eligibility-authorization-01.json',c['private']/'candidate-executions.sqlite3']
    return {str(p):sha256(p) for p in paths}


def envelope(asin,payload):
    return dict(schema=1,asin=asin,marketplace=US,condition=CONDITION,observed_at=NOW.isoformat(),
                review_reference='manual:synthetic-M69',payload=payload)


def product(row):
    i=int(row['asin'][1:])
    return dict(brand=row['brand'],title='Synthetic item',gtin='012345678905',model='M'+str(i),
        size='small',pack_quantity=1,variation='blue',url='https://www.amazon.com/dp/'+row['asin'],
        observed_at=NOW.isoformat(),source_reference='manual:synthetic-product')


def prepared(fixture,tmp_path):
    report,h=analyze(fixture);row=next(r for r in report['ranking']['rows'] if r['selected'])
    journal=workflow.WorkflowStore(tmp_path/'journal/state.sqlite3',create=True)
    journal.register(report,row['asin'],h,NOW)
    return report,h,row,journal


def pending(fixture,tmp_path):
    report,h,row,journal=prepared(fixture,tmp_path);asin=row['asin']
    for target,payload in (
        ('IDENTITY_VERIFIED',dict(amazon_product=product(row))),
        ('OFFLINE_RISK_REVIEWED',dict(score_components_sha256=fingerprint(row['score_components']),unknowns_acknowledged=True,condition_reviewed_new=True)),
        ('LIVE_ELIGIBILITY_PENDING',dict(separate_live_authorization_required=True))):
        journal.advance(asin,target,h,envelope(asin,payload),NOW,workflow.thresholds())
    return report,h,row,journal


def eligible_context(row,h):
    h=deepcopy(h);asin=row['asin']
    fact=dict(asin=asin,marketplace=US,condition=CONDITION,observed_at=NOW.isoformat(),operation_status='SUCCEEDED',
              eligibility='NO_REPORTED_RESTRICTIONS',source_reference='sha256:'+'a'*64)
    h['events'].append(fact)
    h['rows'].append(dict(asin=asin,operation_status='SUCCEEDED',api_state='NO_REPORTED_RESTRICTIONS',conflicting_evidence=False))
    h['excluded_asins'].append(asin)
    manual=positive_sc()
    for e in manual:e.update(asin=asin,observed_at=NOW.isoformat())
    h['manual_verifications']=manual
    h['evidence_sha256']=fingerprint(h)
    return h


def complete_opportunity(row):
    o=opportunity();asin=row['asin'];o['asin']=asin
    o['amazon_product']=product(row)
    o['retailer_product']=dict(product(row),url='https://example.com/exact-product')
    for k,v in o['costs'].items():
        v['observed_at']=NOW.isoformat()
        if k in ('amazon_sale_price','referral_fee','fba_fee'):v['asin']=asin
    return o


def test_realistic_consolidation_40_counts_exclusions_and_privacy(fixture):
    before=protected(fixture);report,h=analyze(fixture)
    assert h['cohort_summary']==dict(unique_asins=40,NO_REPORTED_RESTRICTIONS=0,APPROVAL_REQUIRED=36,NOT_ELIGIBLE=4,OTHER_RESTRICTED=0,UNKNOWN=0)
    assert h['history_complete'] and h['global_claim_count']==20
    assert set(h['original_m63_asins'])|set(h['original_m67_asins'])<=set(h['excluded_asins'])
    assert not set(report['ranking']['selected_asins'])&set(h['excluded_asins'])
    assert report['summary']['selected_count']==100
    assert protected(fixture)==before
    encoded=canonical(dict(report=report,history=h))
    assert 'PRIVATESELLER' not in encoded and 'PRIVATESECRET' not in encoded
    assert all(r['eligibility']=='UNKNOWN' for r in report['ranking']['rows'] if r['selected'])
    assert all(not r['identity_verified'] and r['workflow_state']=='DISCOVERED' for r in report['ranking']['rows'])


def test_deterministic_duplicate_source_and_bounded_pool(fixture):
    first,h=analyze(fixture)
    second,_=discovery.analyze([fixture['source'],fixture['source']],fixture['store_path'],fixture['private'],fixture['path'],fixture['digest'],as_of=NOW)
    assert first==second
    small,_=analyze(fixture,maximum=7,max_per_brand=2)
    assert len(small['ranking']['selected_asins'])==7
    assert len(first['ranking']['rows'])==160
    assert len(set(first['ranking']['selected_asins']))==100


@pytest.mark.parametrize('maximum',[0,101,True,-1])
def test_invalid_pool_budgets(fixture,maximum):
    with pytest.raises(ValueError):analyze(fixture,maximum=maximum)


def test_brand_and_category_patterns_are_counts_and_soft_penalties(fixture):
    report,h=analyze(fixture)
    assert sum(r['sample_size'] for r in report['brand_risk'])==40
    assert sum(r['sample_size'] for r in report['category_risk'])==40
    assert len(report['summary']['category_distribution'])==4
    assert len(report['summary']['brand_distribution'])>=10
    selected=[r for r in report['ranking']['rows'] if r['selected']]
    assert any(r['brand_history']['APPROVAL_REQUIRED']>0 for r in selected)
    assert all(r['score_components']['brand_observed_approval']<=0 for r in selected)
    assert all('probability' not in r for r in report['brand_risk'])


def test_invoice_observation_deprioritizes_not_brand_exclusion(fixture):
    # Use the existing validated observation contract.
    value=dict(asin='B000000000',brand='Brand0',marketplace=US,condition=CONDITION,review_date=DATE,
        application_scope='BRAND',approval_pathway='INVOICE',invoice_required=True,minimum_invoiced_units=100,
        minimum_invoice_count=1,supplier_documentation_requirements=['MANUFACTURER_OR_DISTRIBUTOR_PURCHASE_INVOICE'],
        immediate_approval_offered=False,additional_requirements=None,source_reference='manual:synthetic',review_status='REVIEWED')
    from app.m65_intelligence import manual_observation
    fixture['store'].append([manual_observation(value)])
    r,_=analyze(fixture)
    rows=[e for e in r['ranking']['rows'] if e['brand']=='Brand0' and e['asin'] not in r['excluded_asins']]
    assert rows and all(e['score_components']['invoice_heavy_observation']==-35 for e in rows)
    assert all(not e['exclusion_reasons'] for e in rows)


@pytest.mark.parametrize('pathkey',['ledger','path','store_path'])
def test_missing_authoritative_sources_fail_closed(fixture,pathkey):
    fixture[pathkey].unlink()
    with pytest.raises((ValueError,FileNotFoundError)):analyze(fixture)


def test_missing_m63_report_and_wrong_manifest_digest_fail(fixture):
    original=fixture['digest'];fixture['digest']='0'*64
    with pytest.raises(ValueError):analyze(fixture)
    fixture['digest']=original
    (fixture['private']/'m63-eligibility-results.json').unlink()
    with pytest.raises(ValueError):analyze(fixture)


def test_missing_response_is_unknown_consumed_and_never_reselected(fixture):
    c=fixture;db=sqlite3.connect(c['ledger'])
    db.execute('DROP TRIGGER immutable_m67_outcomes_DELETE')
    key=c['digest']+':'+c['inner']['asins'][0]
    db.execute('DELETE FROM m67_outcomes WHERE id=?',(key,))
    db.execute("CREATE TRIGGER immutable_m67_outcomes_DELETE BEFORE DELETE ON m67_outcomes BEGIN SELECT RAISE(ABORT,'immutable'); END")
    db.commit();db.close()
    r,h=analyze(c)
    assert not h['history_complete'] and h['cohort_summary']['UNKNOWN']==1
    assert c['inner']['asins'][0] in h['excluded_asins']
    assert c['inner']['asins'][0] not in r['ranking']['selected_asins']


def test_additional_permanent_claim_excluded_without_response(fixture):
    c=fixture;first,_=analyze(c);asin=first['ranking']['selected_asins'][0]
    db=sqlite3.connect(c['ledger']);db.execute('INSERT INTO m67_claims VALUES (?,?)',(asin,c['digest']));db.commit();db.close()
    report,h=analyze(c)
    assert asin in h['excluded_asins'] and asin not in report['ranking']['selected_asins']


def test_explicit_condition_mismatch_excludes_exact_asin(fixture):
    c=fixture;report,_=analyze(c);asin=report['ranking']['selected_asins'][0]
    rows=json.loads(c['source'].read_text());next(r for r in rows if r['asin']==asin)['condition']='used_like_new';write(c['source'],rows)
    report,_=analyze(c);row=next(r for r in report['ranking']['rows'] if r['asin']==asin)
    assert not row['selected'] and row['condition_compatibility']=='INCOMPATIBLE'
    assert 'CONDITION_INCOMPATIBLE' in row['exclusion_reasons']


def test_csv_exports_safe_complete_no_overwrite(fixture,tmp_path):
    report,h=analyze(fixture);out=tmp_path/'export'
    summary=m69.export_analysis(report,h,out)
    assert summary['selected_count']==100
    with (out/'M69_candidates.csv').open(encoding='utf-8-sig') as f:assert len(list(csv.DictReader(f)))==100
    assert len(json.loads((out/'M69_exclusions.json').read_text())['original_m63_asins'])==20
    assert all(p.stat().st_mode&0o777==0o600 for p in out.iterdir())
    with pytest.raises(FileExistsError):m69.export_analysis(report,h,out)
    m69.export_csv(tmp_path/'formula.csv',[dict(value='=CMD()')],['value'])
    assert "'=CMD()" in (tmp_path/'formula.csv').read_text(encoding='utf-8-sig')


def test_full_offline_stages_require_independent_verified_evidence(fixture,tmp_path):
    report,h,row,journal=pending(fixture,tmp_path);a=row['asin']
    assert journal.current(a)['stage']=='LIVE_ELIGIBILITY_PENDING'
    manifest=journal.proposed_manifest([a],h,NOW)
    assert not manifest['execution_authorized'] and manifest['budget']['maximum_requests']==2
    with pytest.raises(ValueError):validate_manifest(manifest)
    with pytest.raises(ValueError):journal.advance(a,'ELIGIBILITY_OBSERVED',h,envelope(a,dict(history_sha256=h['evidence_sha256'])),NOW,workflow.thresholds())
    verified=eligible_context(row,h)
    journal.advance(a,'ELIGIBILITY_OBSERVED',verified,envelope(a,dict(history_sha256=verified['evidence_sha256'])),NOW,workflow.thresholds())
    with pytest.raises(ValueError):journal.proposed_manifest([a],verified,NOW)
    journal.advance(a,'FBA_REVIEW_PENDING',verified,envelope(a,dict(independent_fba_review_required=True)),NOW,workflow.thresholds())
    o=complete_opportunity(row)
    journal.advance(a,'PROFITABILITY_REVIEWED',verified,envelope(a,dict(opportunity=o)),NOW,workflow.thresholds())
    journal.advance(a,'READY_FOR_HUMAN_DECISION',verified,envelope(a,dict(opportunity=o,human_review_requested=True)),NOW,workflow.thresholds())
    final=journal.current(a)
    assert final['stage']=='READY_FOR_HUMAN_DECISION' and final['purchase_authorized'] is False
    tables={r[0] for r in journal.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables=={'m69_reports','m69_events'}
    assert journal.db.execute('SELECT count(*) FROM m69_events').fetchone()[0]==8
    journal.db.close()


@pytest.mark.parametrize('target',['READY_FOR_HUMAN_DECISION','FBA_REVIEW_PENDING','PROFITABILITY_REVIEWED'])
def test_stage_skips_are_blocked(fixture,tmp_path,target):
    _,h,row,journal=prepared(fixture,tmp_path)
    with pytest.raises(ValueError):journal.advance(row['asin'],target,h,envelope(row['asin'],{}),NOW,workflow.thresholds())
    assert journal.current(row['asin'])['stage']=='DISCOVERED';journal.db.close()


def test_re_registration_claims_and_expired_reviews_blocked(fixture,tmp_path):
    report,h,row,journal=pending(fixture,tmp_path)
    with pytest.raises(ValueError):journal.register(report,row['asin'],h,NOW)
    h['excluded_asins'].append(row['asin'])
    with pytest.raises(ValueError):journal.proposed_manifest([row['asin']],h,NOW)
    h['excluded_asins'].remove(row['asin'])
    with pytest.raises(ValueError):journal.proposed_manifest([row['asin']],h,NOW+timedelta(days=2))
    with pytest.raises(ValueError):journal.proposed_manifest([row['asin']]*2,h,NOW)
    journal.db.close()


@pytest.mark.parametrize('which',['missing_gtin','wrong_pack','wrong_upc','wrong_model','wrong_scope','stale_review'])
def test_identity_review_cannot_claim_similar_or_missing_product(fixture,tmp_path,which):
    _,h,row,journal=prepared(fixture,tmp_path);p=product(row);e=envelope(row['asin'],dict(amazon_product=p))
    if which=='missing_gtin':p['gtin']=None
    elif which=='wrong_pack':p['pack_quantity']=2
    elif which=='wrong_upc':p['gtin']='036000291452'
    elif which=='wrong_model':p['model']='OTHER'
    elif which=='wrong_scope':e['marketplace']='OTHER'
    else:e['observed_at']=(NOW-timedelta(days=2)).isoformat()
    with pytest.raises(ValueError):journal.advance(row['asin'],'IDENTITY_VERIFIED',h,e,NOW,workflow.thresholds())
    journal.db.close()


@pytest.mark.parametrize('state',['UNKNOWN','APPROVAL_REQUIRED','NOT_ELIGIBLE','OTHER_RESTRICTED'])
def test_financial_calculation_disabled_without_unrestricted_verified_evidence(fixture,tmp_path,monkeypatch,state):
    _,h,row,journal=prepared(fixture,tmp_path);h=eligible_context(row,h)
    h['events'][-1]['eligibility']=state
    monkeypatch.setattr(workflow,'economics',lambda *a,**k:pytest.fail('Economics must remain disabled'))
    with pytest.raises(ValueError):workflow.financial_review(complete_opportunity(row),row,h,NOW,workflow.thresholds())
    journal.db.close()


@pytest.mark.parametrize('missing',['seller','fba','copy_listing','fba_commingling','conflict'])
def test_no_reported_restrictions_alone_never_enables_economics(fixture,tmp_path,monkeypatch,missing):
    _,h,row,journal=prepared(fixture,tmp_path);h=eligible_context(row,h)
    if missing=='seller':h['manual_verifications']=h['manual_verifications'][1:]
    elif missing=='fba':h['manual_verifications']=h['manual_verifications'][:1]
    elif missing=='copy_listing':h['manual_verifications'][0].update(verification_method='MANUAL_COPY_LISTING',seller_central_states=['LISTING_CREATION_ACCESSIBLE'])
    elif missing=='fba_commingling':h['manual_verifications'][1]['fba_program']='COMMINGLING'
    else:h['events'].append(dict(h['events'][-1],eligibility='APPROVAL_REQUIRED'))
    monkeypatch.setattr(workflow,'economics',lambda *a,**k:pytest.fail('Economics must remain disabled'))
    with pytest.raises(ValueError):workflow.financial_review(complete_opportunity(row),row,h,NOW,workflow.thresholds())
    journal.db.close()


@pytest.mark.parametrize('missing',['fee','tax','shipping','sale','cost_date','identity_pack'])
def test_incomplete_financial_inputs_never_profitable(fixture,tmp_path,missing):
    _,h,row,journal=prepared(fixture,tmp_path);h=eligible_context(row,h);o=complete_opportunity(row)
    key={'fee':'fba_fee','tax':'sales_tax','shipping':'inbound_shipping','sale':'amazon_sale_price','cost_date':'fba_fee'}.get(missing)
    if missing=='identity_pack':o['retailer_product']['pack_quantity']=2
    elif missing=='cost_date':o['costs'][key]['observed_at']=DATE
    else:o['costs'][key]['value']=None
    with pytest.raises(ValueError):workflow.financial_review(o,row,h,NOW,workflow.thresholds())
    journal.db.close()


def test_financial_cost_basis_configurable_targets_and_budget(fixture,tmp_path):
    _,h,row,journal=prepared(fixture,tmp_path);h=eligible_context(row,h);o=complete_opportunity(row)
    r=workflow.financial_review(o,row,h,NOW,workflow.thresholds())
    assert Decimal(r['net_profit'])==Decimal('12')
    assert Decimal(r['total_invested_cost_per_unit'])==Decimal('17.5')
    assert Decimal(r['estimated_inventory_investment'])==Decimal('350')
    assert r['passes'] and Decimal(r['roi_percent'])==Decimal('12')/Decimal('17.5')*100
    assert not workflow.financial_review(o,row,h,NOW,workflow.thresholds(100,5,500))['passes']
    assert not workflow.financial_review(o,row,h,NOW,workflow.thresholds(50,20,500))['passes']
    assert not workflow.financial_review(o,row,h,NOW,workflow.thresholds(50,5,100))['passes']
    journal.db.close()


@pytest.mark.parametrize('args',[('NaN','5','500'),('50','-1','500'),('50','5','0'),('bad','5','500')])
def test_invalid_financial_targets(args):
    with pytest.raises(ValueError):workflow.thresholds(*args)


def test_workflow_never_migrates_original_databases_and_has_immutable_events(fixture,tmp_path):
    before=protected(fixture)
    for path in (fixture['ledger'],fixture['store_path']):
        with pytest.raises(ValueError):workflow.WorkflowStore(path,create=True)
    report,h,row,journal=prepared(fixture,tmp_path)
    with pytest.raises(sqlite3.IntegrityError):journal.db.execute('DELETE FROM m69_events')
    with pytest.raises(sqlite3.IntegrityError):journal.db.execute('UPDATE m69_reports SET payload=payload')
    assert protected(fixture)==before;journal.db.close()


def test_cli_integration_and_no_execution_actions(fixture,tmp_path,capsys):
    c=fixture;args=['--catalog',str(c['source']),'--store',str(c['store_path']),'--history-dir',str(c['private']),
        '--m67-manifest',str(c['path']),'--m67-sha256',c['digest']]
    assert m69.main(['analyze',*args,'--as-of',NOW.isoformat(),'--output',str(tmp_path/'report')])==0
    text=capsys.readouterr().out
    assert 'PRIVATESELLER' not in text and 'PRIVATESECRET' not in text
    for action in ('execute','purchase','listing','approve'):
        with pytest.raises(SystemExit):m69.main([action,*args])
    assert m69.main(['analyze',*args,'--output',str(tmp_path/'report')])==2


def test_duplicate_historical_reports_do_not_multiply_samples_or_scores(fixture):
    c=fixture;first,h=analyze(c)
    original=c['private']/'m63-eligibility-results.json'
    (c['private']/'m63-eligibility-copy.json').write_bytes(original.read_bytes())
    second,h2=analyze(c)
    assert h2['cohort_summary']==h['cohort_summary']
    assert first['ranking']==second['ranking']
    assert len(h2['events'])==40
    assert all('source_sha256' in e for e in h2['events'])


def test_historical_conflicts_remain_unknown_and_excluded(fixture):
    c=fixture;asin='B000000001'
    event=dict(kind='eligibility',asin=asin,marketplace=US,condition=CONDITION,observed_at=DATE,
        operation_status='SUCCEEDED',eligibility='NO_REPORTED_RESTRICTIONS',reason_codes=[],brand='Brand1',category='office',
        brand_approval_requirement=None,fba_eligibility=None,purchase_authorized=False,
        source_reference='sha256:'+'b'*64+':row:0',source_sha256='b'*64)
    c['store'].append([event])
    report,h=analyze(c);row=next(r for r in h['rows'] if r['asin']==asin)
    assert row['conflicting_evidence'] and row['api_state']=='UNKNOWN' and not h['history_complete']
    assert asin not in report['ranking']['selected_asins']


def test_http_failure_cannot_be_successful_selling_evidence(fixture):
    c=fixture;db=sqlite3.connect(c['ledger']);key=c['digest']+':'+c['inner']['asins'][0]
    db.execute('DROP TRIGGER immutable_m67_outcomes_UPDATE')
    value=json.loads(db.execute('SELECT payload FROM m67_outcomes WHERE id=?',(key,)).fetchone()[0])
    value['http_status']=403
    db.execute('UPDATE m67_outcomes SET payload=? WHERE id=?',(canonical(value),key))
    db.execute("CREATE TRIGGER immutable_m67_outcomes_UPDATE BEFORE UPDATE ON m67_outcomes BEGIN SELECT RAISE(ABORT,'immutable'); END")
    db.commit();db.close()
    _,h=analyze(c)
    assert h['cohort_summary']['UNKNOWN']==1 and not h['history_complete']


@pytest.mark.parametrize('field,value',[('marketplace','WRONG'),('condition','used'),('observed_at',None),
                                      ('eligibility','SELLING_PERMISSION_CONFIRMED'),('operation_status','succeeded')])
def test_malformed_or_wrong_scope_never_unrestricted(field,value):
    e=dict(asin='B000000001',marketplace=US,condition=CONDITION,observed_at=DATE,
        eligibility='NO_REPORTED_RESTRICTIONS',operation_status='SUCCEEDED')
    e[field]=value
    result=history_api.normalize(e,'UNIT_TEST')
    assert result['eligibility']=='UNKNOWN' and result['operation_status']=='UNCERTAIN'


def test_absent_identity_is_unknown_and_blocks_advancement(fixture,tmp_path):
    c=fixture;rows=json.loads(c['source'].read_text())
    for r in rows:r['catalog']['identifiers']=[]
    write(c['source'],rows)
    report,h,row,journal=prepared(c,tmp_path)
    assert not row['catalog_identity_complete']
    with pytest.raises(ValueError):journal.advance(row['asin'],'IDENTITY_VERIFIED',h,envelope(row['asin'],dict(amazon_product=product(row))),NOW,workflow.thresholds())
    journal.db.close()


def test_explicit_risk_and_condition_review_required(fixture,tmp_path):
    _,h,row,journal=prepared(fixture,tmp_path);a=row['asin']
    journal.advance(a,'IDENTITY_VERIFIED',h,envelope(a,dict(amazon_product=product(row))),NOW,workflow.thresholds())
    for payload in ({},dict(score_components_sha256='0'*64,unknowns_acknowledged=True,condition_reviewed_new=True),
                    dict(score_components_sha256=fingerprint(row['score_components']),unknowns_acknowledged=False,condition_reviewed_new=True)):
        with pytest.raises(ValueError):journal.advance(a,'OFFLINE_RISK_REVIEWED',h,envelope(a,payload),NOW,workflow.thresholds())
    journal.db.close()


def test_live_pending_and_proposals_block_incomplete_history(fixture,tmp_path):
    _,h,row,journal=pending(fixture,tmp_path)
    h['history_complete']=False
    with pytest.raises(ValueError):journal.proposed_manifest([row['asin']],h,NOW)
    journal.db.close()


def test_manifest_rechecks_catalog_bindings_and_code(fixture,tmp_path,monkeypatch):
    _,h,row,journal=pending(fixture,tmp_path)
    changed=deepcopy(h);changed['catalog_source_sha256']=['0'*64]
    with pytest.raises(ValueError):journal.proposed_manifest([row['asin']],changed,NOW)
    monkeypatch.setattr(discovery,'implementation',lambda:{})
    with pytest.raises(ValueError):journal.proposed_manifest([row['asin']],h,NOW)
    journal.db.close()


def test_workflow_integrity_detects_forced_hash_chain_tampering(fixture,tmp_path):
    _,h,row,journal=prepared(fixture,tmp_path)
    journal.db.execute('DROP TRIGGER immutable_m69_events_UPDATE')
    journal.db.execute("UPDATE m69_events SET payload='{}'");journal.db.commit()
    with pytest.raises((ValueError,KeyError)):journal.current(row['asin'])
    journal.db.close()


def test_safe_cli_error_no_secret_echo(fixture,capsys,monkeypatch,tmp_path):
    c=fixture;args=['--catalog',str(c['source']),'--store',str(c['store_path']),'--history-dir',str(c['private']),
        '--m67-manifest',str(c['path']),'--m67-sha256',c['digest'],'--output',str(tmp_path/'out')]
    def fail(*a,**k):raise ValueError('PRIVATESELLER PRIVATESECRET')
    monkeypatch.setattr(m69,'analyze',fail)
    assert m69.main(['analyze',*args])==2
    with pytest.raises(SystemExit):m69.main(['analyze','--seller-id','PRIVATESELLER'])
    text=capsys.readouterr()
    assert 'PRIVATESELLER' not in text.out+text.err and 'PRIVATESECRET' not in text.out+text.err


def test_import_help_does_not_need_transport_or_execution_modules():
    import subprocess,sys
    script="import sys,socket; sys.modules['app.m67_execution']=None; sys.modules['app.m67_transport']=None; socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('NETWORK')); from app.m69 import main; main(['--help'])"
    r=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True)
    assert r.returncode==0 and 'M69 offline' in r.stdout


def test_cli_explicit_journal_and_proposal_integration(fixture,tmp_path,capsys):
    c=fixture;report,h=analyze(c);out=tmp_path/'reports';summary=m69.export_analysis(report,h,out)
    row=next(r for r in report['ranking']['rows'] if r['selected']);a=row['asin'];journal_path=tmp_path/'state.sqlite3'
    args=['--catalog',str(c['source']),'--store',str(c['store_path']),'--history-dir',str(c['private']),
          '--m67-manifest',str(c['path']),'--m67-sha256',c['digest'],'--workflow-store',str(journal_path),'--asin',a]
    before=protected(c)
    assert m69.main(['register',*args,'--analysis',str(out/'M69_analysis.json'),'--analysis-sha256',summary['analysis_sha256']])==0
    payloads=[('IDENTITY_VERIFIED',dict(amazon_product=product(row))),
        ('OFFLINE_RISK_REVIEWED',dict(score_components_sha256=fingerprint(row['score_components']),unknowns_acknowledged=True,condition_reviewed_new=True)),
        ('LIVE_ELIGIBILITY_PENDING',dict(separate_live_authorization_required=True))]
    for target,payload in payloads:
        path=tmp_path/(target+'.json');write(path,envelope(a,payload))
        assert m69.main(['advance',*args,'--target',target,'--evidence',str(path)])==0
    frozen=tmp_path/'proposal.json'
    assert m69.main(['manifest',*args,'--output',str(frozen)])==0
    p=json.loads(frozen.read_text())
    assert p['asins']==[a] and not p['execution_authorized'] and p['budget']['maximum_requests']==2
    journal_before=sha256(journal_path)
    assert m69.main(['status',*args])==0 and sha256(journal_path)==journal_before
    assert protected(c)==before
    assert 'PRIVATESELLER' not in capsys.readouterr().out


def test_missing_legacy_attempt_ledger_or_dangling_lock_fail_closed(fixture):
    p=fixture['private']/'candidate-execution.lock';p.symlink_to('missing-lock')
    with pytest.raises(ValueError):analyze(fixture)
    p.unlink();(fixture['private']/'candidate-executions.sqlite3').unlink()
    with pytest.raises(FileNotFoundError):analyze(fixture)


def test_no_padding_when_all_source_asins_are_historical(fixture):
    c=fixture
    known=set(c['inner']['asins'])|{f'B{i:09d}' for i in range(20)}
    write(c['source'],[r for r in json.loads(c['source'].read_text()) if r['asin'] in known])
    report,h=analyze(c)
    assert report['summary']['candidates_evaluated']==40
    assert not report['ranking']['selected_asins'] and report['summary']['selected_count']==0


def test_fake_catalog_eligibility_assertion_does_not_grant_permission(fixture):
    c=fixture;rows=json.loads(c['source'].read_text())
    for r in rows:r.update(eligibility='NO_REPORTED_RESTRICTIONS',listing_permission=True,fba_eligible=True)
    write(c['source'],rows);report,_=analyze(c)
    assert all(r['eligibility']=='UNKNOWN' and r['verification']['api_state']=='UNKNOWN' for r in report['ranking']['rows'] if r['selected'])


def test_failed_financial_review_cannot_advance_ready(fixture,tmp_path):
    _,h,row,journal=pending(fixture,tmp_path);a=row['asin'];h=eligible_context(row,h)
    journal.advance(a,'ELIGIBILITY_OBSERVED',h,envelope(a,dict(history_sha256=h['evidence_sha256'])),NOW,workflow.thresholds())
    journal.advance(a,'FBA_REVIEW_PENDING',h,envelope(a,dict(independent_fba_review_required=True)),NOW,workflow.thresholds())
    o=complete_opportunity(row);limits=workflow.thresholds(1000,100,500)
    journal.advance(a,'PROFITABILITY_REVIEWED',h,envelope(a,dict(opportunity=o)),NOW,limits)
    with pytest.raises(ValueError):journal.advance(a,'READY_FOR_HUMAN_DECISION',h,envelope(a,dict(opportunity=o,human_review_requested=True)),NOW,limits)
    assert journal.current(a)['stage']=='PROFITABILITY_REVIEWED';journal.db.close()


def test_financial_inclusive_threshold_boundaries(fixture,tmp_path):
    _,h,row,journal=prepared(fixture,tmp_path);h=eligible_context(row,h);o=complete_opportunity(row)
    result=workflow.financial_review(o,row,h,NOW,workflow.thresholds())
    limits=workflow.thresholds(result['roi_percent'],result['net_profit'],result['estimated_inventory_investment'])
    assert workflow.financial_review(o,row,h,NOW,limits)['passes'];journal.db.close()


def test_pending_review_expiry_and_maximum_20_manifest(fixture,tmp_path):
    _,h,row,journal=prepared(fixture,tmp_path);a=row['asin']
    journal.advance(a,'IDENTITY_VERIFIED',h,envelope(a,dict(amazon_product=product(row))),NOW,workflow.thresholds())
    later=NOW+timedelta(days=2)
    evidence=envelope(a,dict(score_components_sha256=fingerprint(row['score_components']),unknowns_acknowledged=True,condition_reviewed_new=True))
    evidence['observed_at']=later.isoformat()
    journal.advance(a,'OFFLINE_RISK_REVIEWED',h,evidence,later,workflow.thresholds())
    e=envelope(a,dict(separate_live_authorization_required=True));e['observed_at']=later.isoformat()
    with pytest.raises(ValueError):journal.advance(a,'LIVE_ELIGIBILITY_PENDING',h,e,later,workflow.thresholds())
    with pytest.raises(ValueError):journal.proposed_manifest([f'B{i:09d}' for i in range(21)],h,NOW)
    journal.db.close()


def test_tampered_analysis_cannot_register_invented_or_rescored_candidates(fixture,tmp_path):
    c=fixture;report,h=analyze(c);row=next(r for r in report['ranking']['rows'] if r['selected'])
    row['score']+=999
    path=tmp_path/'edited-analysis.json';write(path,report)
    args=['--catalog',str(c['source']),'--store',str(c['store_path']),'--history-dir',str(c['private']),
        '--m67-manifest',str(c['path']),'--m67-sha256',c['digest'],'--analysis',str(path),
        '--analysis-sha256',sha256(path),'--workflow-store',str(tmp_path/'state.sqlite3'),'--asin',row['asin']]
    assert m69.main(['register',*args])==2
    assert not (tmp_path/'state.sqlite3').exists()
    fresh,h=analyze(c);new=deepcopy(next(r for r in fresh['ranking']['rows'] if r['selected']));new['asin']='B999999999'
    fresh['ranking']['rows']=[new];fresh['ranking']['selected_asins']=[new['asin']]
    journal=workflow.WorkflowStore(tmp_path/'journal.sqlite3',create=True)
    with pytest.raises(ValueError):journal.register(fresh,new['asin'],h,NOW)
    journal.db.close()


def test_financial_flags_do_not_silently_change_analysis_policy(fixture,tmp_path):
    c=fixture;args=['--catalog',str(c['source']),'--store',str(c['store_path']),'--history-dir',str(c['private']),
        '--m67-manifest',str(c['path']),'--m67-sha256',c['digest'],'--output',str(tmp_path/'out'),'--minimum-roi','100']
    assert m69.main(['analyze',*args])==2 and not (tmp_path/'out').exists()


def test_new_exact_asin_manual_block_defers_manifest_but_brand_only_does_not(fixture,tmp_path):
    _,h,row,journal=pending(fixture,tmp_path);a=row['asin']
    from test_m66 import sc
    block=sc(['APPROVAL_APPLICATION_REQUIRED'],asin=a,method='MANUAL_APPROVAL_SCREEN')
    block['observed_at']=NOW.isoformat()
    h['manual_verifications'].append(block)
    with pytest.raises(ValueError):journal.proposed_manifest([a],h,NOW)
    h['manual_verifications'][-1]['asin']=None
    assert journal.proposed_manifest([a],h,NOW)['asins']==[a]
    journal.db.close()
