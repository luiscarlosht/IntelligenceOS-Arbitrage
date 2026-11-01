"""Synthetic offline evidence. Real API/account/network operations are forbidden."""
from copy import deepcopy
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

import pytest

from app import m66
from app import m65_batch
from app import m66_discovery as discovery
from app.m65_intelligence import US, CONDITION, import_report, build_audit, sha256
from app.m66_verification import VerificationStore, ACCOUNT, normalize, verify, verification_rows
from app.m66_opportunity import template, exact_match, economics, decide, DECISIONS, COSTS
from app.observations import canonical

NOW=datetime(2026,1,2,12,tzinfo=timezone.utc)
DATE=NOW.isoformat()
ASIN='B000000001'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args,**kwargs):pytest.fail('Live operation forbidden')
    monkeypatch.setattr(socket,'create_connection',denied)
    monkeypatch.setattr(socket,'getaddrinfo',denied)
    from app import amazon_pilot
    monkeypatch.setattr(amazon_pilot,'load_credentials',denied)
    monkeypatch.setattr(amazon_pilot,'_request_json',denied)


@pytest.fixture
def store(tmp_path):
    value=VerificationStore(tmp_path/'private/state.sqlite3')
    yield value
    value.close()


def api(state='NO_REPORTED_RESTRICTIONS',asin=ASIN):
    return dict(asin=asin,marketplace=US,condition=CONDITION,observed_at=DATE,
                operation_status='SUCCEEDED',eligibility=state,source_reference='sha256:'+'a'*64+':row:0')


def sc(states=None,fba='FBA_UNKNOWN',asin=ASIN,method='MANUAL_EXISTING_ASIN_OFFER'):
    return dict(asin=asin,brand='Synthetic Brand',marketplace=US,condition=CONDITION,
        account_reference=ACCOUNT,observed_at=DATE,verification_method=method,
        seller_central_states=states or ['OFFER_CREATION_AVAILABLE'],fba_state=fba,
        invoice_required=None,minimum_invoiced_units=None,restriction_scope='ASIN',source_reference='manual:synthetic')


def positive_sc():
    return [sc(),sc(['UNVERIFIED'],'FBA_ELIGIBLE',method='MANUAL_FBA_ELIGIBILITY')]


def permitted():return verify(ASIN,[api()],positive_sc(),as_of=NOW)


def opportunity():
    row=template(ASIN)
    product=dict(brand='Synthetic Brand',title='Synthetic item',gtin='012345678905',model='MODEL',
        size='small',pack_quantity=2,variation='blue',observed_at=DATE,source_reference='manual:synthetic-product')
    row['amazon_product']=dict(product,url='https://www.amazon.com/dp/'+ASIN)
    row['retailer_product']=dict(product,url='https://example.com/product')
    values=dict(amazon_sale_price='40',retailer_price='12',retailer_shipping='1',sales_tax='1',referral_fee='6',fba_fee='4',
        inbound_shipping='2',preparation_cost='0.5',packaging_cost='0.5',storage_cost='0.25',
        other_acquisition_cost='0.5',other_selling_cost='0.25')
    row['costs']={key:dict(value=value,currency='USD',observed_at=DATE,source_reference='manual:synthetic-cost') for key,value in values.items()}
    for key in ('amazon_sale_price','referral_fee','fba_fee'):
        row['costs'][key].update(asin=ASIN,condition=CONDITION)
    for key in ('referral_fee','fba_fee'):
        row['costs'][key].update(fulfillment='FBA',sale_price_basis='40')
    row['inventory_units']=20
    return row


@pytest.mark.parametrize('state,expected',[
    ('NO_REPORTED_RESTRICTIONS','NEEDS_SELLER_VERIFICATION'),('APPROVAL_REQUIRED','REQUIRES_APPROVAL'),
    ('NOT_ELIGIBLE','REJECTED_RESTRICTION'),('OTHER_RESTRICTED','REJECTED_RESTRICTION'),('UNKNOWN','NEEDS_SELLER_VERIFICATION')])
