"""Offline export tests with synthetic offers only."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import sqlite3

from app.priceapi_export import import_export, rows_from_export
from app.connectors import CsvConnector


def document():
    items = [dict(id=None, name=f'Utensils {i}', url=f'https://www.ebay.com/itm/{100000000000+i}?track=1',
                  shop_name='seller', shop_id='seller-id', price='12.99', currency='USD',
                  shipping_costs=None if i == 0 else '0.0', condition_text='Brand New') for i in range(12)]
    items.insert(1, dict(items[0], url=items[0]['url'].replace('track=1', 'track=2')))
    return dict(job_id='synthetic', status='finished', results=[dict(success=True,
        query=dict(source='ebay', country='us', topic='search_results'),
        metadata=dict(updated_at='2026-10-27T22:45:31Z'), content=dict(search_results=items))])


def test_distinct_url_ids_order_and_missing_evidence():
    rows = rows_from_export(document(), 'synthetic', 'hash', datetime.now(timezone.utc))
    assert [r['retailer_item_id'] for r in rows] == [str(100000000000+i) for i in range(10)]
    assert 'result_rank=3;' in rows[1]['provenance']
    assert rows[0]['source_shipping_cost'] == ''
    assert rows[1]['source_shipping_cost'] == '0.0'
    assert rows[0]['provider_product_id'] == ''
    assert rows[0]['retrieved_at'] == rows[0]['purchase_price'] == rows[0]['package_quantity'] == ''


def test_import_preserves_file_and_persists_unknowns(tmp_path):
    source = tmp_path/'export.json'
    source.write_text(json.dumps(document()))
    before = source.read_bytes()
    output = tmp_path/'import'
    plan = import_export(source, output)
    assert source.read_bytes() == before
    assert plan['source_sha256'] == hashlib.sha256(before).hexdigest()
    assert plan['budget']['maximum_http_attempts'] == 21
    products = list(CsvConnector(output/'observations.csv').products())
    assert len(products) == 10
    assert products[0].source_context['source_condition'] == 'Brand New'
    assert products[0].source_context['source_seller_id'] == 'seller-id'
    assert products[0].source_context['source_shipping_cost'] is None
    assert products[1].source_context['source_shipping_cost'] == 0
    with sqlite3.connect(output/'report/source-plan.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM pilot_run_items').fetchone()[0] == 10
        assert db.execute('SELECT sum(exact) FROM marketplace_matches').fetchone()[0] == 0
