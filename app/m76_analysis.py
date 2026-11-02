"""Exact-ASIN catalog consolidation and hypothetical M77 query ranking."""
from collections import Counter, defaultdict
from math import ceil
from app.m70_identity import FIELDS, merge
from app.m73_analysis import baseline_observation
from app.observations import fingerprint


def analyze(prior, observations, pages, manifest, baseline_digest):
    baseline = {p['asin']:p for p in prior['catalog']}
    grouped = defaultdict(list)
    for p in baseline.values(): grouped[p['asin']].append(baseline_observation(p, baseline_digest))
    observed = {o['asin'] for o in observations}
    excluded = set(manifest['permanently_excluded_asins']); checked = set(manifest['previously_checked_asins'])
    if (len(baseline) != 377 or len(baseline) != len(prior['catalog']) or len(observed-baseline.keys()-excluded) != 400
            or len(observed|baseline.keys()) != 777 or len(observations) != 400 or len(observed) != 400
            or len(excluded) != 97 or len(checked) != 40 or not checked <= excluded):
        raise ValueError('Exact 377 + 400 = 777 reconciliation required')
    for obs in observations:
        if obs['role'] != 'amazon': raise ValueError('Real Amazon observations required')
        grouped[obs['asin']].append(obs)
    catalog=[]
    for asin, rows in sorted(grouped.items()):
        p=merge(rows)
        p.update(cohorts=(['M73'] if asin in baseline else [])+(['M75'] if asin in observed else []),
                 permanently_excluded=asin in excluded, previously_checked_seller_specific=asin in checked,
                 historical_m73_record=baseline.get(asin), economics='UNKNOWN')
        p['identity_sha256']=fingerprint(p); catalog.append(p)
    conflicts=[dict(asin=p['asin'],field=f,observed_values=p['observed_alternatives'][f],
                    field_provenance=p['field_provenance'][f],resolution='UNRESOLVED')
               for p in catalog for f in p['identity_conflicts']]
    definitions={q['query_id']:q for q in manifest['queries']}
    coverage=[]; seen=set(baseline)
    for page in sorted(pages,key=lambda p:p['request_slot']):
        asins={i['asin'] for i in page['items']}; q=definitions[page['query_reference']]
        coverage.append(dict(query_id=q['query_id'],keywords=q['keywords'],category_intent=q['category_intent'],
            returned=len(page['items']),distinct=len(asins),incremental=len(asins-seen),
            duplicate_observations=len(page['items'])-len(asins),overlap=len(asins&seen)))
        seen |= asins
    executed=set(manifest['executed_query_ids']) | {p['query_reference'] for p in pages}
    intent_counts=Counter(c['category_intent'] for c in coverage)
    candidates=[q for q in manifest['queries'] if q['query_id'] not in executed]
    candidates.sort(key=lambda q:(intent_counts[q['category_intent']],q['review_order'],q['query_id']))
    queries=[dict(rank=n,query_id=q['query_id'],keywords=q['keywords'],category_intent=q['category_intent'],
        observed_m75_pages_in_intent=intent_counts[q['category_intent']],
        observed_m75_incremental_in_intent=sum(c['incremental'] for c in coverage if c['category_intent']==q['category_intent']),
        rationale='Unobserved M75 intent first; original reviewed order breaks ties. Exact intent labels are not marketplace coverage.',
        evidence_class='OFFLINE_QUERY_HYPOTHESIS', execution_authorized=False) for n,q in enumerate(candidates,1)]
    scenarios=[dict(duplicate_percent=r,required_result_slots=ceil(223/(1-r/100)),
                    full_twenty_item_pages=ceil(223/(20*(1-r/100))),
                    projected_incremental_at_capacity=int(20*len(queries)*(1-r/100)),
                    additional_query_definitions_required=max(0,ceil(223/(20*(1-r/100)))-len(queries))) for r in (25,50,75)]
    proposal=dict(mode='M77_OFFLINE_PROPOSAL_ONLY',queries=queries,selected_query_ids=[q['query_id'] for q in queries[:23]],
        remaining_target=223,planning_duplicate_percent=50,planning_full_pages=23,planning_raw_slots=460,
        projected_incremental=230,scenarios=scenarios,execution_authorized=False,live_enabled=False,
        limitation='Full pages and duplicate rates are assumptions. Sparse/rejected pages or overlap may require more queries; yield is not guaranteed.',
        observed_m75_distinct_new=400,observed_m75_pages=20,observed_m75_new_per_page=20)
    if len(queries)<23: raise ValueError('Insufficient unreplayed query proposals')
    annotations=[dict(asin=a,permanently_excluded=a in excluded,previously_checked_seller_specific=a in checked,
                      in_catalog=a in grouped,eligibility='HISTORICAL_ONLY_NOT_REINTERPRETED',
                      historical_m73_annotation=next((r for r in prior['exclusions'] if r['asin']==a),None))
                 for a in sorted(excluded|checked)]
    summary=dict(mode='M76_OFFLINE_CONSOLIDATION',real_asins=777,baseline_asins=377,m75_distinct_new=400,
        remaining_asins=223,missing_fields={f:sum(p[f] is None for p in catalog) for f in FIELDS},
        identity_complete=sum(p['identity_complete'] for p in catalog),
        catalog_identity_complete=sum(p['catalog_identity_complete'] for p in catalog),
        conflict_asins=sum(bool(p['identity_conflicts']) for p in catalog),prior_unresolved_conflict_asins=31,
        permanent_exclusions=97,previously_checked_asins=40,excluded_in_catalog=sum(p['permanently_excluded'] for p in catalog),
        previously_checked_in_catalog=sum(p['previously_checked_seller_specific'] for p in catalog),
        actual_requests=0,actual_authentication=0,purchase_ready_inventory=0,execution_authorized=False,
        purchase_authorized=False,eligibility='UNKNOWN',economics='UNKNOWN')
    return dict(summary=summary,catalog=catalog,conflicts=conflicts,annotations=annotations,coverage=coverage,proposal=proposal)