def test_api_states_do_not_imply_seller_central_or_fba(state,expected):
    v=verify(ASIN,[api(state)],[],as_of=NOW)
    assert v['api_state']==state and v['fba_state']=='FBA_UNKNOWN'
    assert decide(template(ASIN),v,as_of=NOW)['decision']==expected


def test_kozerite_copy_listing_false_positive_prevention():
    data,_=m66.read_json(m66.SC_SEEDS)
    row=next(v for v in data['observations'] if v['brand']=='Kozerite')
    v=verify('B0FM84W641',[],[row],as_of=NOW)
    assert v['api_state']=='UNKNOWN' and v['listing_permission_verified'] is False
    assert 'LISTING_CREATION_ACCESSIBLE' in v['seller_central_states']
    assert 'BRAND_VALIDATION_BLOCKED' in v['seller_central_states']
    assert decide(template('B0FM84W641'),v,as_of=NOW)['decision']=='NEEDS_SELLER_VERIFICATION'
    with pytest.raises(ValueError):normalize(sc(method='MANUAL_COPY_LISTING'))


def test_copy_listing_alone_is_not_offer_or_fba():
    v=verify(ASIN,[api()],[sc(['LISTING_CREATION_ACCESSIBLE'],method='MANUAL_COPY_LISTING')],as_of=NOW)
    assert not v['listing_permission_verified'] and v['fba_state']=='FBA_UNKNOWN'


@pytest.mark.parametrize('negative',['APPROVAL_REQUIRED','NOT_ELIGIBLE','OTHER_RESTRICTED'])
def test_api_conflicts_require_manual_review(negative):
    v=verify(ASIN,[api(),api(negative)],positive_sc(),as_of=NOW)
    assert v['conflict_requires_review'] is True and v['api_state']=='UNKNOWN'
    assert decide(opportunity(),v,as_of=NOW)['decision']=='NEEDS_SELLER_VERIFICATION'


@pytest.mark.parametrize('state',['APPROVAL_APPLICATION_REQUIRED','BRAND_VALIDATION_BLOCKED','NEW_LISTINGS_NOT_ACCEPTED'])
def test_conflicting_seller_central_evidence_never_ready(state):
    v=verify(ASIN,[api()],positive_sc()+[sc([state],method='MANUAL_APPROVAL_SCREEN')],as_of=NOW)
    assert v['conflict_requires_review'] is True
    assert decide(opportunity(),v,as_of=NOW)['decision']=='NEEDS_SELLER_VERIFICATION'


def test_fba_conflict_is_separate():
    evidence=positive_sc()+[sc(['UNVERIFIED'],'FBA_INELIGIBLE',method='MANUAL_FBA_ELIGIBILITY')]
    v=verify(ASIN,[api()],evidence,as_of=NOW)
    assert v['listing_permission_verified'] and v['fba_conflict_requires_review']
    assert decide(opportunity(),v,as_of=NOW)['decision']=='NEEDS_FBA_VERIFICATION'


@pytest.mark.parametrize('field,value',[('condition','used'),('marketplace','OTHER'),('operation_status','failed'),('observed_at',None)])
def test_missing_wrong_scope_or_failed_api_unknown(field,value):
    evidence=api();evidence[field]=value
    v=verify(ASIN,[evidence],positive_sc(),as_of=NOW)
    assert not v['listing_permission_verified'] and v['api_state']=='UNKNOWN'


def test_stale_positive_and_expired_aggregate_cannot_be_reused():
    v=permitted()
    assert decide(opportunity(),v,as_of=NOW+timedelta(hours=25))['decision']=='NEEDS_SELLER_VERIFICATION'
    old=api();old['observed_at']=(NOW-timedelta(hours=23)).isoformat()
    v=verify(ASIN,[old],positive_sc(),as_of=NOW)
    assert v['listing_permission_verified']
    assert decide(opportunity(),v,as_of=NOW+timedelta(hours=2))['decision']=='NEEDS_SELLER_VERIFICATION'


