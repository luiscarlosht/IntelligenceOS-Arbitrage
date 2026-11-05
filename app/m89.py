"""Amazon-first offline sourcing queue. No executor or credential access."""
import argparse
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from app.evidence_io import digest, json_write, offline, pinned, publication, safe
from app.m88_identity import barcode_evidence
from app.m78_reporting import write
from app.product_analysis import comparison, workbook

RECON = '20261105T033415756534Z-reconciliation-analysis-v2/candidate-reconciliation.json'
DETAIL = 'm88-targeted-verification-v1-analysis/targeted-evidence.json'
LEDGER = '20261105T022741571627Z/amazon-http-attempt-ledger.json'


def rank(records: list[dict], details: list[dict]) -> list[dict]:
    """Completeness first; package clarity proxy, never Walmart availability proof."""
    products = {}
    history = {}
    for row in records:
        asin = row['asin']
        products.setdefault(asin, deepcopy(row['amazon_product']))
        history.setdefault(asin, []).append({k: deepcopy(row[k]) for k in
            ('walmart_item_id', 'classification', 'remaining_gaps', 'source_exceptions')})
    for row in details:
        product = row['evidence']['product']
        if product['asin'] not in products:
            raise ValueError('Targeted ASIN outside saved population')
        products[product['asin']] = deepcopy(product)
    ranked = []
    for asin, product in products.items():
        barcodes = barcode_evidence(product)
        gtins = barcodes['distinct_canonical_gtins']
        fields = {k: bool(product.get(k)) and product[k] != 'UNKNOWN' for k in
                  ('brand', 'model', 'size', 'variation', 'pack_quantity')}
        fields['single_canonical_gtin'] = len(gtins) == 1 and not barcodes['invalid_identifiers']
        fields['manufacturer_part_number'] = product.get('manufacturer_part_number', 'UNKNOWN') not in ('', 'UNKNOWN', None)
        fields['pack_quantity'] = type(product.get('pack_quantity')) is int and product['pack_quantity'] > 0
        gaps = [k for k, present in fields.items() if not present]
        gaps += product.get('mapping_issues', [])
        # Typed unit_count/number_of_items retained by details is stronger than size text.
        attrs = product.get('retained_attributes', {})
        typed_pack = bool(attrs.get('unit_count') and attrs.get('number_of_items'))
        row = dict(asin=asin, amazon_evidence=product, canonical_gtins=gtins,
            identity_fields_present=fields, amazon_gaps=gaps, barcode_validation=barcodes,
            retail_pack_basis='TYPED_ATTRIBUTES_REQUIRE_VERIFICATION' if typed_pack else 'CATALOG_SIZE_TEXT_ONLY',
            feasibility_basis='Unique barcode, explicit model and size reduce search ambiguity; Walmart availability unverified',
            prior_m88_pairs=history[asin], walmart_evidence=None, verified_exact_match=False,
            financial_assessment='INSUFFICIENT_DATA', net_profit='UNKNOWN', roi_percent='UNKNOWN')
        row['_sort'] = (len(gaps), not typed_pack, asin)
        ranked.append(row)
    ranked.sort(key=lambda r: r['_sort'])
    for i, row in enumerate(ranked, 1):
        del row['_sort']
        row['research_priority'] = i
    return ranked


COMMON = [
    'Search Walmart by each Amazon barcode and manufacturer model/MPN as leads only; record actual result URL and item ID. Do not force the original six IDs.',
    'Independently transcribe Walmart retail outer-pack UPC/GTIN with leading zeros, brand, manufacturer model and MPN separately; leave unavailable fields UNKNOWN.',
    'Capture selected size/color/style/formulation, contents per pack, sellable-pack count, outer versus individual barcode, bundles and case quantities. Do not equate packageQuantity 1 with one contents unit.',
    'Save per-field excerpts, actual screenshot files/references, exact URL, aware observation time and reviewer/agent/human status. Preserve contradictions and unavailable fields.',
    'Record current price, seller, fulfillment, Sacramento CA 95829 availability, shipping, tax and quantity limits with separate timestamps. Do not carry forward old item prices as current landed cost.',
    'Compare UPC, model, brand, variation and sellable pack independently after collection. Titles and shared UPC alone cannot establish identity. A conflict or missing critical field keeps NEEDS_REVIEW.',
    'Use ordinary permitted browsing; stop on access blockers. No cart, purchases, listings or account changes. Return Walmart observations separately from Amazon lead data.'
]


