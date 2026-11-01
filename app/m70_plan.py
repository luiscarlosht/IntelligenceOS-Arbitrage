"""Non-executable Catalog discovery budgeting and offline pagination projection."""
from decimal import Decimal, ROUND_CEILING
from app.amazon_pacing import OperationPacer

SEARCH_PATH='/catalog/2022-04-01/items'
DETAIL_PATH='/catalog/2022-04-01/items/{asin}'
REFERENCES=[
 'https://github.com/amzn/selling-partner-api-models/blob/main/models/catalog-items-api-model/catalogItems_2022-04-01.json',
 'https://developer-docs.amazon.com/sp-api/docs/catalog-items-api-rate-limits']


def validate_budget(budget: dict) -> None:
    expected={'authentication','keyword','identifier','detail','total','retries','restrictions','pricing','fees','retailer'}
    if (not isinstance(budget,dict) or set(budget)!=expected or any(type(v) is not int or v<0 for v in budget.values())
            or budget['authentication']!=1 or any(budget[k] for k in ('retries','restrictions','pricing','fees','retailer'))
            or budget['total']!=sum(budget[k] for k in ('authentication','keyword','identifier','detail'))
            or not 2<=budget['total']<=10001):
        raise ValueError('Exact finite proposed Catalog-only budget required')


def plan(*,target: int=1000,query_slots: int=50,pages_per_query: int=4,page_size: int=20,
         keyword_budget: int=200,identifier_budget: int=50,detail_budget: int=0,maximum_requests: int=251) -> dict:
    for value,maximum in ((target,10000),(query_slots,1000),(pages_per_query,1000),(page_size,20)):
        if type(value) is not int or not 1<=value<=maximum:raise ValueError('Explicit bounded discovery dimensions required')
    if pages_per_query*page_size>1000:raise ValueError('One Catalog query cannot page beyond 1000 results')
    budget=dict(authentication=1,keyword=keyword_budget,identifier=identifier_budget,detail=detail_budget,total=maximum_requests,
                retries=0,restrictions=0,pricing=0,fees=0,retailer=0)
    validate_budget(budget)
    if keyword_budget>query_slots*pages_per_query:raise ValueError('Keyword budget exceeds reviewed query/page coverage')
    pacer=OperationPacer()  # no state_path, token lookup, requests or persistence
    scenarios=[]
    for fraction in (Decimal('1'),Decimal('.5'),Decimal('.25')):
        pages=int((Decimal(target)/(Decimal(page_size)*fraction)).to_integral_value(rounding=ROUND_CEILING))
        scenarios.append(dict(assumed_unique_qualifying_fraction=str(fraction),estimated_keyword_pages=pages,
            fits_proposed_keyword_budget=pages<=keyword_budget,
            interpretation='Planning scenario only, not observed yield or guaranteed product count'))
    return dict(schema=1,mode='M70_CATALOG_PLANNING_ONLY',execution_authorized=False,executable=False,
        target_distinct_asins=target,query_slots=query_slots,query_keywords_and_filters='NOT_YET_REVIEWED',
        maximum_pages_per_query=pages_per_query,page_size=page_size,service_query_result_window=1000,
        identifier_batch_maximum=20,budget=budget,
        endpoints=[dict(method='GET',path=SEARCH_PATH,operation='searchCatalogItems',purpose='keyword discovery or separately budgeted ASIN batches'),
                   dict(method='GET',path=DETAIL_PATH,operation='getCatalogItem',purpose='optional identity detail only within reviewed detail budget')],
        included_data=['summaries','identifiers','relationships','attributes','productTypes','classifications','dimensions'],
        theoretical_record_capacity_before_overlap=keyword_budget*page_size,scenarios=scenarios,
        minimum_identifier_batches_if_all_target_asins_need_enrichment=(target+19)//20,
        identifier_pagination_note='All identifier pages consume the identifier budget; absent matches or omitted datasets can prevent full identity coverage',
        configured_limits=dict(search_rps_cap=pacer.rates['searchCatalogItems'],detail_rps_cap=pacer.rates['getCatalogItem'],
            headroom=pacer.headroom,effective_search_rps=pacer.rates['searchCatalogItems']*pacer.headroom,
            effective_detail_rps=pacer.rates['getCatalogItem']*pacer.headroom,
            documented_account_application_default_rps=2,documented_default_burst=2,
            documented_search_application_rps=500,documented_keyword_application_rps=50,documented_detail_application_rps=250,
            reference_discrepancy='Operation reference lists 5 RPS/burst 5; rate-limit guide lists 2/2. Keep configured conservative 2 RPS caps; confirm current account plan only after separate authorization.',
            account_usage_plan='UNKNOWN_NO_LIVE_PROBE',live_rate_headers_observed=False),
        minimum_paced_catalog_seconds=(keyword_budget+identifier_budget)/(pacer.rates['searchCatalogItems']*pacer.headroom)
            +detail_budget/(pacer.rates['getCatalogItem']*pacer.headroom),
        stop_rules=['Stop keyword phase at target or keyword/query/page exhaustion',
                    'Continue separately budgeted identity enrichment of collected ASINs after reaching discovery target',
                    'Stop on absent/repeated/invalid pagination cursor, service window, first failure or uncertainty',
                    'Never extend budgets, retry, refresh authentication or add unreviewed query partitions automatically'],
        checkpoint_strategy=['Future executor must durably consume every request before transport, including authentication',
            'Append-only reviewed query/filter hash, page index, response hash, seen-ASIN digest and budget counters',
            'Opaque continuation tokens stay private; export hashes only; never follow arbitrary source URLs',
            'Interruption/uncertain dispatch remains consumed; offline reconciliation and fresh authorization precede any continuation'],
        discovery_strategy=['Owner must review actual query/category/type partitions; avoid only national-brand seeds',
            'At most 1000 pageable results per query; overlap, missing identities and exhausted queries lower unique yield',
            'Normalize/deduplicate exact ASINs after each page and merge only compatible observed identity fields',
            'Identifier enrichment is limited to collected ASINs; no new ASIN intake from enrichment responses'],
        future_authorization_requirements=['Separate reviewed executable adapter and frozen actual request/query manifest',
            'Exact digests, existing-account/US scope, current history and fresh explicit owner authorization',
            'Hard Catalog/authentication budgets, zero retries, permanent dispatch accounting and bounded pacing',
            'No Listings Restrictions, Pricing, Fees, FBA, retailer or follow-on operations'],
        references=REFERENCES,actual_requests=0,actual_authentication=0,new_reservations=0)