def test_all_nine_decision_states_and_no_purchase():
    rows=[]
    def check(record,v,expected):
        d=decide(record,v,as_of=NOW);rows.append(d['decision'])
        assert d['decision']==expected and d['purchase_authorized'] is False and d['listing_submission_authorized'] is False
    check(opportunity(),verify(ASIN,[api('NOT_ELIGIBLE')],[],as_of=NOW),'REJECTED_RESTRICTION')
    check(opportunity(),verify(ASIN,[api('APPROVAL_REQUIRED')],[],as_of=NOW),'REQUIRES_APPROVAL')
    check(opportunity(),verify(ASIN,[],[],as_of=NOW),'NEEDS_SELLER_VERIFICATION')
    check(opportunity(),verify(ASIN,[api()],[sc()],as_of=NOW),'NEEDS_FBA_VERIFICATION')
    check(template(ASIN),permitted(),'NEEDS_RETAILER_MATCH')
    row=opportunity();row['retailer_product']['pack_quantity']=3
    check(row,permitted(),'REJECTED_IDENTITY_MISMATCH')
    row=opportunity();row['costs']['fba_fee']['value']=None
    check(row,permitted(),'NEEDS_FEE_DATA')
    row=opportunity();row['costs']['amazon_sale_price']['value']='20'
    for key in ('referral_fee','fba_fee'):row['costs'][key]['sale_price_basis']='20'
    check(row,permitted(),'REJECTED_PROFITABILITY')
    check(opportunity(),permitted(),'READY_FOR_PURCHASE_REVIEW')
    assert set(rows)==set(DECISIONS)


@pytest.mark.parametrize('field,value',[('gtin','000123456784'),('brand','Other'),('model','Other'),('size','large'),('pack_quantity',3),('variation','red')])
def test_exact_identity_mismatches_rejected(field,value):
    row=opportunity();row['retailer_product'][field]=value
    assert decide(row,permitted(),as_of=NOW)['decision']=='REJECTED_IDENTITY_MISMATCH'


def test_missing_gtin_does_not_fall_back_to_model():
    row=opportunity();row['retailer_product']['gtin']=None
    assert not exact_match(row,as_of=NOW)['exact']
    assert decide(row,permitted(),as_of=NOW)['decision']=='NEEDS_RETAILER_MATCH'


def test_profit_math_cost_basis_and_budget_no_double_counting():
    result=economics(opportunity(),as_of=NOW)
    assert result['net_profit']=='12.00' and result['total_invested_cost_per_unit']=='17.5'
    assert result['estimated_inventory_investment']=='350.0' and result['passes'] is True
    from decimal import Decimal
    assert Decimal(result['roi_percent'])==Decimal('12')/Decimal('17.5')*100
    row=opportunity();row['inventory_units']=29
    assert decide(row,permitted(),as_of=NOW)['decision']=='REJECTED_PROFITABILITY'


@pytest.mark.parametrize('cost',COSTS)
def test_every_missing_cost_blocks_profitability(cost):
    row=opportunity();row['costs'][cost]['value']=None
    out=decide(row,permitted(),as_of=NOW)
    assert out['decision']=='NEEDS_FEE_DATA' and out['economics']['net_profit'] is None


@pytest.mark.parametrize('change',[dict(currency='EUR'),dict(value='NaN'),dict(value='-1'),dict(source_reference=None),dict(source_reference=True),dict(observed_at=None)])
def test_invalid_fee_or_missing_provenance_blocks(change):
    row=opportunity();row['costs']['fba_fee'].update(change)
    assert decide(row,permitted(),as_of=NOW)['decision']=='NEEDS_FEE_DATA'


