from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from app.amazon_evaluation import COSTS, MODES, SCENARIOS, evaluate, financial
from app.amazon_evaluation_sheets import HEADERS, TAB, plan, seed, publish, read_evaluations

NOW = datetime(2026, 11, 3, 16, tzinfo=timezone.utc)
STAMP = NOW.isoformat()


def observation(value, **extra):
    return dict(value=value, source='SYNTHETIC TEST ONLY', observed_at=STAMP, **extra)


def complete():
    asin = 'B000YZASYO'
    product = dict(brand='Synthetic', title='Synthetic fixture', gtin='012345678905', model='TEST',
        size='one size', pack_quantity=1, variation='blue', observed_at=STAMP,
        source_reference='SYNTHETIC ONLY', url='https://www.amazon.com/dp/'+asin)
    retailer = dict(product, url='https://www.walmart.com/ip/123')
    record = dict(asin=asin, is_synthetic=True,
        identity=dict(amazon_product=product, retailer_product=retailer),
        eligibility=dict(status='ELIGIBLE',source='SYNTHETIC ONLY',observed_at=STAMP),
        seller_documentation=observation(True),policy_checks=observation(True),
        monthly_sales=observation(50),competing_offers=observation(5),fba_eligible=observation(True),financials={})
    for mode in MODES:
        record['financials'][mode] = {}
        for scenario, price in zip(SCENARIOS, ('36','40','44')):
            inputs = {k:observation('0',currency='USD') for k in COSTS}
            for k, value in dict(purchase='10',sales_tax='1',inbound_shipping='1',preparation='0.5',
                packaging='0.5',storage='0.25',placement='0.25',returns_allowance='1',
                referral_fee=str(Decimal(price)*Decimal('0.15')),
                fulfillment_fee='5' if mode=='FBA' else '7').items():
                inputs[k]['value'] = value
            inputs['selling_price'] = observation(price,currency='USD',asin=asin,condition='New')
            for k in ('referral_fee','fulfillment_fee'):
                inputs[k].update(asin=asin,condition='New',mode=mode,
                                 price_basis=observation(price,currency='USD'))
            record['financials'][mode][scenario] = inputs
    return record


def test_fiskars_blocks_any_profit():
    record = json.loads(Path('sample_data/amazon_evaluation_fiskars.json').read_text())[0]
    assert evaluate(record,NOW)['decision']=='BLOCKED_APPROVAL_REQUIRED'
    record['financials']=complete()['financials']
    result=evaluate(record,NOW)
    assert result['decision']=='BLOCKED_APPROVAL_REQUIRED'
    assert result['buy_candidate_modes']==[]
    assert result['purchase_authorized'] is False


@pytest.mark.parametrize('mode,profit', [('FBA','14.5'),('FBM','12.5')])
def test_decimal_calculation(mode,profit):
    result=financial(complete(),mode,'base',NOW)
    assert result['complete']
    assert Decimal(result['net_profit'])==Decimal(profit)
    assert Decimal(result['invested_cost'])==13
    assert Decimal(result['roi_percent'])==Decimal(profit)/13*100
    assert Decimal(result['net_margin_percent'])==Decimal(profit)/40*100
    assert Decimal(result['break_even_price'])==40-Decimal(profit)


@pytest.mark.parametrize('value', [None,'UNKNOWN','','NaN','Infinity','-1'])
@pytest.mark.parametrize('key', COSTS+('selling_price',))
def test_unknown_or_invalid_never_zero(value,key):
    record=complete()
    record['financials']['FBA']['base'][key]['value']=value
    result=financial(record,'FBA','base',NOW)
    assert not result['complete']
    assert key in result['missing']
    assert result['net_profit']=='UNKNOWN'


@pytest.mark.parametrize('field,value', [('asin','B000000000'),('condition','Used'),('mode','FBM'),('price_basis',{})])
def test_fee_scope(field,value):
    record=complete()
    record['financials']['FBA']['base']['referral_fee'][field]=value
    assert not financial(record,'FBA','base',NOW)['complete']


