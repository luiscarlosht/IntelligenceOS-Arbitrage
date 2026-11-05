"""Offline reconciliation of enriched Walmart evidence with pinned M88 candidates."""
import argparse
from collections import Counter,defaultdict
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import tempfile

from app.evidence_io import offline,publication,safe
from app.m88_identity import barcode_evidence
from app.m88_state import ledger,read,sha,write
from app.normalization import gtin,identity
from app.product_analysis import comparison,workbook
from app.walmart_evidence import normalize

EXCEPTIONS={
 '13952053139':['Missing model/MPN','Selected variant unknown','Separate outer-pack barcode unknown'],
 '721324153':['Conflicting 0.5 oz description; do not discard in favor of 5.75 oz'],
 '37481849':['Lined/unlined unknown','Selected variant unknown'],
 '47070933':['Core size unknown','Dispenser inclusion unknown'],
 '711088244':['Conflicting Pen + Gear versus Scotch brand field','Conflicting roll dimensions'],
}


def known(value: object) -> bool:
    return isinstance(value,str) and value.strip().upper() not in ('','UNKNOWN')


def equality(left: object,right: object) -> str:
    if not known(left) or not known(right):return 'UNKNOWN'
    return 'MATCH' if identity(left)==identity(right) else 'DIFFERENT_LABELS'


def contents(text: str) -> tuple[int | None,str | None]:
    """Extract only an explicit leading content count, not a derived package count."""
    words={'one':1,'two':2,'three':3,'four':4,'eight':8}
    start=re.match(r'^\s*(one|two|three|four|eight|\d+)\b',text,re.I)
    if not start:return None,None
    count=words.get(start[1].lower(),int(start[1]) if start[1].isdigit() else None)
    unit=re.search(r'\b(bottle|bottles|pads|rolls|cells)\b',text,re.I)
    return count,unit[1].lower().rstrip('s') if unit else None


def amazon_contents(product: dict) -> dict[str,list[int]]:
    texts=[product.get('size','')]
    try:
        variant=json.loads(product.get('variation') or '{}')
        if isinstance(variant,dict): texts.extend(v for v in variant.values() if isinstance(v,str))
    except (TypeError,ValueError):pass
    values=defaultdict(set)
    for text in texts:
        for count,unit in re.findall(r'\b(\d+)\s*(pads?|rolls?|bottles?|cells?)\b',text,re.I):
            values[unit.lower().rstrip('s')].add(int(count))
    return {unit:sorted(counts) for unit,counts in values.items()}


def source_issues(row: dict) -> list[str]:
    return list(dict.fromkeys(EXCEPTIONS.get(row['walmart_item_id'],[])+row.get('conflicts',[])+
                             [s for s in row.get('unresolved',[]) if s!='Independent human signoff']))


