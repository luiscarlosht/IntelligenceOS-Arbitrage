"""Reproduce a pinned real research baseline without network or account state."""
import argparse
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import tempfile

from app.evidence_io import digest, json_write, offline, pinned, publication
from app.m70_sources import strict_json
from app.m88_evidence import match
from app.product_analysis import comparison, workbook
from app.walmart_evidence import normalize

BASE = Path(__file__).resolve().parents[1] / 'evidence/m91'


def build(base: Path = BASE) -> dict:
    pins = strict_json(base / 'pins.json')
    now = datetime.fromisoformat(pins['as_of'])
    documents, inventory = {}, []
    for item in pins['artifacts']:
        if item['kind'] != 'REAL_SAVED_RESEARCH' or Path(item['path']).name != item['path']:
            raise ValueError('Only pinned real baseline artifacts allowed')
        document = pinned(base / item['path'], item['sha256'])
        if document.get('is_mock') or document.get('is_synthetic') or document.get('batch_kind') == 'SYNTHETIC_DEMO':
            raise ValueError('Synthetic evidence cannot enter real baseline')
        documents[item['path']] = document
        inventory.append(dict(item, status='HASH_VERIFIED_SAVED_ARTIFACT',
                              limitation='Integrity and recorded provenance; not independent verification of retail facts'))
    batch = documents['six-product-manifest.json']
    if batch['batch_kind'] != 'NEW_PILOT':
        raise ValueError('Real intake required')
    manifest = normalize(batch)
    originals = {p['walmart_item_id']: p for p in documents['walmart-observations-original.json']['products']}
    receipts = {d['candidate_id']: (name, d) for name, d in documents.items() if name.startswith('receipt-')}
    for record in manifest['candidates']:
        retailer = record['identity']['retailer_product']
        original = originals[retailer['walmart_item_id']]
        if (retailer['title'] != original['title'] or retailer['seller'] != original['seller']
                or retailer['observed_at'] != original['observed_at_utc']
                or record['financials']['FBA']['base']['purchase']['value'] != str(original['observed_price_usd'])):
            raise ValueError('Intake differs from original Walmart observation')
        name, receipt = receipts[record['candidate_id']]
        if receipt['phase'] != 'search':
            raise ValueError('Saved search receipt required')
        products = [c['product'] for c in receipt['evidence']['candidates']]
        if not products or any(p.get('is_mock') or p.get('is_synthetic') for p in products):
            raise ValueError('Real saved Catalog candidates required')
        # One reproducible lead per source, never an inferred selected/exact ASIN.
        amazon = deepcopy(sorted(products, key=lambda p: p['asin'])[0])
        record['asin'] = amazon['asin']
        record['identity']['amazon_product'] = amazon
        record['input_conflicts'] = ['Walmart identity unverified; Catalog lead selection is not a match']
        gate = match(retailer, amazon, now)
        record['baseline_inventory'] = dict(
            evidence_kind='REAL_SAVED_RESEARCH', walmart_original=original,
            amazon_saved_observation=amazon, amazon_receipt=name,
            source_timestamps=dict(walmart=original['observed_at_utc'], amazon=amazon['observed_at']),
            verified_facts=['Pinned saved artifact bytes and recorded source timestamps'],
            unresolved_observations=['Walmart listing, seller, price and package are browser research assertions',
                                     'Lexicographically first saved ASIN is a research lead only'],
            synthetic_test_records=False, matching_gate=gate,
            alternative_asins=sorted(p['asin'] for p in products if p['asin'] != amazon['asin']),
            missing_data=['Independent Walmart identity signoff and field-level captures',
                          'Exact sellable pack, GTIN, model, size and variation equivalence',
                          'Current complete price-bound economics and seller eligibility'])
    manifest.update(expected_candidates=6, source_inventory=inventory,
                    recovery_blockers=['Historical research baseline only; no current verified exact pair or profitability'])
    report = comparison(manifest, now)
    for row in report['records']:
        row['baseline_inventory'] = row['input_evidence']['baseline_inventory']
        row['baseline_inventory']['review_priority'] = row['rank']
    report['baseline'] = dict(schema='m91_evidence_baseline_v1', synthetic_records=0,
        selection='Six original Walmart records; lexicographically first saved Catalog ASIN per source; alternatives retained',
        pins_sha256=digest(base / 'pins.json'), additional_amazon_requests=0,
        evaluation='Fixed historical clock; freshness gates unchanged; not current market evidence')
    target = report['records'][0]
    report['m92_checklist'] = [dict(priority=i, candidate_id=target['candidate_id'], asin=target['asin'], evidence=text)
        for i, text in enumerate([
            'Review this lead and alternatives; discard incompatible ASINs. Save independent Walmart and Amazon field-level captures with timestamps, hashes and reviewer signoff.',
            'Resolve GTIN applicability, manufacturer/model, brand, variation, size and sellable package quantity. Pass existing exact-match gate without exceptions.',
            'Refresh Walmart seller, destination availability, purchase price, shipping and tax; retain UNKNOWN for unavailable values.',
            'Obtain supported New selling prices and price-bound referral/fulfillment fees for conservative/base/optimistic FBA and FBM; document inbound, prep, packaging, storage and all other costs, including explicit evidence for zero.',
            'Obtain independent seller-specific listing and fulfillment eligibility plus scoped demand, competition and comparable price history.',
            'Run existing product analysis with fresh evidence; require complete economics and unchanged $5 profit / 50% acquisition ROI gates. No purchase authorization follows.'
        ], 1)]
    return report


def run(output: Path, base: Path = BASE) -> dict:
    with publication(output, [base]) as stage:
        previous = tempfile.tempdir
        try:
            tempfile.tempdir = str(stage)
            with offline(reads=[base], writes=[stage]):
                report = build(base)
                json_write(stage / 'comparison.json', report)
                workbook(report, stage / 'comparison.xlsx')
                checklist = '\n'.join(f"{r['priority']}. {r['evidence']}" for r in report['m92_checklist'])
                (stage / 'm92-checklist.md').write_text(
                    f"# M92 evidence checklist\n\nFirst research priority: {report['m92_checklist'][0]['candidate_id']} / {report['m92_checklist'][0]['asin']}. This lead may need replacement.\n\n{checklist}\n")
                (stage / 'm92-checklist.md').chmod(0o600)
                # Detect source drift during report generation.
                if build(base) != report:
                    raise ValueError('Baseline changed during reporting')
        finally:
            tempfile.tempdir = previous
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Fresh local output directory')
    run(parser.parse_args().output)


if __name__ == '__main__':
    main()
