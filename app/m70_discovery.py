"""Scalable offline catalog composition with unchanged M69 history and scoring."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import tempfile

from app.m65 import write_json
from app.m69_discovery import analyze as m69_analyze
from app.m70_sources import ingest,file_hash
from app.m70_identity import merge,match_key,exact_match,FIELDS
from app.normalization import identity
from app.observations import fingerprint


def implementation() -> dict:
    from app.m69_discovery import implementation as prior
    root=Path(__file__).parent
    return dict(prior(),**{n:file_hash(root/n) for n in ('m70.py','m70_sources.py','m70_identity.py','m70_discovery.py','m70_plan.py','sp_catalog_targets.py','amazon_catalog.py')})


def scoring_row(product: dict) -> dict:
    """Lossless observed-data projection for M69, not synthetic enrichment."""
    cat=dict(asin=product['asin'],title=product['title'],model=product['model'],
        package_quantity=product['pack_quantity'],variation=product['variation'],product_type=product['product_type'],
        identifiers=[dict(kind='GTIN',value=product['gtin'])] if product['gtin'] else [],
        mapping_issues=['Ambiguous source identity; explicit review required'] if product['identity_conflicts'] or product['review_blocks'] else [])
    row=dict(asin=product['asin'],brand=product['brand'],category=product['category'],marketplace=product['marketplace'],
        observed_at=product['observed_at'],provenance='local:source-bound-M70-normalization',
        catalog=cat,summary_fields=dict(size=product['size']))
    if product['condition']:row['condition']=product['condition']
    return row


def select(rows: list[dict],maximum: int,max_per_brand: int) -> list[str]:
    if type(maximum) is not int or not 1<=maximum<=200 or type(max_per_brand) is not int or not 1<=max_per_brand<=200:
        raise ValueError('Bounded shortlist of at most 200 and explicit brand cap required')
    brands=Counter();categories=Counter();types=Counter();selected=[]
    for row in rows:row['selected']=False;row.pop('selection_score',None)
    eligible=[r for r in rows if not r['exclusion_reasons'] and not r['priority_review_required']]
    while len(selected)<maximum:
        pool=[r for r in eligible if not r['selected'] and brands[identity(r.get('diversification_brand') or r['brand'])]<max_per_brand]
        if not pool:break
        def ordering(row):
            diversity=12*brands[identity(row.get('diversification_brand') or row['brand'])]+8*categories[row['category']]
            if row['product_type']!='UNKNOWN':diversity+=4*types[row['product_type']]
            return (-(row['score']-diversity),row['asin'])
        chosen=min(pool,key=ordering);chosen['selected']=True;chosen['selection_score']=-ordering(chosen)[0]
        selected.append(chosen['asin']);brands[identity(chosen.get('diversification_brand') or chosen['brand'])]+=1
        categories[chosen['category']]+=1
        if chosen['product_type']!='UNKNOWN':types[chosen['product_type']]+=1
    positions={a:i for i,a in enumerate(selected)}
    rows.sort(key=lambda r:(not r['selected'],positions[r['asin']] if r['selected'] else -r['score'],r['asin']))
    return selected


def build(source_manifest: Path,store: Path,private: Path,manifest: Path,manifest_digest: str,*,
          as_of: datetime,shortlist: int=150,max_per_brand: int=10,page_size: int=200,
          maximum_observations: int=100000,maximum_asins: int=10000) -> dict:
    if as_of.tzinfo is None or as_of>datetime.now(timezone.utc):raise ValueError('Aware nonfuture analysis clock required')
    observations,coverage=ingest(source_manifest,page_size=page_size,
        maximum_observations=maximum_observations,maximum_asins=maximum_asins)
    if any(datetime.fromisoformat(o['observed_at'])>as_of for o in observations):raise ValueError('Analysis clock predates source observations')
    grouped=defaultdict(list);retailers=[]
    for obs in observations:
        if obs['role']=='amazon':grouped[obs['asin']].append(obs)
        else:retailers.append(merge([obs]))
    catalog=[merge(grouped[a]) for a in sorted(grouped)]
    lookup={p['asin']:p for p in catalog};retailer_index=defaultdict(list)
    for retailer in retailers:
        k=match_key(retailer)
        if k is not None:retailer_index[k].append(retailer)
    for product in catalog:
        candidates=retailer_index.get(match_key(product),[]) if match_key(product) is not None else []
        matched=[r for r in candidates if exact_match(product,r)['status']=='EXACT_IDENTITY_OBSERVED']
        product['retailer_match_status']='EXACT_IDENTITY_OBSERVED' if matched else 'UNKNOWN'
        product['retailer_match_source_references']=sorted({ref for r in matched for ref in r['source_references']})
    # Existing M69 accepts local normalized product observations, not retailer
    # records or quality flags. Temporary projections carry only real observed
    # values; their hashes are reproducible and no private ledger is written.
    with tempfile.TemporaryDirectory(prefix='m70-offline-') as temp:
        paths=[]
        for start in range(0,max(len(catalog),1),500):
            path=Path(temp)/f'catalog-{start:06}.json'
            write_json(path,[scoring_row(p) for p in catalog[start:start+500]]);paths.append(path)
        prior,history=m69_analyze(paths,store,private,manifest,manifest_digest,as_of=as_of,maximum=100,max_per_brand=min(max_per_brand,100))
    rows=prior['ranking']['rows']
    for row in rows:
        product=lookup[row['asin']]
        quality=max((6 if c in ('m63_json','amazon_catalog_items','amazon_catalog_pages') else 3 if c=='m63_csv' else 1) for c in product['source_classes'])
        row['score_components']['source_quality']=quality
        row['score_components']['M70_complete_observed_identity']=20 if product['identity_complete'] else 0
        row['score_components']['M70_complete_core_identity']=10 if product['m69_core_complete'] else 0
        row['score']=sum(row['score_components'].values())
        row['priority_review_required']=row['score'] < -100
        row['source_references']=product['source_references'];row['source_reference']=product['source_references'][0]
        row.pop('source_sha256',None)
        row['source_observation_sha256']=product['source_sha256'];row['normalized_identity_sha256']=fingerprint(product)
        row['identity_complete']=product['identity_complete'];row['identity_confidence_percent']=product['identity_confidence_percent']
        row['identity_conflicts']=product['identity_conflicts'];row['retailer_match_status']=product['retailer_match_status']
        row['eligibility']='UNKNOWN';row['identity_verified']=False
    selected=select(rows,shortlist,max_per_brand)
    if set(selected)&set(history['excluded_asins']):raise ValueError('Permanent exclusion invariant')
    excluded=set(history['excluded_asins'])
    for product in catalog:product['permanently_excluded']=product['asin'] in excluded
    amazon_count=sum(o['role']=='amazon' for o in observations)
    duplicate_count=amazon_count-len(catalog)
    enriched=sum((len(FIELDS)-len(p['missing_fields']))>max(sum(bool(o['fields'][f]) and len(o['fields'][f])==1 for f in FIELDS) for o in grouped[p['asin']]) for p in catalog)
    coverage.update(amazon_observations=amazon_count,retailer_observations=len(retailers),unique_amazon_asins=len(catalog),
        duplicate_asin_observations=duplicate_count,duplicate_asin_rate=duplicate_count/amazon_count if amazon_count else None,
        retailer_only_asins=len({r['asin'] for r in retailers if r['asin'] and r['asin'] not in lookup}),
        complementary_enriched_asins=enriched,
        normalized_scoring_input_sha256=[p['source_sha256'] for p in prior['source_profiles']])
    chosen=[lookup[a] for a in selected]
    brands=Counter(p['brand'] or 'UNKNOWN' for p in catalog);categories=Counter(p['category'] or 'UNKNOWN' for p in catalog)
    complete=sum(p['identity_complete'] for p in catalog)
    completion=100*complete/len(catalog) if catalog else None
    known_brands=len([b for b in brands if b!='UNKNOWN']);known_categories=len([c for c in categories if c!='UNKNOWN'])
    summary=dict(schema=1,mode='M70_OFFLINE_CATALOG',as_of=as_of.isoformat(),discovered_asins=len(catalog),
        identity_complete=complete,identity_complete_percent=completion,
        catalog_identity_complete=sum(p['catalog_identity_complete'] for p in catalog),
        m69_core_identity_complete=sum(p['m69_core_complete'] for p in catalog),
        conflict_asins=sum(bool(p['identity_conflicts']) for p in catalog),
        missing_fields=dict(Counter(f for p in catalog for f in p['missing_fields'])),
        brand_count=known_brands,category_count=known_categories,brand_distribution=dict(sorted(brands.items())),
        category_distribution=dict(sorted(categories.items())),shortlist_count=len(selected),shortlist_requested=shortlist,
        shortlist_brand_distribution=dict(sorted(Counter(p['brand'] or 'UNKNOWN' for p in chosen).items())),
        shortlist_category_distribution=dict(sorted(Counter(p['category'] or 'UNKNOWN' for p in chosen).items())),
        permanent_exclusions=len(excluded),historically_excluded_in_catalog=sum(p['asin'] in excluded for p in catalog),
        historical_cohort=history['cohort_summary'],history_complete=history['history_complete'],data_gaps=history['data_gaps'],
        target_results=dict(distinct_1000=len(catalog)>=1000,complete_80_percent=completion is not None and completion>=80,
            brands_50=known_brands>=50,categories_10=known_categories>=10,shortlist_100_to_200=100<=len(selected)<=200),
        eligibility='UNKNOWN',identity_verified=False,fba_state='FBA_UNKNOWN',
        actual_amazon_requests=0,actual_authentication=0,retailer_network_requests=0,eligibility_checks=0,
        new_permanent_reservations=0,purchases=0,listing_submissions=0,approval_submissions=0,
        limitation='Targets require legitimate additional source coverage. Complete means structurally observed, not manually verified or sellable; Catalog data is condition-agnostic.')
    return dict(schema=1,mode='M70_OFFLINE_REPORT',implementation_sha256=implementation(),summary=summary,
        catalog=catalog,ranking=rows,selected_asins=selected,history=history,source_coverage=coverage,
        interpretation='No generated fields, new ASINs, selling permission or profitability inferred by enrichment')