def classify(row: dict, candidate: dict, review: dict) -> dict:
    """No title-based exact match, model/MPN alias inference, or quantity conflation."""
    amazon=candidate['product']; codes=barcode_evidence(amazon)
    canonical=gtin(row['upc']); alternatives=codes['distinct_canonical_gtins']
    overlap=canonical in alternatives
    source_conflicts=row.get('conflicts',[])
    brand_conflict=any('brand' in c.lower() for c in source_conflicts) or 'CONFLICT' in row['brand']
    brand_status='SOURCE_CONFLICT' if brand_conflict else equality(row['brand'],amazon.get('brand'))
    model_status=equality(row['model'],amazon.get('model'))
    source_count,source_unit=contents(row['sellable_pack']); target_contents=amazon_contents(amazon)
    conflict=[]; gaps=[]
    if brand_status=='DIFFERENT_LABELS':conflict.append('Observed source and Amazon brands differ')
    count_values=target_contents.get(source_unit,[]) if source_unit else []
    if source_count is not None and count_values and source_count not in count_values:
        conflict.append('Explicit same-unit contents counts differ (not Amazon packageQuantity)')
    # A source UPC absent from a multi-identifier list is not proof of exclusion.
    # Two independent contradictory labels can reject a research candidate, except
    # where the source explicitly lacks barcode/outer-pack basis.
    uncertain_barcode=any('outer' in s.lower() for s in row.get('unresolved',[]))
    if (not overlap and len(alternatives)==1 and model_status=='DIFFERENT_LABELS'
            and not uncertain_barcode):
        conflict.append('Different canonical barcode and different model labels; no alias evidence')
    if overlap and model_status=='DIFFERENT_LABELS':
        gaps.append('Barcode overlap but model labels differ; manufacturer alias/MPN evidence not retained')
    if not overlap:gaps.append('No independently matching Amazon barcode in saved alternatives')
    if len(alternatives)>1:gaps.append('Amazon has multiple canonical barcode alternatives; package applicability unresolved')
    if model_status=='UNKNOWN':gaps.append('Source or Amazon model unknown')
    if brand_status in ('UNKNOWN','SOURCE_CONFLICT'):gaps.append('Brand not consistently established')
    gaps.extend(source_issues(row))
    gaps.extend(amazon.get('mapping_issues',[]))
    gaps.append('Amazon manufacturer part number not retained; do not relabel model as MPN')
    if not known(row.get('selected_variant')) or not known(amazon.get('variation')):
        gaps.append('Selected variant evidence incomplete')
    # The current schema contains free-text packs. No typed package equivalence is
    # invented from counts, matching UPCs or the Single selector.
    gaps.append('Retail sellable-pack equivalence requires independent scoped evidence')
    if review.get('screenshot_files_not_embedded'):
        gaps.append('Screenshot references retained; image files not supplied or inspected')
    # These retained fields lack scoped MPN/variant/retail-pack corroboration.
    # EXACT_MATCH is not assigned by relaxing the existing exact-identity gate.
    category='REJECTED' if conflict else 'NEEDS_REVIEW'
    return dict(walmart_item_id=row['walmart_item_id'],asin=amazon['asin'],classification=category,
        decisive_contradictions=conflict,remaining_gaps=sorted(set(gaps)),
        comparisons=dict(upc=dict(walmart_original=row['upc'],walmart_canonical=canonical,
            amazon_identifiers=codes,overlap=overlap),brand=dict(walmart=row['brand'],amazon=amazon.get('brand'),status=brand_status),
            model=dict(walmart=row['model'],amazon=amazon.get('model'),status=model_status),
            mpn=dict(walmart=row['mpn'],amazon='UNKNOWN_NOT_RETAINED'),
            variant=dict(walmart=row['selected_variant'],amazon=amazon.get('variation') or 'UNKNOWN',
                status=equality(row['selected_variant'],amazon.get('variation'))),
            size=dict(walmart_description=row['sellable_pack'],amazon_size=amazon.get('size') or 'UNKNOWN',
                status='SOURCE_CONFLICT' if any('size' in c.lower() or 'dimension' in c.lower() or '0.5' in c for c in source_conflicts)
                else 'UNRESOLVED_FREE_TEXT_AND_UNIT_BASIS'),
            pack=dict(walmart_description=row['sellable_pack'],reported_contents_count=source_count,
                reported_contents_unit=source_unit,amazon_same_unit_counts=target_contents,
                amazon_package_quantity=amazon.get('pack_quantity'),equivalence='UNKNOWN')),
        amazon_product=amazon,source_exceptions=source_issues(row),
        agent_review_completed=review.get('agent_review_completed') is True,
        independent_human_signoff=review.get('independent_human_signoff') is True,
        verified_exact_match=False,purchase_authorized=False)


def validate(enriched: dict,batch: dict) -> None:
    if enriched.get('cohort','').casefold()!='m88-real-six-pilot' or enriched.get('purchase_authorized') is not False:
        raise ValueError('Explicit M88 cohort and purchase_authorized=false required')
    review=enriched.get('review')
    if not isinstance(review,dict) or any(type(review.get(k)) is not bool for k in
            ('agent_review_completed','independent_human_signoff','screenshot_files_not_embedded')):
        raise ValueError('Separate explicit agent-review, human-signoff and screenshot flags required')
    rows=enriched.get('observations',[])
    expected={r['walmart_product']['walmart_item_id']:r['walmart_product']['url'] for r in batch['observations']}
    if len(rows)!=6 or {r.get('walmart_item_id') for r in rows}!=set(expected):raise ValueError('Exact original six IDs required')
    for row in rows:
        if row.get('url')!=expected[row['walmart_item_id']]:raise ValueError('Original product URL drift')
        if not isinstance(row.get('upc'),str) or not re.fullmatch('[0-9]{12}',row['upc']):raise ValueError('12-digit observed UPC required')
        gtin(row['upc'])
        for field in ('brand','model','mpn','selected_variant','sellable_pack','screenshot_reference'):
            if not isinstance(row.get(field),str) or not row[field].strip():raise ValueError('Explicit observed text or UNKNOWN required')
        at=datetime.fromisoformat(row['observed_utc'].replace('Z','+00:00'))
        if at.utcoffset() is None or at>datetime.now(timezone.utc):raise ValueError('Valid aware observation time required')
        for key in ('unresolved','conflicts'):
            if not isinstance(row.get(key,[]),list) or any(not isinstance(s,str) for s in row.get(key,[])):
                raise ValueError('Explicit source exception lists required')


