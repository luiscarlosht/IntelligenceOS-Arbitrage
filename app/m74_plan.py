"""Deterministic observed coverage and explicitly hypothetical future query planning."""
from collections import Counter
from itertools import combinations

from app.m71_manifest import AUTH_URL, DATA, HOST, PATH
from app.m65_intelligence import US
from app.observations import fingerprint

# Reviewed human vocabulary only: neither categories nor uniqueness are verified.
NEW_QUERIES = (
    ('baking_accessories', 'silicone baking brush'),
    ('travel_accessories', 'luggage handle wrap'),
    ('laundry_accessories', 'mesh laundry wash bag'),
    ('bath_accessories', 'shower curtain clips'),
    ('cleaning_accessories', 'microfiber dusting mitt'),
    ('sewing_accessories', 'sewing seam gauge'),
    ('outdoor_accessories', 'tent guyline adjusters'),
    ('bicycle_accessories', 'bicycle valve adapter'),
    ('desk_accessories', 'monitor memo board'),
    ('planting_accessories', 'seedling transplant tool'),
)
OPERATION = 'M75-US-CATALOG-EXPLORE20-ONCE'
BUDGET = dict(authentication=1, keyword=20, total=21, identifier=0, additional_pages=0,
              retries=0, refreshes=0, eligibility=0, pricing=0, fees=0, fba=0,
              retailer=0, listings=0, purchases=0, approvals=0)


def words(value: str) -> set[str]:
    return set(value.casefold().split())


def parameters(keywords: str) -> dict:
    return dict(marketplaceIds=US, includedData=','.join(DATA), pageSize='20', keywords=keywords)


def budgets(remaining: int, capacity: int) -> list[dict]:
    if type(remaining) is not int or remaining < 0 or type(capacity) is not int or capacity < 1:
        raise ValueError('Nonnegative remaining target and positive candidate capacity required')
    result = []
    for duplicate in (25,50,75):
        # Integer arithmetic, rounded upward. Rates are assumptions, not estimates
        # of query-specific uniqueness or marketplace counts.
        slots = (remaining*100 + 99-duplicate)//(100-duplicate)
        pages = (slots+19)//20
        operations = (pages+19)//20
        result.append(dict(evidence_class='PROJECTION_FROM_ASSUMPTION', duplicate_percent=duplicate,
            remaining_unique_target=remaining, result_slots=slots, keyword_pages=pages,
            single_operation_authentication=1 if pages else 0,
            single_operation_request_ceiling=pages+(1 if pages else 0),
            twenty_page_operation_count=operations, twenty_page_authentication=operations,
            twenty_page_total_request_ceiling=pages+operations,
            planned_first_page_capacity=capacity, extra_query_definitions_required=max(0,pages-capacity),
            m75_request_ceiling=BUDGET['total'], m75_maximum_raw_result_slots=400,
            m75_can_reach_remaining_target_at_zero_duplicates=remaining<=400,
            assumption='Full 20-result pages; duplicates include accumulated-catalog overlap; sparse/rejected results can require more requests',
            monetary_cost='UNKNOWN_NOT_ESTIMATED', execution_authorized=False))
    return result


