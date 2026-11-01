"""Deterministic offline research priority; scores are never probabilities."""
from collections import Counter
from datetime import datetime, timezone
import csv
import json
from pathlib import Path

from app.m65_intelligence import ASIN, US, observed, private_values, read_json, safe_text
from app.normalization import gtin, identity
from app.observations import canonical, fingerprint

# Previous discovery seeds, not a claim about company size or approval likelihood.
PREVIOUS_SEED_BRANDS={'oxo','whitmor','post-it','command','kitchenaid','idesign','avery',
                      'duck','joseph joseph','sterilite','bic','stanley'}


def candidates(path: Path) -> list[dict]:
    """M63 saved Catalog report, candidate JSON list, or M63-compatible CSV."""
    if path.suffix.casefold()=='.csv':
        if path.is_symlink() or path.stat().st_size>16*1024*1024:
            raise ValueError('Bounded regular candidate CSV required')
        with path.open(encoding='utf-8-sig',newline='') as stream:
            source=list(csv.DictReader(stream))
        digest=__import__('hashlib').sha256(path.read_bytes()).hexdigest()
        secrets=private_values(source)
    else:
        document,digest=read_json(path)
        secrets=private_values(document)
        if isinstance(document,dict):
            if document.get('is_mock') is True:
                raise ValueError('Synthetic data cannot prepare real cohorts')
            source=document.get('candidates',[])
            if isinstance(source,dict):
                source=list(source.values())
        else:
            source=document
    if not isinstance(source,list) or len(source)>10000:
        raise ValueError('Bounded candidate list required')
    grouped={}
    for index,row in enumerate(source):
        if not isinstance(row,dict) or row.get('is_mock') is True:
            raise ValueError('Real structured candidates required')
        cat=row.get('catalog') or row
        asin=row.get('asin') or cat.get('asin')
        if not isinstance(asin,str) or not ASIN.fullmatch(asin) or cat.get('asin',asin)!=asin:
            raise ValueError('Explicit consistent ASIN required')
        marketplace=row.get('marketplace') or row.get('marketplace_id')
        # M63 CSV has a canonical US URL but no marketplace column.
        if marketplace is None and row.get('amazon_url')=='https://www.amazon.com/dp/'+asin:
            marketplace=US
        provenance=row.get('provenance') or row.get('discovery_source')
        date=observed(row.get('observed_at'))
        if marketplace!=US or not provenance or not date or datetime.fromisoformat(date)>datetime.now(timezone.utc):
            raise ValueError('US scope, original aware observation and provenance required')
        ids=cat.get('identifiers',[])
        if row.get('identifiers_json'):
            ids=json.loads(row['identifiers_json'])
        if not isinstance(ids,list):
            raise ValueError('Identifier array required')
        valid_ids=[]
        for value in ids:
            if not isinstance(value,dict):
                raise ValueError('Structured identifier required')
            raw=value.get('value') or value.get('identifier')
            kind=value.get('kind') or value.get('identifier_type') or value.get('identifierType')
            try:
                normalized=gtin(raw) if kind in ('UPC','EAN','GTIN') and isinstance(raw,str) else ''
            except ValueError:
                normalized=''
            if normalized:
                valid_ids.append(normalized)
        pack=cat.get('package_quantity')
        package_attrs=row.get('package_attributes') or {}
        if row.get('pack_information_json'):
            pack_info=json.loads(row['pack_information_json'])
            pack=pack_info.get('package_quantity')
            package_attrs=pack_info.get('attributes') or {}
        summary=row.get('summary_fields') or {}
        size=summary.get('size') or cat.get('size') or row.get('size')
        variation=cat.get('variation')
        issues=list(cat.get('mapping_issues') or [])
        if row.get('mapping_issues_json'):
            issues=json.loads(row['mapping_issues_json'])
        if not isinstance(issues,list):
            raise ValueError('Mapping issues array required')
        conflict=len(set(valid_ids))>1 or any(any(t in str(issue).casefold() for t in ('ambiguous','conflict','invalid gtin','variation parent')) for issue in issues)
        brand=safe_text(row.get('brand') or summary.get('brand'),secrets)
        title=safe_text(cat.get('title') or row.get('title'),secrets)
        model=safe_text(cat.get('model') or row.get('model'),secrets)
        product_type=safe_text(row.get('product_type') or cat.get('product_type'),secrets) or 'UNKNOWN'
        flags=dict(gtin=bool(valid_ids) and len(set(valid_ids))==1,model=bool(model),
                   size=bool(size),pack=type(pack) is int and pack>0,
                   variation=bool(variation),product_type=product_type!='UNKNOWN')
        candidate=dict(asin=asin,candidate_id='amazon-us:'+asin,marketplace=US,
            title=title,brand=brand or 'UNKNOWN',category=safe_text(row.get('category'),secrets) or 'UNKNOWN',
            product_type=product_type,observed_at=date,identity_features=flags,
            identity_conflict=conflict,identity_exact_match=None,eligibility='UNKNOWN',
            fba_eligibility=None,purchase_authorized=False,
            source_reference=f'sha256:{digest}:candidate:{index}',source_sha256=digest,
            identity_fingerprint=fingerprint(dict(ids=sorted(set(valid_ids)),model=model,
                pack=pack,size=safe_text(size,secrets),variation=safe_text(variation,secrets))))
        prior=grouped.get(asin)
        if prior:
            if prior['identity_fingerprint']!=candidate['identity_fingerprint'] or prior['brand']!=candidate['brand']:
                prior['identity_conflict']=True
            prior['source_references'].append(candidate['source_reference'])
        else:
            grouped[asin]=dict(candidate,source_references=[candidate['source_reference']])
    return [grouped[a] for a in sorted(grouped)]


