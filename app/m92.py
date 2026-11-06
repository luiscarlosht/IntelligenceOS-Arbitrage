"""Offline review of every M91 pair and evidence-gated FBA profitability POC."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from openpyxl import load_workbook
from app.amazon_evaluation import COSTS
from app.evidence_io import digest, json_write, offline, pinned, publication
from app.m70_sources import strict_json
from app.m78_reporting import cell
from app.m88_evidence import match
from app.m88_reconcile import classify, equality, validate
from app.m91 import BASE as M91_BASE, build as baseline
from app.product_analysis import comparison, workbook
from app.walmart_evidence import normalize

BASE = Path(__file__).resolve().parents[1] / 'evidence/m92'
DFW_ZIP = '76063'


def checklist(best: dict) -> list[dict]:
    return [dict(priority=i, candidate_id=best['candidate_id'], asin=best['asin'], required=evidence,
                 status='EXTERNAL_EVIDENCE_REQUIRED_NOT_COLLECTED') for i, evidence in enumerate([
        "Save independent Walmart 17011265 and Amazon B000Q3KHCM field-level captures with URLs, aware timestamps, original files/hashes and reviewer signoff. Screenshot references alone are insufficient.",
        "Establish outer sellable-pack UPC applicability: Walmart 026000003049 overlaps one of three Amazon canonical alternatives. Resolve Walmart model SAP_2089725 / MPN 2089725 versus Amazon model/MPN E304 with manufacturer evidence; do not infer an alias.",
        "Independently confirm brand, one 4 fl oz bottle, formulation, selected variation and package count on each side. Resolve Amazon White color / Clear included-components wording; confirm condition New from an actual offer, not Catalog metadata. Pass unchanged exact-identity and freshness gates.",
        "Use DFW Mansfield TX 76063 delivery context. Capture Walmart seller/fulfiller, quantity, availability, item price, shipping, applicable tax and quantity limits there, without purchasing. ZIP alone does not establish tax jurisdiction/rate. Sacramento CA 95829 observations are historical only and cannot establish DFW landed cost.",
        "For FBA first, retain a fresh supported New selling price for this exact ASIN, marketplace and quantity. Obtain referral and fulfillment fee evidence bound to that price and mode; also placement, inbound shipping, prep, packaging, storage, tax, returns allowance, transaction and other costs. Document explicit zero values; never assume zero. Supply all scenarios required by existing product_analysis.",
        "Obtain separate seller-specific listing and FBA eligibility plus scoped demand/competition evidence. Catalog and UPC overlap establish neither condition nor eligibility.",
        "Rerun existing product_analysis with complete fresh evidence and unchanged $5/unit profit and 50% acquisition ROI gates. Only then can net profit, ROI and margins be supported. FBM is deferred. No purchase authorization follows."
    ], 1)]


def build(now: datetime, base: Path = BASE, m91_base: Path = M91_BASE) -> dict:
    if now.utcoffset() is None:
        raise ValueError('Aware evaluation clock required')
    pins = strict_json(base / 'pins.json')
    if digest(m91_base / 'pins.json') != pins['m91_pins_sha256']:
        raise ValueError('M91 baseline pins changed')
    old = baseline(m91_base)  # Verify original intake and every M91 artifact.
    inventory = deepcopy(old['source_inventory'])
    documents = {}
    for item in pins['artifacts']:
        if Path(item['path']).name != item['path'] or item['kind'] not in ('REAL_SAVED_RESEARCH', 'DERIVED_OFFLINE_REVIEW'):
            raise ValueError('Pinned research/review artifacts required')
        doc = pinned(base / item['path'], item['sha256'])
        if doc.get('is_mock') or doc.get('is_synthetic'):
            raise ValueError('Synthetic evidence forbidden')
        documents[item['path']] = doc
        inventory.append(dict(item, status='HASH_VERIFIED_SAVED_ARTIFACT'))
    intake = strict_json(m91_base / 'six-product-manifest.json')
    enriched = documents['walmart-identity-enrichment-original.json']
    validate(enriched, intake)
    normalized = normalize(intake)
    by_id = {r['identity']['retailer_product']['walmart_item_id']: r for r in normalized['candidates']}
    intake_rows = {r['walmart_product']['walmart_item_id']: r for r in intake['observations']}
    source_rows = {r['walmart_item_id']: r for r in enriched['observations']}
    review_doc = documents['offline-review.json']
    if review_doc['kind'] != 'DERIVED_OFFLINE_REVIEW':
        raise ValueError('Review must be distinguished from source observations')
    reviews = {(r['walmart_item_id'], r['asin']): r for r in review_doc['rejections']}
    if len(reviews) != len(review_doc['rejections']):
        raise ValueError('Duplicate pair review')
    details = {}
    for name, doc in documents.items():
        if name.startswith('receipt-'):
            product = doc['evidence']['product']
            if doc['phase'] != 'detail' or doc['candidate_id'].split(':')[-1] not in by_id:
                raise ValueError('Detail receipt scope mismatch')
            details[product['asin']] = (name, product)
    candidates = []
    seen_reviews = set()
    for file in sorted(m91_base.glob('receipt-*.json')):
        receipt = strict_json(file)
        item_id = receipt['candidate_id'].split(':')[-1]
        original = by_id[item_id]
        if receipt['phase'] != 'search' or receipt['candidate_id'] != original['candidate_id']:
            raise ValueError('Search receipt scope mismatch')
        source = source_rows[item_id]
        for saved in receipt['evidence']['candidates']:
            search_product = saved['product']
            detail_name, amazon = details.get(search_product['asin'], (None, search_product))
            if amazon.get('is_mock') or amazon.get('is_synthetic'):
                raise ValueError('Synthetic product forbidden')
            review = classify(source, dict(product=amazon), enriched['review'])
            # Detail observations retain independent MPNs; do not report them missing.
            mpn = amazon.get('manufacturer_part_number', 'UNKNOWN')
            if mpn not in ('', 'UNKNOWN'):
                review['remaining_gaps'].remove('Amazon manufacturer part number not retained; do not relabel model as MPN')
                review['comparisons']['mpn'].update(amazon=mpn, status=equality(source['mpn'], mpn))
                if equality(source['mpn'], mpn) != 'MATCH':
                    review['remaining_gaps'].append('Independent manufacturer part numbers differ; alias correspondence unverified')
            annotation = reviews.get((item_id, amazon['asin']))
            if annotation:
                if annotation['amazon_title'] != search_product['title'] or annotation['amazon_size'] != search_product['size']:
                    raise ValueError('Offline review differs from saved observation')
                review['classification'] = 'REJECTED'
                review['decisive_contradictions'].append(annotation['reason'])
                seen_reviews.add((item_id, amazon['asin']))
            record = deepcopy(original)
            retailer = record['identity']['retailer_product']
            # New source observations are separate and unverified, never Amazon-derived.
            retailer.update(brand=source['brand'], gtin=source['upc'], model=source['model'],
                            variation=source['selected_variant'], observed_at=source['observed_utc'],
                            pack_description=source['sellable_pack'], verified=False,
                            source_reference='walmart-identity-enrichment-original.json#'+item_id)
            record.update(candidate_id=original['candidate_id']+':'+amazon['asin'], asin=amazon['asin'])
            record['identity']['amazon_product'] = deepcopy(amazon)
            record['input_conflicts'] = sorted(set(review['remaining_gaps'] + review['decisive_contradictions'] +
                ['Independent Walmart signoff absent', 'Sellable-pack equivalence unverified', 'Offer condition New unverified']))
            # Keep observed Sacramento cost as evidence only, remove it from actionable DFW inputs.
            historical_acquisition = deepcopy(intake_rows[item_id]['acquisition'])
            record['financials'] = {'FBA': {'base': {k: {'value': 'UNKNOWN'} for k in COSTS + ('retailer_shipping', 'selling_price')}}}
            strict_gate = match(retailer, amazon, now)
            record['identity_review'] = dict(review, strict_gate=strict_gate,
                walmart_enrichment=deepcopy(source), original_walmart=deepcopy(original['identity']['retailer_product']),
                historical_acquisition=historical_acquisition, search_receipt=file.name,
                detail_receipt=detail_name, original_amazon_search_observation=search_product,
                condition=dict(required='New', walmart='UNKNOWN', amazon_offer='UNKNOWN'),
                sourcing=dict(required='DFW Mansfield TX '+DFW_ZIP, required_zip=DFW_ZIP,
                              observed=enriched['delivery_context'], verified=False),
                evidence_kind='REAL_SAVED_RESEARCH', review_kind='DERIVED_OFFLINE_REVIEW')
            candidates.append(record)
    if seen_reviews != set(reviews) or len(candidates) != 60 or len({r['candidate_id'] for r in candidates}) != 60:
        raise ValueError('All sixty original pairs and all scoped reviews required')
    def priority(record: dict) -> tuple:
        r = record['identity_review']; c = r['comparisons']
        return (r['classification'] == 'REJECTED', not c['upc']['overlap'],
                len(r['walmart_enrichment'].get('conflicts', [])),
                -sum(c[k].get('status') == 'MATCH' for k in ('brand', 'model', 'mpn', 'variant')),
                len(r['remaining_gaps']), r['walmart_item_id'], r['asin'])
    candidates.sort(key=priority)
    report = comparison(dict(schema='walmart_product_analysis_input_v1', expected_candidates=60,
        candidates=candidates, source_inventory=inventory,
        recovery_blockers=['No independently verified exact pair; DFW sourcing and complete FBA economics absent']), now)
    by_key = {r['candidate_id']: r for r in report['records']}
    report['records'] = [by_key[r['candidate_id']] for r in candidates]
    for rank, row in enumerate(report['records'], 1):
        row['rank'] = rank
        row['identity_review'] = row['input_evidence']['identity_review']
        row['identity_verdict'] = row['identity_review']['classification']
        row['eligibility_verdict'] = dict(listing='UNKNOWN', FBA='UNKNOWN')
        row['economics_verdict'] = 'INSUFFICIENT_EVIDENCE'
        row['final_decision'] = ('REJECTED_IDENTITY' if row['identity_verdict'] == 'REJECTED'
                                 else 'INSUFFICIENT_EVIDENCE')
        row['poc_decision'] = row['final_decision']
        row['selected_mode'] = 'FBA'
        row['deferred_mode'] = 'FBM'
        row['missing_information'] = sorted(set(row['missing_information'] + row['input_evidence']['input_conflicts'] +
            ['DFW 76063 destination-specific acquisition evidence', 'Condition New independently evidenced', 'Seller and FBA eligibility evidence']))
    best = next(r for r in report['records'] if r['identity_verdict'] != 'REJECTED')
    counts = dict(Counter(r['identity_verdict'] for r in report['records']))
    report.update(schema='m92_real_product_profitability_v1',
        ranking_basis='IDENTITY_EVIDENCE_ONLY',
        ranking_limitation='Non-rejected pairs, barcode overlap, fewest source conflicts, most equal observed fields, fewest identity gaps, IDs; no price/profit ranking',
        best_candidate=dict(candidate_id=best['candidate_id'], walmart_item_id=best['walmart_product']['walmart_item_id'],
                            asin=best['asin'], identity_verdict=best['identity_verdict'], economics_verdict=best['economics_verdict'],
                            decision=best['poc_decision']),
        pair_counts=counts, additional_network_requests=0, synthetic_records=0,
        rejected_alternatives=[dict(candidate_id=r['candidate_id'], asin=r['asin'], walmart_item_id=r['walmart_product']['walmart_item_id'],
            final_decision=r['final_decision'], reasons=r['identity_review']['decisive_contradictions'])
            for r in report['records'] if r['identity_verdict']=='REJECTED'],
        m93_ready=False, m93_blockers=['Verified exact identity', 'DFW landed acquisition cost', 'Complete fresh FBA economics and eligibility'],
        pins_sha256=digest(base/'pins.json'))
    report['evidence_collection_checklist'] = checklist(best)
    research = documents.get('continuation-review.json')
    if research:
        if research.get('schema') != 'm92_continuation_review_v1':
            raise ValueError('M92 continuation review schema required')
        expected = [('17011265', 'B000Q3KHCM'), ('721324153', 'B07GQ1CT47'),
                    ('13952053139', 'B003SI0TD4')]
        if [(r['walmart_item_id'], r['asin']) for r in research['candidates']] != expected:
            raise ValueError('Ordered M92 continuation candidates required')
        report['continuation_review'] = research
        report['m92_complete'] = False
        report['closure_status'] = 'INSUFFICIENT_EVIDENCE'
        report['network_collection'] = 'No network collection in this continuation; earlier public captures retained separately'
        report['additional_network_requests_scope'] = 'Offline report generation only; public collection is retained separately'
        report['evidence_collection_checklist'] += [dict(priority=i+8,
            candidate_id='ALL_THREE_REMAINING_CANDIDATES', asin='SEE_CONTINUATION_REVIEW',
            required=task, status='MISSING_EVIDENCE') for i, task in enumerate(research['collection_plan'])]
        for row in report['records']:
            review = next((r for r in research['candidates'] if
                (r['walmart_item_id'], r['asin']) == (row['walmart_product']['walmart_item_id'], row['asin'])), None)
            if review:
                review.update(eligibility_verdict=row['eligibility_verdict'],
                    economics_verdict=row['economics_verdict'], final_decision=row['final_decision'],
                    missing_evidence=row['missing_information'], scenarios=row['financials']['FBA'],
                    cost_breakdown=row['base_inputs']['FBA'])
                review['public_offer_context']['required_destination_zip'] = DFW_ZIP
                row['continuation_review'] = review
    plan = documents.get('completion-plan.json')
    if plan:
        if plan.get('schema') != 'm92_completion_plan_v1' or plan['delivery_context']['zip'] != DFW_ZIP:
            raise ValueError('M92 completion plan for reference ZIP 76063 required')
        report.update(collection_plan=plan, delivery_context=plan['delivery_context'],
                      decision_classifications=plan['decision_classifications'],
                      final_decision_counts=dict(Counter(r['final_decision'] for r in report['records'])))
        report['evidence_collection_checklist'] = [dict(t, candidate_id=t['scope'], asin=t['scope'],
            required=t['fields']) for t in plan['tasks']]
        if research:
            research['classification_note'] = 'User-supplied final decision taxonomy; identity, eligibility and economics retained separately.'
            research['collection_plan'] = plan['tasks']
    return report


def run(output: Path, now: datetime, base: Path = BASE, m91_base: Path = M91_BASE) -> dict:
    with publication(output, [base, m91_base]) as stage:
        previous = tempfile.tempdir
        try:
            tempfile.tempdir = str(stage)
            with offline(reads=[base, m91_base], writes=[stage]):
                report = build(now, base, m91_base)
                json_write(stage/'comparison.json', report)
                workbook(report, stage/'comparison.xlsx')
                wb = load_workbook(stage/'comparison.xlsx')
                if 'continuation_review' in report:
                    sheet = wb.create_sheet('M92 Decision Report')
                    sheet.append(['walmart_item_id', 'asin', 'identity_status', 'eligibility_verdict',
                                  'economics_verdict', 'final_decision',
                                  'findings', 'missing_evidence', 'public_offer_context'])
                    sheet.freeze_panes = 'C2'
                    for row in report['continuation_review']['candidates']:
                        sheet.append([cell(row[k]) for k in ('walmart_item_id', 'asin',
                            'identity_status', 'eligibility_verdict', 'economics_verdict', 'final_decision',
                            'findings', 'missing_evidence', 'public_offer_context')])
                for title, fields, rows in [
                    ('Identity Review', ('rank','candidate_id','asin','identity_verdict','eligibility_verdict',
                                         'economics_verdict','final_decision','identity_review'), report['records']),
                    ('Rejected Alternatives', ('walmart_item_id','asin','final_decision','reasons'), report['rejected_alternatives']),
                    ('Evidence Collection', ('priority','candidate_id','asin','required','status','sources',
                                             'authorization_required'), report['evidence_collection_checklist'])]:
                    sheet = wb.create_sheet(title); sheet.append(list(fields)); sheet.freeze_panes='B2'
                    for row in rows:
                        sheet.append([cell(row.get(k, 'UNKNOWN')) for k in fields])
                wb.save(stage/'comparison.xlsx')
                text = '# M92 evidence collection — Mansfield TX 76063\n\nNo new network or account access is authorized. M92 remains open.\n\n' + '\n\n'.join(
                    f"{r['priority']}. {r['required']}\n\n   Sources: {', '.join(r.get('sources', []))}\n\n"
                    f"   Authorization: {r.get('authorization_required', 'Separate authorization required')}"
                    for r in report['evidence_collection_checklist'])
                (stage/'evidence-collection.md').write_text(text+'\n')
                (stage/'evidence-collection.md').chmod(0o600)
                if build(now, base, m91_base) != report:
                    raise ValueError('Evidence changed during reporting')
        finally:
            tempfile.tempdir = previous
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--as-of', help='Aware evaluation timestamp; defaults to current UTC')
    args = parser.parse_args()
    run(args.output, datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc))


if __name__ == '__main__':
    main()
