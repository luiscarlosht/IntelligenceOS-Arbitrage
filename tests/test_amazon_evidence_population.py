from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from app.amazon_evidence_population import cohort, main, prepare, report, evaluation_proposal
from app.amazon_research_queue import ORIGINAL_ASINS
from app.amazon_evaluation_sheets import HEADERS, seed

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
ASIN = ORIGINAL_ASINS[0]


def observation(**extra):
    return dict(source='Owner manual Seller Central', source_reference='private:screen-1',
        observed_at=NOW.isoformat(), verified=True, confidence='HIGH',
        seller_alias='owner', marketplace='ATVPDKIKX0DER', condition='New', **extra)


def test_empty_twenty_complete_gap_report():
    result = report([dict(asin=ASIN)], 'owner', NOW)
    assert result['coverage']['asins'] == 20
    assert result['coverage']['decisions'] == {'BLOCKED': 20}
    assert result['coverage']['populated_records'] == 0
    assert result['coverage']['eligibility_screen_first'] == 20
    assert all(n == 0 for n in result['coverage']['complete_by_group'].values())
    assert result['requests'] == []
    assert all(all(r['gaps'].values()) for r in result['records'])


def test_scope_freshness_and_verification_do_not_mutate_original():
    original = dict(asin=ASIN, eligibility=observation(status='ELIGIBLE'))
    saved = deepcopy(original)
    assert report([original], 'owner', NOW)['records'][0]['next_action'] == 'DETAILED_RESEARCH'
    for field, bad in [('seller_alias', 'other'), ('marketplace', 'other'), ('condition', 'Used'),
                       ('source_reference', 'UNKNOWN'), ('verified', False),
                       ('observed_at', '2026-10-01T00:00:00+00:00'), ('confidence', 'UNKNOWN')]:
        row = deepcopy(original)
        row['eligibility'][field] = bad
        result = report([row], 'owner', NOW)['records'][0]
        assert result['decision'] == 'BLOCKED'
        assert result['next_action'] == 'ELIGIBILITY_SCREEN_FIRST'
        assert result['validation_issues']
    assert original == saved


def test_restrictions_preserved_and_no_rank_or_mixed_offer_conversion():
    row = dict(asin=ASIN, eligibility=dict(status='APPROVAL_REQUIRED'), market={
        'sales_rank': observation(value=435),
        'competing_offers': observation(value=9, basis='mixed_used_new')})
    result = report([row], 'owner', NOW)['records'][0]
    assert result['decision'] == 'BLOCKED'
    assert result['gaps']['demand'] and result['gaps']['competing_offers']
    assert result['analysis']['eligibility']['status'] == 'APPROVAL_REQUIRED'


def test_bad_demand_and_conflicting_evidence():
    row = dict(asin=ASIN, market={'monthly_sales': observation(value=True, basis='authorized_sales')},
               input_conflicts=['visible restriction'])
    result = report([row], 'owner', NOW)['records'][0]
    assert result['gaps']['demand']
    assert result['decision'] == 'BLOCKED'


def test_identity_and_money_invalidated_without_reference():
    row = dict(asin=ASIN, identity={'amazon_product': observation(value='unused')},
        financials={'FBA': {'base': {'purchase': observation(value='10', currency='USD')}}})
    del row['financials']['FBA']['base']['purchase']['source_reference']
    clean, issues = prepare(row, 'owner', NOW)
    assert clean['financials']['FBA']['base']['purchase']['value'] == 'UNKNOWN'
    assert 'financials.FBA.base.purchase.source_reference' in issues


class ReadOnly:
    def __init__(self, existing=None):
        self.existing = existing or []
    def select(self, workbook):
        pass
    def metadata(self):
        return {'sheets': [{'properties': dict(title='Amazon_Evaluation', sheetId=7,
            gridProperties=dict(rowCount=2002, columnCount=30))}]} if self.existing else {'sheets': []}
    def request(self, path, *args):
        assert not args and path.startswith('values/')
        return {'values': self.existing}


def test_proposal_separate_preserves_rows_and_does_not_publish():
    row = dict(asin=ASIN, eligibility=observation(status='ELIGIBLE'))
    proposal = evaluation_proposal(ReadOnly(), [row], 'owner', NOW)
    assert proposal['publication_authorized'] is False
    assert proposal['requests'][0]['addSheet']['properties']['title'] == 'Amazon_Evaluation'
    existing = [HEADERS, seed(row)+['custom']]
    saved = deepcopy(existing)
    assert evaluation_proposal(ReadOnly(existing), [row], 'owner', NOW)['requests'] == []
    assert saved == existing


def test_proposed_unverified_data_is_unknown_with_audit_original():
    row = dict(asin=ASIN, eligibility=dict(status='ELIGIBLE'))
    proposal = evaluation_proposal(ReadOnly(), [row], 'owner', NOW)
    cells = proposal['requests'][-1]['updateCells']['rows'][0]['values']
    imported = json.loads(cells[23]['userEnteredValue']['stringValue'])
    assert imported['eligibility']['status'] == 'UNKNOWN'
    assert imported['manual_import_audit']['original_evidence'] == row


def test_cohort_rejects_unknown_duplicates_and_naive_time(tmp_path):
    with pytest.raises(ValueError):
        cohort([dict(asin='B000000000')])
    with pytest.raises(ValueError):
        cohort([dict(asin=ASIN), dict(asin=ASIN)])
    with pytest.raises(ValueError):
        report([dict(asin=ASIN)], 'owner', NOW.replace(tzinfo=None))
    target = tmp_path/'report.json'
    main(['--seller-alias', 'owner', '--as-of', NOW.isoformat(), '--output', str(target)])
    assert len(json.loads(target.read_text())['records']) == 20
    with pytest.raises(FileExistsError):
        main(['--seller-alias', 'owner', '--output', str(target)])


def test_complete_scoped_manual_record_reuses_existing_engine():
    from test_analysis_engine import verified
    from test_amazon_evaluation import NOW as fixture_now
    from app.analysis_engine import analyze_record
    row = verified()
    old_asin = row['asin']
    row['asin'] = ASIN

    def scope(node):
        if not isinstance(node, dict):
            return
        if node.get('asin') == old_asin:
            node['asin'] = ASIN
        if node.get('url') == 'https://www.amazon.com/dp/'+old_asin:
            node['url'] = 'https://www.amazon.com/dp/'+ASIN
        if 'observed_at' in node:
            node.update(seller_alias='owner', marketplace='ATVPDKIKX0DER', condition='New',
                        verified=True, source='Synthetic test reference', source_reference='test:only')
        for value in node.values():
            scope(value)
    scope(row)
    result = report([row], 'owner', fixture_now)['records'][0]
    assert result['validation_issues'] == []
    assert not any(result['gaps'].values())
    assert result['decision'] == analyze_record(row, fixture_now)['decision'] == 'BUY_CANDIDATE'
    assert not result['analysis']['purchase_authorized']
    row['financials']['FBA']['conservative']['purchase']['observed_at'] = 'UNKNOWN'
    result = report([row], 'owner', fixture_now)['records'][0]
    assert result['gaps']['acquisition_costs']
    assert not result['analysis']['financials']['FBA']['conservative']['complete']


def test_proposal_cell_bound():
    row = dict(asin=ASIN, notes='x'*49001)
    with pytest.raises(ValueError, match='cell bound'):
        evaluation_proposal(ReadOnly(), [row], 'owner', NOW)
