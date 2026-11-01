"""Official contract edge cases and descriptive experimental measurements."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
import socket

import pytest

from app import m66,m66_experiments as experiments
from app.m65_intelligence import classify,US,CONDITION
from app.m66_verification import verify,normalize,VerificationStore
from app.m66_opportunity import template
from app.observations import fingerprint

DATE='2026-01-02T12:00:00+00:00'
NOW=datetime.fromisoformat(DATE)
ASIN='B000000001'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args,**kwargs):pytest.fail('Network/credentials forbidden')
    monkeypatch.setattr(socket,'create_connection',blocked)
    monkeypatch.setattr(socket,'getaddrinfo',blocked)
    from app import amazon_pilot
    monkeypatch.setattr(amazon_pilot,'load_credentials',blocked)
    monkeypatch.setattr(amazon_pilot,'_request_json',blocked)


@pytest.mark.parametrize('raw',[dict(restrictions=[]),dict(restrictions=[{}]),dict(restrictions=[],errors=[])])
def test_documented_empty_variants_only_no_reported_restrictions(raw):
    result=classify(dict(status='succeeded',http_status=200,response=raw),US,CONDITION,DATE)
    assert result==('SUCCEEDED','NO_REPORTED_RESTRICTIONS',[])
    v=verify(ASIN,[dict(asin=ASIN,marketplace=US,condition=CONDITION,operation_status=result[0],
        eligibility=result[1],observed_at=DATE,source_reference='sha256:'+'a'*64+':row:0')],[],as_of=NOW)
    assert v['api_state']=='NO_REPORTED_RESTRICTIONS' and v['listing_review_gate_complete'] is False
    assert v['selling_authorization_confirmed'] is False and v['fba_state']=='FBA_UNKNOWN'
    assert v['offer_submission_status']=='NOT_SUBMITTED'


@pytest.mark.parametrize('raw',[{},dict(restrictions=None),dict(restrictions={}),dict(restrictions=[None]),
    dict(restrictions=[{},{}]),dict(restrictions=[dict(reasons=[])]),
    dict(restrictions=[{},dict(marketplaceId=US,reasons=[])]),dict(payload=dict(restrictions=[])),
    dict(restrictions=[],errors=[dict(code='ERROR')])])
def test_ambiguous_shapes_not_promoted(raw):
    assert classify(dict(status='succeeded',response=raw),US,CONDITION,DATE)[1]=='UNKNOWN'


@pytest.mark.parametrize('changes',[dict(status='failed'),dict(http_status=403),dict(http_status=429)])
def test_empty_placeholder_on_failed_http_is_unknown(changes):
    stage=dict(status='succeeded',response=dict(restrictions=[{}]));stage.update(changes)
    assert classify(stage,US,CONDITION,DATE)[1]=='UNKNOWN'


def test_placeholder_needs_explicit_scope_and_observation():
    stage=dict(status='succeeded',response=dict(restrictions=[{}]))
    assert classify(stage,'OTHER',CONDITION,DATE)[1]=='UNKNOWN'
    assert classify(stage,US,'used',DATE)[1]=='UNKNOWN'
    assert classify(stage,US,CONDITION,None)[1]=='UNKNOWN'


@pytest.mark.parametrize('row',[dict(marketplaceId=US),dict(marketplaceId=US,reasons=[]),dict(marketplaceId=US,conditionType=CONDITION,reasons=[])])
def test_real_restriction_without_reasons_still_restricted(row):
    assert classify(dict(status='succeeded',response=dict(restrictions=[row])),US,CONDITION,DATE)[1]=='OTHER_RESTRICTED'


def test_inbound_program_and_offer_only_contract():
    data,_=m66.read_json(m66.SC_SEEDS);row=deepcopy(data['observations'][0])
    row.update(verification_method='MANUAL_FBA_ELIGIBILITY',seller_central_states=['UNVERIFIED'],fba_state='FBA_ELIGIBLE',observed_at=DATE)
    with pytest.raises(ValueError):normalize(row)
    row['fba_program']='COMMINGLING'
    with pytest.raises(ValueError):normalize(row)
    row['fba_program']='INBOUND'
    v=verify(row['asin'],[],[normalize(row)],as_of=NOW)
    assert v['fba_state']=='FBA_ELIGIBLE' and v['api_state']=='UNKNOWN'
    assert v['listing_review_gate_complete'] is False and v['selling_authorization_confirmed'] is False
    t=template(ASIN)
    assert t['intended_listing_workflow']=='EXISTING_ASIN_OFFER_ONLY'
    assert t['listing_requirements']=='LISTING_OFFER_ONLY' and t['product_type']=='PRODUCT'
    assert t['create_new_asin_authorized'] is False and t['offer_submission_authorized'] is False


def fixture(tmp_path):
    store=VerificationStore(tmp_path/'private/store.sqlite3')
    ranking=dict(rows=[dict(asin=f'B{i:09d}',brand='Brand'+str(i%4),category='Cat'+str(i%2)) for i in range(20)])
    m=dict(mode='M66_ELIGIBILITY_REVIEW_ONLY',evaluated_at=DATE,restrictions_proposal=dict(asins=[r['asin'] for r in ranking['rows']],
        marketplace_id=US,condition=CONDITION,ranking_sha256=fingerprint(ranking)))
    return store,ranking,m


def event(asin,state,operation='SUCCEEDED',date=DATE):
    return dict(kind='eligibility',asin=asin,marketplace=US,condition=CONDITION,observed_at=date,
        operation_status=operation,eligibility=state,reason_codes=[],brand=None,category=None,
        brand_approval_requirement='UNKNOWN',fba_eligibility=None,purchase_authorized=False,
        source_reference='sha256:'+'a'*64+':row:'+asin[-1],source_sha256='a'*64)


def test_20_asin_experiment_no_checks_has_no_success_fraction(tmp_path):
    store,r,m=fixture(tmp_path)
    try:
        result=experiments.measure(m,r,store,'b'*64)
        assert result['overall']['selected']==20 and result['overall']['checked']==0
        assert result['overall']['not_checked']==20 and result['overall']['observed_no_restrictions_fraction'] is None
        assert sum(v['selected'] for v in result['by_brand'])==20
        assert sum(v['selected'] for v in result['by_category'])==20
        assert result['additional_live_requests']==0
    finally:store.close()


def test_measured_outcomes_by_brand_category_and_failures(tmp_path):
    store,r,m=fixture(tmp_path)
    try:
        store.append([event('B000000000','NO_REPORTED_RESTRICTIONS'),event('B000000001','APPROVAL_REQUIRED'),
                      event('B000000002','NOT_ELIGIBLE'),event('B000000003','UNKNOWN','FAILED')])
        result=experiments.measure(m,r,store,'b'*64)
        assert result['overall']['checked']==4 and result['overall']['not_checked']==16
        assert result['overall']['operation_succeeded']==3 and result['overall']['failed_or_uncertain']==1
        assert result['overall']['NO_REPORTED_RESTRICTIONS']==1 and result['overall']['UNKNOWN']==1
        assert result['overall']['observed_no_restrictions_fraction']==0.25
        assert sum(v['checked'] for v in result['by_brand'])==4
        assert sum(v['checked'] for v in result['by_category'])==4
        assert all(v['selling_authorization_confirmed'] is False for v in result['rows'])
    finally:store.close()


def test_experiment_conflicts_and_pre_cohort_observations_not_successes(tmp_path):
    store,r,m=fixture(tmp_path)
    try:
        a=event('B000000000','NO_REPORTED_RESTRICTIONS');b=event('B000000000','APPROVAL_REQUIRED')
        b['source_reference']='sha256:'+'c'*64+':row:0';b['source_sha256']='c'*64
        store.append([a,b,event('B000000001','NO_REPORTED_RESTRICTIONS',date='2026-01-01T12:00:00+00:00')])
        result=experiments.measure(m,r,store,'b'*64)
        assert result['overall']['checked']==1 and result['overall']['UNKNOWN']==1
        assert result['overall']['conflicting_evidence']==1 and result['overall']['NO_REPORTED_RESTRICTIONS']==0
        bad=deepcopy(r);bad['rows'][0]['brand']='Other'
        with pytest.raises(ValueError):experiments.measure(m,bad,store,'b'*64)
    finally:store.close()
