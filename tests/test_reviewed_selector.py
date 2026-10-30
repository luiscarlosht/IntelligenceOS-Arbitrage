from app.candidate_quality import review_candidates
from decimal import Decimal


def test_different_titles_explicit_evidence_and_ties():
    source = dict(name='Energizer MAX AAA batteries 8 pack', source_context=dict(brand='Energizer'))
    candidates = [dict(asin=a, rank=i, title='Energizer AAA MAX 8 pack alkaline batteries')
                  for i, a in enumerate(('B004U42A28', 'B0D51H9LQP'), 1)]
    result = review_candidates(source, dict(candidates=candidates))
    assert result['selected_asin'] is None
    assert len(result['plausible_asins']) == 2
    result = review_candidates(source, dict(candidates=candidates[:1]))
    assert result['selected_asin'] == 'B004U42A28'
    assert result['exact'] is False


def test_conflicts_and_unknowns_retained():
    source = dict(name='Energizer AAA 8 pack', source_context=dict(brand='Energizer'))
    result = review_candidates(source, dict(candidates=[dict(asin='B004U429ME', rank=1, title='Energizer AA 8 pack')]))
    assert result['selected_asin'] is None
    assert result['candidates'][0]['differences']
    assert result['candidates'][0]['missing_evidence']



def test_pack_word_order_does_not_create_conflict():
    source = dict(name='Energizer AAA 8 pack', source_context=dict(brand='Energizer'))
    result = review_candidates(source, dict(candidates=[dict(asin='B004U42A28', rank=1, title='Energizer AAA pack of 8')]))
    assert result['selected_asin'] == 'B004U42A28'


def test_source_neutral_report_keeps_observed_walmart_price(tmp_path):
    from test_candidate_review_report import saved_fixture
    from app.candidate_review_report import build_review
    from app.reporting import write_report
    from openpyxl import load_workbook
    report, *_ = saved_fixture(tmp_path)
    report['rows'][0]['source'].update(retailer='Walmart', purchase_price='7.94')
    rows, review, enrichments = build_review(report)
    assert review['comparisons'][0]['observed_item_price'] == Decimal('7.94')
    assert rows[0]['acquisition_cost'] is None
    destination = tmp_path/'neutral.xlsx'
    write_report(rows, destination, discovery=True, candidate_review=review, enrichment_rows=enrichments)
    workbook = load_workbook(destination)
    assert workbook['Candidate Comparison']['A1'].value == 'Source Title'
    workbook.close()
