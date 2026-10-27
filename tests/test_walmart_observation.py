"""Offline schema/lineage regression inputs only, never real product observations."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest
from openpyxl import load_workbook

from app.amazon_source_intake import intake
from app.authorized_imports import HEADERS, validate
from app.connectors import CsvConnector, WALMART_FIELDS
from app.config import ROOT


def source(tmp_path, **changes):
    # Deliberately incomplete: no invented identity, price, stock or permission.
    values = dict.fromkeys(HEADERS + WALMART_FIELDS, '')
    values.update(retailer='Walmart', destination_zip='76063')
    values.update(changes)
    path = tmp_path/'supplied.csv'
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS + WALMART_FIELDS)
        writer.writeheader()
        writer.writerow(values)
    return path


def test_walmart_template_is_header_only_and_extends_existing_schema():
    with (ROOT/'templates/walmart_observation.csv').open() as stream:
        rows = list(csv.reader(stream))
    assert rows == [list(HEADERS + WALMART_FIELDS)]


def test_missing_walmart_fields_stay_unknown_and_persist_offline(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No external actions permitted')
    monkeypatch.setattr('urllib.request.OpenerDirector.open', forbidden)
    monkeypatch.setattr('app.mailer.send_report', forbidden)
    path = source(tmp_path)
    before = path.read_bytes()
    result = intake(path, tmp_path/'state')
    assert path.read_bytes() == before
    assert result['source_findings']
    assert any('Missing Walmart source_seller' in s for s in result['source_findings'])
    assert result['rows'][0]['buy_cost'] is None
    assert result['rows'][0]['status'] == 'REJECT'
    assert not result['scenarios'][0]['fee_request_planned']
    assert result['budget']['live_requests'] == 0
    with sqlite3.connect(tmp_path/'state/source-plan.sqlite3') as db:
        product = json.loads(db.execute('SELECT payload_json FROM source_observations').fetchone()[0])
    assert product['source_context']['destination_zip'] == '76063'
    assert product['source_context']['source_shipping_cost'] is None
    assert product['source_context']['source_seller'] is None
    assert product['authorization_reference'] == ''
    assert product['retrieved_at'] is None
    workbook = load_workbook(tmp_path/'state/SOURCE-PLAN.xlsx')
    assert 'walmart_source_context' in str(list(workbook['Enrichment Evidence'].values))
    assert '76063' in str(list(workbook['Enrichment Evidence'].values))


def test_supplied_seller_shipping_context_is_not_inferred_into_economics(tmp_path):
    path = source(tmp_path, source_seller='SUPPLIED TEST SELLER', source_item_id='123456',
                  url='https://www.walmart.com/ip/123456', fulfillment_method='shipping',
                  source_shipping_cost='0', shipping_conditions='TEST: only with supplied basket threshold')
    product = next(CsvConnector(path).products())
    assert product.source_context['source_shipping_cost'] == 0
    assert product.source_context['source_seller'] == 'SUPPLIED TEST SELLER'
    assert product.purchase_price is None
    assert product.retrieved_at is None
    assert product.availability == ''
    assert product.authorization_reference == ''
    assert 'threshold' in product.source_context['shipping_conditions']


@pytest.mark.parametrize('changes,reason', [
    ({'destination_zip':''}, 'destination ZIP'),
    ({'destination_zip':'10001'}, 'destination ZIP'),
    ({'source_shipping_cost':'-1'}, 'Invalid source_shipping_cost'),
    ({'source_item_id':'bad'}, 'Invalid Walmart item ID'),
    ({'source_item_id':'123', 'url':'https://www.walmart.com/ip/456'}, 'item ID and URL mismatch'),
    ({'url':'https://www.walmart.com.example.org/ip/123'}, 'Walmart product URL required'),
    ({'url':'https://['}, 'Invalid Walmart product URL'),
    ({'fulfillment_method':'unknown'}, 'fulfillment method missing or unsupported'),
])
def test_missing_or_contradictory_context_is_flagged(tmp_path, changes, reason):
    path = source(tmp_path, **changes)
    findings = validate(path, datetime.now(timezone.utc))
    assert any(reason in issue for issue in findings)
