"""Rebuild candidate-review presentation from saved evidence only; no transport or credentials."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path

from app.normalization import gtin, identity, money
from app.observations import canonical
from app.profitability import COST_FIELDS
from app.reporting import write_report


def evidence_gaps(source: dict, catalog: dict, search: dict) -> list[str]:
    """Compare only independently supplied like fields; absence is never a conflict."""
    gaps = []
    if not source.get('gtin') and not (source.get('manufacturer') and source.get('model')):
        gaps.append('Source GTIN/manufacturer-model identity unknown')
    for key, label in (('gtin', 'GTIN'), ('manufacturer', 'manufacturer'), ('model', 'model'),
                       ('package_quantity', 'retail package quantity')):
        left, right = source.get(key), catalog.get(key)
        if left is None or left == '':
            if key == 'package_quantity': gaps.append('Source retail package count unknown')
        elif right is None or right == '':
            gaps.append('Amazon '+label+' unknown')
        else:
            try:
                equal = gtin(left)==gtin(right) if key=='gtin' else (
                    identity(left)==identity(right) if isinstance(left,str) and isinstance(right,str) else left==right)
            except (ValueError,TypeError):
                gaps.append('Identifier invalid; comparison unavailable')
                continue
            if not equal:
                gaps.append('CONFLICT: supplied source/Amazon '+label+' differ')
    context = source.get('source_context') or {}
    if not context.get('source_package_contents'):
        gaps.append('Source package contents unknown')
    else:
        gaps.append('Package composition requires independent verification')
    if not source.get('variation'):
        gaps.append('Source size/color/material/variation unknown')
    else:
        try:
            source_variant=json.loads(source['variation'])
            target_variant=json.loads(catalog.get('variation') or '{}')
        except (ValueError,TypeError):
            source_variant,target_variant=None,None
        if isinstance(source_variant,dict) and isinstance(target_variant,dict):
            for dimension,value in source_variant.items():
                target=target_variant.get(dimension)
                if target is None:
                    gaps.append('Amazon variation '+dimension+' unknown')
                elif isinstance(value,str) and isinstance(target,str) and identity(value)!=identity(target):
                    gaps.append('CONFLICT: supplied source/Amazon variation '+dimension+' differ')
        else:
            gaps.append('Selected variation requires independent verification')
    for issue in catalog.get('mapping_issues', []):
        gaps.append('Amazon: '+issue)
    if catalog and not catalog.get('gtin'):
        gaps.append('Amazon GTIN unavailable')
    if search.get('more_results') or not search.get('complete',False):
        gaps.append('Multiple/unexamined candidates; first page only')
    elif len(search.get('candidates',[]))>1:
        gaps.append('Multiple candidates returned')
    if not search.get('candidates'):
        gaps.append('No candidate returned' if search else 'Search not completed')
    return list(dict.fromkeys(gaps))


def build_review(report: dict, *, amazon_enrichment: dict | None = None, source_label: str = 'SUPPLIED source/search observations; live origin not independently checked'):
    if type(report.get('is_mock')) is not bool:
        raise ValueError('Explicit catalog mock/live provenance required')
    rows, comparisons, enrichments = [], [], []
    mocked = report.get('is_mock') is True
    amazon_label = ('MOCK Amazon catalog fixtures — illustrative only' if mocked else
                    'LIVE Amazon catalog observations — saved evidence; not verified product identity')
    from app.candidate_enrichment_report import project
    enrichment_by_asin, specs = {}, {}
    if amazon_enrichment is not None:
        if amazon_enrichment.get('is_mock') is not mocked:
            raise ValueError('Amazon enrichment mock/live provenance mismatch')
        enrichment_by_asin = {r['asin']: r for r in amazon_enrichment['rows']}
        specs = {r['asin']: r for r in amazon_enrichment['manifest']['requests']}
        candidates = {(r.get('search') or {}).get('selected_asin') for r in report['rows']} - {None}
        if (set(enrichment_by_asin) != candidates or set(specs) != candidates
                or len(enrichment_by_asin) != len(amazon_enrichment['rows'])):
            raise ValueError('Enrichment must retain every distinct candidate ASIN exactly once')
    counts = Counter()
    for result in report['rows']:
        source = result['source']
        search = result.get('search') or {}
        detail = result.get('detail') or {}
        catalog = (detail.get('value') or {}).get('catalog') or {}
        if catalog and (catalog.get('is_mock') is not mocked or detail.get('is_mock') is not mocked):
            raise ValueError('Mixed/unknown catalog provenance must not be relabeled')
        if catalog and catalog.get('asin') != search.get('selected_asin'):
            raise ValueError('Selected candidate/detail ASIN mismatch')
        candidate = search.get('selected_asin')
        status = result['status']
        exact = result.get('exact') is True
        counts['exact' if exact else 'candidate' if candidate else 'unmatched'] += 1
        gaps = evidence_gaps(source,catalog,search)
        if exact:
            gaps.append('Saved exact-identity assertion requires separate sourcing/economics validation')
        match_status = 'Confirmed exact (saved evidence)' if exact else ('Ambiguous candidate only' if status=='ambiguous'
            else 'Candidate only — unverified' if candidate else 'Unmatched' if status=='unmatched' else status.replace('_',' ').title())
        if status in ('failed', 'not_attempted'):
            match_status = 'Failed stage — retained candidate only' if status == 'failed' else 'Not attempted'
            gaps.append('Detail outcome unresolved')
        observed = source.get('source_context') or {}
        comparisons.append(dict(ebay_title=source['name'],seller=observed.get('source_seller'),
            observed_item_price=money(source.get('purchase_price') if source.get('retailer') == 'Walmart' else observed.get('search_price')),
            reported_shipping=money(observed.get('source_shipping_cost')),
            source_url=source.get('url'),candidate_asin=candidate,
            amazon_title=catalog.get('title') or next((c.get('title') for c in search.get('candidates',[]) if c.get('asin')==candidate),None),
            match_status=match_status,evidence_gaps='; '.join(gaps)))
        comparisons[-1].update(amazon_item_price=None, amazon_shipping=None,
            price_provenance=str(source.get('provenance') or 'Unknown'),
            conditional_ebay_coupon_price=None)
        comparisons[-1].update(project(comparisons[-1], enrichment_by_asin.get(candidate),
                                       specs.get(candidate), mocked=mocked))
        if candidate in enrichment_by_asin:
            enrichments.append(dict(kind='amazon_candidate_enrichment', asin=candidate,
                value=canonical(enrichment_by_asin[candidate]),
                provenance='Saved independent pricing, fee and restriction outcomes; request-bound manifest',
                is_mock=mocked, notice='Candidate identity unverified; no purchase approval or verified net profit'))

        reasons=gaps+['Verified acquisition cost, Amazon sale price, fees and other economics unknown; profitability not established']
        provenance = detail.get('provenance') or search.get('provenance')
        data_mode = source_label+' | '+amazon_label+' | ECONOMICS UNKNOWN'
        row = dict(source=source.get('retailer'),product=source['name'],source_url=source.get('url'),
            upc=source.get('gtin') or None,amazon_asin=candidate,destination='Amazon',status='REJECT',
            manufacturer=source.get('manufacturer') or None,model=source.get('model') or None,
            package_quantity=source.get('package_quantity'),variation=source.get('variation') or None,
            availability=source.get('availability'),reason='; '.join(reasons),quality_issues='; '.join(reasons),
            source_timestamp=source.get('retrieved_at'),marketplace_timestamp=detail.get('observed_at') or search.get('observed_at'),
            source_provenance=source.get('provenance'),marketplace_provenance=provenance,data_mode=data_mode,
            cost_basis='UNKNOWN — no verified economics',unverified_costs=', '.join(COST_FIELDS),purchase_ready=False,
            matching_confidence=100 if exact else 0,confidence=None,ranking_score=None,budget_units=None)
        # A catalog lookup never supplies verified acquisition costs, offers, fees or profit.
        for key in ('buy_cost','sale_price','profit','roi','acquisition_cost','break_even_price',
                    'maximum_purchase_price','monthly_sales','offer_count',*COST_FIELDS):
            row[key]=None
        rows.append(row)
        for kind,value,stamp,label in (
            ('source_search_observation',source,source.get('retrieved_at'),source_label),
            ('amazon_catalog_observation',dict(search=search,detail=detail),detail.get('observed_at'),amazon_label)):
            enrichments.append(dict(kind=kind,asin=candidate,value=canonical(value),observed_at=stamp,
                provenance=label,is_mock=mocked if kind=='amazon_catalog_observation' else None,
                notice='Unknowns retained; no economics inferred; not a purchase recommendation'))
    review = {'Source evidence':source_label,'Amazon evidence':amazon_label,
        'Economics':'UNKNOWN — observed item prices/shipping are not verified acquisition costs; profitability not established',
        'Confirmed exact matches':counts['exact'],'Candidate-only rows':counts['candidate'],
        'Unmatched rows':counts['unmatched'],'comparisons':comparisons}
    return rows,review,enrichments


def regenerate(saved_report: Path, source_export: Path, original_workbook: Path, output: Path, *, amazon_enrichment: Path | None = None) -> dict:
    inputs = [Path(p) for p in (saved_report,source_export,original_workbook)]
    if amazon_enrichment is not None:
        inputs.append(Path(amazon_enrichment))
    output=Path(output)
    if output.resolve() in {p.resolve() for p in inputs} or output.exists() or output.is_symlink():
        raise ValueError('A separate new corrected workbook is required')
    before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    report=json.loads(inputs[0].read_text())
    export=json.loads(inputs[1].read_text())
    if (report.get('status')!='succeeded' or report.get('is_mock') is not False or report.get('live_requests')!=21
            or len(report.get('attempts',[]))!=21 or len(report.get('rows',[]))!=10):
        raise ValueError('Saved successful real ten-row/21-attempt report required')
    if export.get('status')!='finished' or len(export.get('results',[]))!=1:
        raise ValueError('Completed original source export required')
    result=export['results'][0];query=result.get('query',{});metadata=result.get('metadata',{})
    if (result.get('success') is not True or any(query.get(k)!=v for k,v in
        dict(source='ebay',country='us',topic='search_results').items()) or metadata.get('page_count_live')!=1):
        raise ValueError('Live eBay source-search provenance required')
    if [r['ordinal'] for r in report['rows']]!=list(range(1,11)):
        raise ValueError('Every original source ordinal required')
    source_label='LIVE eBay search observations via Price API — saved export; source-detail identity unverified'
    source_items=result.get('content',{}).get('search_results',[])
    for row in report['rows']:
        source=row['source'];context=source.get('source_context') or {}
        if before[inputs[1]] not in source.get('provenance',''):
            raise ValueError('Source export hash absent from row provenance')
        if not any(item.get('url')==source.get('url') and item.get('name')==source.get('name')
                   and money(item.get('price'))==money(context.get('search_price'))
                   and money(item.get('shipping_costs'))==money(context.get('source_shipping_cost'))
                   and item.get('shop_name')==context.get('source_seller') for item in source_items):
            raise ValueError('Source row differs from saved original export')
    enrichment = json.loads(Path(amazon_enrichment).read_text()) if amazon_enrichment is not None else None
    if enrichment is not None:
        from app.amazon_candidate_enrichment import plan
        manifest = enrichment['manifest']
        if manifest != plan(inputs[0], fixed_fee_prices=manifest.get('fixed_fee_prices'),
                            seller_reference=manifest.get('seller_reference', '')):
            raise ValueError('Saved enrichment manifest does not match candidate/scenario scope')
    rows,review,enrichments=build_review(report,source_label=source_label,amazon_enrichment=enrichment)
    output.parent.mkdir(parents=True,exist_ok=True)
    # Reserve output without overwriting any original or preexisting artifact.
    fd=os.open(output,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    os.close(fd)
    write_report(rows,output,discovery=True,candidate_review=review,enrichment_rows=enrichments,
        job=dict(label='Proof of concept — candidate review',phase='Offline presentation correction from saved evidence',
                 original_saved_run_status=report['status'],original_saved_run_attempts=21,
                 new_api_calls=0,original_workbook_sha256=before[inputs[2]],
                 saved_candidate_report_sha256=before[inputs[0]],source_export_sha256=before[inputs[1]]))
    if any(hashlib.sha256(p.read_bytes()).hexdigest()!=digest for p,digest in before.items()):
        raise ValueError('Original saved evidence changed')
    return dict(output=str(output.resolve()),rows=len(rows),confirmed=review['Confirmed exact matches'],
                candidate_only=review['Candidate-only rows'],unmatched=review['Unmatched rows'],
                original_preserved=True,new_api_calls=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved-report',required=True,type=Path)
    parser.add_argument('--source-export',required=True,type=Path)
    parser.add_argument('--original-workbook',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--amazon-enrichment',type=Path,help='Saved request-bound Amazon enrichment report')
    args=parser.parse_args()
    print(json.dumps(regenerate(args.saved_report,args.source_export,args.original_workbook,args.output,amazon_enrichment=args.amazon_enrichment)))


if __name__=='__main__':
    main()
