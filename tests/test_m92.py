"""M92 integration against real pinned observations; no invented economics."""
from datetime import datetime
import json
from pathlib import Path
import shutil
import socket

from openpyxl import load_workbook
import pytest

from app.evidence_io import digest
from app.m91 import BASE as M91_BASE
from app.m92 import BASE, build, run

NOW = datetime.fromisoformat('2026-11-06T13:00:00+00:00')


def test_all_alternatives_reviewed_no_false_match_or_profit():
    report = build(NOW)
    expected = set()
    for path in M91_BASE.glob('receipt-*.json'):
        receipt = json.loads(path.read_text())
        expected.update((receipt['candidate_id'].split(':')[-1], c['product']['asin'])
                        for c in receipt['evidence']['candidates'])
    assert len(expected) == 60
    assert {(r['walmart_product']['walmart_item_id'],r['asin']) for r in report['records']} == expected
    assert report['pair_counts'] == {'NEEDS_REVIEW': 3, 'REJECTED': 57}
    assert report['best_candidate']['asin'] == 'B000Q3KHCM'
    assert report['best_candidate']['walmart_item_id'] == '17011265'
    best = report['records'][0]
    assert best['identity_review']['comparisons']['upc']['overlap']
    assert best['identity_review']['comparisons']['mpn']['status'] == 'DIFFERENT_LABELS'
    assert not best['identity_review']['strict_gate']['exact']
    assert best['identity_review']['detail_receipt'] == 'receipt-9.json'
    assert best['identity_review']['historical_acquisition']['purchase']['value'] == '1.17'
    rejected = {(r['walmart_item_id'],r['asin']) for r in report['rejected_alternatives']}
    assert {('47070933','B0000AQOAB'), ('17011265','B0006HUJJO'),
            ('13952053139','B0035LCFNQ'), ('17011265','B08BFDVHWB')} <= rejected
    assert all(r['reasons'] for r in report['rejected_alternatives'])
    for row in report['records']:
        assert row['match_confidence'] == 'UNRESOLVED'
        assert row['selling_eligibility'] == 'UNKNOWN'
        assert row['poc_decision'] == row['economics_verdict'] == 'INSUFFICIENT_EVIDENCE'
        assert not row['purchase_authorized']
        assert not row['identity_review']['verified_exact_match']
        assert not row['identity_review']['sourcing']['verified']
        assert 'DFW' in row['identity_review']['sourcing']['required']
        assert row['identity_review']['condition']['amazon_offer'] == 'UNKNOWN'
        assert row['selected_mode'] == 'FBA' and row['deferred_mode'] == 'FBM'
        assert all(i['value'] == 'UNKNOWN' for i in row['input_evidence']['financials']['FBA']['base'].values())
        assert row['financials']['FBA']['base']['net_profit'] == 'UNKNOWN'
        assert row['financials']['FBA']['base']['roi_percent'] == 'UNKNOWN'
        assert row['financials']['FBA']['base']['net_margin_percent'] == 'UNKNOWN'
        assert row['thresholds']['minimum_profit'] == '5' and row['thresholds']['minimum_roi'] == '50'
    assert not report['m93_ready'] and report['synthetic_records'] == 0
    assert 'DFW' in report['evidence_collection_checklist'][3]['required']


def test_offline_reproducible_excel_json_and_preserved_sources(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Network or account state access forbidden')
    monkeypatch.setattr(socket, 'socket', forbidden)
    original_open = Path.open
    def guarded(path, *args, **kwargs):
        if any(word in path.name.lower() for word in ('ledger', '.lock', 'credential', 'token')):
            forbidden()
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    before = {str(p): digest(p) for root in (BASE,M91_BASE) for p in root.iterdir()}
    first = run(tmp_path/'one', NOW)
    assert first == run(tmp_path/'two', NOW)
    assert (tmp_path/'one/comparison.json').read_bytes() == (tmp_path/'two/comparison.json').read_bytes()
    one = load_workbook(tmp_path/'one/comparison.xlsx')
    two = load_workbook(tmp_path/'two/comparison.xlsx')
    assert {'Identity Review','Rejected Alternatives','Evidence Collection'} <= set(one.sheetnames)
    assert one['Identity Review'].max_row == 61
    assert one['Rejected Alternatives'].max_row == 58
    assert [[list(r) for r in s.values] for s in one] == [[list(r) for r in s.values] for s in two]
    assert not any(c.data_type == 'f' for s in one for row in s for c in row)
    assert before == {str(p): digest(p) for root in (BASE,M91_BASE) for p in root.iterdir()}
    assert (tmp_path/'one/comparison.xlsx').stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        run(tmp_path/'one', NOW)


def test_pinned_supplement_drift_and_changed_baseline_rejected(tmp_path):
    base = tmp_path/'evidence'
    shutil.copytree(BASE, base)
    source = base/'receipt-9.json'
    source.write_bytes(source.read_bytes()+b' ')
    with pytest.raises(ValueError, match='SHA-256'):
        build(NOW, base)
    shutil.copyfile(BASE/source.name,source)
    m91 = tmp_path/'m91'
    shutil.copytree(M91_BASE,m91)
    (m91/'pins.json').write_bytes((m91/'pins.json').read_bytes()+b' ')
    with pytest.raises(ValueError, match='M91 baseline'):
        build(NOW, base, m91)
    with pytest.raises(ValueError, match='Aware'):
        build(datetime(2026,11,6))
