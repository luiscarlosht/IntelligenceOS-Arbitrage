from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.m96_profitability import evaluate
from app.profitability import COST_FIELDS

NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)


def record():
    values = {key: '0' for key in COST_FIELDS}
    values.update(retail_acquisition_cost='10', amazon_selling_price='18', referral_fee='2',
                  fulfillment_fee='1', exact_product_variant_pack_match=True,
                  listing_permission='SELL_THIS_PRODUCT', fba_inbound='ELIGIBLE_PREVIEW')
    return dict(asin='B000000001', marketplace='ATVPDKIKX0DER', condition='new_new',
        channel='AUTHORIZED_RETAIL', evidence={key: dict(value=value, observed_at=NOW.isoformat(),
            seller_scope_reference='test-account-context', source='synthetic test fixture', status='VERIFIED', asin='B000000001',
            marketplace='ATVPDKIKX0DER', condition='new_new', is_mock=False) for key, value in values.items()})


def test_boundaries_preserve_formula_and_no_authorization():
    data = record()
    before = deepcopy(data)
    result = evaluate(data, NOW)
    assert result['net_profit'] == '5' and result['roi_percent'] == '50.0'
    assert result['status'] == 'MANUAL_REVIEW_ONLY' and not result['purchase_authorized']
    assert data == before
    data['evidence']['amazon_selling_price']['value'] = '17.99'
    assert evaluate(data, NOW)['status'] == 'BELOW_THRESHOLDS'


@pytest.mark.parametrize('field', ['fulfillment_fee', 'referral_fee', 'inbound_shipping',
    'preparation', 'exact_product_variant_pack_match', 'listing_permission', 'fba_inbound'])
def test_missing_evidence_blocks(field):
    data = record()
    del data['evidence'][field]
    result = evaluate(data, NOW)
    assert result['status'] == 'BLOCKED_MISSING_EVIDENCE' and result['net_profit'] is None


@pytest.mark.parametrize('updates', [dict(value='UNKNOWN'), dict(value='NaN'), dict(value='-1'),
    dict(status='ESTIMATED'), dict(is_mock=True),dict(asin='B000000002'),
    dict(observed_at='2026-11-01T00:00:00Z'),dict(observed_at='2026-11-08T00:00:00Z'),dict(source='')])
def test_uncertain_fees_never_become_zero(updates):
    data = record()
    data['evidence']['fulfillment_fee'].update(updates)
    assert evaluate(data, NOW)['status'] == 'BLOCKED_MISSING_EVIDENCE'


def test_wholesale_and_unmatched_variant_blocked():
    data = record()
    data['channel'] = 'WHOLESALE'
    data['evidence']['exact_product_variant_pack_match']['value'] = False
    assert evaluate(data, NOW)['status'] == 'BLOCKED_MISSING_EVIDENCE'


def test_different_seller_contexts_blocked():
    data = record()
    data['evidence']['fba_inbound']['seller_scope_reference'] = 'other-context'
    assert evaluate(data, NOW)['status'] == 'BLOCKED_MISSING_EVIDENCE'
