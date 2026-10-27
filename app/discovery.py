"""Discovery screening, evidence quality and deterministic ranking."""
from datetime import datetime, timezone
from decimal import Decimal
from app.connectors import RetailerConnector
from app.marketplace import AmazonProvider
from app.profitability import analyze, COST_FIELDS
from app.normalization import http_url


def screen(product, match, config, now):
    listing = match.listing
    issues = list(product.issues) + list(match.reasons)
    if listing and listing.asin == 'B0G1MJ24B4':
        issues.append('NOT_ELIGIBLE: retained US/new_new authorized-seller restriction; sourcing excluded')
    for field in ('retailer', 'name', 'url', 'provenance', 'package_quantity', 'purchase_price', 'retrieved_at'):
        if not getattr(product, field): issues.append('Missing source ' + field)
    if product.url and not http_url(product.url): issues.append('Invalid source URL')
    if product.availability != 'in_stock': issues.append('Inventory not confirmed in stock')
    if not match.exact: issues.append('Exact match not verified')
    if not listing: issues.append('Missing marketplace listing')
    costs = {}
    if listing:
        if listing.seller_eligible is not True: issues.append('Seller eligibility not verified')
        if listing.sale_price is None: issues.append('Missing sale price')
        if not listing.provenance: issues.append('Missing marketplace provenance')
        if not listing.asin: issues.append('Missing ASIN')
        if listing.monthly_sales is None: issues.append('Missing demand indicator')
        elif listing.monthly_sales < config.minimum_monthly_sales: issues.append('Demand below threshold')
        if listing.offer_count is None: issues.append('Missing competition indicator')
        elif listing.offer_count > config.maximum_offers: issues.append('Competition above threshold')
        for key in COST_FIELDS:
            value = listing.costs.get(key)
            if key == 'referral_fee' and listing.referral_rate is not None:
                value = Decimal('0')
            if value is None: issues.append('Missing cost ' + key)
            else: costs[key] = value
    for label, stamp in [('source', product.retrieved_at), ('marketplace', listing.retrieved_at if listing else None)]:
        if stamp is None: issues.append('Missing ' + label + ' timestamp')
        elif stamp > now: issues.append('Future ' + label + ' timestamp')
        elif (now - stamp).total_seconds() > config.maximum_data_age_hours * 3600:
            issues.append('Stale ' + label + ' data')
    economics = None
    if listing and listing.sale_price is not None and product.purchase_price and len(costs) == len(COST_FIELDS):
        try:
            economics = analyze(product.purchase_price, listing.sale_price, costs,
                Decimal(str(config.minimum_roi)), Decimal(str(config.minimum_profit)), listing.referral_rate)
        except (ValueError, KeyError):
            issues.append('Invalid economics input')
    if economics:
        if economics.net_profit < Decimal(str(config.minimum_profit)): issues.append('Profit below threshold')
        if economics.roi < Decimal(str(config.minimum_roi)): issues.append('ROI below threshold')
        if economics.acquisition_cost > Decimal(str(config.inventory_budget)): issues.append('One unit exceeds inventory budget')
    else: issues.append('Economics cannot be calculated')
    is_mock = listing.is_mock if listing else config.amazon_provider == 'mock'
    unverified = [k for k in COST_FIELDS if not listing or k not in listing.verified_costs]
    if listing and listing.referral_rate is not None:
        unverified = [k for k in unverified if k != 'referral_fee']
        if 'referral_rate' not in listing.verified_costs: unverified.append('referral_rate')
    # Transparent evidence score, not a probability of matching or profit.
    components = [not product.issues, match.exact, bool(product.provenance),
                  bool(listing and listing.provenance), not unverified,
                  bool(listing and listing.seller_eligible is True),
                  not any('timestamp' in i or 'Stale' in i for i in issues),
                  bool(listing and listing.monthly_sales is not None),
                  bool(listing and listing.offer_count is not None), not issues]
    confidence = sum(components) * 10
    if is_mock: confidence = min(confidence, 50)
    status = 'REVIEW' if not issues else 'REJECT'
    row = dict(source=product.retailer, product=product.name, source_url=product.url,
        upc=product.gtin, manufacturer=product.manufacturer, model=product.model,
        package_quantity=product.package_quantity, variation=product.variation,
        availability=product.availability, amazon_asin=listing.asin if listing else '', destination='Amazon',
        buy_cost=product.purchase_price, sale_price=listing.sale_price if listing else None,
        profit=round(economics.net_profit, 2) if economics else None,
        roi=round(economics.roi, 1) if economics else None,
        acquisition_cost=economics.acquisition_cost if economics else None,
        break_even_price=economics.break_even_price if economics else None,
        maximum_purchase_price=economics.maximum_purchase_price if economics else None,
        status=status, reason='; '.join(dict.fromkeys(issues)) if issues else 'Manual live validation required; not purchase approval',
        confidence=confidence, matching_confidence=float(match.confidence * 100),
        source_timestamp=product.retrieved_at.isoformat() if product.retrieved_at else '',
        marketplace_timestamp=listing.retrieved_at.isoformat() if listing and listing.retrieved_at else '',
        source_provenance=product.provenance, marketplace_provenance=listing.provenance if listing else '',
        data_mode='MOCK — illustrative only' if is_mock else 'SUPPLIED — requires verification',
        purchase_ready=False, cost_basis='estimated' if unverified or is_mock else 'verified by supplied provider',
        unverified_costs=', '.join(unverified), quality_issues='; '.join(dict.fromkeys(issues)),
        monthly_sales=listing.monthly_sales if listing else None, offer_count=listing.offer_count if listing else None,
        ranking_score=0, budget_units=0, rejection_reasons=list(dict.fromkeys(issues)))
    row.update(costs)
    if economics: row['referral_fee'] = economics.referral_fee
    if status == 'REVIEW':
        row['budget_units'] = int(Decimal(str(config.inventory_budget)) // economics.acquisition_cost)
        # ROI saturates at 200%; demand and competition use explicit bounded factors.
        row['ranking_score'] = round(float(min(economics.roi, Decimal('200'))) * .25 +
            confidence * .3 + min(listing.monthly_sales, 300) / 300 * 10 +
            10 / (1 + listing.offer_count) +
            float(max(Decimal('0'), 1 - economics.acquisition_cost / Decimal(str(config.inventory_budget)))) * 10, 2)
    return row


def discover(connector: RetailerConnector, provider: AmazonProvider, config, now=None):
    now = now or datetime.now(timezone.utc)
    rows = []
    for product in connector.products():
        if len(rows) >= config.maximum_candidates:
            raise ValueError('Maximum candidate limit exceeded; partition the input')
        rows.append(screen(product, provider.match(product), config, now))
    # Stable secondary keys make fixture reruns deterministic.
    return sorted(rows, key=lambda row: (-row['ranking_score'], row['amazon_asin'], row['product']))
