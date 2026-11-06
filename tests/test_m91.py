"""Integration coverage uses only pinned real research, never synthetic product facts."""
import json
import shutil
import socket

from openpyxl import load_workbook
import pytest

from app.m91 import BASE, build, run
from app.evidence_io import digest


def test_reproducible_offline_baseline(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Network forbidden')
    monkeypatch.setattr(socket, 'socket', forbidden)
    before = {p.name: digest(p) for p in BASE.iterdir()}
    first = run(tmp_path / 'first')
    second = run(tmp_path / 'second')
    assert first == second
    assert (tmp_path / 'first/comparison.json').read_bytes() == (tmp_path / 'second/comparison.json').read_bytes()
    assert before == {p.name: digest(p) for p in BASE.iterdir()}
    assert len(first['records']) == 6
    for row in first['records']:
        assert row['match_confidence'] == 'UNRESOLVED'
        assert row['financial_assessment'] == 'INSUFFICIENT_DATA'
        assert row['selling_eligibility'] == 'UNKNOWN'
        assert row['purchase_authorized'] is False
        assert row['baseline_inventory']['synthetic_test_records'] is False
        assert row['financials']['FBA']['base']['net_profit'] == 'UNKNOWN'
        assert row['baseline_inventory']['amazon_saved_observation']['asin'] == row['asin']
    one = load_workbook(tmp_path / 'first/comparison.xlsx')
    two = load_workbook(tmp_path / 'second/comparison.xlsx')
    assert one.sheetnames == two.sheetnames
    assert [[list(r) for r in s.values] for s in one] == [[list(r) for r in s.values] for s in two]
    assert not any(c.data_type == 'f' for s in one for row in s for c in row)
    assert first['m92_checklist'][0]['priority'] == 1
    with pytest.raises(ValueError):
        run(tmp_path / 'first')


def test_changed_or_synthetic_artifact_rejected(tmp_path):
    base = tmp_path / 'evidence'
    shutil.copytree(BASE, base)
    source = base / 'six-product-manifest.json'
    source.write_bytes(source.read_bytes() + b' ')
    with pytest.raises(ValueError, match='SHA-256'):
        build(base)
    shutil.copyfile(BASE / source.name, source)
    pins = json.loads((base / 'pins.json').read_text())
    pins['artifacts'][0]['kind'] = 'SYNTHETIC_DEMO'
    (base / 'pins.json').write_text(json.dumps(pins))
    with pytest.raises(ValueError, match='real baseline'):
        build(base)
