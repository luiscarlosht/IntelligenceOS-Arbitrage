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
        assert row['economics_verdict'] == 'INSUFFICIENT_EVIDENCE'
        assert row['poc_decision'] == row['final_decision'] == (
            'REJECTED_IDENTITY' if row['identity_verdict'] == 'REJECTED' else 'INSUFFICIENT_EVIDENCE')
        assert row['eligibility_verdict'] == {'listing': 'UNKNOWN', 'FBA': 'UNKNOWN'}
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
    assert '76063' in report['evidence_collection_checklist'][3]['required']


def test_continuation_does_not_promote_research_or_non_dfw_prices():
    report = build(NOW)
    assert report['m92_complete'] is False
    rows = report['continuation_review']['candidates']
    assert [r['asin'] for r in rows] == ['B000Q3KHCM', 'B07GQ1CT47', 'B003SI0TD4']
    for row in rows:
        assert row['identity_status'] == 'NEEDS_REVIEW'
        assert row['final_decision'] == 'INSUFFICIENT_EVIDENCE'
        assert row['public_offer_context']['dfw_landed_cost'] == 'UNKNOWN'
        assert row['listing_eligibility'] == row['fba_eligibility'] == 'UNKNOWN'
        assert set(row['scenarios']) == {'conservative', 'base', 'optimistic'}
        assert all(s['net_profit'] == 'UNKNOWN' for s in row['scenarios'].values())
    assert '1906833' in ' '.join(rows[1]['findings'])
    assert len(report['evidence_collection_checklist']) == 10
    assert report['delivery_context']['zip'] == '76063'
    assert not report['delivery_context']['verified_purchase_quote']
    assert report['final_decision_counts'] == {'INSUFFICIENT_EVIDENCE': 3, 'REJECTED_IDENTITY': 57}
    assert set(report['decision_classifications']) == {
        'VERIFIED_PROFITABLE', 'VERIFIED_UNPROFITABLE', 'INELIGIBLE',
        'REJECTED_IDENTITY', 'INSUFFICIENT_EVIDENCE'}
    plan = report['collection_plan']
    assert not any(plan['authorization'][k] for k in (
        'network_collection', 'account_access', 'credential_access', 'sp_api',
        'purchases', 'production_changes', 'deployment'))
    assert all(t['sources'] and t['authorization_required'] for t in plan['tasks'])
    assert all(r['identity_review']['sourcing']['required_zip'] == '76063' for r in report['records'])
    assert 'User must supply actual DFW ZIP' not in json.dumps(report)


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
    decisions = list(one['M92 Decision Report'].values)
    assert decisions[0][3:6] == ('eligibility_verdict', 'economics_verdict', 'final_decision')
    assert all(r[5] == 'INSUFFICIENT_EVIDENCE' for r in decisions[1:])
    checklist = (tmp_path/'one/evidence-collection.md').read_text()
    assert '76063' in checklist and 'Authorization:' in checklist
    assert [[list(r) for r in s.values] for s in one] == [[list(r) for r in s.values] for s in two]
    assert not any(c.data_type == 'f' for s in one for row in s for c in row)
    assert before == {str(p): digest(p) for root in (BASE,M91_BASE) for p in root.iterdir()}
    assert (tmp_path/'one/comparison.xlsx').stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        run(tmp_path/'one', NOW)


@pytest.mark.parametrize('artifact', ['receipt-9.json', 'completion-plan.json'])
def test_pinned_supplement_drift_and_changed_baseline_rejected(tmp_path, artifact):
    base = tmp_path/'evidence'
    shutil.copytree(BASE, base)
    source = base/artifact
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
