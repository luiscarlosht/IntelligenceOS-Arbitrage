"""M93 offline integration and synthetic gate regressions."""
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import socket

from openpyxl import load_workbook
import pytest

from app.amazon_evaluation import COSTS
from app.m93 import build, run, screen
from test_product_analysis import candidate
from test_amazon_evaluation import NOW


def seller_record():
    record = candidate()
    record['eligibility']['status'] = 'ELIGIBLE'
    record['seller_evidence'] = {}
    for key, value in dict(listing_new='ELIGIBLE', fba='ELIGIBLE', approval_required=False, restrictions=[]).items():
        record['seller_evidence'][key] = dict(value=value, asin=record['asin'], condition='New',
            marketplace='ATVPDKIKX0DER', evidence_type='SELLER_ACCOUNT', seller_scope_reference='SYNTHETIC scope',
            observed_at=NOW.isoformat(), source='SYNTHETIC', source_reference='SYNTHETIC', verified=True, confidence='HIGH')
    return record


@pytest.mark.parametrize('key', COSTS + ('retailer_shipping', 'selling_price'))
def test_missing_mandatory_cost_blocks(key):
    record = seller_record()
    del record['financials']['FBA']['base'][key]
    result = screen(record, NOW)
    assert result['outcome'] == 'INSUFFICIENT_EVIDENCE'
    assert result['analysis']['financials']['FBA']['base']['net_profit'] == 'UNKNOWN'


@pytest.mark.parametrize('key,value', [('listing_new','INELIGIBLE'), ('fba','INELIGIBLE'),
                                      ('approval_required',True), ('restrictions',['HAZMAT'])])
def test_seller_restrictions_block_even_stale(key, value):
    record = seller_record()
    record['seller_evidence'][key].update(value=value, observed_at=(NOW-timedelta(days=2)).isoformat())
    assert screen(record, NOW)['outcome'] == 'INELIGIBLE'


@pytest.mark.parametrize('change', ['catalog', 'wrong_asin', 'stale', 'wrong_condition', 'no_scope'])
def test_no_inferred_seller_permission(change):
    record = seller_record()
    item = record['seller_evidence']['listing_new']
    if change == 'catalog': item['evidence_type'] = 'CATALOG'
    if change == 'wrong_asin': item['asin'] = 'B000000000'
    if change == 'stale': item['observed_at'] = (NOW-timedelta(days=2)).isoformat()
    if change == 'wrong_condition': item['condition'] = 'Used'
    if change == 'no_scope': del item['seller_scope_reference']
    assert screen(record, NOW)['outcome'] == 'ELIGIBILITY_UNKNOWN'


def test_math_shipping_identity_and_synthetic_gate():
    record = seller_record()
    original = deepcopy(record)
    record['financials']['FBA']['base']['retailer_shipping']['value'] = '2'
    result = screen(record, NOW)
    base = result['analysis']['financials']['FBA']['base']
    assert Decimal(base['net_profit']) == Decimal('12.50')
    assert Decimal(base['roi_percent']) == Decimal('12.5')/15*100
    assert result['outcome'] != 'VERIFIED_PROFITABLE'  # synthetic is never verified
    original['identity']['retailer_product']['pack_quantity'] = 2
    result = screen(original, NOW)
    assert result['outcome'] == 'INSUFFICIENT_EVIDENCE'
    assert result['analysis']['match_confidence'] == 'UNRESOLVED'


def test_offline_report_reproducibility_and_excel(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Network forbidden')
    monkeypatch.setattr(socket, 'socket', forbidden)
    now = datetime.fromisoformat('2026-11-06T18:00:00+00:00')
    report = run(tmp_path/'one', now)
    assert report == run(tmp_path/'two', now)
    assert (tmp_path/'one/amazon-candidates.json').read_bytes() == (tmp_path/'two/amazon-candidates.json').read_bytes()
    assert report['retained_distinct_asins'] == 56
    assert report['selected_research_leads'] == 30
    assert report['defensible_opportunities'] == report['verified_profitable'] == 0
    assert report['outcome_counts'] == {'ELIGIBILITY_UNKNOWN': 30}
    assert len(set(r['asin'] for r in report['records'])) == 30
    assert all(r['net_profit'] == r['roi_percent'] == 'UNKNOWN' for r in report['records'])
    assert all(r['identity']['observed_at'] for r in report['records'])
    first = load_workbook(tmp_path/'one/amazon-candidates.xlsx')
    second = load_workbook(tmp_path/'two/amazon-candidates.xlsx')
    assert [[list(r) for r in s.values] for s in first] == [[list(r) for r in s.values] for s in second]
    assert not any(c.data_type == 'f' for s in first for row in s for c in row)
    assert first['ELIGIBILITY_UNKNOWN'].max_row == first['RESEARCH_PRIORITY'].max_row == 31
    assert first['VERIFIED_PROFITABLE'].max_row == 1
    with pytest.raises(ValueError): run(tmp_path/'one', now)
    with pytest.raises(ValueError): build(now, 31)
    with pytest.raises(ValueError): build(datetime(2026,11,6))


def test_positive_control_and_profit_thresholds():
    # Synthetic fixture exercises the gate only; never enters retained reports.
    record = seller_record()
    record['is_synthetic'] = False
    assert screen(record, NOW)['outcome'] == 'VERIFIED_PROFITABLE'
    record['financials']['FBA']['conservative']['purchase']['value'] = '30'
    assert screen(record, NOW)['outcome'] == 'INSUFFICIENT_EVIDENCE'


def test_missing_seller_evidence_and_malformed_adverse():
    record = seller_record()
    del record['seller_evidence']
    assert screen(record, NOW)['outcome'] == 'ELIGIBILITY_UNKNOWN'
    record = seller_record()
    record['seller_evidence']['fba'].update(value='INELIGIBLE', observed_at='invalid')
    assert screen(record, NOW)['outcome'] == 'ELIGIBILITY_UNKNOWN'


def test_cannot_combine_different_seller_accounts():
    record = seller_record()
    record['is_synthetic'] = False
    record['seller_evidence']['fba']['seller_scope_reference'] = 'different seller'
    assert screen(record, NOW)['outcome'] == 'ELIGIBILITY_UNKNOWN'
