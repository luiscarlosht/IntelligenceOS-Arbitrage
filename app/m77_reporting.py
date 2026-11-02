"""Private partial-result preservation and redacted M77 Catalog-quality reporting."""
from collections import Counter, defaultdict
from pathlib import Path
from app.m65 import write_json
from app.m65_intelligence import sha256, US
from app.m70_sources import ingest
from app.m70_identity import merge, FIELDS
from app.m77_policy import OPERATION, BUDGET


def export(snapshot: dict,manifest: dict,baseline: set[str],output: Path) -> dict:
    if output.is_symlink() or any(p.is_symlink() for p in output.parents):raise ValueError('New private output required')
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    pages=output/'M77_catalog_pages.json'
    write_json(pages,dict(mode='M77_SAVED_AUTHORIZED_CATALOG_PAGES',operation_id=OPERATION,
        manifest_sha256=manifest['manifest_sha256'],status=snapshot['status'],pages=snapshot['pages'],
        eligibility='UNKNOWN',economics='UNKNOWN'))
    sources=output/'M77_M70_sources.json'
    write_json(sources,dict(schema=1,sources=[dict(path=pages.name,sha256=sha256(pages),adapter='amazon_catalog_pages',
        permission_reference='local:M77-explicit-owner-catalog-expansion',marketplace=US)]))
    observations,coverage=ingest(sources);grouped=defaultdict(list)
    for row in observations:grouped[row['asin']].append(row)
    identities={a:merge(rows) for a,rows in grouped.items()}
    raw=[item for page in snapshot['pages'] for item in page['items']]
    observed={item['asin'] for item in raw};excluded=set(manifest['permanently_excluded_asins'])
    unclaimed=observed-excluded;new=unclaimed-baseline
    report=dict(schema=1,mode='M77_REDACTED_CATALOG_EXPANSION',operation_id=OPERATION,
        manifest_sha256=manifest['manifest_sha256'],status=snapshot['status'],budget=dict(BUDGET),
        requests_consumed=snapshot['requests_consumed'],authentication_requests_consumed=int(snapshot['requests_consumed']>0),
        keyword_requests_consumed=max(0,snapshot['requests_consumed']-1),uncertain_slots=snapshot['uncertain_slots'],
        successful_keyword_pages=len(snapshot['pages']),distinct_observed_asins=len(observed),
        distinct_unclaimed_asins=len(unclaimed),distinct_new_asins=len(new),baseline_asins=len(baseline),
        distinct_real_asins_in_union=len(baseline|observed),
        historical_exclusions=len(excluded),previously_checked_asins=len(manifest['previously_checked_asins']),
        previously_known_asins=len(observed&baseline),distinct_excluded_asins=len(observed&excluded),
        returned_product_observations=len(raw),normalized_product_observations=len(observations),
        duplicate_observations=len(raw)-len(observed),excluded_observations=sum(i['asin'] in excluded for i in raw),
        identity_complete=sum(bool(identities.get(a,{}).get('identity_complete')) for a in unclaimed),
        catalog_identity_complete=sum(bool(identities.get(a,{}).get('catalog_identity_complete')) for a in unclaimed),
        identity_conflicts=sum(bool(identities.get(a,{}).get('identity_conflicts')) for a in unclaimed),
        missing_fields=dict(Counter(f for a in unclaimed for f in identities.get(a,dict(missing_fields=FIELDS))['missing_fields'])),
        source_coverage=coverage,checkpoint_sha256=snapshot['checkpoint_sha256'],
        source_quality='AUTHORIZED_CATALOG_OBSERVATIONS_NOT_VERIFIED_IDENTITY',
        eligibility='UNKNOWN',economics='UNKNOWN',new_reservations=0,
        pricing_requests=0,fee_requests=0,restriction_requests=0,retailer_requests=0,fba_requests=0,
        listings=0,purchases=0,approval_submissions=0,purchase_authorized=False,
        accounting='Consumed slots conservatively include uncertain or reserved-but-unsent attempts; no replay',
        interpretation='New means absent from the original M76 catalog and exclusions; reports do not modify that catalog or establish selling permission')
    write_json(output/'M77_summary.json',report)
    write_json(output/'M77_output_digests.json',{p.name:sha256(p) for p in sorted(output.iterdir())})
    return report