@pytest.mark.parametrize('status,decision', [('UNKNOWN','BLOCKED_DATA'),('RESTRICTED','REJECTED'),('APPROVAL_REQUIRED','BLOCKED_APPROVAL_REQUIRED')])
def test_eligibility_gate(status,decision):
    record=complete();record['eligibility']['status']=status
    assert evaluate(record,NOW)['decision']==decision


def test_all_gates_and_synthetic_review():
    record=complete()
    assert evaluate(record,NOW)['decision']=='REVIEW'
    record['is_synthetic']=False
    assert evaluate(record,NOW)['decision']=='BUY_CANDIDATE'
    record['identity']['retailer_product']['pack_quantity']=2
    assert evaluate(record,NOW)['decision']=='BLOCKED_IDENTITY'


@pytest.mark.parametrize('key', ['eligibility','policy_checks','seller_documentation','monthly_sales','competing_offers'])
def test_stale_provenance_blocks(key):
    record=complete();record['is_synthetic']=False
    record[key]['observed_at']='2026-01-01T00:00:00+00:00'
    assert evaluate(record,NOW)['decision']=='BLOCKED_DATA'


@pytest.mark.parametrize('key,value', [('monthly_sales',29),('competing_offers',11)])
def test_demand_thresholds(key,value):
    record=complete();record[key]['value']=value
    assert evaluate(record,NOW)['decision']=='REJECTED'


def test_incomplete_fba_can_use_complete_fbm():
    record=complete();record['is_synthetic']=False
    del record['financials']['FBA']['base']['fulfillment_fee']
    assert evaluate(record,NOW)['buy_candidate_modes']==['FBM']
    del record['financials']['FBM']['base']['fulfillment_fee']
    assert evaluate(record,NOW)['decision']=='BLOCKED_DATA'


def test_fba_eligibility_independent():
    record=complete();record['is_synthetic']=False
    record['fba_eligible']['value']=False
    assert evaluate(record,NOW)['buy_candidate_modes']==['FBM']


def test_conservative_failure_review_and_base_failure_rejected():
    record=complete();record['is_synthetic']=False
    for mode in MODES:
        record['financials'][mode]['conservative']['purchase']['value']='30'
    assert evaluate(record,NOW)['decision']=='REVIEW'
    for mode in MODES:
        record['financials'][mode]['base']['purchase']['value']='30'
    assert evaluate(record,NOW)['decision']=='REJECTED'


def metadata():
    return dict(sheets=[dict(properties=dict(title='Historical',sheetId=0))])


def fiskars():
    return json.loads(Path('sample_data/amazon_evaluation_fiskars.json').read_text())[0]


def test_sparse_upsert_preserves_manual_rows_and_other_tabs():
    record=fiskars()
    requests=plan([record],metadata(),[])
    assert len(requests)==5
    sid=requests[0]['addSheet']['properties']['sheetId']
    assert sid!=0
    meta=metadata();meta['sheets'].append(dict(properties=dict(title=TAB,sheetId=sid,
        gridProperties=dict(rowCount=2002,columnCount=24))))
    existing=[HEADERS,seed(record)]
    existing[1][-2]='manual edit'
    assert plan([record],meta,existing)==[]
    with pytest.raises(ValueError):plan([record,record],meta,existing)
    with pytest.raises(ValueError):plan([record],meta,existing+[seed(record)])
    with pytest.raises(ValueError):plan([record],meta,[['wrong']])


def test_literal_cells_and_no_live_write_in_preview():
    record=fiskars();record['observations']['notes']='=IMPORTXML("bad")'
    requests=plan([record],metadata(),[])
    cells=requests[-1]['updateCells']['rows'][0]['values']
    assert cells[-2]['userEnteredValue']==dict(stringValue='=IMPORTXML("bad")')
    class Client:
        def select(self,workbook):self.workbook=workbook
        def metadata(self):return metadata()
        def request(self,*args):raise AssertionError('Preview wrote')
    assert publish(Client(),[record])['mode']=='preview'