def build(report: dict, evidence: dict, frozen: dict, account_binding: str, hashes: dict,
          implementation: dict) -> dict:
    catalog = {p['asin']:p for p in report['catalog']}
    definitions = {q['id']:q for q in frozen['queries']}
    pages = sorted(evidence['pages'], key=lambda p:p['request_slot'])
    executed = [p['query_reference'] for p in pages]
    if len(executed)!=len(set(executed)) or any(q not in definitions for q in executed):
        raise ValueError('Distinct original executed query identifiers required')
    intent_counts = Counter(definitions[q]['category_intent'] for q in executed)
    sets = {}; coverage = []
    for page in pages:
        query = definitions[page['query_reference']]; asins = {i['asin'] for i in page['items']}
        if not asins <= set(catalog): raise ValueError('Every observed ASIN must exist in verified M73')
        sets[query['id']] = asins
        baseline_overlap = sum('M70' in catalog[a]['cohorts'] for a in asins)
        coverage.append(dict(evidence_class='OBSERVATION', query_id=query['id'], keywords=query['keywords'],
            category_intent=query['category_intent'], request_slot=page['request_slot'],
            returned_observations=len(page['items']), distinct_asins=len(asins),
            within_page_duplicates=len(page['items'])-len(asins), baseline_overlap=baseline_overlap,
            conflict_asins=sum(bool(catalog[a]['identity_conflicts']) for a in asins),
            brand_counts=dict(sorted(Counter(catalog[a]['brand'] or 'UNKNOWN' for a in asins).items())),
            category_counts=dict(sorted(Counter(catalog[a]['category'] or 'UNKNOWN' for a in asins).items())),
            has_unfollowed_cursor=bool(page['pagination'].get('nextToken')),
            source_sha256=evidence['pages_digest'], response_sha256=page['response_sha256']))
    overlaps = [dict(evidence_class='OBSERVATION', query_a=a, query_b=b,
        shared_asins=len(sets[a]&sets[b]), union_asins=len(sets[a]|sets[b]),
        shared_brand_labels=sorted({catalog[x]['brand'] for x in sets[a] if catalog[x]['brand']} &
                                   {catalog[x]['brand'] for x in sets[b] if catalog[x]['brand']}),
        shared_category_labels=sorted({catalog[x]['category'] for x in sets[a] if catalog[x]['category']} &
                                      {catalog[x]['category'] for x in sets[b] if catalog[x]['category']}),
        jaccard=len(sets[a]&sets[b])/len(sets[a]|sets[b]) if sets[a]|sets[b] else None)
        for a,b in combinations(sorted(sets),2)]
    intents = list(dict.fromkeys(q['category_intent'] for q in frozen['queries']))
    gaps = [dict(evidence_class='OBSERVATION', category_intent=intent,
        completed_m72_pages=intent_counts[intent],
        observed_m72_distinct_asins=len(set().union(*(sets[q] for q in sets if definitions[q]['category_intent']==intent))),
        unexecuted_frozen_queries=[q['id'] for q in frozen['queries'] if q['category_intent']==intent and q['id'] not in executed],
        status='NO_M72_QUERY_PAGE_OBSERVED' if not intent_counts[intent] else 'ONE_FIRST_PAGE_ONLY',
        limitation='No mapping from legacy coarse categories to query intents is inferred; no marketplace coverage claim')
        for intent in intents]
    existing = [dict(query_id=q['id'], origin='M71_FROZEN_UNEXECUTED', keywords=q['keywords'],
        category_intent=q['category_intent'], frozen_definition=q, definition_sha256=fingerprint(q),
        evidence_class='PROPOSED_ACTION_FROM_FROZEN_DEFINITION',
        traceability=dict(proposal_sha256=frozen['proposal_sha256'], original_query_id=q['id']),
        rationale='Untested intent first' if not intent_counts[q['category_intent']] else 'New phrase within intent sampled once; later rounds diversify vocabulary')
        for q in frozen['queries'] if q['id'] not in executed]
    # One earliest frozen query for each intent before later vocabulary rounds.
    first = {intent: next((q['query_id'] for q in existing if q['category_intent']==intent),None) for intent in intents}
    untouched = [q for q in existing if q['query_id']==first[q['category_intent']] and not intent_counts[q['category_intent']]]
    proposals = [dict(query_id=f'm74-n{n:03}', origin='M74_NEW_HYPOTHESIS', keywords=phrase,
        category_intent=intent, evidence_class='HUMAN_VOCABULARY_HYPOTHESIS',
        frozen_definition=None, definition_sha256=fingerprint(dict(intent=intent,keywords=phrase)),
        traceability=dict(configuration='app/m74_plan.py:NEW_QUERIES',
                          matching_observed_category_labels=[x['value'] for x in report['diversity']
                              if x['dimension']=='category' and x['value'].casefold()==intent.replace('_',' ').casefold()]),
        rationale='New proposed intent label with no M72 query history; category absence is an exact-label observation only, semantic coverage and yield unknown')
        for n,(intent,phrase) in enumerate(NEW_QUERIES,1)]
    candidates = untouched + proposals + [q for q in existing if q not in untouched]
    normalized = set()
    for rank,q in enumerate(candidates,1):
        key=' '.join(q['keywords'].casefold().split())
        if key in normalized or any(key==' '.join(definitions[x]['keywords'].casefold().split()) for x in executed):
            raise ValueError('Repeated/executed phrase cannot enter the proposed plan')
        normalized.add(key)
        q.update(review_order=rank, future_asin_overlap=None, marketplace_demand=None,
                 uniqueness_probability=None, request_parameters=parameters(q['keywords']), execution_authorized=False,
                 lexical_overlap_with_executed=[dict(query_id=x, shared_words=sorted(words(q['keywords'])&words(definitions[x]['keywords'])))
                    for x in executed if words(q['keywords'])&words(definitions[x]['keywords'])])
    if len({q['query_id'] for q in candidates})!=len(candidates) or set(executed)&{q['query_id'] for q in candidates}:
        raise ValueError('Executed IDs are permanently fenced from candidate queries')
    selected = candidates[:20]
    if len(selected)!=20: raise ValueError('Exactly twenty distinct future queries required')
    manifest = dict(schema=1, mode='M74_OFFLINE_QUERY_PROPOSAL', execution_authorized=False, live_enabled=False,
        proposal_sha256=frozen['proposal_sha256'], evidence_sha256=fingerprint(hashes),
        implementation_sha256=implementation, executed_query_ids=executed, proposed_m75_budget=dict(BUDGET),
        permanently_excluded_asins=evidence['excluded'], previously_checked_asins=evidence['checked'],
        queries=candidates, proposed_m75_query_ids=[q['query_id'] for q in selected],
        note='All queries are proposals. Original M71 definitions remain frozen; no old authorization or unused budget carries forward.')
    manifest['manifest_sha256'] = fingerprint(manifest)
    contract = dict(mode='M75_EXECUTION_CONTRACT_PROPOSAL_ONLY', implementation_required=True,
        execution_authorized=False, live_enabled=False, operation_id=OPERATION,
        permanent_registry='m75-catalog-discovery.sqlite3', global_account_lock='candidate-execution.lock',
        account_reference=frozen['account_reference'], marketplace=US, account_binding_sha256=account_binding,
        m74_manifest_sha256=manifest['manifest_sha256'], evidence_sha256=fingerprint(hashes), budget=dict(BUDGET),
        authentication=dict(method='POST',url=AUTH_URL,grant_type='refresh_token',maximum_requests=1),
        keyword_requests=[dict(slot=i+2,query_id=q['query_id'],method='GET',host=HOST,path=PATH,
                               parameters=q['request_parameters']) for i,q in enumerate(selected)],
        allowed_query_keys=['marketplaceIds','includedData','pageSize','keywords'],
        transport='Verified TLS; no proxies, redirects, SDK retries or automatic refresh; exact host/path/method/body/parameter validation',
        pacing=dict(maximum_effective_search_rps=1,minimum_spacing_seconds=1,burst=1,
                    respect_lower_frozen_config=True,respect_saved_cooldowns=True,lower_response_rates_only=True),
        socket_timeout_seconds=10,hard_operation_timeout_seconds=120,
        accounting='Exclusive global account lock; exclusively create and fsync permanent registry/parent; append-only FULL-synchronous intent before every dispatch including authentication; any prior claim blocks forever',
        stop_policy='First error, throttle, Retry-After, timeout, interruption, expiry, drift or uncertain dispatch stops permanently; no retry, replay, resume, replacement query or cursor following',
        authorization=dict(required=True,maximum_lifetime_seconds=600,interactive_owner_confirmation=True,
            separate_from_all_historical_operations=True,
            bind_to=['new M75 operation ID','exact reviewed M75 executable implementation digest',
                'M74 manifest file and canonical digests','M74 completion manifest and exact M75 contract file digest',
                'all evidence digests and current history',
                'existing account/credential binding and US marketplace','exact twenty request definitions',
                'integer 1 authentication + 20 keyword / 21 total ceiling','UTC issue/expiry and no-replay acknowledgement'],
            recheck='Before credential loading and every dispatch under the global account lock; create/consume only in a separately reviewed M75 implementation'),
        retention='Save successful/partial Catalog evidence privately; maintain all exclusions/conflicts; report consumed/uncertain slots; unknown eligibility and economics',
        forbidden_operations=['identifier','additional page','retry','refresh','eligibility','pricing','fees','FBA','retailer','listings','purchase','approval'])
    return dict(manifest=manifest, contract=contract, coverage=coverage, overlaps=overlaps, gaps=gaps,
        diversity=[dict(x,evidence_class='OBSERVATION') for x in report['diversity']], scenarios=budgets(report['summary']['remaining_asins'],len(candidates)),
        historical=dict(evidence_class='OBSERVATION',exclusions=report['exclusions'],
            conflict_summary=[dict(asin=p['asin'],conflict_fields=p['identity_conflicts'],cohorts=p['cohorts'])
                              for p in report['catalog'] if p['identity_conflicts']],
            missing_fields=report['summary']['missing_fields']),
        summary=dict(mode='M74_OFFLINE_DISCOVERY_PLANNING',real_asins=len(catalog),target=1000,
            remaining_asins=report['summary']['remaining_asins'],executed_queries=len(executed),
            unexecuted_m71_queries=len(existing),new_hypothetical_queries=len(proposals),candidate_queries=len(candidates),
            untested_m71_intents=[g['category_intent'] for g in gaps if not g['completed_m72_pages']],
            observed_pairwise_shared_asins=sum(x['shared_asins'] for x in overlaps),
            overlap_limitation='Observed first pages only; zero observed overlap does not imply future uniqueness',
            permanent_exclusions=len(evidence['excluded']),previously_checked_asins=len(evidence['checked']),
            unresolved_conflict_asins=report['summary']['combined_conflict_asins'],
            offline_identity_research_candidates=report['summary']['research_reviewable'],
            observed_brand_labels=sum(x['dimension']=='brand' for x in report['diversity']),
            observed_category_labels=sum(x['dimension']=='category' for x in report['diversity']),
            sparse_observed_category_labels=[x['value'] for x in report['diversity']
                if x['dimension']=='category' and x['asin_count']<=2],
            sparse_sample_definition='At most two catalog ASINs per exact category label; reporting threshold, not evidence of marketplace scarcity',
            category_limit='Exact source labels, not a harmonized taxonomy or proven marketplace gaps',
            proposed_m75_request_ceiling=21,proposed_m75_maximum_raw_results=400,
            m75_cannot_complete_remaining_target=report['summary']['remaining_asins']>400,
            economic_cost='UNKNOWN_NOT_ESTIMATED',execution_authorized=False,live_enabled=False,
            actual_amazon_requests=0,actual_authentication=0,purchase_authorized=False))
