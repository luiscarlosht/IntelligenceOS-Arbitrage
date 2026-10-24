import csv
from datetime import datetime, timedelta, timezone

import pytest
from app.authorized_imports import HEADERS, validate
from app.config import Config, ROOT
from app.connectors import CsvConnector
from app.discovery import discover
from app.marketplace import MockAmazonProvider

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def write_csv(tmp_path, **changes):
    row = dict.fromkeys(HEADERS, '')
    row.update(retailer='TEST supplier', name='TEST product', url='https://example.org/item',
               gtin='036000291452', package_quantity='1', purchase_price='8',
               availability='in_stock', retrieved_at=NOW.isoformat(), provenance='TEST export',
               variation='blue', authorization_reference='TEST permission record')
    row.update(changes)
    path = tmp_path / 'input.csv'
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, HEADERS)
        writer.writeheader(); writer.writerow(row)
    return path


def test_valid_input_preserves_original_evidence(tmp_path):
    path = write_csv(tmp_path)
    original = path.read_bytes()
    assert validate(path, NOW) == []
    assert path.read_bytes() == original
    assert list(CsvConnector(path).products())[0].gtin == '00036000291452'


@pytest.mark.parametrize('change,reason', [
    ({'authorization_reference': ''}, 'authorization_reference'),
    ({'provenance': ''}, 'provenance'),
    ({'purchase_price': 'NaN'}, 'purchase_price'),
    ({'package_quantity': '0'}, 'quantity'),
    ({'gtin': '036000291453'}, 'gtin'),
    ({'url': 'https://user:secret@example.org'}, 'URL'),
    ({'retrieved_at': '2026-10-23T12:00:00'}, 'retrieved_at'),
    ({'retrieved_at': (NOW - timedelta(days=2)).isoformat()}, 'Stale'),
    ({'retrieved_at': (NOW + timedelta(seconds=1)).isoformat()}, 'Future'),
    ({'availability': 'unknown'}, 'stock'),
    ({'gtin': '', 'model': '', 'manufacturer': ''}, 'identity'),
])
def test_invalid_evidence_blocked(tmp_path, change, reason):
    assert any(reason in issue for issue in validate(write_csv(tmp_path, **change), NOW))


def test_empty_template_and_row_limit(tmp_path):
    assert validate(ROOT / 'templates/authorized_products.csv', NOW) == ['No product rows supplied']
    assert 'Maximum' in validate(write_csv(tmp_path), NOW, maximum_rows=0)[0]


def test_authorized_source_does_not_supply_marketplace_evidence(tmp_path):
    path = write_csv(tmp_path, gtin='96385074', variation='unknown')
    assert not validate(path, NOW)
    config = Config.from_env()
    rows = discover(CsvConnector(path), MockAmazonProvider(config.amazon_fixture), config, NOW)
    assert rows[0]['status'] == 'REJECT'
    assert 'Missing marketplace listing' in rows[0]['reason']
    assert rows[0]['purchase_ready'] is False


def test_populated_sample_and_actionable_cli(tmp_path, monkeypatch, capsys):
    import json
    from app.authorized_imports import main, remediation
    from app.demo import DEMO_NOW
    assert validate(ROOT / 'sample_data/authorized_source_sample.csv', DEMO_NOW) == []
    path = write_csv(tmp_path, purchase_price='NaN', authorization_reference='')
    monkeypatch.setattr('sys.argv', ['authorized_imports', str(path)])
    with pytest.raises(SystemExit) as outcome:
        main()
    assert outcome.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert report['issues'] and len(report['findings']) == len(report['issues'])
    assert all(f['action'] for f in report['findings'])
    assert not report['authorization_verified'] and not report['marketplace_verified']
    assert 'positive' in remediation('Row 1: Invalid purchase_price')
    assert 'actual permission' in remediation('Row 1: Missing authorization_reference')
