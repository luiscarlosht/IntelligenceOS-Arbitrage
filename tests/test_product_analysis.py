"""Synthetic M86 regression evidence; no live requests or real product claims."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import socket

from openpyxl import load_workbook
import pytest

from app.amazon_evaluation import COSTS, MODES, SCENARIOS, EvaluationPolicy, financial
from app.product_analysis import ResearchPolicy, assess, comparison, main, workbook
from test_analysis_engine import verified
from test_amazon_evaluation import NOW, observation


def candidate():
    record = verified()
    record['candidate_id'] = 'SYNTHETIC:123'
    record['is_synthetic'] = True
    record['identity']['retailer_product']['walmart_item_id'] = '123'
    record['eligibility']['status'] = 'UNKNOWN'
    def metadata(item):
        if isinstance(item, dict):
            if 'observed_at' in item:
                item.update(verified=True, source_reference='SYNTHETIC saved reference')
            for value in item.values(): metadata(value)
    metadata(record)
    for key in ('monthly_sales', 'competing_offers'):
        record[key].update(asin=record['asin'], marketplace='ATVPDKIKX0DER')
    for mode in MODES:
        for scenario in SCENARIOS:
            record['financials'][mode][scenario]['retailer_shipping'] = dict(observation('0', currency='USD'), confidence='HIGH', verified=True, source_reference='SYNTHETIC shipping')
    return record


def manifest(records):
    return dict(schema='walmart_product_analysis_input_v1', expected_candidates=6, candidates=records)


@pytest.mark.parametrize('status', ['UNKNOWN', 'RESTRICTED', 'APPROVAL_REQUIRED'])
def test_independent_financial_and_market_while_buying_blocked(status):
    record = candidate(); record['eligibility']['status'] = status
    result = assess(record, NOW)
    assert result['financial_assessment'] == 'PROMISING'
    assert result['market_assessment'] == 'ATTRACTIVE'
    assert result['selling_eligibility'] == status
    assert result['decision'] == 'BLOCKED'
    assert result['purchase_authorized'] is False
    assert result['financials']['FBA']['base']['net_profit'] == '14.50'
    if status == 'UNKNOWN':
        assert record == candidate()


def test_reuses_existing_decimal_math_and_adds_shipping_once():
    record = candidate()
    original = deepcopy(record)
    record['financials']['FBA']['base']['retailer_shipping']['value'] = '2'
    result = assess(record, NOW)['financials']['FBA']['base']
    assert Decimal(result['net_profit']) == Decimal('12.50')
    assert Decimal(result['invested_cost']) == 15
    assert Decimal(result['gross_margin_percent']) == 75
    assert result['net_margin_percent'] != result['gross_margin_percent']
    assert original['financials']['FBA']['base']['retailer_shipping']['value'] == '0'
    original['financials']['FBA']['base']['other_cost']['value'] = '2'
    expected = financial(original, 'FBA', 'base', NOW)
    for key in expected:
        assert result[key] == expected[key]


@pytest.mark.parametrize('key', COSTS + ('selling_price', 'retailer_shipping'))
@pytest.mark.parametrize('problem', ['missing', 'stale', 'assumed', 'unknown_confidence'])
def test_incomplete_cost_never_confident(key, problem):
    record = candidate()
    for mode in MODES:
        item = record['financials'][mode]['base'][key]
        if problem == 'missing': del record['financials'][mode]['base'][key]
        if problem == 'stale': item['observed_at'] = (NOW-timedelta(days=2)).isoformat()
        if problem == 'assumed': item['assumed'] = True
        if problem == 'unknown_confidence': item['confidence'] = 'UNKNOWN'
    result = assess(record, NOW)
    assert result['financial_assessment'] == 'INSUFFICIENT_DATA'
    assert result['financials']['FBA']['base']['net_profit'] == 'UNKNOWN'


@pytest.mark.parametrize('change', ['quantity', 'gtin', 'stale', 'unknown', 'assumed', 'confidence'])
def test_identity_prevents_both_assessments(change):
    record = candidate(); product = record['identity']['retailer_product']
    if change == 'quantity': product['pack_quantity'] = 2
    if change == 'gtin': product['gtin'] = '036000291452'
    if change == 'stale': product['observed_at'] = (NOW-timedelta(days=2)).isoformat()
    if change == 'unknown': product['model'] = 'UNKNOWN'
    if change == 'assumed': product['assumed'] = True
    if change == 'confidence': product['confidence'] = 'UNKNOWN'
    result = assess(record, NOW)
    assert result['match_confidence'] == 'UNRESOLVED'
    assert result['financial_assessment'] == result['market_assessment'] == 'INSUFFICIENT_DATA'


@pytest.mark.parametrize('key,basis', [('monthly_sales','rank_estimate'), ('competing_offers','mixed_used_new_count')])
def test_rank_estimates_and_mixed_counts_do_not_pass(key, basis):
    record = candidate(); record[key]['basis'] = basis
    result = assess(record, NOW)
    assert result['market_assessment'] == 'INSUFFICIENT_DATA'
    assert result['supported_market'][key] == 'UNKNOWN'
    assert result['financial_assessment'] == 'PROMISING'


def test_lower_bound_and_configurable_thresholds():
    record = candidate()
    record['monthly_sales'].update(value=20, basis='bought_past_month_lower_bound')
    assert assess(record, NOW)['market_assessment'] == 'INSUFFICIENT_DATA'
    record['monthly_sales']['value'] = 30
    assert assess(record, NOW)['market_assessment'] == 'ATTRACTIVE'
    record['competing_offers']['value'] = 11
    assert assess(record, NOW)['market_assessment'] == 'UNATTRACTIVE'
    policy = ResearchPolicy(EvaluationPolicy(Decimal('100'), Decimal('50')), 30, 12)
    result = assess(record, NOW, policy)
    assert result['market_assessment'] == 'ATTRACTIVE'
    assert result['financial_assessment'] == 'BELOW_TARGET'


def test_one_incomplete_mode_does_not_hide_complete_mode_or_claim_below_target():
    record = candidate(); record['financials'].pop('FBM')
    result = assess(record, NOW)
    assert result['financial_assessment'] == 'PROMISING'
    assert result['financial_assessment_by_mode']['FBM'] == 'INSUFFICIENT_DATA'
    record['financials']['FBA']['base']['purchase']['value'] = '100'
    assert assess(record, NOW)['financial_assessment'] == 'INSUFFICIENT_DATA'


def test_scenarios_conflicts_stale_market_and_fee_basis():
    record = candidate()
    for mode in MODES:
        record['financials'][mode]['conservative'], record['financials'][mode]['optimistic'] = record['financials'][mode]['optimistic'], record['financials'][mode]['conservative']
    assert assess(record, NOW)['financial_assessment'] == 'INSUFFICIENT_DATA'
    record = candidate(); record['input_conflicts'] = ['conflicting evidence']
    assert assess(record, NOW)['financial_assessment'] == 'INSUFFICIENT_DATA'
    record = candidate(); record['monthly_sales']['observed_at'] = (NOW-timedelta(days=2)).isoformat()
    assert assess(record, NOW)['market_assessment'] == 'INSUFFICIENT_DATA'
    record = candidate()
    for mode in MODES:
        record['financials'][mode]['base']['referral_fee']['price_basis']['confidence'] = 'UNKNOWN'
    assert assess(record, NOW)['financial_assessment'] == 'INSUFFICIENT_DATA'


def test_unresolved_asin_and_empty_recovery_do_not_invent_products():
    record = dict(candidate_id='original:unknown', identity={})
    result = assess(record, NOW)
    assert result['asin'] == 'UNKNOWN' and result['financial_assessment'] == 'INSUFFICIENT_DATA'
    report = comparison(manifest([]), NOW)
    assert report['records'] == [] and report['recovered_candidates'] == 0
    assert report['recovery_status'] == 'INCOMPLETE'
    assert report['ranking_basis'] == 'RESEARCH_PRIORITY_ONLY'
    with pytest.raises(ValueError): comparison(manifest([candidate(), candidate()]), NOW)


def test_research_ranking_and_formula_safe_workbook(tmp_path):
    record = candidate(); record['candidate_id'] = '=1+1'
    report = comparison(manifest([record, dict(candidate_id='unmatched')]), NOW)
    assert report['ranking_basis'] == 'RESEARCH_PRIORITY_ONLY'
    assert report['records'][0]['candidate_id'] == '=1+1'
    output = tmp_path/'comparison.xlsx'
    workbook(report, output)
    wb = load_workbook(output)
    assert len(wb.sheetnames) == 6
    assert not any(c.data_type == 'f' for s in wb for row in s for c in row)
    assert wb['Product Comparison']['B1'].value == "'=1+1"


def test_cli_exclusive_offline_reports(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('No network')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    (tmp_path/'evidence').mkdir()
    source = tmp_path/'evidence'/'input.json'; source.write_text(json.dumps(manifest([candidate()])))
    output = tmp_path/'results'
    monkeypatch.setattr('sys.argv', ['product_analysis', '--input', str(source), '--output', str(output), '--as-of', NOW.isoformat()])
    before = source.read_bytes()
    main()
    assert source.read_bytes() == before
    report = json.loads((output/'comparison.json').read_text())
    assert report['records'][0]['financial_assessment'] == 'PROMISING'
    assert (output/'comparison.xlsx').stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError): main()


def test_conflicting_market_observations_are_not_silently_selected():
    record = candidate()
    record['market'] = {'monthly_sales': dict(record['monthly_sales'], value=500)}
    result = assess(record, NOW)
    assert result['market_assessment'] == result['financial_assessment'] == 'INSUFFICIENT_DATA'


@pytest.mark.parametrize('field,value', [('walmart_item_id','999'), ('url','https://example.org/ip/123')])
def test_walmart_source_identity(field, value):
    record = candidate(); record['identity']['retailer_product'][field] = value
    assert assess(record, NOW)['match_confidence'] == 'UNRESOLVED'


def test_stricter_research_quality_cannot_expose_untrusted_buy_candidate():
    record = candidate(); record['is_synthetic'] = False
    record['eligibility']['status'] = 'ELIGIBLE'
    for mode in MODES:
        del record['financials'][mode]['base']['retailer_shipping']
    result = assess(record, NOW)
    assert result['legacy_decision'] == 'BUY_CANDIDATE'
    assert result['decision'] == 'BLOCKED'
    assert result['financial_assessment'] == 'INSUFFICIENT_DATA'
    assert result['purchase_authorized'] is False


@pytest.mark.parametrize('field,value', [('asin','B000000001'), ('marketplace','OTHER'), ('confidence','LOW'), ('verified',False)])
def test_market_scope_and_quality(field, value):
    record = candidate(); record['monthly_sales'][field] = value
    assert assess(record, NOW)['market_assessment'] == 'INSUFFICIENT_DATA'


@pytest.mark.parametrize('value', [None, '', 'UNKNOWN', '   ', True, 123])
def test_estimate_requires_meaningful_validation_reference(value):
    record = candidate()
    record['monthly_sales'].update(basis='validated_estimate', model_validation_reference=value)
    assert assess(record, NOW)['market_assessment'] == 'INSUFFICIENT_DATA'


def test_six_synthetic_records_exercise_comparison_without_real_product_claims():
    records = []
    for i in range(6):
        record = candidate(); record['candidate_id'] = f'SYNTHETIC:{i}'
        records.append(record)
    report = comparison(manifest(records), NOW)
    assert report['recovered_candidates'] == 6 and report['recovery_status'] == 'RECOVERED'
    assert report['ranking_basis'] == 'BASE_NET_PROFIT_BEST_MODE'
    assert all(r['evidence_quality']['mode'] == 'ILLUSTRATIVE' for r in report['records'])
    assert all(r['financial_assessment'] == 'PROMISING' and r['decision'] == 'BLOCKED' for r in report['records'])


def test_stale_eligibility_and_original_evidence_hash_preserved():
    from app.observations import fingerprint
    record = candidate(); record['eligibility']['status'] = 'ELIGIBLE'
    record['eligibility']['observed_at'] = (NOW-timedelta(days=2)).isoformat()
    original = deepcopy(record)
    result = assess(record, NOW)
    assert result['selling_eligibility'] == 'UNKNOWN'
    assert result['decision'] == 'BLOCKED' and result['financial_assessment'] == 'PROMISING'
    assert result['evidence_sha256'] == fingerprint(original)
    assert record == original


def test_duplicate_json_keys_and_zero_expected_count_rejected(tmp_path, monkeypatch):
    with pytest.raises(ValueError): comparison(dict(manifest([]), expected_candidates=0), NOW)
    evidence = tmp_path/'evidence'; evidence.mkdir()
    source = evidence/'input.json'
    source.write_text('{"schema":"walmart_product_analysis_input_v1","candidates":[],"candidates":[]}')
    output = tmp_path/'output'
    monkeypatch.setattr('sys.argv', ['product_analysis','--input',str(source),'--output',str(output)])
    with pytest.raises(ValueError, match='Duplicate JSON key'): main()
    assert not output.exists()


def test_complete_finances_with_missing_market_still_use_research_priority():
    record = candidate(); del record['monthly_sales']
    report = comparison(manifest([record]), NOW)
    assert report['records'][0]['financial_assessment'] == 'PROMISING'
    assert report['ranking_basis'] == 'RESEARCH_PRIORITY_ONLY'


@pytest.mark.parametrize('stats', ['garbage', {}, dict(min='NaN',max='30',mean='25'), dict(min='40',max='20',mean='30')])
def test_bad_history_never_claims_available(stats):
    record = candidate()
    record['market'] = {'historical_30d': dict(observation(stats), currency='USD', condition='New',
        confidence='HIGH', verified=True, source_reference='SYNTHETIC history',
        marketplace='ATVPDKIKX0DER', asin=record['asin'], basis='New USD 30-day range')}
    assert assess(record, NOW)['price_history']['status'] == 'UNAVAILABLE'


def test_valid_history_requires_fresh_scoped_statistics():
    record = candidate()
    record['market'] = {'historical_30d': dict(observation(dict(min='20',max='30',mean='25')),
        currency='USD', condition='New', confidence='HIGH', verified=True,
        source_reference='SYNTHETIC history', marketplace='ATVPDKIKX0DER',
        asin=record['asin'], basis='New USD 30-day range')}
    assert assess(record, NOW)['price_history']['status'] == 'AVAILABLE'
    record['market']['historical_30d']['observed_at'] = (NOW-timedelta(days=2)).isoformat()
    assert assess(record, NOW)['price_history']['status'] == 'UNAVAILABLE'
