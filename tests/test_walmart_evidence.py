"""Synthetic saved evidence only; no actual product observations."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.walmart_evidence import normalize, preview, execute_live, main
from app.product_analysis import comparison
from app.evidence_io import digest
from test_amazon_evaluation import NOW


def batch():
    return json.loads(Path('sample_data/m87_synthetic_batch.json').read_text())


def test_six_format_idempotent_financial_integration():
    source = batch(); original = deepcopy(source)
    a = normalize(source)
    assert a == normalize(source) and source == original
    report = comparison(a, NOW)
    assert len(report['records']) == 6
    for r in report['records']:
        assert r['financial_assessment'] == 'PROMISING'
        assert r['selling_eligibility'] == 'UNKNOWN'
        assert r['financials']['FBA']['base']['net_profit'] == '14.50'
        assert r['financials']['FBM']['base']['net_profit'] == '12.50'
        assert not r['purchase_authorized']


@pytest.mark.parametrize('change', ['duplicate','missing','count','basis','id'])
def test_invalid_batch(change):
    b=batch()
    if change=='duplicate': b['observations'][1]['source_candidate_id']=b['observations'][0]['source_candidate_id']
    if change=='missing': del b['observations'][0]['source_candidate_id']
    if change=='count': b['observations'].pop()
    if change=='basis': b['other_cost_basis']='includes_shipping'
    if change=='id': b['batch_id']='arbitrary'
    with pytest.raises(ValueError): normalize(b)


@pytest.mark.parametrize('change', ['conflict','quantity','variation','stale','fees','unverified'])
def test_incomplete_evidence(change):
    b=batch(); r=b['observations'][0]
    if change=='conflict': r['conflicting_observations']=[{'price':'99'}]
    if change=='quantity': r['walmart_product']['pack_quantity']=2
    if change=='variation': r['walmart_product']['variation']='red'
    if change=='stale': r['acquisition']['purchase']['observed_at']='2020-01-01T00:00:00+00:00'
    if change=='unverified': r['amazon']['product']['verified']=False
    if change=='fees':
        for m in r['amazon']['financials'].values():
            for s in m.values(): s.pop('referral_fee')
    result=comparison(normalize(b),NOW)
    row=next(v for v in result['records'] if v['candidate_id']==r['source_candidate_id'])
    assert row['financial_assessment']=='INSUFFICIENT_DATA'


def test_unsupported_demand_and_preview_gate():
    b=batch(); b['observations'][0]['amazon']['market']['monthly_sales']['basis']='rank_estimate'
    m=normalize(b); p=preview(m)
    assert p['maximum_requests']==49
    assert all(r.get('query',{}).get('ItemCondition','New')=='New' for r in p['requests'])
    assert p['approval_required'] and not p['live_executor_available']
    with pytest.raises(PermissionError): execute_live(p, approval=True)
    r=next(r for r in comparison(m,NOW)['records'] if r['candidate_id']=='SYNTHETIC:1')
    assert r['market_assessment']=='INSUFFICIENT_DATA' and r['financial_assessment']=='PROMISING'


def test_private_reports_preserve_source(tmp_path, monkeypatch):
    source=tmp_path/'source'/'batch.json';source.parent.mkdir();source.write_text(json.dumps(batch()))
    before=source.read_bytes();sha=digest(source);out=tmp_path/'report'
    monkeypatch.setattr('sys.argv',['m87','--input',str(source),'--sha256',sha,'--output',str(out),'--as-of',NOW.isoformat()])
    main()
    assert source.read_bytes()==before
    assert (out/'comparison.xlsx').stat().st_mode & 0o777==0o600
    assert json.loads((out/'comparison.json').read_text())['purchase_authorized'] is False
    with pytest.raises(ValueError): main()


def test_saved_agent_exports_reuse_validation_and_preserve_original_rows():
    from test_sheets_intake import fixture
    from app.walmart_evidence import agent_export
    rows=[]
    for i in range(6):
        row,_=fixture(); row['record_id']=f'original:{i}'
        row['walmart_item_id']=str(200000+i)
        row['product_url']='https://www.walmart.com/ip/'+row['walmart_item_id']
        row['raw_record_json']=json.dumps({k:v for k,v in row.items() if k!='raw_record_json'})
        rows.append(row)
    saved=dict(schema='walmart_agent_saved_export_v1',rows=rows)
    converted=agent_export(saved)
    assert converted['batch_kind']=='NEW_PILOT'
    assert converted['observations'][0]['original_agent_row']==rows[0]
    m=normalize(converted)
    assert m['candidates'][0]['candidate_id']=='original:0'
    assert m['candidates'][0]['identity']['retailer_product']['gtin']=='UNKNOWN'
    assert all(r['financial_assessment']=='INSUFFICIENT_DATA' for r in comparison(m,NOW)['records'])
    rows[0]['item_price_usd']='99'
    with pytest.raises(ValueError): agent_export(saved)


def test_acquisition_conflict_and_shipping_once():
    b=batch()
    for mode in b['observations'][0]['amazon']['financials'].values():
        for scenario in mode.values(): scenario['purchase']={'value':'999'}
    m=normalize(b)
    assert m['candidates'][0]['input_conflicts']
    b=batch();b['observations'][0]['acquisition']['retailer_shipping']['value']='2'
    r=next(r for r in comparison(normalize(b),NOW)['records'] if r['candidate_id']=='SYNTHETIC:1')
    assert r['financials']['FBA']['base']['net_profit']=='12.50'


def test_network_is_forbidden_in_offline_boundary():
    import socket
    from app.evidence_io import offline
    with offline():
        with pytest.raises(PermissionError): socket.socket()


def test_duplicate_item_and_missing_prices_preview():
    b=batch();b['observations'][1]['walmart_product']['walmart_item_id']=b['observations'][0]['walmart_product']['walmart_item_id']
    with pytest.raises(ValueError): normalize(b)
    b=batch();b['observations'][0].pop('amazon')
    p=preview(normalize(b))
    assert p['unresolved']==['SYNTHETIC:1'] and p['maximum_requests']==41
