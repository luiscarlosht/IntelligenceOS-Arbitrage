"""Private M70 import and redacted pilot-quality reporting; no live operations."""
from collections import Counter,defaultdict
from pathlib import Path
from app.m65 import write_json
from app.m65_intelligence import sha256, US
from app.m70_sources import ingest
from app.m70_identity import merge,FIELDS
from app.m72_policy import OPERATION, PROPOSAL_SHA256, BUDGET


def export(snapshot: dict,proposal: dict,baseline: set[str],output: Path):
    if output.is_symlink() or any(p.is_symlink() for p in output.parents):raise ValueError('Dedicated nonsymlink private output required')
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    pages=output/'M72_catalog_pages.json'
    write_json(pages,dict(mode='M72_CATALOG_PILOT_SAVED',pages=snapshot['pages'],operation_id=OPERATION,
        proposal_sha256=PROPOSAL_SHA256,status=snapshot['status'],eligibility='UNKNOWN'))
    sources=output/'M72_M70_sources.json'
    write_json(sources,dict(schema=1,sources=[dict(path=pages.name,sha256=sha256(pages),adapter='amazon_catalog_pages',
        permission_reference='local:M72-explicit-owner-pilot',marketplace=US)]))
    observations,coverage=ingest(sources)
    grouped=defaultdict(list)
    for row in observations:grouped[row['asin']].append(row)
    identities={a:merge(rows) for a,rows in sorted(grouped.items())}
    raw=[item for page in snapshot['pages'] for item in page['items']]
    observed={item['asin'] for item in raw};excluded=set(proposal['excluded_asins']);unclaimed=observed-excluded;new=unclaimed-baseline
    complete=sum(bool(identities.get(a,{}).get('identity_complete')) for a in unclaimed)
    report=dict(schema=1,mode='M72_REDACTED_CATALOG_PILOT',operation_id=OPERATION,proposal_sha256=PROPOSAL_SHA256,
        status=snapshot['status'],requests_consumed=snapshot['requests_consumed'],
        authentication_requests_consumed=int(snapshot['requests_consumed']>0),
        keyword_requests_consumed=max(0,snapshot['requests_consumed']-1),budget=BUDGET,
        uncertain_slots=snapshot['uncertain_slots'],successful_keyword_pages=len(snapshot['pages']),
        distinct_observed_asins=len(observed),distinct_unclaimed_asins=len(unclaimed),distinct_new_asins=len(new),
        previously_known_unclaimed_asins=len(unclaimed&baseline),baseline_asins=len(baseline),
        returned_product_observations=len(raw),normalized_product_observations=len(observations),
        duplicate_observations=len(raw)-len(observed),
        duplicate_rate=(len(raw)-len(observed))/len(raw) if raw else None,
        distinct_excluded_asins=len(observed&excluded),excluded_observations=sum(r['asin'] in excluded for r in raw),
        historical_exclusions=len(excluded),
        identity_complete=complete,
        identity_complete_percent=100*complete/len(unclaimed) if unclaimed else None,
        catalog_identity_complete=sum(bool(identities.get(a,{}).get('catalog_identity_complete')) for a in unclaimed),
        identity_conflicts=sum(bool(identities.get(a,{}).get('identity_conflicts')) for a in unclaimed),
        missing_fields=dict(Counter(f for a in unclaimed for f in identities.get(a,dict(missing_fields=FIELDS))['missing_fields'])),
        source_quality='SAVED_AUTHORIZED_SP_API_CATALOG_OBSERVATIONS_NOT_IDENTITY_VERIFICATION',source_coverage=coverage,
        eligibility='UNKNOWN',new_asin_reservations=0,eligibility_checks=0,pricing_requests=0,fees_requests=0,
        fba_checks=0,listings=0,purchases=0,approval_submissions=0,
        checkpoint_sha256=snapshot['checkpoint_sha256'],
        interpretation='New means distinct unclaimed ASINs absent from the hash-bound M70 baseline, not eligibility or verified identity')
    write_json(output/'M72_summary.json',report)
    return report