def rank(catalog: list[dict], history: list[dict], manual: list[dict], excluded: set[str],
         *, maximum: int=20, max_per_brand: int=2, minimum_score: int=0,
         additional_points: dict[str,dict[str,int]] | None=None) -> dict:
    if type(maximum) is not int or not 1<=maximum<=100 or type(max_per_brand) is not int or not 1<=max_per_brand<=maximum:
        raise ValueError('Explicit bounded cohort and brand caps required')
    if type(minimum_score) is not int or not -100<=minimum_score<=100:
        raise ValueError('Explicit research-priority floor required')
    checked=excluded|{e['asin'] for e in history}
    # Any observed heavy pathway remains a cautious soft priority penalty until
    # reviewed. It never propagates ASIN eligibility or asserts a universal rule.
    invoice_brands={identity(m['brand']) for m in manual if m['review_status'] in ('REVIEWED','VERIFIED_USER_OBSERVATION')
                    and m['invoice_required'] is True and (m['minimum_invoiced_units'] or 0)>=100}
    history_brands=Counter(identity(e['brand']) for e in history if e.get('brand'))
    rows=[]
    seen=set()
    for entry in catalog:
        if entry['asin'] in seen:
            raise ValueError('Deduplicate candidate input first')
        seen.add(entry['asin'])
        brand=identity(entry.get('diversification_brand') or entry['brand'])
        features=entry['identity_features']
        points={key:(weight if features[key] else 0) for key,weight in
                (('gtin',8),('model',4),('size',4),('pack',4),('variation',4),('product_type',2))}
        points['outside_previous_seed_brands']=8 if brand not in PREVIOUS_SEED_BRANDS and brand!='unknown' else 0
        points['invoice_heavy_observation']=-35 if brand in invoice_brands else 0
        points['previous_sample_concentration']=-6 if history_brands[brand]>=2 else 0
        # Optional, explicit milestone policy extends shared scoring without
        # changing the existing M65 defaults or duplicating greedy selection.
        extra=(additional_points or {}).get(entry['asin'],{})
        if any(not isinstance(k,str) or k in points or type(v) is not int or not -100<=v<=100 for k,v in extra.items()):
            raise ValueError('Bounded, uniquely named priority adjustments required')
        points.update(extra)
        reasons=[]
        if entry['asin'] in checked:reasons.append('PREVIOUSLY_CHECKED_OR_RESERVED')
        if entry['identity_conflict']:reasons.append('IDENTITY_CONFLICT')
        if not entry['title'] or brand=='unknown':reasons.append('MISSING_TITLE_OR_BRAND')
        rows.append(dict(entry,score=sum(points.values()),score_components=points,
                         exclusion_reasons=reasons,selected=False,eligibility='UNKNOWN',
                         priority_review_required=sum(points.values())<minimum_score,
                         brand_pathway_signal='OBSERVED_INVOICE_HEAVY' if brand in invoice_brands else 'UNKNOWN'))
    # Greedy diversity costs are explicit integer ordering heuristics. No
    # statistical eligibility likelihood is calculated from the small sample.
    brands,categories,types=Counter(),Counter(),Counter()
    selected=[]
    while len(selected)<maximum:
        pool=[r for r in rows if not r['selected'] and not r['exclusion_reasons'] and not r['priority_review_required']
              and brands[identity(r.get('diversification_brand') or r['brand'])]<max_per_brand]
        if not pool:break
        def key(r):
            diversity=12*brands[identity(r.get('diversification_brand') or r['brand'])]+8*categories[r['category']]
            if r['product_type']!='UNKNOWN':diversity+=4*types[r['product_type']]
            return (-(r['score']-diversity),r['asin'])
        choice=min(pool,key=key)
        choice['selection_score']=-key(choice)[0]
        choice['selected']=True
        selected.append(choice['asin'])
        brands[identity(choice.get('diversification_brand') or choice['brand'])]+=1
        categories[choice['category']]+=1
        if choice['product_type']!='UNKNOWN':types[choice['product_type']]+=1
    rows.sort(key=lambda r:(not r['selected'], selected.index(r['asin']) if r['selected'] else -r['score'],r['asin']))
    return dict(schema=1,mode='M65_OFFLINE_RANKING',rows=rows,selected_asins=selected,
                requested_maximum=maximum,actual_selected=len(selected),max_per_brand=max_per_brand,
                minimum_score=minimum_score,
                score_interpretation='deterministic research priority, not eligibility probability',
                eligibility='UNKNOWN',live_requests=0,purchase_authorized=False,
                diversity_gaps=dict(outside_previous_seed_brands=sum(r['brand']!='UNKNOWN' and identity(r['brand']) not in PREVIOUS_SEED_BRANDS for r in rows),
                                    unknown_product_type=sum(r['product_type']=='UNKNOWN' for r in rows)))