def test_manual_store_append_only_and_brand_signal_not_universal(store):
    data,_=m66.read_json(m66.SC_SEEDS)
    assert store.append_verifications(data['observations'])==dict(added=7,duplicates=0)
    assert store.append_verifications(data['observations'])==dict(added=0,duplicates=7)
    signal=next(r for r in data['observations'] if r['brand']=='Duck')
    assert signal['asin'] is None
    assert verify(ASIN,[],[signal],as_of=NOW)['seller_central_states']==['UNVERIFIED']
    with pytest.raises(sqlite3.IntegrityError):store.db.execute('DELETE FROM m66_verifications')
    with pytest.raises(ValueError):store.append_verifications([dict(sc(),seller_id='PRIVATESELLER')])


def catalog_row(i,brand=None,category=None):
    return dict(asin=f'B{i:09d}',brand=brand or f'Brand{i//2}',category=category or ['kitchen','office','household','home_improvement'][i%4],
        marketplace=US,observed_at=DATE,provenance='synthetic:test',product_type='TYPE'+str(i%3),
        catalog=dict(asin=f'B{i:09d}',title='Synthetic example',model='M'+str(i),package_quantity=1,
            variation='blue',identifiers=[dict(identifier_type='UPC',value='012345678905')]),summary_fields=dict(size='small'))


def setup_pool(tmp_path):
    history=tmp_path/'history';history.mkdir()
    protected=history/'m63-eligibility-authorization-01.json'
    protected.write_text(json.dumps(dict(asins=[f'B{i:09d}' for i in range(20)])))
    source=tmp_path/'catalog.json';source.write_text(json.dumps([catalog_row(i) for i in range(60)]))
    return history,source,protected


def test_cohort_diversity_determinism_and_no_replay(tmp_path,store):
    history,source,protected=setup_pool(tmp_path)
    before=sha256(protected)
    m,r,a=discovery.build([source],store,history,as_of=NOW)
    assert len(m['restrictions_proposal']['asins'])==20
    assert not set(m['restrictions_proposal']['asins'])&{f'B{i:09d}' for i in range(20)}
    selected=[v for v in r['rows'] if v['selected']]
    assert max(Counter(v['brand'] for v in selected).values())<=2
    assert len({v['category'] for v in selected})==4
    assert discovery.build([source],store,history,as_of=NOW)==(m,r,a)
    assert sha256(protected)==before and not store.excluded()


def test_brand_approval_pattern_penalty_not_permanent_exclusion(tmp_path,store):
    history,source,_=setup_pool(tmp_path)
    signal=sc(['APPROVAL_APPLICATION_REQUIRED'],asin=None,method='USER_REPORTED_OBSERVATION');signal['brand']='Brand10'
    store.append_verifications([signal])
    _,r,_=discovery.build([source],store,history,as_of=NOW)
    row=next(v for v in r['rows'] if v['brand']=='Brand10')
    assert row['score_components']['observed_approval_pattern']==-8 and not row['exclusion_reasons']
    assert row['eligibility']=='UNKNOWN'


def test_manifest_integrity_sources_authorization_and_immutable_results(tmp_path,store):
    history,source,_=setup_pool(tmp_path)
    out=tmp_path/'out';summary=m66.prepare([source],store,history,out,as_of=NOW)
    path=out/'M66_review_manifest.json';digest=summary['manifest_sha256']
    m=discovery.validate(path,digest,[source],store,history)
    with pytest.raises(ValueError):discovery.reserve_future(path,digest,[source],store,history,None,execute=True)
    inner=m['restrictions_proposal'];now=datetime.now(timezone.utc)
    auth=dict(approved=True,manifest_sha256=digest,asins=inner['asins'],marketplace_id=US,condition=CONDITION,
              budget=inner['budget'],review_reference='manual:synthetic',reviewed_at=(now-timedelta(minutes=1)).isoformat(),expires_at=(now+timedelta(hours=1)).isoformat())
    with pytest.raises(ValueError):discovery.reserve_future(path,digest,[source],store,history,auth,execute=False)
    discovery.reserve_future(path,digest,[source],store,history,auth,execute=True)
    m65_batch.consume_attempt(store,digest,'authentication')
    asin=inner['asins'][0];m65_batch.consume_attempt(store,digest,'restrictions',asin)
    discovery.record_result(store,digest,asin,'SUCCEEDED','UNKNOWN','a'*64,DATE)
    with pytest.raises(sqlite3.IntegrityError):discovery.record_result(store,digest,asin,'SUCCEEDED','UNKNOWN','a'*64,DATE)
    with pytest.raises(ValueError):m65_batch.consume_attempt(store,digest,'restrictions',inner['asins'][1])
    with pytest.raises(sqlite3.IntegrityError):store.db.execute('DELETE FROM m66_results')
    with pytest.raises(ValueError):discovery.reserve_future(path,digest,[source],store,history,auth,execute=True)


