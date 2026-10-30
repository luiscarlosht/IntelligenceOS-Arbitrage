"""Offline synthetic rows with the exact rejected text formats."""
import json
from pathlib import Path

import pytest

from app.sheets_intake import FIELDS, ValidationFailure, availability_description, product, table


def rows():
    snapshot = json.loads((Path(__file__).parent / 'fixtures/sheets_rejected_20261030.json').read_text())
    return table(snapshot['Walmart_Intake'], FIELDS)


def test_all_38_format_rows_validate_without_changing_evidence():
    evidence = rows()
    assert len(evidence) == 38
    assert len({r['batch_id'] for r in evidence}) == 7
    assert len({r['record_id'] for r in evidence}) == 38
    assert len({r['walmart_item_id'] for r in evidence}) == 38
    for row in evidence:
        before = dict(row)
        result = product(row)
        assert row == before
        assert result.source_context['source_shipping_cost'] is None
        for field in ('shipping_availability', 'local_delivery_availability', 'pickup_availability'):
            assert result.source_context[field + '_description'] == row[field]
            assert result.source_context[field] == ('UNAVAILABLE' if 'Not available' in row[field] else 'AVAILABLE')
        assert result.availability == 'unknown'


@pytest.mark.parametrize('price', ['Now $6.71', '$6.71', '6.71'])
def test_single_observed_price_numeric_comparison(price):
    row = rows()[0]
    raw = json.loads(row['raw_record_json'])
    raw['displayed_price'] = price
    row['item_price_usd'] = '6.71'
    row['raw_record_json'] = json.dumps(raw)
    product(row)
    row['item_price_usd'] = '6.72'
    with pytest.raises(ValidationFailure):
        product(row)


@pytest.mark.parametrize('price', [
    '$6.71-$7.00', 'Now $6.71 Was $8.00', '2 for $6.71', '$6.71 each',
    '6,71', '$6.710', '$6.71 or $6.71', 'About $6.71', '$NaN', '$-6.71',
])
def test_ambiguous_observed_prices_rejected(price):
    row = rows()[0]
    raw = json.loads(row['raw_record_json'])
    raw['displayed_price'] = price
    row['raw_record_json'] = json.dumps(raw)
    with pytest.raises(ValidationFailure):
        product(row)


def test_multiline_channels_remain_independent_and_conflicts_reject():
    assert availability_description('shipping_availability', 'Delivery\nAs soon as 20 mins') is None
    assert availability_description('shipping_availability', 'Shipping\nPrice depends on location') is None
    with pytest.raises(ValidationFailure, match='CONFLICTING_AVAILABILITY'):
        availability_description('shipping_availability', 'Shipping\nNot available\nArrives tomorrow')
    row = rows()[0]
    row['shipping_availability'] = row['shipping_availability'].replace('\n', ' ')
    with pytest.raises(ValidationFailure, match='RAW_EXPORT_MISMATCH'):
        product(row)