def checklist(rows: list[dict]) -> str:
    lines = ['# M89 Walmart Browser Use research checklist', '',
             'Research priority only. No verified matches or profitability claims. purchase_authorized=false.', '']
    lines += [f'- [ ] {step}' for step in COMMON]
    for row in rows[:10]:
        p = row['amazon_evidence']
        upcs = [i['value'] for i in p.get('identifiers', []) if i.get('identifier_type') == 'UPC']
        lines += ['', f"## Priority {row['research_priority']}: {row['asin']}", '',
            f"Amazon lead only: {p['title']}",
            f"Brand {p.get('brand')}; model {p.get('model')}; MPN {p.get('manufacturer_part_number', 'UNKNOWN_NOT_RETAINED')}; UPC alternatives {', '.join(upcs) or 'UNKNOWN'}.",
            f"Size {p.get('size')}; catalog package quantity {p.get('pack_quantity')}; variation {p.get('variation') or 'UNKNOWN'}.",
            'Walmart evidence: NOT COLLECTED. Find a new exact retail item; do not copy these lead fields into observations.',
            'Verify outer pack and contents explicitly: battery cell count/AA chemistry for Duracell; Magic versus Transparent, roll length/width, core, dispenser and number of boxes/rolls for Scotch. Do not substitute a similar product.',
            'Amazon gaps: ' + ('; '.join(row['amazon_gaps']) or 'No normalized field gaps; independent package applicability still unverified.'),
            '- [ ] Return an independent Walmart record, or explicit NOT_FOUND / BLOCKED / INSUFFICIENT_DATA with search references.']
    return '\n'.join(lines) + '\n'


