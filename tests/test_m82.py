from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import pytest
from app.opportunity_engine import evaluate,COSTS,RISKS
from app.opportunity_fixtures import case,NOW


def test_complete_synthetic_economics():
    row=evaluate(*case(),NOW,synthetic=True)
    assert row['status']=='REVIEW_PROPOSAL_ONLY'
    assert row['net_profit']=='12.40' and row['roi_percent']=='124.00'
    assert row['margin_percent']==str(Decimal('12.40')/30*100)
    assert not row['purchase_authorized'] and not row['sourcing_authorized']
    assert row['quantity_proposal']=='UNKNOWN'


@pytest.mark.parametrize('key',COSTS)
def test_missing_cost_never_zero(key):
    a,q,f,r=case();(f if key in COSTS[6:] else q).pop(key)
    row=evaluate(a,q,f,r,NOW,synthetic=True)
    assert row['status']=='EXCLUDED' and row['net_profit']=='UNKNOWN'


@pytest.mark.parametrize('value',['NaN','Infinity','-1',True,None,'UNKNOWN'])
def test_invalid_costs(value):
    a,q,f,r=case();f['fulfillment_fee']=value
    assert evaluate(a,q,f,r,NOW,synthetic=True)['status']=='EXCLUDED'


@pytest.mark.parametrize('key',['gtin','brand','model','quantity','size','variation'])
def test_identity_fail_closed(key):
    a,q,f,r=case();q['identity'][key]='UNKNOWN'
    assert evaluate(a,q,f,r,NOW,synthetic=True)['status']=='EXCLUDED'


@pytest.mark.parametrize('key',RISKS)
def test_risk_and_fba_permission_not_inferred(key):
    a,q,f,r=case();r[key]='UNKNOWN'
    assert evaluate(a,q,f,r,NOW,synthetic=True)['status']=='EXCLUDED'


@pytest.mark.parametrize('mutation',['stale','future','account','fee_price','class','gtin','restriction','variation','review','url'])
def test_receipt_and_scope_failures(mutation):
    a,q,f,r=case()
    if mutation=='stale':q['observed_at']=(NOW-timedelta(days=2)).isoformat()
    if mutation=='future':f['observed_at']=(NOW+timedelta(seconds=1)).isoformat()
    if mutation=='account':f['account_binding_sha256']='f'*64
    if mutation=='fee_price':f['sale_price']='31'
    if mutation=='class':r['evidence_class']='CURRENT_LIVE'
    if mutation=='gtin':a['current_gtins']=[]
    if mutation=='restriction':a['listing_permission']='RESTRICTED'
    if mutation=='variation':q['variation_verified']=False
    if mutation=='review':f['owner_reviewed']=False
    if mutation=='url':q['source_reference']='https://walmart.com.evil.test/ip/x'
    assert evaluate(a,q,f,r,NOW,synthetic=True)['status']=='EXCLUDED'


def test_thresholds_unrounded_and_shipping_in_acquisition():
    a,q,f,r=case();f.update(referral_fee='5',fulfillment_fee='0',storage='0',transaction_cost='0')
    q['purchase_price']='16.666666666667'
    row=evaluate(a,q,f,r,NOW,synthetic=True)
    assert 'BELOW_50_PERCENT_ACQUISITION_ROI' in row['flags']
    q['purchase_price']='10';q['walmart_shipping']='5'
    row=evaluate(a,q,f,r,NOW,synthetic=True)
    assert row['acquisition_cost']=='15' and row['net_profit']=='10'


def test_synthetic_cannot_be_live():
    assert evaluate(*case(),NOW,synthetic=False)['status']=='EXCLUDED'


@pytest.mark.parametrize('field,value',[
    ('availability','UNKNOWN'),('availability','OUT_OF_STOCK'),
    ('product_condition','USED'),('seller','UNKNOWN'),('fulfillment',''),
])
def test_walmart_offer_context_must_be_observed(field,value):
    a,q,f,r=case();q[field]=value
    assert evaluate(a,q,f,r,NOW,synthetic=True)['status']=='EXCLUDED'