def test_manifest_tampering_and_budget_expansion_rejected(tmp_path,store):
    history,source,_=setup_pool(tmp_path)
    with pytest.raises(ValueError):discovery.build([source],store,history,as_of=NOW,maximum=21)
    out=tmp_path/'out';s=m66.prepare([source],store,history,out,as_of=NOW)
    path=out/'M66_review_manifest.json';m=json.loads(path.read_text())
    m['restrictions_proposal']['budget']['retries']=1;path.write_text(json.dumps(m))
    with pytest.raises(ValueError):discovery.validate(path,sha256(path),[source],store,history)


def test_shared_request_budget_once_only_and_no_followon(tmp_path,store):
    history,source,_=setup_pool(tmp_path)
    out=tmp_path/'out';s=m66.prepare([source],store,history,out,as_of=NOW,maximum=2)
    path=out/'M66_review_manifest.json';m=discovery.validate(path,s['manifest_sha256'],[source],store,history)
    inner=m['restrictions_proposal'];digest=s['manifest_sha256'];now=datetime.now(timezone.utc)
    auth=dict(approved=True,manifest_sha256=digest,asins=inner['asins'],marketplace_id=US,condition=CONDITION,budget=inner['budget'],
        review_reference='manual:test',reviewed_at=(now-timedelta(minutes=1)).isoformat(),expires_at=(now+timedelta(hours=1)).isoformat())
    discovery.reserve_future(path,digest,[source],store,history,auth,execute=True)
    m65_batch.consume_attempt(store,digest,'authentication')
    for asin in inner['asins']:m65_batch.consume_attempt(store,digest,'restrictions',asin)
    with pytest.raises(ValueError):m65_batch.consume_attempt(store,digest,'authentication')
    with pytest.raises((ValueError,sqlite3.IntegrityError)):m65_batch.consume_attempt(store,digest,'restrictions',inner['asins'][0])
    with pytest.raises(ValueError):m65_batch.consume_attempt(store,digest,'pricing',inner['asins'][0])
    assert store.db.execute('SELECT count(*) FROM request_attempts').fetchone()[0]==3


def test_no_private_response_messages_in_outputs(tmp_path,store):
    path=tmp_path/'report.json'
    path.write_text(json.dumps(dict(is_mock=False,finished_at=DATE,seller_id='PRIVATESELLER',access_token='PRIVATETOKEN',
        rows=[dict(asin=ASIN,marketplace_id=US,condition=CONDITION,restrictions=dict(status='succeeded',response=dict(restrictions=[
            dict(marketplaceId=US,reasons=[dict(reasonCode='APPROVAL_REQUIRED',message='PRIVATESELLER PRIVATETOKEN')])])))])))
    store.append(import_report(path))
    assert 'PRIVATESELLER' not in canonical(store.events()) and 'PRIVATETOKEN' not in canonical(store.events())


def test_cli_has_no_live_or_submission_actions(tmp_path):
    for action in ('run','execute','buy','copy-listing','apply','upload'):
        result=subprocess.run([sys.executable,'-m','app.m66',action,'--store',str(tmp_path/'state.sqlite3')],capture_output=True)
        assert result.returncode!=0
    assert not (tmp_path/'state.sqlite3').exists()


