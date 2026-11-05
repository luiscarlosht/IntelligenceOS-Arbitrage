"""Offline sourcing provenance, conservative assessment and publication boundaries."""
import json
import socket
from pathlib import Path

import pytest

from app.evidence_io import digest
from app.m89 import DETAIL, LEDGER, RECON, analyze, rank


@pytest.fixture
def evidence(tmp_path):
    root = tmp_path / 'm88'
    root.mkdir()
    def save(name, data):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return path
    p = dict(asin='B003SI0TD4', brand='DURACELL', model='1', size='8 Count (Pack of 1)',
        variation='Black', pack_quantity=1, gtin='00041333825014', title='Saved fixture',
        identifiers=[dict(identifier_type='UPC', value='041333825014', normalized_gtin='00041333825014')],
        mapping_issues=[], url='https://www.amazon.com/dp/B003SI0TD4')
    attempts, details = [], []
    for number in range(1, 12):
        folder = 'm88-executor-v1-20261105T0301Z' if number <= 7 else 'm88-targeted-verification-v1'
        plan = save(folder + '/plan.json', dict(scope=folder))
        phase = 'authentication' if number in (1, 8) else 'search' if number <= 7 else 'detail'
        record = dict(number=number, phase=phase, candidate_id=None if phase == 'authentication' else 'fixture',
                      evidence=dict(candidates=[dict(product=p)]) if phase == 'search' else dict(product=p))
        receipt = save(folder + f'/receipt-{number}.json', record)
        attempts.append(dict(number=number, phase=phase, candidate_id=record['candidate_id'],
            status='COMPLETE', receipt_sha256=digest(receipt), plan_sha256=digest(plan)))
        if phase == 'detail':
            details.append(record)
    save(LEDGER, dict(attempts=attempts, attempts_used=11, ceiling=49, purchase_authorized=False))
    save(RECON, dict(records=[dict(asin=p['asin'], amazon_product=p, walmart_item_id='123',
        classification='REJECTED', remaining_gaps=['original contradiction'], source_exceptions=[])]))
    save(DETAIL, dict(details=details))
    return root


def test_preserves_evidence_and_m86_unknowns(evidence, tmp_path):
    before = {str(p): digest(p) for p in evidence.rglob('*') if p.is_file()}
    out = tmp_path / 'report'
    result = analyze(evidence, out)
    assert result['cumulative_attempts'] == 11
    assert result['remaining_attempts'] == 38
    assert result['additional_amazon_http_attempts'] == 0
    assert not result['purchase_authorized']
    assert result['shortlist'][0]['prior_m88_pairs'][0]['classification'] == 'REJECTED'
    assert result['shortlist'][0]['walmart_evidence'] is None
    financial = json.loads((out / 'comparison.json').read_text())
    assert financial['records'][0]['financial_assessment'] == 'INSUFFICIENT_DATA'
    assert all(digest(Path(p)) == h for p, h in before.items())
    assert (out / 'comparison.xlsx').stat().st_mode & 0o777 == 0o600
    plan = json.loads((out / 'conditional-amazon-plan.json').read_text())
    assert plan['maximum_new_attempts'] == sum(plan[k] for k in ('authentication', 'new_offers', 'listing_restrictions', 'fee_estimates'))
    assert plan['maximum_cumulative_attempts'] <= 49
    assert not plan['executable'] and plan['reserved_attempts'] == 0
    with pytest.raises(ValueError, match='Fresh local output'):
        analyze(evidence, out)


def test_receipt_tampering_stops_publication(evidence, tmp_path):
    receipt = evidence / 'm88-targeted-verification-v1/receipt-9.json'
    receipt.write_text('{}')
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        analyze(evidence, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_uncertain_ledger_rejected(evidence, tmp_path):
    path = evidence / LEDGER
    data = json.loads(path.read_text())
    data['attempts'][0]['status'] = 'RESERVED'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='11/49'):
        analyze(evidence, tmp_path / 'out')


def test_network_and_input_writes_blocked(evidence, tmp_path, monkeypatch):
    import app.m89 as module
    original = module.rank
    def forbidden(*args):
        with pytest.raises(PermissionError, match='network/processes'):
            socket.socket()
        with pytest.raises(PermissionError, match='outside new report'):
            (evidence / 'unexpected.json').write_text('{}')
        return original(*args)
    monkeypatch.setattr(module, 'rank', forbidden)
    analyze(evidence, tmp_path / 'out')


def test_multi_barcode_ranks_lower_without_forcing_identity(evidence):
    data = json.loads((evidence / RECON).read_text())['records']
    ambiguous = json.loads(json.dumps(data[0]))
    ambiguous['asin'] = 'B000Q3KHCM'
    ambiguous['amazon_product']['asin'] = ambiguous['asin']
    ambiguous['amazon_product']['identifiers'].append(dict(identifier_type='UPC', value='026000003049', normalized_gtin='00026000003049'))
    rows = rank(data + [ambiguous], [])
    assert rows[0]['asin'] == 'B003SI0TD4'
    assert 'single_canonical_gtin' in rows[1]['amazon_gaps']
    assert all(not row['verified_exact_match'] for row in rows)
