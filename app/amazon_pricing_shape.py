"""Fixed pricing validation labels and bounded shape facts, never response values."""
from decimal import Decimal

from app.amazon_catalog import ASIN, MARKETPLACE
from app.provider_runtime import ProviderFailure

LABELS = frozenset({
    'pricing_validated', 'pricing_validation_failed', 'token_validation_failed',
    'pricing_errors_present', 'pricing_payload_not_object', 'pricing_status_not_success',
    'pricing_marketplace_mismatch', 'pricing_asin_missing', 'pricing_asin_mismatch',
    'pricing_condition_mismatch', 'pricing_identifier_not_object',
    'pricing_identifier_marketplace_mismatch', 'pricing_identifier_condition_mismatch',
    'pricing_summary_not_object', 'pricing_offers_not_array', 'pricing_offer_row_not_object', 'pricing_count_missing_or_invalid',
    'pricing_price_rows_not_array', 'pricing_price_row_not_object',
    'pricing_row_condition_invalid', 'pricing_currency_not_usd', 'pricing_amount_invalid',
    'pricing_money_not_object', 'pricing_no_offers_inconsistent',
})


class PricingValidationError(ProviderFailure):
    def __init__(self, label: str):
        self.label = label if label in LABELS else 'pricing_validation_failed'
        super().__init__(self.label)


def require(check: bool, label: str) -> None:
    if not check:
        raise PricingValidationError(label)


def pricing_usd(value: object) -> Decimal | None:
    if value is None:
        return None
    require(isinstance(value, dict), 'pricing_money_not_object')
    require(value.get('CurrencyCode') == 'USD', 'pricing_currency_not_usd')
    amount = value.get('Amount')
    if amount is None:
        return None
    require(type(amount) in (int, float, Decimal), 'pricing_amount_invalid')
    try:
        result = Decimal(str(amount))
    except Exception:
        raise PricingValidationError('pricing_amount_invalid') from None
    require(result.is_finite() and result >= 0, 'pricing_amount_invalid')
    return result


def field_type(value: object) -> str:
    if value is None: return 'null'
    if isinstance(value, dict): return 'object'
    if isinstance(value, list): return 'array'
    if isinstance(value, bool): return 'boolean'
    if isinstance(value, str): return 'string'
    if type(value) in (int, float, Decimal): return 'number'
    return 'other'


def fields(value: object, names: tuple[str, ...]) -> dict:
    if not isinstance(value, dict):
        return {}
    return {name: field_type(value[name]) if name in value else 'absent' for name in names}


def matches(value: object, key: str, expected: str) -> bool | None:
    return value[key] == expected if isinstance(value, dict) and key in value else None


def pricing_shape(document: dict) -> dict:
    """Known field names, types, lengths and comparison booleans only.

    No key enumeration or arbitrary status/currency/error/identifier/price text.
    At most three summary rows per group are sampled; prices are never emitted.
    """
    payload = document.get('payload')
    payload = payload if isinstance(payload, dict) else {}
    identifier = payload.get('Identifier')
    summary = payload.get('Summary')
    status = payload.get('status')
    safe_statuses = ('Success', 'ClientError', 'ServiceError', 'ActiveButTooSoonForProcessing')
    shape = {
        'root': fields(document, ('payload', 'errors', 'status', 'Payload')),
        'payload': fields(payload, ('status', 'ASIN', 'marketplaceId', 'ItemCondition', 'Identifier', 'Offers', 'Summary')),
        'identifier': fields(identifier, ('ASIN', 'MarketplaceId', 'ItemCondition')),
        'summary': fields(summary, ('TotalOfferCount', 'LowestPrices', 'BuyBoxPrices')),
        'status_label': status if isinstance(status, str) and status in safe_statuses else 'OTHER' if isinstance(status, str) else 'MISSING_OR_NONSTRING',
        'status_exact_success': status == 'Success',
        'status_casefold_success': status.casefold() == 'success' if isinstance(status, str) else False,
        'errors_present': bool(document.get('errors')),
        'context': {
            'payload_asin_matches': matches(payload, 'ASIN', ASIN),
            'identifier_asin_matches': matches(identifier, 'ASIN', ASIN),
            'payload_marketplace_matches': matches(payload, 'marketplaceId', MARKETPLACE),
            'identifier_marketplace_matches': matches(identifier, 'MarketplaceId', MARKETPLACE),
            'payload_condition_matches': matches(payload, 'ItemCondition', 'New'),
            'identifier_condition_matches': matches(identifier, 'ItemCondition', 'New'),
        },
        'summary_count_state': ('absent' if not isinstance(summary, dict) or 'TotalOfferCount' not in summary else
            'zero' if type(summary['TotalOfferCount']) is int and summary['TotalOfferCount'] == 0 else
            'positive' if type(summary['TotalOfferCount']) is int and summary['TotalOfferCount'] > 0 else 'invalid'),
        'offers_count': len(payload['Offers']) if isinstance(payload.get('Offers'), list) else None,
        'price_groups': {},
    }
    for key in ('LowestPrices', 'BuyBoxPrices'):
        rows = summary.get(key) if isinstance(summary, dict) else None
        sample = []
        for row in rows[:3] if isinstance(rows, list) else []:
            fact = {'type': field_type(row), 'fields': fields(row, ('condition', 'fulfillmentChannel', 'ListingPrice', 'Shipping', 'LandedPrice'))}
            if isinstance(row, dict):
                fact['condition_is_new'] = isinstance(row.get('condition'), str) and row['condition'].lower() == 'new'
                fact['money'] = {}
                for name in ('ListingPrice', 'Shipping', 'LandedPrice'):
                    value = row.get(name)
                    state = {'fields': fields(value, ('CurrencyCode', 'Amount')),
                             'currency_is_usd': matches(value, 'CurrencyCode', 'USD')}
                    try:
                        amount = pricing_usd(value)
                        state['validation'] = 'missing' if amount is None else 'valid_nonnegative_usd'
                    except PricingValidationError as error:
                        state['validation'] = error.label
                    fact['money'][name] = state
            sample.append(fact)
        shape['price_groups'][key] = {'count': len(rows) if isinstance(rows, list) else None, 'sample': sample}
    return shape