def project_pages(pages: list[dict],budget: dict,*,per_query_limit: int=50) -> dict:
    """Validate saved/synthetic page sequences, not dispatch instructions."""
    validate_budget(budget)
    if type(per_query_limit) is not int or not 1<=per_query_limit<=1000:raise ValueError('Finite page bound required')
    counts={'keyword':0,'identifier':0,'detail':0};cursors={};ended=set();seen=set();query_counts={}
    for page in pages:
        kind=page.get('kind');query=page.get('query_id')
        if kind not in counts or not isinstance(query,str):raise ValueError('Fixed Catalog operation/page identity required')
        if sum(counts.values())+1>=budget['total'] or counts[kind]>=budget[kind]:raise ValueError('Proposed request budget exhausted')
        key=(kind,query)
        if key in ended or page.get('page_token')!=cursors.get(key):raise ValueError('Broken/terminal pagination sequence')
        query_counts[key]=query_counts.get(key,0)+1
        if query_counts[key]>per_query_limit:raise ValueError('Per-query paging bound exhausted')
        token=page.get('next_token')
        if token is not None and (not isinstance(token,str) or not token or (key,token) in seen):raise ValueError('Repeated or invalid token')
        if token:seen.add((key,token))
        else:ended.add(key)
        cursors[key]=token;counts[kind]+=1
    return dict(planned_page_counts=counts,projected_authentication_slots=1,
                projected_total_slots=sum(counts.values())+1,incomplete_queries=len(set(cursors)-ended),
                actual_requests=0,new_reservations=0,executable=False)
