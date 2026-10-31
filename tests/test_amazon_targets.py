from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from app.amazon_targets import (TargetStore, acquisition_ceiling, browser_jobs,
    pilot_plan, target_from_keepa, verify_observation, select_discovery_asins, sheets_export, write_target_report)
from app.config import Config
from app.models import MarketplaceListing, RetailProduct
from app.observations import canonical
from app.profitability import COST_FIELDS

NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


@dataclass(frozen=True)
class SourceProduct(RetailProduct):
    # Compatible normalized extension for published evidence bases predating
    # the current Sheets source_context field.
    source_context: dict = field(default_factory=dict)


def target():
    fixture = json.loads(Path('sample_data/amazon_first_fixture.json').read_text())
    return target_from_keepa(fixture['products'][0], NOW, provenance='fixture')


def test_plan_is_bounded_and_offline():
    plan = pilot_plan('B002XQ1R06')
    assert plan['maximum_requests'] == 12
    assert plan['documented_total_token_reservation'] == 22
    assert plan['discovery']['selection']['perPage'] == 50
    assert not plan['hard_vendor_billing_ceiling_guaranteed']
    assert not plan['live_execution_available']
    assert 'key' not in plan['connectivity']['options']
    with pytest.raises(ValueError):
        pilot_plan('bad')


def test_ambiguous_identifiers_and_history_preserved():
    t = target()
    assert len(t.identifiers) == 2
    assert all(i.status == 'uncertain' and i.provenance for i in t.identifiers)
    assert t.historical_metrics['sales_rank']['latest'] == 25000
    assert t.historical_metrics['amazon_price_usd']['latest'] == Decimal('29.99')
    assert t.current_price_context['executable_sale_price'] is None
    assert t.seller_restrictions['eligible'] is None
    assert acquisition_ceiling(t) is None
    job = browser_jobs([t])[0]
    assert job['location'] == '76063'
    assert [q['basis'] for q in job['queries']] == ['UPC', 'UPC', 'model', 'wording_fallback']


def test_ceiling_uses_existing_defaults_explicit_costs_and_rounds_down():
    assumptions = dict(currency='USD', observed_at=NOW, provenance='explicit scenario',
                       proposed_sale_price='30', costs={k: '0' for k in COST_FIELDS})
    assumptions['costs']['fulfillment_fee'] = '5'
    t = replace(target(), fee_assumptions=assumptions)
    assert acquisition_ceiling(t) == Decimal('16.66')
    assert acquisition_ceiling(t, minimum_roi=Decimal('100')) == Decimal('12.50')
    t.fee_assumptions['costs']['sales_tax'] = None
    assert acquisition_ceiling(t) is None


@pytest.mark.parametrize('bad', ['NaN', '-1', 'Infinity'])
def test_invalid_costs_fail_closed(bad):
    assumptions = dict(currency='USD', observed_at=NOW, provenance='explicit scenario',
                       proposed_sale_price='30', costs={k: '0' for k in COST_FIELDS})
    assumptions['costs']['storage'] = bad
    with pytest.raises(ValueError):
        acquisition_ceiling(replace(target(), fee_assumptions=assumptions))


def test_target_job_limits_and_aware_timestamps():
    with pytest.raises(ValueError):
        browser_jobs([target()] * 11)
    with pytest.raises(ValueError):
        browser_jobs([target(), target()])
    with pytest.raises(ValueError):
        replace(target(), fetched_at=datetime(2026, 10, 31))


def test_append_only_revision_refresh_outcomes_and_unknown_cost(tmp_path):
    store = TargetStore(tmp_path / 'pilot.sqlite3')
    t = target()
    job = browser_jobs([t])[0]
    with pytest.raises(ValueError):
        store.save_job(job)
    store.save_target(t)
    assert store.save_job(job)
    assert not store.save_job(job)
    with pytest.raises(ValueError):
        store.save_job(dict(job, status='changed'))
    next_job = browser_jobs([t], query_version='v2')[0]
    with pytest.raises(ValueError):
        store.save_job(next_job)
    assert store.save_job(next_job, prior_job_id=job['job_id'], refresh_reason='new model evidence')
    for outcome in ('no_result', 'mismatch', 'unavailable', 'unresolved', 'matched'):
        store.record_outcome(job['job_id'], outcome=outcome, observed_at=NOW,
            query='DEMO-1', evidence_reference='fixture:' + outcome, elapsed_seconds=2)
    metrics = store.metrics()
    assert metrics['query_attempts'] == 5
    assert metrics['elapsed_seconds'] == 10
    assert metrics['exact_match_jobs'] == metrics['profitable_match_jobs'] == 0
    assert not metrics['cost_complete']
    assert sum(metrics['outcomes'].values()) == 5
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM amazon_search_events').fetchone()[0] == 6
    with pytest.raises(ValueError):
        store.record_outcome('missing', outcome='matched', observed_at=NOW,
                             query='x', evidence_reference='x', elapsed_seconds=1)