def run(plan_path: Path,plan_sha: str,enrichment: Path,enrichment_sha: str,output: Path) -> dict:
    plan_path=safe(plan_path);enrichment=safe(enrichment)
    if sha(plan_path)!=plan_sha or sha(enrichment)!=enrichment_sha:raise ValueError('Pinned inputs required')
    plan=read(plan_path);source_path=safe(Path(plan['source_path']));ledger_path=safe(Path(plan['ledger_path']))
    if sha(source_path)!=plan['source_sha256']:raise ValueError('Original source drift')
    before=sha(ledger_path);accounting=ledger(ledger_path)
    if (accounting['attempts_used']!=7 or accounting.get('m88_operation')!=plan_sha
            or Counter(a['phase'] for a in accounting['attempts'])!={'authentication':1,'search':6}):
        raise ValueError('Original completed 7/49 operation required')
    inventory=[dict(path=str(p),sha256=sha(p)) for p in (plan_path,source_path,ledger_path,enrichment)]
    searches=[]
    for attempt in accounting['attempts']:
        if attempt['status']!='COMPLETE' or attempt.get('plan_sha256')!=plan_sha:raise ValueError('Unexpected attempt state')
        receipt=safe(plan_path.parent/f"receipt-{attempt['number']}.json")
        if sha(receipt)!=attempt['receipt_sha256']:raise ValueError('Receipt hash mismatch')
        d=read(receipt)
        if d['number']!=attempt['number'] or d['phase']!=attempt['phase'] or d['candidate_id']!=attempt['candidate_id']:raise ValueError('Receipt scope mismatch')
        if d['phase']=='search':searches.append(d)
        inventory.append(dict(path=str(receipt),sha256=sha(receipt)))
    batch=read(source_path);new=read(enrichment);validate(new,batch)
    original_ids={r['source_candidate_id']:r['walmart_product']['walmart_item_id'] for r in batch['observations']}
    if any(r['candidate_id'] not in original_ids for r in searches):raise ValueError('Unknown original source candidate ID')
    by_id={original_ids[r['candidate_id']]:r for r in searches}
    if set(by_id)!={r['walmart_item_id'] for r in new['observations']} or len(searches)!=6:raise ValueError('Six original search receipts required')
    with publication(output,[enrichment,source_path,plan_path.parent,ledger_path]) as stage:
        previous=tempfile.tempdir
        try:
            tempfile.tempdir=str(stage)
            with offline(writes=[stage]):
                records=[classify(row,c,new['review']) for row in new['observations']
                         for c in by_id[row['walmart_item_id']]['evidence']['candidates']]
                counts=Counter(r['classification'] for r in records)
                per_product={row['walmart_item_id']:dict(Counter(r['classification'] for r in records if r['walmart_item_id']==row['walmart_item_id'])) for row in new['observations']}
                enriched=deepcopy(batch);enriched.pop('batch_id',None)
                for original in enriched['observations']:
                    row=next(r for r in new['observations'] if r['walmart_item_id']==original['walmart_product']['walmart_item_id'])
                    original['identity_enrichment_original']=row
                    p=original['walmart_product'];p.update(gtin=gtin(row['upc']),original_upc=row['upc'],brand=row['brand'],model=row['model'],mpn=row['mpn'],
                        variation=row['selected_variant'],observed_at=row['observed_utc'],source_reference=str(enrichment)+'#'+row['walmart_item_id'],
                        pack_description=row['sellable_pack'],verified=False,review_type='AGENT_OBSERVATION',
                        independent_human_signoff=new['review'].get('independent_human_signoff') is True,screenshot_reference=row['screenshot_reference'])
                    original['conflicting_observations']=row.get('conflicts',[])
                    original['identity_exceptions']=source_issues(row)
                    # Original acquisition prices/timestamps and pack-basis fields remain intact.
                manifest=normalize(enriched);manifest['source_inventory']=inventory
                manifest['recovery_blockers']=['New enriched agent observations; no independent human signoff or screenshot files supplied; unresolved identity exceptions retained']
                assessed=comparison(manifest,datetime.now(timezone.utc))
                assessed.update(cohort='m88-real-six-pilot',reconciliation_counts={k:counts.get(k,0) for k in ('EXACT_MATCH','REJECTED','NEEDS_REVIEW')},delivery_context=new['delivery_context'])
                unique=defaultdict(list)
                for r in records:unique[r['asin']].append(r['classification'])
                unique_counts=Counter('NEEDS_REVIEW' if 'NEEDS_REVIEW' in states else 'REJECTED' for states in unique.values())
                summary=dict(cohort='m88-real-six-pilot',candidate_records=len(records),unique_asins=len(unique),
                    counts={k:counts.get(k,0) for k in ('EXACT_MATCH','REJECTED','NEEDS_REVIEW')},
                    unique_asin_counts=dict(unique_counts),per_product=per_product,
                    barcode_overlap_pairs=[dict(walmart_item_id=r['walmart_item_id'],asin=r['asin'],classification=r['classification']) for r in records if r['comparisons']['upc']['overlap']],
                    additional_amazon_http_attempts=0,cumulative_attempts=7,ceiling=49,
                    products_with_supported_profitability=sum(r['financial_assessment']!='INSUFFICIENT_DATA' for r in assessed['records']),
                    independent_human_signoff=new['review'].get('independent_human_signoff') is True,purchase_authorized=False)
                write(stage/'candidate-reconciliation.json',dict(summary,records=records,source_inventory=inventory))
                write(stage/'reconciliation-summary.json',summary)
                write(stage/'normalized.json',manifest);write(stage/'enriched-batch.json',enriched)
                write(stage/'comparison.json',assessed);workbook(assessed,stage/'comparison.xlsx')
                write(stage/'missing-data-report.json',dict(source_exceptions={r['walmart_item_id']:source_issues(r) for r in new['observations']},
                    screenshot_references={r['walmart_item_id']:r['screenshot_reference'] for r in new['observations']},
                    screenshot_files_supplied=False,agent_review=new['review'],
                    financial_gaps={r['candidate_id']:r['missing_information'] for r in assessed['records']},purchase_authorized=False))
                write(stage/'additional-request-assessment.json',dict(decision='DEFER_ADDITIONAL_AMAZON_REQUESTS',requests=[],additional_attempts=0,
                    reason='Only two barcode-overlap candidates remain promising, but model/pack applicability and independent source exceptions are unresolved; Amazon offers/fees cannot resolve Walmart contradictions or missing source evidence.',
                    conditional_future_catalog_targets=summary['barcode_overlap_pairs'],
                    future_scope='If source gaps are resolved, review at most one new authentication plus two Catalog detail GETs; no automatic replay of completed operation',
                    cumulative_attempts=7,remaining_ceiling=42,purchase_authorized=False))
                from app.m78_reporting import write as bytes_write
                lines=['# M88 enriched identity reconciliation','',
                    f"Compared {len(records)} source/candidate records ({len(unique)} distinct ASINs): {counts.get('EXACT_MATCH',0)} EXACT_MATCH, {counts.get('REJECTED',0)} REJECTED, {counts.get('NEEDS_REVIEW',0)} NEEDS_REVIEW.",'',
                    'Classification is per source/ASIN pair. REJECTED means contradictory observed identity evidence, not a permanent ASIN ban. Missing evidence and barcode/model conflicts remain NEEDS_REVIEW. No title similarity or single barcode establishes exact identity.','',
                    'Barcode-overlap pairs: '+(', '.join(p['walmart_item_id']+'/'+p['asin'] for p in summary['barcode_overlap_pairs']) or 'none')+'. A matching alternative does not confirm package applicability or model/MPN aliases.','',
                    'All explicit exceptions remain: Duracell missing model/outer barcode; Gorilla conflicting 0.5 oz; Post-it lined/unlined unknown; Scotch core/dispenser unknown; Pen + Gear brand/dimensions conflicts. Screenshot references are retained, but files were not supplied or inspected. Agent review is not independent human signoff.','',
                    f"Supported profitability products: {summary['products_with_supported_profitability']} of 6. All results remain INSUFFICIENT_DATA; original item prices and timestamps are preserved, missing costs/fees/prices remain unknown.",'',
                    'No additional Amazon requests were necessary now: source contradictions and package-basis gaps must be resolved before offers/fees could support a valid pairing. A possible later two-target Catalog clarification is not dispatched or authorized for automatic replay.','',
                    'Amazon HTTP attempts consumed this phase: 0. Cumulative ledger unchanged at 7/49, all COMPLETE. No purchases, listings, inventory or credential changes. purchase_authorized=false.']
                bytes_write(stage/'executive-summary.md',('\n'.join(lines)+'\n').encode())
                for item in inventory:
                    if sha(Path(item['path']))!=item['sha256']:raise ValueError('Pinned evidence changed during reconciliation')
                if sha(ledger_path)!=before:raise ValueError('Ledger changed')
        finally:tempfile.tempdir=previous
    return summary


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',required=True,type=Path);parser.add_argument('--plan-sha256',required=True)
    parser.add_argument('--enrichment',required=True,type=Path);parser.add_argument('--enrichment-sha256',required=True)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();result=run(args.plan,args.plan_sha256,args.enrichment,args.enrichment_sha256,args.output)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
