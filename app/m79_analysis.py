"""Offline evidence coverage and research priority; never infer demand from identity."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from app.m65_intelligence import US, ASIN
from app.m70_identity import FIELDS

UNKNOWN = 'UNKNOWN'
TTL = {'eligibility': 24, 'bsr': 24, 'amazon_price': 6, 'offer_count': 6,
       'buy_box': 6, 'category': 720, 'catalog_list_price': 720}


def date(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo and result.utcoffset() is not None else None
    except ValueError:
        return None


def state(value, timestamp, now, hours):
    if value is None or value == UNKNOWN:
        return 'MISSING'
    observed = date(timestamp)
    if not observed or observed > now:
        return 'UNVERIFIED'
    return 'AVAILABLE' if now - observed <= timedelta(hours=hours) else 'STALE'


def list_prices(pages, digest):
    result = {}
    rejected = {}
    for page in pages:
        for item in page['items']:
            values = []
            for entry in item.get('attributes', {}).get('list_price', []):
                if entry.get('marketplace_id') != US or entry.get('currency') != 'USD':
                    rejected.setdefault(item['asin'], []).append(dict(reason='NON_USD_OR_WRONG_MARKETPLACE', raw=entry))
                    continue
                try:
                    raw = entry.get('value')
                    amount = Decimal(str(raw)) if not isinstance(raw, bool) else Decimal('NaN')
                    if not amount.is_finite() or amount <= 0:
                        rejected.setdefault(item['asin'], []).append(dict(reason='NONPOSITIVE_OR_INVALID_PRICE', raw=entry))
                        continue
                except (InvalidOperation, ValueError):
                    rejected.setdefault(item['asin'], []).append(dict(reason='INVALID_PRICE', raw=entry))
                    continue
                values.append(dict(value=str(amount), currency='USD', observed_at=page['observed_at'],
                                   source_sha256=digest, source_reference=f'page:{page["request_slot"]}:asin:{item["asin"]}:attributes.list_price',
                                   interpretation='CATALOG_LIST_PRICE_NOT_CURRENT_OFFER'))
            if values:
                result.setdefault(item['asin'], []).extend(values)
    return result, rejected


def analyze(catalog, history, pages, pages_digest, now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Aware UTC analysis time required')
    now = now.astimezone(timezone.utc)
    asins = [p['asin'] for p in catalog]
    if len(asins) != len(set(asins)) or any(not ASIN.fullmatch(a) for a in asins):
        raise ValueError('Distinct observed ASINs required')
    historical = {}
    for event in history.get('events', []):
        if event.get('marketplace') == US and event.get('condition') == 'new_new':
            historical.setdefault(event['asin'], []).append(event)
    prices, rejected_prices = list_prices(pages, pages_digest)
    rows = []
    for product in catalog:
        asin = product['asin']
        rows.append(dict(asin=asin, marketplace=US,
            **{f: product.get(f) if product.get(f) is not None else UNKNOWN for f in FIELDS},
            upc_values=product.get('upc_values', []),
            identity_conflicts=product.get('identity_conflicts', []), review_blocks=product.get('review_blocks', []),
            permanently_excluded=bool(product.get('permanently_excluded')),
            historical_seller_checked=bool(product.get('previously_checked_seller_specific')),
            historical_eligibility=[{k: event.get(k) for k in ('eligibility', 'observed_at', 'condition',
                'marketplace', 'operation_status', 'source_reference', 'source_sha256')} for event in historical.get(asin, [])],
            eligibility=UNKNOWN, bsr=UNKNOWN, amazon_price=UNKNOWN, offer_count=UNKNOWN,
            buy_box=UNKNOWN, price_stability=UNKNOWN, estimated_monthly_sales=UNKNOWN,
            demand_rank=UNKNOWN, competition_rank=UNKNOWN, stability_rank=UNKNOWN, eligibility_rank=UNKNOWN,
            sales_estimate_confidence=UNKNOWN, metric_status={},
            catalog_list_prices=prices.get(asin, []), catalog_list_price_rejections=rejected_prices.get(asin, []),
            field_provenance=product.get('field_provenance', {}), field_status=product.get('field_status', {}),
            identity_verified=False,
            source_references=product.get('source_references', []), source_sha256=product.get('source_sha256', []),
            observed_at=product.get('observed_at'), last_observed_at=product.get('last_observed_at'),
            cohorts=product.get('cohorts', []), purchase_authorized=False, sourcing_allowed=False))
    for row in rows:
        for metric in TTL:
            if metric == 'category':
                evidence = [e for e in row['field_provenance'].get('category', []) if e.get('status') == 'SOURCE_OBSERVED']
                timestamp = max((e.get('observed_at', '') for e in evidence), default=None)
                row['metric_status'][metric] = state(row['category'], timestamp, now, TTL[metric])
            elif metric == 'catalog_list_price':
                statuses = [state(p['value'], p['observed_at'], now, TTL[metric]) for p in row['catalog_list_prices']]
                row['metric_status'][metric] = 'AVAILABLE' if 'AVAILABLE' in statuses else 'STALE' if 'STALE' in statuses else 'UNVERIFIED' if row['catalog_list_price_rejections'] else 'MISSING'
            else:
                # Catalog discovery has no adapter for actual offer, BSR or
                # current seller permission evidence. History is separate.
                row['metric_status'][metric] = 'MISSING'
        row['historical_eligibility_status'] = [dict(value=e['eligibility'],
            status=state(e['eligibility'], e['observed_at'], now, TTL['eligibility'])) for e in row['historical_eligibility']]
        blockers = (['PERMANENT_EXCLUSION'] if row['permanently_excluded'] else [])
        if row['identity_conflicts'] or row['review_blocks']:
            blockers.append('IDENTITY_REVIEW_BLOCK')
        row['research_blockers'] = blockers
        # Explicitly a coverage count, never a demand/eligibility probability.
        row['identity_field_count'] = sum(row[f] != UNKNOWN for f in FIELDS)
        row['priority_basis'] = 'IDENTITY_COVERAGE_ONLY_FOR_AMAZON_METRIC_ACQUISITION'
        row['shortlist_status'] = 'BLOCKED_NO_VERIFIED_DEMAND_OR_CURRENT_ELIGIBILITY'
    research = sorted((r for r in rows if not r['research_blockers']),
                      key=lambda r: (-r['identity_field_count'], r['asin']))
    for n, row in enumerate(research, 1):
        row['research_position'] = n
    for row in rows:
        row.setdefault('research_position', UNKNOWN)
    coverage = []
    for metric in TTL:
        counts = Counter(r['metric_status'][metric] for r in rows)
        coverage.append(dict(metric=metric, total_asins=len(rows), available=counts['AVAILABLE'],
            missing=counts['MISSING'], stale=counts['STALE'], unverified=counts['UNVERIFIED'],
            available_observed=counts['AVAILABLE'] + counts['STALE'], freshness_hours=TTL[metric]))
    historical_states = Counter()
    for row in rows:
        states = [e['status'] for e in row['historical_eligibility_status']]
        historical_states['AVAILABLE' if 'AVAILABLE' in states else 'STALE' if 'STALE' in states else
                          'UNVERIFIED' if states else 'MISSING'] += 1
    coverage.append(dict(metric='historical_eligibility_only', total_asins=len(rows),
        available=historical_states['AVAILABLE'], stale=historical_states['STALE'],
        missing=historical_states['MISSING'], unverified=historical_states['UNVERIFIED'],
        available_observed=historical_states['AVAILABLE'] + historical_states['STALE'], freshness_hours=24))
    for field in ('gtin', 'brand', 'model', 'title', 'pack_quantity'):
        statuses = []
        for row in rows:
            evidence = [e for e in row['field_provenance'].get(field, []) if e.get('status') == 'SOURCE_OBSERVED']
            timestamp = max((e.get('observed_at', '') for e in evidence), default=None)
            statuses.append(state(row[field], timestamp, now, 720))
        counts = Counter(statuses)
        coverage.append(dict(metric=field, total_asins=len(rows), available=counts['AVAILABLE'],
            stale=counts['STALE'], missing=counts['MISSING'], unverified=counts['UNVERIFIED'],
            available_observed=counts['AVAILABLE'] + counts['STALE'], freshness_hours=720))
    history_counts = Counter(e['eligibility'] for r in rows for e in r['historical_eligibility'])
    categories = Counter(r['category'] for r in rows)
    summary = dict(asins=len(rows), as_of=now.isoformat(), verified_demand_shortlist=0,
        demand_ranking='BLOCKED_MISSING_SALES_METRICS', walmart_handoff_ready=False,
        historical_checks_in_catalog=sum(bool(r['historical_eligibility']) for r in rows),
        historical_check_states=dict(history_counts), permanent_exclusions=sum(r['permanently_excluded'] for r in rows),
        identity_conflict_asins=sum(bool(r['identity_conflicts']) for r in rows),
        catalog_list_price_present_asins=sum(bool(r['catalog_list_prices'] or r['catalog_list_price_rejections']) for r in rows),
        catalog_list_price_rejected_observations=sum(len(r['catalog_list_price_rejections']) for r in rows),
        research_candidates=len(research), actual_amazon_requests=0, purchase_authorized=False,
        limitation='Saved M76/M77 catalog data does not support demand, competition, price stability or current selling permission.')
    return dict(summary=summary, coverage=coverage, catalog=sorted(rows, key=lambda r:r['asin']),
        top100=[], top20=[], research100=research[:100], research20=research[:20],
        categories=[dict(category=k, asins=v, bsr_available=0) for k,v in sorted(categories.items())],
        method=dict(demand='UNKNOWN: no retained BSR observations or calibrated sales labels',
            competition='UNKNOWN: no current offer counts or Buy Box evidence',
            stability='UNKNOWN: no comparable current-offer time series',
            eligibility='UNKNOWN: historical restrictions are not current permission; permanent exclusions retained',
            research_order='Unblocked identity coverage count descending, exact ASIN ascending for ties; no demand implication',
            sales_model='NOT_FITTED: no validated category-specific BSR-to-units calibration; no unit estimates or confidence intervals',
            shortlist='Empty until supported fresh demand and seller eligibility evidence is separately obtained and reviewed'))