def analyze(root: Path, output: Path) -> dict:
    root = safe(root)
    # Pin every prior artifact, including reports/classifications, without rewriting any.
    paths = sorted(p for p in root.rglob('*') if p.is_file() and p.suffix != '.lock')
    inventory = {str(p): digest(p) for p in paths}
    ledger = pinned(root / LEDGER, inventory[str(root / LEDGER)])
    attempts = ledger['attempts']
    if (ledger['ceiling'] != 49 or ledger['attempts_used'] != 11 or len(attempts) != 11
            or any(a['number'] != i or a['status'] != 'COMPLETE' for i, a in enumerate(attempts, 1))
            or ledger.get('purchase_authorized') is not False):
        raise ValueError('Expected authoritative completed 11/49 ledger')
    receipts = []
    for a in attempts:
        folder = 'm88-executor-v1-20261105T0301Z' if a['number'] <= 7 else 'm88-targeted-verification-v1'
        pinned(root / folder / 'plan.json', a['plan_sha256'])
        receipt = pinned(root / folder / f"receipt-{a['number']}.json", a['receipt_sha256'])
        if any(receipt[k] != a[k] for k in ('number', 'phase', 'candidate_id')):
            raise ValueError('Receipt binding mismatch')
        receipts.append(receipt)
    recon = pinned(root / RECON, inventory[str(root / RECON)])
    detail = pinned(root / DETAIL, inventory[str(root / DETAIL)])
    # Derive ranking from authenticated receipt evidence, checking report projections.
    detail_receipts = [r for r in receipts if r['phase'] == 'detail']
    if detail['details'] != detail_receipts:
        raise ValueError('Detail report differs from receipts')
    for row in recon['records']:
        candidates = [c['product'] for r in receipts if r['phase'] == 'search'
                      for c in r['evidence']['candidates'] if c['product']['asin'] == row['asin']]
        if row['amazon_product'] not in candidates:
            raise ValueError('Reconciliation Catalog product differs from receipts')
    with publication(output, [root]) as stage:
        with offline(reads=paths, writes=[stage]):
            rows = rank(recon['records'], detail_receipts)
            now = datetime.now(timezone.utc)
            report = dict(schema='m89-amazon-first-offline-v1', evaluated_at=now.isoformat(),
                starting_commit='b8fa9ec', purchase_authorized=False, additional_amazon_http_attempts=0,
                cumulative_attempts=11, ceiling=49, remaining_attempts=38,
                authoritative_ledger_path=str(root / LEDGER), authoritative_ledger_sha256=inventory[str(root / LEDGER)],
                verified_exact_matches=0, supported_profitability_products=0,
                ranking_basis='Missing catalog fields/mapping issues, typed pack attributes, ASIN tie-break; no sales or profitability ranking',
                candidates=rows, shortlist=rows[:3], source_inventory=inventory)
            manifest = dict(schema='walmart_product_analysis_input_v1', expected_candidates=3,
                source_inventory=[dict(path=path, sha256=sha) for path, sha in inventory.items()],
                candidates=[dict(candidate_id='m89:'+r['asin'], asin=r['asin'], identity=dict(amazon_product=r['amazon_evidence'])) for r in rows[:3]])
            financial = comparison(manifest, now)
            json_write(stage / 'candidate-shortlist.json', report)
            json_write(stage / 'comparison.json', financial)
            previous_temp = tempfile.tempdir
            try:
                tempfile.tempdir = str(stage)
                workbook(financial, stage / 'comparison.xlsx')
            finally:
                tempfile.tempdir = previous_temp
            json_write(stage / 'missing-data-report.json', dict(records=financial['records'],
                common_missing=['Independent Walmart exact identity and current landed acquisition costs',
                    'Fresh New selling prices and scoped fees for all FBA/FBM scenarios',
                    'Account-specific eligibility; supported demand, New competition and price history'], purchase_authorized=False))
            json_write(stage / 'browser-use-request.json', dict(common_checklist=COMMON,
                amazon_leads=rows[:10], walmart_observations=[], purchase_authorized=False))
            write(stage / 'browser-use-checklist.md', checklist(rows).encode())
            json_write(stage / 'conditional-amazon-plan.json', dict(executable=False, reserved_attempts=0,
                gate='After independently verified exact matches only; reuse saved evidence first. Fresh reviewed executor required; never replay M88 claims.',
                maximum_products=3, authentication=1, new_offers=3, listing_restrictions=3,
                fee_estimates=18, maximum_new_attempts=25, maximum_cumulative_attempts=36,
                remaining_after_maximum=13, retries=0, searches=0,
                fee_basis='Up to three documented prices x FBA/FBM per exact ASIN; deduplicate equal prices. Missing costs remain UNKNOWN.',
                eligibility_basis='Read-only account/condition/marketplace restrictions; absence of restrictions is not proof of FBA eligibility. Unavailable permissions remain UNKNOWN.',
                accounting='Charge all authentication, failed and uncertain dispatches against the original cumulative 49 ceiling; stop on error, no refresh or retries.',
                purchase_authorized=False))
            summary = ('# M89 offline executive summary\n\nReviewed 60 saved source/ASIN pairs (56 distinct ASINs), reusing three targeted Catalog details. '
                'M88 classifications and all evidence remain unchanged. Ledger remains 11/49 COMPLETE, 38 remaining; zero new HTTP requests.\n\n'
                'Top three research leads: ' + ', '.join(r['asin'] for r in rows[:3]) + '. '
                'These are Amazon-first search priorities, not exact matches. Walmart availability and independent retail identity are unverified. '
                'Previous rejections apply to their original Walmart pairs, not newly researched retail items.\n\n'
                'Zero exact matches; zero defensible profit calculations. M86 FBA/FBM assessments remain INSUFFICIENT_DATA; ROI and net profit UNKNOWN. '
                'Targets remain ROI >=50% and net profit >=$5 per unit. No sales velocity inferred. '
                'Collect independent Walmart evidence using the checklist before conditional offer, eligibility and price-bound fee research. '
                'The non-executable later plan caps 25 attempts (36/49 total), reserves zero now, and cannot dispatch requests. purchase_authorized=false.\n')
            lead_table = ['\n| Priority | ASIN | Brand / model | UPC leads | Critical next evidence |', '| --- | --- | --- | --- | --- |']
            for row in rows[:3]:
                p = row['amazon_evidence']
                upcs = ', '.join(i['value'] for i in p.get('identifiers', []) if i.get('identifier_type') == 'UPC')
                lead_table.append(f"| {row['research_priority']} | {row['asin']} | {p['brand']} / {p['model']} | {upcs or 'UNKNOWN'} | Independent Walmart UPC/model/variation/outer-pack; fresh full costs and scoped prices/fees |")
            write(stage / 'executive-summary.md', (summary + '\n'.join(lead_table) + '\n').encode())
            for path, expected in inventory.items():
                if digest(Path(path)) != expected:
                    raise ValueError('M88 evidence drift during publication')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.evidence_root, args.output)
    print(f"M89: {len(report['candidates'])} ASINs; 0 exact matches; ledger unchanged 11/49; purchase_authorized=false")


if __name__ == '__main__':
    main()
