"""Conservative catalog union, conflict review and offline research priority."""
from collections import Counter, defaultdict
from math import ceil

from app.m70_identity import FIELDS, merge, observation
from app.observations import fingerprint


def baseline_observation(product: dict, digest: str) -> dict:
    mapped = dict(asin=product['asin'], marketplace=product['marketplace'],
                  **{f: product['observed_alternatives'][f] for f in FIELDS})
    result = observation(mapped, role='amazon', reference=f'sha256:{digest}:asin:{product["asin"]}',
                         source_hash=digest, source_class='M70_FROZEN_BASELINE', observed_at=product['observed_at'])
    result['review_blocks'] = product['review_blocks']
    return result


def analyze(evidence: dict) -> dict:
    baseline = {p['asin']: p for p in evidence['baseline']}
    if len(baseline) != len(evidence['baseline']):
        raise ValueError('Distinct baseline identities required')
    grouped = defaultdict(list)
    for p in baseline.values():
        grouped[p['asin']].append(baseline_observation(p, evidence['baseline_digest']))
    live = defaultdict(list)
    for obs in evidence['observations']:
        grouped[obs['asin']].append(obs); live[obs['asin']].append(obs)
    catalog = []
    for asin, rows in sorted(grouped.items()):
        p = merge(rows)
        p['cohorts'] = (['M70'] if asin in baseline else []) + (['M72'] if asin in live else [])
        p['permanently_excluded'] = asin in evidence['excluded']
        p['previously_checked_seller_specific'] = asin in evidence['checked']
        # Baseline provenance is aggregate: alternatives cannot honestly be
        # assigned individually to a particular old source observation.
        p['baseline_field_provenance'] = baseline[asin]['field_provenance'] if asin in baseline else {}
        p['baseline_source_classes'] = baseline[asin]['source_classes'] if asin in baseline else []
        p['baseline_source_references'] = baseline[asin]['source_references'] if asin in baseline else []
        p['baseline_unsupported_observations'] = baseline[asin]['unsupported_observations'] if asin in baseline else []
        p['identity_sha256'] = fingerprint(p)
        catalog.append(p)
    conflicts = []
    for cohort, products in (('M70', baseline.values()), ('M72', [merge(v) for v in live.values()])):
        for p in products:
            for field in p['identity_conflicts']:
                conflicts.append(dict(cohort=cohort, asin=p['asin'], field=field,
                    conflict_kind='MULTIPLE_CATALOG_GTINS' if field=='gtin' and cohort=='M72' else 'OBSERVED_IDENTITY_DISAGREEMENT',
                    raw_catalog_evidence=[dict(query_reference=page['query_reference'], request_slot=page['request_slot'],
                        dataset='identifiers', marketplace_scoped_values=item.get('identifiers',[]))
                        for page in evidence.get('pages',[]) for item in page['items']
                        if cohort=='M72' and field=='gtin' and item['asin']==p['asin']],
                    observed_values=p['observed_alternatives'][field], source_references=p['source_references'],
                    field_provenance=p['field_provenance'][field], resolution='UNRESOLVED',
                    investigation='Multiple normalized observed values; no supported primary value',
                    next_action='Review GTIN ownership and unit/case packaging; do not choose an identifier or infer a pack from prefixes' if field=='gtin' else 'Review original structured datasets; retain null until independently resolved'))
    # Do not silently resolve cross-cohort contradictions.
    for p in catalog:
        if len(p['cohorts']) == 2:
            for field in p['identity_conflicts']:
                conflicts.append(dict(cohort='COMBINED', asin=p['asin'], field=field,
                    observed_values=p['observed_alternatives'][field], source_references=p['source_references'],
                    field_provenance=p['field_provenance'][field], resolution='UNRESOLVED',
                    investigation='Combined observed alternatives disagree', next_action='Review both frozen sources'))
    ranking = []
    for p in catalog:
        reasons = (['PERMANENT_EXCLUSION'] if p['permanently_excluded'] else [])
        reasons += ['IDENTITY_CONFLICT'] if p['identity_conflicts'] else []
        reasons += p['review_blocks']
        score = sum(10 for f in FIELDS if p[f] is not None)
        ranking.append(dict(asin=p['asin'], brand=p['brand'], category=p['category'], title=p['title'],
            observed_field_score=score, missing_fields=p['missing_fields'], blockers=sorted(set(reasons)),
            research_reviewable=not reasons, identity_complete=p['identity_complete'],
            eligibility='UNKNOWN', purchase_authorized=False, source_references=p['source_references']))
    ranking.sort(key=lambda r:(not r['research_reviewable'], -r['observed_field_score'], r['asin']))
    for position, row in enumerate(ranking, 1): row['review_position'] = position
    missing = {f: sum(p[f] is None for p in catalog) for f in FIELDS}
    remaining = max(0, 1000-len(catalog))
    scenarios = [dict(duplicate_rate_percent=rate, additional_result_slots=ceil(remaining/(1-rate/100)),
        minimum_full_20_item_pages=ceil(ceil(remaining/(1-rate/100))/20),
        assumption='Full 20-item pages; duplicate rate includes overlap with existing catalog; not a request authorization or guarantee')
        for rate in (25, 50, 75)]
    m72_conflicts = len({r['asin'] for r in conflicts if r['cohort']=='M72'})
    if m72_conflicts != evidence['completion']['identity_conflicts']:
        raise ValueError('Recomputed M72 conflicts differ from immutable summary')
    observed = set(live); new = observed-set(baseline)-set(evidence['excluded'])
    if len(new) != evidence['completion']['distinct_new_asins']:
        raise ValueError('Recomputed M72 new count differs from immutable summary')
    summary = dict(mode='M73_OFFLINE_CONSOLIDATION', real_asins=len(catalog), target=1000,
        unexcluded_real_asins=sum(not p['permanently_excluded'] for p in catalog),
        remaining_asins=remaining, target_percent=len(catalog)/10, expected_unique_asins=377,
        target_count_basis='All distinct real observed ASINs, including permanent exclusions; not a sellable candidate count',
        expected_count_reconciled=len(catalog)==377, count_difference=len(catalog)-377,
        baseline_asins=len(baseline), m72_asins=len(live), cross_cohort_duplicates=len(set(baseline)&observed),
        m72_duplicate_observations=len(evidence['observations'])-len(live), m72_new_asins=len(new),
        baseline_conflict_asins=sum(bool(p['identity_conflicts']) for p in baseline.values()),
        m72_conflict_asins=m72_conflicts, combined_conflict_asins=sum(bool(p['identity_conflicts']) for p in catalog),
        missing_fields=missing, identity_complete=sum(p['identity_complete'] for p in catalog),
        catalog_identity_complete=sum(p['catalog_identity_complete'] for p in catalog),
        permanent_exclusions=len(evidence['excluded']), previously_checked_asins=len(evidence['checked']),
        excluded_in_catalog=sum(p['permanently_excluded'] for p in catalog),
        research_reviewable=sum(r['research_reviewable'] for r in ranking),
        readiness='OFFLINE_IDENTITY_RESEARCH_ONLY',
        limitation='Research priority is observed field coverage only. Missing condition, identity conflicts and unknown eligibility/economics block purchase readiness.',
        checkpoint_sha256=evidence['checkpoint'], actual_requests=0, actual_authentication=0,
        execution_authorized=False, purchase_authorized=False)
    diversity = [dict(dimension=f, value=k, asin_count=v) for f in ('brand','category')
                 for k,v in sorted(Counter(p[f] or 'UNKNOWN' for p in catalog).items())]
    exclusions = [dict(asin=a, permanently_excluded=True, previously_checked_seller_specific=a in evidence['checked'],
                       in_combined_catalog=a in grouped) for a in evidence['excluded']]
    return dict(summary=summary, catalog=catalog, conflicts=conflicts, ranking=ranking,
                diversity=diversity, exclusions=exclusions, scenarios=scenarios,
                source_coverage=evidence['coverage'])
