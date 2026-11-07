"""Retail-only evidence gates over the established Decimal profitability formula."""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.profitability import COST_FIELDS, analyze
from app.amazon_catalog import MARKETPLACE
from app.m96 import ASIN


def evaluate(record: dict, now: datetime) -> dict:
    """Inputs are attributed evidence; passing is manual review only, never purchase approval."""
    if now.utcoffset() is None:
        raise ValueError('Aware evaluation time required')
    missing = []
    asin = record.get('asin', '')
    if not isinstance(asin, str) or not ASIN.fullmatch(asin):
        missing.append('asin')
    if record.get('marketplace') != MARKETPLACE or record.get('condition') != 'new_new':
        missing.append('marketplace_condition')
    if record.get('channel') != 'AUTHORIZED_RETAIL':
        missing.append('authorized_retail_channel')
    evidence = record.get('evidence', {})

    def value(key):
        entry = evidence.get(key, {})
        try:
            stamp = datetime.fromisoformat(entry.get('observed_at', ''))
            valid = (stamp.utcoffset() is not None and timedelta(0) <= now-stamp <= timedelta(hours=24)
                     and entry.get('source') and entry.get('status') == 'VERIFIED'
                     and entry.get('asin') == asin and entry.get('marketplace') == MARKETPLACE
                     and entry.get('condition') == 'new_new' and entry.get('is_mock') is False)
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            missing.append(key)
            return None
        return entry.get('value')

    for key, expected in [('exact_product_variant_pack_match', True),
                          ('listing_permission', 'SELL_THIS_PRODUCT'),
                          ('fba_inbound', 'ELIGIBLE_PREVIEW')]:
        actual = value(key)
        if actual != expected or (expected is True and actual is not True):
            missing.append(key)
    seller_scopes = {evidence.get(key, {}).get('seller_scope_reference')
                     for key in ('listing_permission', 'fba_inbound')}
    if len(seller_scopes) != 1 or not next(iter(seller_scopes), None):
        missing.append('consistent_seller_scope_reference')
    numbers = {}
    for key in ('retail_acquisition_cost', 'amazon_selling_price', *COST_FIELDS):
        raw = value(key)
        try:
            number = Decimal(str(raw))
            if not number.is_finite() or number < 0 or (key in ('retail_acquisition_cost', 'amazon_selling_price') and number <= 0):
                raise ValueError('Invalid value')
            numbers[key] = number
        except (InvalidOperation, ValueError):
            missing.append(key)
    result = dict(status='BLOCKED_MISSING_EVIDENCE', missing=sorted(set(missing)),
                  net_profit=None, roi_percent=None, purchase_authorized=False,
                  listing_authorized=False, minimum_profit='5', minimum_roi_percent='50')
    if missing:
        return result
    economics = analyze(numbers['retail_acquisition_cost'], numbers['amazon_selling_price'],
                        {key: numbers[key] for key in COST_FIELDS})
    result.update(net_profit=str(economics.net_profit), roi_percent=str(economics.roi),
        status='MANUAL_REVIEW_ONLY' if economics.net_profit >= 5 and economics.roi >= 50 else 'BELOW_THRESHOLDS')
    return result