class SheetsFixture:
    def __init__(self):
        self.meta=metadata();self.rows=[];self.writes=0
    def select(self,book):
        assert book=='1q9TPwNTka_wzSo_T283LBP7iFpfAorR3_QYB19LKDHA'
    def metadata(self):
        from copy import deepcopy
        return deepcopy(self.meta)
    def request(self,suffix,payload=None):
        from copy import deepcopy
        if payload is None:return dict(values=deepcopy(self.rows))
        assert suffix==':batchUpdate'
        self.writes+=1
        for request in payload['requests']:
            if 'addSheet' in request:
                self.meta['sheets'].append(dict(properties=request['addSheet']['properties']))
            elif 'updateCells' in request:
                w=request['updateCells'];n=w['start']['rowIndex']
                while len(self.rows)<=n:self.rows.append([])
                self.rows[n]=[v['userEnteredValue']['stringValue'] for v in w['rows'][0]['values']]


def test_publish_readback_repeat_and_manual_reader():
    client=SheetsFixture()
    assert publish(client,[fiskars()],True)['existing_evidence_preserved']
    assert read_evaluations(client,NOW)[0]['decision']=='BLOCKED_APPROVAL_REQUIRED'
    client.rows[1][-2]='researcher notes'
    assert publish(client,[fiskars()],True)['existing_evidence_preserved']
    assert client.writes==1
    assert client.rows[1][-2]=='researcher notes'
    client.rows[1][HEADERS.index('eligibility_status')]='ELIGIBLE'
    assert read_evaluations(client,NOW)[0]['decision']=='BLOCKED_DATA'


def test_price_condition_missing_does_not_use_used_price():
    record=complete()
    record['financials']['FBA']['base']['selling_price']['condition']='Used'
    assert not financial(record,'FBA','base',NOW)['complete']


def test_future_and_unattributed_costs_block():
    record=complete()
    record['financials']['FBA']['base']['storage']['observed_at']='2026-11-04T16:00:00+00:00'
    assert not financial(record,'FBA','base',NOW)['complete']
    record=complete();record['financials']['FBA']['base']['storage']['source']='UNKNOWN'
    assert not financial(record,'FBA','base',NOW)['complete']


@pytest.mark.parametrize('key', COSTS+('selling_price',))
def test_unstructured_unknown_cost_is_incomplete(key):
    record=complete();record['financials']['FBA']['base'][key]='UNKNOWN'
    assert not financial(record,'FBA','base',NOW)['complete']


def test_unknown_financial_sections_and_eligibility_block():
    record=complete();record['financials']='UNKNOWN'
    assert evaluate(record,NOW)['decision']=='BLOCKED_DATA'
    record['eligibility']='UNKNOWN'
    assert evaluate(record,NOW)['decision']=='BLOCKED_DATA'


@pytest.mark.parametrize('field', ['brand','model','size','variation','source_reference'])
def test_matching_unknown_identity_is_not_verification(field):
    record=complete();record['is_synthetic']=False
    for side in ('amazon_product','retailer_product'):
        record['identity'][side][field]='UNKNOWN'
    assert evaluate(record,NOW)['decision']=='BLOCKED_IDENTITY'


def test_profit_roi_thresholds_use_unrounded_decimal():
    record=complete();record['is_synthetic']=False
    for mode in MODES:
        for scenario in SCENARIOS:
            inputs=record['financials'][mode][scenario]
            for key in COSTS:inputs[key]['value']='0'
            inputs['purchase']['value']='10'
            inputs['selling_price']['value']='15'
            for key in ('referral_fee','fulfillment_fee'):
                inputs[key]['price_basis']['value']='15'
    assert evaluate(record,NOW)['decision']=='BUY_CANDIDATE'
    for mode in MODES:
        record['financials'][mode]['base']['transaction_cost']['value']='0.00001'
    assert evaluate(record,NOW)['decision']=='REJECTED'


def test_mislabeled_price_scenarios_block():
    record=complete();record['is_synthetic']=False
    for mode in MODES:
        values=record['financials'][mode]
        values['conservative'],values['optimistic']=values['optimistic'],values['conservative']
    assert evaluate(record,NOW)['decision']=='BLOCKED_DATA'