@pytest.mark.parametrize('scope,value',[('asin','B000000002'),('condition','used'),('fulfillment','MFN'),('sale_price_basis','99')])
def test_fee_quotes_must_match_asin_condition_fba_and_sale_price(scope,value):
    row=opportunity();row['costs']['fba_fee'][scope]=value
    assert decide(row,permitted(),as_of=NOW)['decision']=='NEEDS_FEE_DATA'


def test_manual_product_category_restrictions_and_fba_negative():
    event=sc(['UNVERIFIED'],method='MANUAL_APPROVAL_SCREEN');event['restriction_codes']=['CATEGORY_RESTRICTED']
    v=verify(ASIN,[],[event],as_of=NOW)
    assert decide(template(ASIN),v,as_of=NOW)['decision']=='REJECTED_RESTRICTION'
    fba=[sc(),sc(['UNVERIFIED'],'FBA_INELIGIBLE',method='MANUAL_FBA_ELIGIBILITY')]
    assert decide(opportunity(),verify(ASIN,[api()],fba,as_of=NOW),as_of=NOW)['decision']=='REJECTED_RESTRICTION'


def test_combined_sources_input_order_independent(tmp_path):
    left=tmp_path/'left.json';right=tmp_path/'right.json'
    left.write_text(json.dumps([catalog_row(1),catalog_row(2)]))
    right.write_text(json.dumps([catalog_row(1),catalog_row(3)]))
    assert discovery.combined([left,right])==discovery.combined([right,left])


def test_csv_private_context_is_redacted(tmp_path):
    import csv
    source=tmp_path/'candidate.csv'
    row=dict(asin=ASIN,brand='PRIVATESELLER',title='PRIVATESELLER item',seller_id='PRIVATESELLER',
        amazon_url='https://www.amazon.com/dp/'+ASIN,observed_at=DATE,discovery_source='synthetic')
    with source.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(row));writer.writeheader();writer.writerow(row)
    pool,_=discovery.combined([source])
    assert 'PRIVATESELLER' not in canonical(pool)


def test_export_reimport_of_projected_m64_facts_is_idempotent(store):
    from app.m65 import manual_import,SEEDS
    manual_import(SEEDS,store)
    rows=verification_rows(store)
    revision=store.revision()
    assert len(rows)==4
    assert store.append_verifications(rows)==dict(added=0,duplicates=4)
    assert store.revision()==revision and len(verification_rows(store))==4


def test_explicit_simulated_opportunity_never_ready():
    row=opportunity();row['is_synthetic']=True
    assert decide(row,permitted(),as_of=NOW)['decision']=='NEEDS_SELLER_VERIFICATION'


def test_invoice_heavy_brand_can_be_reviewed_without_permanent_brand_ban(tmp_path,store):
    history,source,_=setup_pool(tmp_path)
    invoice=sc(['APPROVAL_APPLICATION_REQUIRED'],asin='B999999999',method='USER_REPORTED_OBSERVATION')
    invoice.update(brand='Brand10',invoice_required=True,minimum_invoiced_units=100)
    store.append_verifications([invoice])
    _,ranking,_=discovery.build([source],store,history,as_of=NOW,minimum_score=-100)
    candidate=next(r for r in ranking['rows'] if r['brand']=='Brand10')
    assert candidate['score_components']['additional_invoice_pathway']==-35
    assert not candidate['exclusion_reasons'] and candidate['eligibility']=='UNKNOWN'
    assert 'B000000020' not in store.excluded()


def test_missing_original_m63_proof_cannot_authorize_replay(tmp_path,store):
    history,source,protected=setup_pool(tmp_path)
    protected.unlink()
    with pytest.raises((ValueError,FileNotFoundError)):
        discovery.build([source],store,history,as_of=NOW)
