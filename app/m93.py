"""Amazon-first selection from pinned retained evidence; entirely offline."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile

from openpyxl import Workbook

from app.evidence_io import json_write, offline, publication
from app.m78_reporting import cell
from app.m89 import rank
from app.m91 import BASE as M91_BASE
from app.m92 import BASE, build as review
from app.product_analysis import assess, usable, reference

UNKNOWN = 'UNKNOWN'
CATEGORIES = ('RESEARCH_PRIORITY', 'ELIGIBILITY_UNKNOWN', 'INELIGIBLE',
              'INSUFFICIENT_EVIDENCE', 'VERIFIED_PROFITABLE')


def seller_screen(record: dict, now: datetime) -> dict:
    """Catalog/public evidence cannot assert seller permission, even when verified."""
    result = {}
    for key in ('listing_new', 'approval_required', 'fba', 'restrictions'):
        item = deepcopy(record.get('seller_evidence', {}).get(key, {}))
        scoped = (item.get('evidence_type') == 'SELLER_ACCOUNT'
                  and reference(item.get('seller_scope_reference'))
                  and item.get('asin') == record['asin']
                  and item.get('condition') == 'New'
                  and item.get('marketplace') == 'ATVPDKIKX0DER')
        value = item.get('value', UNKNOWN)
        # Preserve scoped adverse observations even after freshness expires.
        adverse = ((key in ('listing_new', 'fba') and value == 'INELIGIBLE')
                   or (key == 'approval_required' and value is True)
                   or (key == 'restrictions' and value not in (UNKNOWN, '', [], None)))
        valid_value = (value in ('ELIGIBLE', 'INELIGIBLE', UNKNOWN) if key in ('listing_new', 'fba')
                       else type(value) is bool if key == 'approval_required'
                       else isinstance(value, (str, list)))
        try:
            observed = datetime.fromisoformat(item.get('observed_at', ''))
            attributed_adverse = (observed.utcoffset() is not None and observed <= now
                                  and reference(item.get('source')) and reference(item.get('source_reference')))
        except (ValueError, TypeError):
            attributed_adverse = False
        supported = scoped and valid_value and (usable(item, now) or adverse and attributed_adverse)
        result[key] = dict(value=value if supported else UNKNOWN,
                           source=item.get('source', UNKNOWN),
                           observed_at=item.get('observed_at', UNKNOWN),
                           evidence=item, supported=bool(supported))
    return result


def screen(record: dict, now: datetime) -> dict:
    analysis = assess(record, now)
    seller = seller_screen(record, now)
    values = {k: v['value'] for k, v in seller.items()}
    scopes = {v['evidence'].get('seller_scope_reference') for v in seller.values() if v['supported']}
    same_seller = len(scopes) == 1
    restricted = (values['listing_new'] == 'INELIGIBLE' or values['fba'] == 'INELIGIBLE'
                  or values['approval_required'] is True
                  or values['restrictions'] not in (UNKNOWN, '', [], None))
    eligible = (same_seller and values['listing_new'] == values['fba'] == 'ELIGIBLE'
                and values['approval_required'] is False and values['restrictions'] in ('', []))
    verified = (eligible and analysis['match_confidence'] == 'EXACT'
                and analysis['decision'] == 'BUY_CANDIDATE'
                and analysis['financial_assessment_by_mode']['FBA'] == 'PROMISING'
                and all(s.get('passes') for s in analysis['financials']['FBA'].values())
                and not record.get('is_mock') and not record.get('is_synthetic'))
    outcome = ('INELIGIBLE' if restricted else 'ELIGIBILITY_UNKNOWN' if not eligible else
               'VERIFIED_PROFITABLE' if verified else 'INSUFFICIENT_EVIDENCE')
    return dict(outcome=outcome, seller_eligibility=seller, analysis=analysis,
                economics_status='VERIFIED_PROFITABLE' if verified else 'INSUFFICIENT_EVIDENCE',
                purchase_authorized=False)


def build(now: datetime, limit: int = 30) -> dict:
    if now.utcoffset() is None or type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError('Aware evaluation time and limit 1..30 required')
    prior = review(now)  # Revalidate pins, source inventory and all 60 pair reviews.
    pairs = prior['records']
    amazon_rows = rank([dict(asin=r['asin'], amazon_product=r['input_evidence']['identity']['amazon_product'],
                            walmart_item_id=r['walmart_product']['walmart_item_id'],
                            classification=r['identity_verdict'],
                            remaining_gaps=r['identity_review']['remaining_gaps'], source_exceptions=[])
                        for r in pairs], [])
    rows = []
    for lead in amazon_rows:
        related = [r for r in pairs if r['asin'] == lead['asin']]
        record = deepcopy(related[0]['input_evidence'])
        # Amazon identity is selected before consulting prior Walmart pair outcomes.
        record['identity']['amazon_product'] = deepcopy(lead['amazon_evidence'])
        result = screen(record, now)
        analysis = result.pop('analysis')
        row = dict(asin=lead['asin'], research_rank=lead['research_priority'],
                   screening_priority='RESEARCH_PRIORITY',
                   **{key: lead['amazon_evidence'].get(key, UNKNOWN) for key in
                      ('title', 'brand', 'model', 'manufacturer_part_number', 'identifiers',
                       'variation', 'size', 'pack_quantity', 'source', 'source_reference', 'observed_at')},
                   identity=lead['amazon_evidence'],
                   identity_gaps=lead['amazon_gaps'], canonical_gtins=lead['canonical_gtins'],
                   evidence_temporality='HISTORICAL_RETAINED_OBSERVATION_NOT_CURRENT_VERIFICATION',
                   amazon_price=dict(value=UNKNOWN, source=UNKNOWN, observed_at=UNKNOWN),
                   competition=dict(value=UNKNOWN, source=UNKNOWN, observed_at=UNKNOWN),
                   demand=dict(value=UNKNOWN, source=UNKNOWN, observed_at=UNKNOWN),
                   walmart_exact_match_status='UNRESOLVED' if any(r['identity_verdict'] != 'REJECTED' for r in related)
                                              else 'REJECTED_RETAINED_PAIRS_ONLY',
                   walmart_pairs=[dict(walmart_item_id=r['walmart_product']['walmart_item_id'],
                       identity_verdict=r['identity_verdict'], review=r['identity_review'],
                       continuation=r.get('continuation_review')) for r in related],
                   costs=analysis['base_inputs']['FBA'], scenarios=analysis['financials']['FBA'],
                   net_profit=analysis['financials']['FBA']['base']['net_profit'],
                   roi_percent=analysis['financials']['FBA']['base']['roi_percent'],
                   missing_evidence=sorted(set(analysis['missing_information'] + lead['amazon_gaps'] +
                       ['Seller-specific New listing eligibility', 'Approval requirement', 'FBA eligibility and restrictions',
                        'Amazon New selling price', 'Demand and New seller competition'])),
                   recommended_next_action='Obtain separately authorized seller-specific New listing, approval and FBA evidence before Walmart sourcing; resolve identity and complete fresh costs.',
                   **result)
        rows.append(row)
    selected = rows[:limit]
    return dict(schema='m93_amazon_first_selection_v1', evaluated_at=now.isoformat(),
                retained_distinct_asins=len(rows), selected_research_leads=len(selected),
                defensible_opportunities=0, verified_profitable=0,
                evidence_gap='Zero defensible promising selling opportunities: Amazon price, demand, competition and seller eligibility absent. Up to 30 identity-ranked research leads only; no profitability ranking is supported.',
                ranking_basis='M89 Amazon identity completeness, typed package attributes, ASIN; seller eligibility and economics must precede further sourcing',
                categories=list(CATEGORIES), outcome_counts=dict(Counter(r['outcome'] for r in selected)),
                thresholds=dict(net_profit='5', acquisition_roi_percent='50'),
                records=selected, unselected_asins=[r['asin'] for r in rows[limit:]],
                source_inventory=prior['source_inventory'], purchase_authorized=False,
                additional_network_requests=0)


def run(output: Path, now: datetime, limit: int = 30) -> dict:
    with publication(output, [BASE, M91_BASE]) as stage:
        previous = tempfile.tempdir
        try:
            tempfile.tempdir = str(stage)
            with offline(reads=[BASE, M91_BASE], writes=[stage]):
                report = build(now, limit)
                json_write(stage/'amazon-candidates.json', report)
                wb = Workbook(); wb.remove(wb.active)
                evidence_sheet = wb.create_sheet('Detailed Evidence')
                evidence_sheet.append(['record', 'field', 'part', 'json_fragment'])
                for title, records in [('Ranked Candidates', report['records']),
                                       ('Source Inventory', report['source_inventory'])]:
                    sheet = wb.create_sheet(title)
                    fields = list(records[0]) if records else []
                    sheet.append(fields); sheet.freeze_panes = 'B2'
                    for row in records:
                        values = []
                        for key in fields:
                            value = row.get(key, UNKNOWN)
                            serialized = json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
                            if isinstance(serialized, str) and len(serialized) > 30000:
                                reference = row.get('asin', title)
                                for part, offset in enumerate(range(0, len(serialized), 30000), 1):
                                    evidence_sheet.append([cell(reference), key, part, cell(serialized[offset:offset+30000])])
                                value = 'See Detailed Evidence: '+str(reference)+' / '+key
                            values.append(cell(value))
                        sheet.append(values)
                    sheet.auto_filter.ref = sheet.dimensions
                # Separate tabs make the screening/outcome distinction explicit.
                for category in CATEGORIES:
                    sheet = wb.create_sheet(category)
                    sheet.append(['asin', 'research_rank', 'outcome', 'next_action'])
                    for row in report['records']:
                        if category == row['outcome'] or category == row['screening_priority']:
                            sheet.append([cell(row[k]) for k in ('asin', 'research_rank', 'outcome', 'recommended_next_action')])
                wb.save(stage/'amazon-candidates.xlsx')
                (stage/'amazon-candidates.xlsx').chmod(0o600)
                (stage/'evidence-gap.md').write_text('# M93 evidence gap\n\n'+report['evidence_gap']+'\n\n'
                    f"Retained ASINs: {report['retained_distinct_asins']}; research leads: {report['selected_research_leads']}.\n"
                    'All eligibility outcomes are UNKNOWN. All profit and ROI values are UNKNOWN. '
                    'Catalog quantities do not prove sellable-pack contents. Historical Walmart prices are retained in pair evidence only, not acquisition inputs. '
                    'Prior pair rejections do not reject the ASIN for every possible Walmart product. '
                    'No new collection is authorized by this report.\n')
                (stage/'evidence-gap.md').chmod(0o600)
                if report != build(now, limit):
                    raise ValueError('Evidence changed during reporting')
        finally:
            tempfile.tempdir = previous
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--as-of')
    parser.add_argument('--limit', type=int, default=30)
    args = parser.parse_args()
    run(args.output, datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc), args.limit)


if __name__ == '__main__':
    main()