def test_browser_claim_never_bypasses_match_or_fee_gates(tmp_path):
    t = target()
    job = browser_jobs([t])[0]
    product = SourceProduct('Walmart', 'demo', 'https://www.walmart.com/ip/demo/123', '',
        'Fictional Kitchen', 'DEMO-1', 1, Decimal('5'), 'in_stock', NOW, 'fixture',
        asin_hint=t.asin, variation='blue 10 inch', authorization_reference='fixture',
        source_context={'brand': 'Fictional Kitchen', 'observed_zip': '76063'})
    listing = MarketplaceListing(t.asin, '', 'Fictional Kitchen', 'DEMO-1', 1,
        'blue 10 inch', True, Decimal('30'), {k: Decimal('0') for k in COST_FIELDS},
        monthly_sales=50, offer_count=3, retrieved_at=NOW, provenance='fixture', is_mock=False)
    config = Config(Path('unused'), tmp_path / 'out.xlsx', tmp_path / 'history.sqlite3')
    row = verify_observation(t, job, product, listing, config, NOW)
    assert row['application_verified_exact']
    assert not row['verified_profitable']  # costs supplied but not verified
    assert row['status'] == 'REJECT'
    verified = replace(listing, verified_costs=COST_FIELDS)
    row = verify_observation(t, job, product, verified, config, NOW)
    assert row['verified_profitable']
    for context in ({'brand': 'Different Brand', 'observed_zip': '76063'},
                    {'brand': 'Fictional Kitchen', 'observed_zip': '99999'}, {}):
        unsupported = verify_observation(t, job, replace(product, source_context=context), verified, config, NOW)
        assert not unsupported['application_verified_exact']
        assert not unsupported['verified_profitable']
    write_target_report([row], tmp_path / 'report.xlsx')
    from openpyxl import load_workbook
    workbook = load_workbook(tmp_path / 'report.xlsx')
    metadata = dict(workbook['Job Execution Summary'].values)
    assert job['job_id'] in metadata['lineage_json']
    mismatch = replace(product, package_quantity=2)
    assert not verify_observation(t, job, mismatch, verified, config, NOW)['verified_profitable']
    missing = replace(verified, costs={})
    assert not verify_observation(t, job, product, missing, config, NOW)['verified_profitable']
    assert verify_observation(t, job, product, missing, config, NOW)['profit'] is None
    store = TargetStore(tmp_path / 'evidence.sqlite3')
    store.save_target(t)
    store.save_job(job)
    # Reuse the existing source-observation writer and exact evidence fingerprint.
    from app.marketplace import match_listings
    run_id = store.start_run(NOW, {'test': 'lineage'})
    source_id = store.record_item(run_id, 0, product, match_listings(product, (verified,)), row,
        enrichments=[], recorded_at=NOW)
    store.evaluate(t, job, source_id, product, verified, config, NOW)
    assert store.metrics()['profitable_match_jobs'] == 1
    with pytest.raises(ValueError):
        store.evaluate(t, job, source_id, mismatch, verified, config, NOW)


def test_finder_local_selection_cap_and_rejection():
    values = [f'B{i:09d}' for i in range(50)]
    assert len(select_discovery_asins({'asinList': values}, exclude_asin=values[0])) == 10
    assert select_discovery_asins({'asinList': values}, exclude_asin=values[0])[0] == values[1]
    for payload in ({'asinList': values + ['B999999999']}, {'asinList': ['bad']}, {'error': {}, 'asinList': None}):
        with pytest.raises(ValueError):
            select_discovery_asins(payload, exclude_asin=values[0])


def test_separate_offline_sheets_tabs():
    t = target()
    export = sheets_export([t], browser_jobs([t]))
    assert set(export['tabs']) == {'Amazon_Targets', 'Amazon_Search_Jobs', 'Amazon_Search_Outcomes'}
    for tab in export['tabs'].values():
        assert all(len(row) == len(tab['fields']) for row in tab['rows'])
        assert all(isinstance(cell, str) for row in tab['rows'] for cell in row)
