"""Offline M88 candidate triage and browser enrichment; never confirms a match."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unicodedata

from app.evidence_io import offline, publication, safe
from app.m88_state import ledger, read, sha, write
from app.normalization import gtin

STOP_WORDS = {'a','and','the','for','of','s','in','x','by','with','to','single','pack','pk'}
REQUIRED_SOURCE = ('gtin','brand','model','size','variation')
COMMON_REQUEST = [
    'Capture the selected Walmart product URL/item ID, exact title, seller/fulfiller and Sacramento CA 95829 context.',
    'Capture the retail sellable-pack barcode (UPC/EAN/GTIN) from specifications or a readable package image; retain leading zeros and identify inner-unit versus outer-pack barcodes.',
    'Capture the displayed brand, manufacturer, model and manufacturer part number separately; use UNKNOWN for each field not shown.',
    'Capture selected size/color/style/formulation, contents per retail pack, number of retail packs, and whether the offer is a bundle/case; preserve exact units and selector labels.',
    'Save per-field screenshots or page excerpts with URLs, aware observation timestamps, evidence file references and reviewer attestation. Keep existing observations unchanged.',
    'Record current price/shipping only if revisited, as a new dated observation. Never overwrite old quotes or assume Sacramento availability applies elsewhere.',
    'Use ordinary permitted browser access only. Stop on access blockers. Never copy Amazon identifiers into Walmart observations or substitute another product.',
]


def tokens(value: str) -> set[str]:
    value=unicodedata.normalize('NFKC',value).casefold()
    return set(re.findall(r'[a-z0-9]+',value))-STOP_WORDS


def content_counts(value: str) -> set[int]:
    """Textual clues only: never convert them to verified package quantities."""
    return {int(n) for n in re.findall(r'\b(\d+)\s*(?:count\b|pads?\b|rolls?\b|bottles?\b|/\s*pk\b)',value,re.I)}


def sheets(value: str) -> set[int]:
    return {int(n) for n in re.findall(r'\b(\d+)\s*sheets?\b',value,re.I)}


def measures(value: str) -> set[str]:
    result=set()
    for number,unit in re.findall(r'\b(\d+/\d+|\d+(?:\.\d+)?)\s*(?:fl\s*)?(ounces?\b|oz\b|inches\b|inch\b|in\b|gallons?\b|gal\b|grams?\b|g\b)',value,re.I):
        unit=unit.casefold()
        canonical='oz' if unit.startswith(('oz','ounce')) else 'gal' if unit.startswith('gal') else 'g' if unit.startswith('g') else 'in'
        result.add(number+canonical)
    return result


def barcode_evidence(product: dict) -> dict:
    alternatives=[]; invalid=[]; canonical=set()
    for identifier in product.get('identifiers',[]):
        if identifier.get('identifier_type') not in ('UPC','EAN','GTIN'): continue
        try:
            expected={'UPC':(12,), 'EAN':(8,13), 'GTIN':(14,)}[identifier['identifier_type']]
            if not isinstance(identifier.get('value'),str) or len(identifier['value']) not in expected:
                raise ValueError('Typed barcode length mismatch')
            normalized=gtin(identifier.get('value'))
            if not normalized or normalized!=identifier.get('normalized_gtin'):
                raise ValueError('Identifier normalization mismatch')
        except (ValueError,TypeError,AttributeError):
            invalid.append(identifier);continue
        canonical.add(normalized);alternatives.append(identifier)
    return dict(valid_identifiers=alternatives,invalid_identifiers=invalid,
                distinct_canonical_gtins=sorted(canonical),
                status='MULTIPLE_ALTERNATIVES' if len(canonical)>1 else 'ONE_CANONICAL_IDENTIFIER' if canonical else 'MISSING',
                source_equivalence_verified=False)


def compare(source: dict, candidate: dict, original_rank: int) -> dict:
    product=candidate['product']; raw=source['walmart_product']
    source_title=raw['title']; description=raw.get('pack_description','')
    title=product.get('title',''); detail=' '.join((title,product.get('size',''),product.get('variation','')))
    barcode=barcode_evidence(product)
    brand_tokens=tokens(product.get('brand',''))
    brand_clue=bool(brand_tokens) and brand_tokens<=tokens(source_title)
    overlap=len(tokens(source_title)&tokens(title))
    counts=content_counts(description); target_counts=content_counts(detail)
    measure=measures(description); target_measure=measures(detail)
    warnings=[]
    if not brand_clue: warnings.append('Candidate brand not supported by source-title clue; Walmart brand still unverified')
    if counts and target_counts and counts.isdisjoint(target_counts): warnings.append('Textual contents-count conflict')
    if sheets(description) and sheets(detail) and sheets(description).isdisjoint(sheets(detail)):
        warnings.append('Textual sheets-per-pad conflict')
    if measure and target_measure and measure.isdisjoint(target_measure): warnings.append('Textual size conflict')
    families=[]
    for family in ('super sticky','transparent','invisible','clear','school','clear glue'):
        if family in source_title.casefold() and family not in title.casefold():
            families.append(family)
    if families: warnings.append('Source product-family words absent from candidate title: '+', '.join(families))
    outer={int(n) for n in re.findall(r'pack\s+of\s+(\d+)',detail,re.I)}
    outer.update(int(n) for n in re.findall(r'\b(\d+)\s*[- ]\s*pack\b',detail,re.I))
    if any(n>1 for n in outer): warnings.append('Text describes an outer multipack; sellable-pack basis needs review')
    # Priority is a deterministic research aid, NEVER a match probability or identity evidence.
    score=(20 if brand_clue else -100)+overlap*3
    score+=8 if counts & target_counts else 0
    score+=6 if measure & target_measure else 0
    score-=25*len(warnings)
    promising_clue=brand_clue and not warnings
    gaps=dict(walmart_missing_fields=[k for k in REQUIRED_SOURCE if raw.get(k) in (None,'','UNKNOWN')],
        walmart_review_missing=raw.get('verified') is not True,
        walmart_pack_basis=raw.get('pack_quantity_basis','UNKNOWN'),
        amazon_missing_fields=[k for k in ('gtin','brand','model','size','variation','pack_quantity')
                               if product.get(k) in (None,'','UNKNOWN')],
        amazon_mapping_issues=product.get('mapping_issues',[]),
        prior_gate_missing=candidate.get('identity',{}).get('missing',[]),
        prior_gate_mismatches=candidate.get('identity',{}).get('mismatches',[]))
    return dict(asin=product['asin'],product=product,barcode_evidence=barcode,
        evidence_availability=dict(brand=bool(product.get('brand')),model=bool(product.get('model')),
            manufacturer_part_number='NOT_RETAINED_IN_SAVED_RECEIPTS',manufacturer='NOT_RETAINED_IN_SAVED_RECEIPTS',
            structured_dimensions='NOT_RETAINED_IN_SAVED_RECEIPTS',size_text=product.get('size') or None,
            amazon_package_quantity=product.get('pack_quantity')),
        research_priority_score=score,original_search_rank=original_rank,
        textual_clues=dict(title_token_overlap=overlap,source_title_brand_clue=brand_clue,
            source_contents_counts=sorted(counts),candidate_contents_counts=sorted(target_counts),
            source_measure_clues=sorted(measure),candidate_measure_clues=sorted(target_measure)),
        warnings=warnings,plausible_textual_lead=promising_clue,identity_gaps=gaps,
        status='UNVERIFIED_RESEARCH_LEAD' if promising_clue else 'CONFLICTING_OR_WEAK_LEAD',
        verified_exact_match=False,purchase_authorized=False)


def product_request(source: dict, comparisons: list[dict]) -> list[str]:
    p=source['walmart_product']; description=p.get('pack_description','UNKNOWN')
    requests=[f"Independently confirm the saved package description: {description}.",
              'Distinguish contents count from sellable retail-pack count; do not copy Amazon packageQuantity.']
    title=p['title'].casefold()
    if 'glue' in title:
        requests.append('Capture exact glue formulation/color, net contents and number of bottles; distinguish variants and multipacks.')
    if 'batter' in title:
        requests.append('Capture battery size/chemistry/product line, cells per retail pack and number of packs; confirm whether the barcode is for that whole pack.')
    if 'notes' in title:
        requests.append('Capture adhesive line (including whether Super Sticky), dimensions, pad count, sheets per pad, color and lined/unlined state; verify every count in the saved description.')
    if 'tape' in title:
        requests.append('Capture tape family/finish, width, length per roll, roll count, core size and refill/dispenser packaging; distinguish transparent from invisible/Magic variants.')
    if not any(c['plausible_textual_lead'] for c in comparisons):
        requests.append('No compatible lead is established in the saved first page; collect Walmart identity independently rather than forcing a pairing.')
    return requests


def build(batch: dict, searches: list[dict]) -> dict:
    by_id={r['candidate_id']:r for r in searches}
    products=[]
    for source in batch['observations']:
        saved=by_id[source['source_candidate_id']]
        results=[compare(source,c,i) for i,c in enumerate(saved['evidence']['candidates'],1)]
        results.sort(key=lambda c:(-c['research_priority_score'],c['original_search_rank'],c['asin']))
        leads=[c for c in results if c['plausible_textual_lead']]
        stats=Counter()
        for c in results:
            p=c['product']
            for field in ('brand','model','size','pack_quantity','variation'):
                if p.get(field) not in (None,''): stats[field]+=1
            for kind in ('UPC','EAN','GTIN'):
                if any(v['identifier_type']==kind for v in c['barcode_evidence']['valid_identifiers']):stats[kind]+=1
            stats['single_canonical_gtin']+=c['barcode_evidence']['status']=='ONE_CANONICAL_IDENTIFIER'
            stats['multiple_gtin_alternatives']+=c['barcode_evidence']['status']=='MULTIPLE_ALTERNATIVES'
        products.append(dict(candidate_id=source['source_candidate_id'],walmart_product=source['walmart_product'],
            candidates=results,strongest_textual_leads=[c['asin'] for c in leads[:1]],
            strongest_overall_review_candidates=[c['asin'] for c in results[:2]],
            availability_counts=dict(stats),returned_candidates=len(results),
            search_more_results=saved['evidence']['more_results'],
            estimated_search_results=saved['evidence']['total_results'],
            browser_request=product_request(source,results),verified_exact_match=False))
    # First collect discriminating identifiers for promising leads; then resolve weak cohorts.
    products.sort(key=lambda p:(not bool(p['strongest_textual_leads']),
        -max((c['research_priority_score'] for c in p['candidates'] if c['plausible_textual_lead']),default=-1000),p['candidate_id']))
    for priority,p in enumerate(products,1):p['browser_priority']=priority
    return dict(schema='m88-offline-identity-gaps-v1',cohort='m88-real-six-pilot',
        evaluated_at=datetime.now(timezone.utc).isoformat(),products=products,
        common_browser_request=COMMON_REQUEST,verified_exact_matches=0,purchase_authorized=False,
        ranking_policy='Textual research priority only; no verification, identity updates, fee/offer requests or ledger changes',
        retention_limitations=['Only normalized receipts were saved. Raw responses were not retained.',
            'Manufacturer part numbers, manufacturer and structured dimensions cannot be recovered; absence in receipts is not proof of absence from the HTTP response.',
            'Model is the saved model field, not a verified manufacturer part number.',
            'Numeric packageQuantity and textual contents counts have different possible bases; no automatic equivalence.',
            'All first-page searches were partial; no pagination or new requests in this phase.'])


def checklist(report: dict) -> str:
    lines=['# Browser Use — M88 Walmart identity enrichment','',
        'Use ordinary permitted browser access, Sacramento CA 95829. Keep the six Walmart item IDs unchanged. '+
        'Do not use Amazon lead identifiers as Walmart evidence. Leave unavailable fields UNKNOWN; stop on blockers.','',
        'For every item: capture retail-pack UPC/EAN/GTIN (leading zeros and barcode/pack basis), displayed brand, manufacturer, model/MPN separately, '+
        'selected variant/size and pack contents. Save per-field screenshots/excerpts, exact URL, aware timestamp and reviewer attestation. '+
        'Record any refreshed price/shipping separately; preserve old observations.','']
    for p in report['products']:
        source=p['walmart_product']; leads=p['strongest_textual_leads']
        lines.append(f"{p['browser_priority']}. **{source['title']} — Walmart {source['walmart_item_id']}**")
        lines.append('   '+source['url'])
        lines.append('   '+ ' '.join(p['browser_request']))
        lines.append('   '+('Unverified Amazon research leads: '+', '.join(leads)+'.' if leads else 'No compatible Amazon lead established in the saved first page.'))
        lines.append('')
    lines.append('Return six evidence records keyed by Walmart item ID, with UNKNOWNs explicit. No purchases, listings or access bypasses. purchase_authorized=false.')
    return '\n'.join(lines)+'\n'


def analyze(plan_path: Path, expected: str, output: Path) -> dict:
    plan_path=safe(plan_path)
    if sha(plan_path)!=expected:raise ValueError('Pinned M88 plan required')
    plan=read(plan_path);source_path=safe(Path(plan['source_path']));ledger_path=safe(Path(plan['ledger_path']))
    baseline=sha(ledger_path)
    if sha(source_path)!=plan['source_sha256']:raise ValueError('Source hash drift')
    accounting=ledger(ledger_path)
    if (accounting.get('m88_operation')!=expected or accounting['attempts_used']!=7
            or Counter(a['phase'] for a in accounting['attempts'])!={'authentication':1,'search':6}
            or any(a['status']!='COMPLETE' for a in accounting['attempts'])):
        raise ValueError('Completed original 7/49 M88 operation required')
    receipts=[];inventory=[dict(path=str(p),sha256=sha(p)) for p in (plan_path,source_path,ledger_path)]
    for attempt in accounting['attempts']:
        if attempt.get('plan_sha256')!=expected: raise ValueError('Unexpected operation binding')
        path=safe(plan_path.parent/f"receipt-{attempt['number']}.json")
        if sha(path)!=attempt['receipt_sha256']:raise ValueError('Receipt hash drift')
        item=read(path)
        if (item['number']!=attempt['number'] or item['phase']!=attempt['phase']
                or item['candidate_id']!=attempt['candidate_id']):raise ValueError('Receipt identity drift')
        if item['phase']=='search':receipts.append(item)
        inventory.append(dict(path=str(path),sha256=sha(path)))
    batch=read(source_path)
    if (len(batch.get('observations',[]))!=6 or len(receipts)!=6
            or len({r['candidate_id'] for r in receipts})!=6
            or {r['candidate_id'] for r in receipts}!={r['source_candidate_id'] for r in batch['observations']}):
        raise ValueError('Exactly six distinct source/search observations required')
    with publication(output,[source_path,plan_path.parent,ledger_path]) as stage:
        with offline(reads=[source_path,ledger_path,plan_path],writes=[stage]):
            report=build(batch,receipts)
            report.update(source_inventory=inventory,amazon_attempts=7,amazon_ceiling=49,
                          additional_http_attempts=0,ledger_sha256=baseline)
            write(stage/'identity-gap-report.json',report)
            write(stage/'browser-use-request.json',dict(cohort=report['cohort'],common_request=COMMON_REQUEST,
                products=[dict(priority=p['browser_priority'],walmart_item_id=p['walmart_product']['walmart_item_id'],
                    url=p['walmart_product']['url'],request=p['browser_request']) for p in report['products']],purchase_authorized=False))
            from app.m78_reporting import write as bytes_write
            bytes_write(stage/'browser-use-checklist.md',checklist(report).encode())
            for item in inventory:
                if sha(Path(item['path']))!=item['sha256']:raise ValueError('Evidence changed during comparison')
    return report


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',required=True,type=Path);parser.add_argument('--plan-sha256',required=True)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();result=analyze(args.plan,args.plan_sha256,args.output)
    print(f"Compared {len(result['products'])} products offline; ledger unchanged at 7/49; purchase_authorized=false.")


if __name__=='__main__':main()
