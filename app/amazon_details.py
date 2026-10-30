"""Manual single-ASIN read-only details pilot, never part of scheduled jobs."""
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import getpass
import json
import os
from pathlib import Path
import re
import signal
import warnings
from uuid import uuid4

from app.amazon_pricing_shape import require, pricing_usd, validate_asin
from app.amazon_offer_coverage import OfferCoverage, offer_coverage
from app.models import Match
from app.amazon_diagnostics import AmazonFailure, error_codes, failure_metadata, response_metadata
from app.amazon_catalog import ASIN, MARKETPLACE, parse_catalog
from app.amazon_pilot import (DIRECTORY, amazon_request, catalog_request, create_file,
    deadline, exchange_token, load_credentials, operation, private_directory, request_json)
from app.normalization import money, timestamp
from app.provider_contracts import Evidence, FeeQuote, SellerContext
from app.provider_runtime import ProviderFailure

MAX_REQUESTS = 5
REPORT_NAME = 'catalog-details-pilot.json'


@dataclass(frozen=True)
class ObservedPrice:
    basis: str
    fulfillment_channel: str
    listing_price: Decimal | None
    shipping: Decimal | None
    landed_price: Decimal | None


@dataclass(frozen=True)
class PricingSnapshot:
    asin: str
    marketplace_id: str
    condition: str
    prices: tuple[ObservedPrice, ...]
    total_offer_count: int | None
    lookup_status: str = 'Success'
    price_unknown: bool = True
    exclude_from_profitability_ranking: bool = True
    offer_coverage: OfferCoverage | None = None
    customer_type: str = 'Consumer'
    overall_lowest_price_verified: bool = False


def usd(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('CurrencyCode') != 'USD':
        raise ProviderFailure('Invalid USD response')
    amount = value.get('Amount')
    if isinstance(amount, bool):
        raise ProviderFailure('Invalid monetary amount')
    try:
        return money(amount)
    except (ValueError, InvalidOperation):
        raise ProviderFailure('Invalid monetary amount') from None


def proposed_price(value: str) -> Decimal:
    if not re.fullmatch(r'[0-9]{1,6}(?:\.[0-9]{1,2})?', value):
        raise ValueError('Positive USD price with at most two decimal places required')
    result = Decimal(value)
    if result <= 0:
        raise ValueError('Positive proposed price required')
    return result


def parse_pricing(data: dict, *, is_mock: bool, expected_asin: str = ASIN) -> Evidence[PricingSnapshot]:
    validate_asin(expected_asin)
    require(not data.get('errors'), 'pricing_errors_present')
    payload = data.get('payload')
    require(isinstance(payload, dict), 'pricing_payload_not_object')
    lookup_status = payload.get('status')
    require(lookup_status in ('Success', 'NoBuyableOffers'), 'pricing_status_not_success')
    require(payload.get('marketplaceId') == MARKETPLACE, 'pricing_marketplace_mismatch')
    require(payload.get('ItemCondition') == 'New', 'pricing_condition_mismatch')
    identifier = payload.get('Identifier')
    require(isinstance(identifier, dict), 'pricing_identifier_not_object')
    require(identifier.get('MarketplaceId') == MARKETPLACE, 'pricing_identifier_marketplace_mismatch')
    require(identifier.get('ItemCondition') == 'New', 'pricing_identifier_condition_mismatch')
    # Both ASIN properties are optional in Amazon's schema. Require at least
    # one response identity and validate every identity that is supplied.
    asins = [row['ASIN'] for row in (payload, identifier) if 'ASIN' in row]
    require(bool(asins), 'pricing_asin_missing')
    require(all(asin == expected_asin for asin in asins), 'pricing_asin_mismatch')
    require(isinstance(payload.get('Offers'), list), 'pricing_offers_not_array')
    require(all(isinstance(row, dict) for row in payload['Offers']), 'pricing_offer_row_not_object')
    summary = payload.get('Summary')
    require(isinstance(summary, dict), 'pricing_summary_not_object')
    count = summary.get('TotalOfferCount')
    require(type(count) is int and count >= 0, 'pricing_count_missing_or_invalid')
    if lookup_status == 'NoBuyableOffers':
        require(count == 0 and not payload['Offers'], 'pricing_no_offers_inconsistent')
        for key in ('LowestPrices', 'BuyBoxPrices'):
            require(isinstance(summary.get(key, []), list) and not summary.get(key, []), 'pricing_no_offers_inconsistent')
        for key in ('NumberOfOffers', 'BuyBoxEligibleOffers'):
            counts = summary.get(key, [])
            require(isinstance(counts, list), 'pricing_no_offer_counts_invalid')
            require(all(isinstance(row, dict) and type(row.get('OfferCount')) is int
                        and row['OfferCount'] == 0 for row in counts), 'pricing_no_offer_counts_invalid')
    coverage = offer_coverage(summary, payload['Offers'], count)
    prices = []
    for key, basis in (('LowestPrices', 'lowest_observed'), ('BuyBoxPrices', 'buy_box_observed')):
        rows = summary.get(key, [])
        require(isinstance(rows, list), 'pricing_price_rows_not_array')
        for row in rows:
            require(isinstance(row, dict), 'pricing_price_row_not_object')
            condition = row.get('condition')
            require(isinstance(condition, str) and bool(condition), 'pricing_row_condition_invalid')
            if condition.lower() != 'new':
                continue
            if 'offerType' in row:
                require(row['offerType'] == 'B2C', 'pricing_offer_customer_type_mismatch')
            channel = row.get('fulfillmentChannel')
            prices.append(ObservedPrice(basis, channel if channel in ('Amazon', 'Merchant') else 'unknown',
                pricing_usd(row.get('ListingPrice')), pricing_usd(row.get('Shipping')), pricing_usd(row.get('LandedPrice'))))
    require(count != 0 or (not payload['Offers'] and not prices), 'pricing_no_offers_inconsistent')
    now = datetime.now(timezone.utc)
    price_unknown = not any(row.listing_price is not None or row.landed_price is not None for row in prices)
    return Evidence(PricingSnapshot(expected_asin, MARKETPLACE, 'New', tuple(prices), count,
                    lookup_status, price_unknown, price_unknown or coverage.incomplete_coverage,
                    coverage), now,
                    'Amazon SP-API Product Pricing v0 getItemOffers; New/Consumer response observations; '
                    'aggregate counts separate from returned details; no overall lowest-price or all-seller guarantee', is_mock)


def apply_pricing_gate(match: Match, pricing: Evidence[PricingSnapshot]) -> Match:
    """Apply negative/unknown price evidence before existing discovery ranking.

    Observed competing offers never overwrite a seller's separate sale quote.
    A no-offer lookup clears any older sale price and supplies a rejection reason.
    """
    snapshot = pricing.value
    if snapshot is not None and match.listing is not None:
        require(snapshot.asin == match.listing.asin, 'pricing_asin_mismatch')
    if snapshot is None or snapshot.lookup_status == 'NoBuyableOffers' or snapshot.price_unknown or snapshot.exclude_from_profitability_ranking:
        reason = ('No buyable offers; current sale price unknown' if snapshot is not None
                  and snapshot.lookup_status == 'NoBuyableOffers' else
                  'Incomplete offer coverage; pricing excluded from ranking' if snapshot is not None
                  and snapshot.offer_coverage is not None and snapshot.offer_coverage.incomplete_coverage
                  else 'Current pricing unavailable')
        listing = replace(match.listing, sale_price=None) if match.listing else None
        return replace(match, listing=listing, reasons=tuple(dict.fromkeys((*match.reasons, reason))))
    return match


def parse_fees(data: dict, context: SellerContext, price: Decimal, identifier: str, *, is_mock: bool,
               expected_asin: str = ASIN, buyer_shipping: Decimal = Decimal('0'),
               fulfillment: str = 'FBA') -> dict:
    validate_asin(expected_asin)
    if (fulfillment not in ('FBA', 'FBM') or money(buyer_shipping) is None):
        raise ValueError('Explicit fulfillment and buyer shipping scenario required')
    if context.marketplace_id != MARKETPLACE or context.condition != 'new_new':
        raise ProviderFailure('Fee seller context mismatch')
    payload = data.get('payload')
    result = payload.get('FeesEstimateResult') if isinstance(payload, dict) else None
    if data.get('errors') or not isinstance(result, dict) or result.get('Status') != 'Success':
        raise ProviderFailure('Fee estimate failed')
    identity = result.get('FeesEstimateIdentifier', {})
    if not isinstance(identity, dict):
        raise ProviderFailure('Fee context missing')
    expected = dict(MarketplaceId=MARKETPLACE, SellerId=context.seller_id, IdType='ASIN', IdValue=expected_asin,
                    IsAmazonFulfilled=fulfillment == 'FBA', SellerInputIdentifier=identifier)
    if any(identity.get(k) != v for k, v in expected.items()) or identity.get('IsAmazonFulfilled') is not (fulfillment == 'FBA'):
        raise ProviderFailure('Fee context mismatch')
    proposed = identity.get('PriceToEstimateFees')
    if not isinstance(proposed, dict) or usd(proposed.get('ListingPrice')) != price or usd(proposed.get('Shipping')) != buyer_shipping:
        raise ProviderFailure('Fee price mismatch')
    estimate = result.get('FeesEstimate')
    if not isinstance(estimate, dict):
        raise ProviderFailure('Fee estimate missing')
    details = estimate.get('FeeDetailList', [])
    if not isinstance(details, list) or any(not isinstance(d, dict) for d in details):
        raise ProviderFailure('Fee details invalid')
    def component(kind):
        matches = [d for d in details if d.get('FeeType') == kind]
        # Use only an explicit top-level aggregate FinalFee. Never add the
        # aggregate and its IncludedFeeDetailList, or turn omissions into zero.
        return usd(matches[0].get('FinalFee')) if len(matches) == 1 else None
    now = datetime.now(timezone.utc)
    quote = FeeQuote(expected_asin, context, price, fulfillment, component('ReferralFee'),
                     component('FBAFees') if fulfillment == 'FBA' else None)
    at = estimate.get('TimeOfFeesEstimation')
    try:
        estimated_at = timestamp(at) if isinstance(at, str) else None
    except ValueError:
        estimated_at = None
    evidence = Evidence(quote, now, f'Amazon SP-API Product Fees v0; proposed USD price; {fulfillment}; buyer shipping {buyer_shipping}; estimates only', is_mock)
    total = usd(estimate.get('TotalFeesEstimate'))
    return {'quote': asdict(evidence), 'total_fees_estimate': total, 'buyer_shipping_scenario': buyer_shipping,
            'estimated_at': estimated_at,
            'missing_fields': [key for key, value in {'referral_fee': quote.referral_fee,
                'fulfillment_fee': quote.fulfillment_fee, 'total_fees_estimate': total, 'estimated_at': estimated_at}.items() if value is None]}


def parse_restrictions(data: dict, context: SellerContext, *, is_mock: bool) -> dict:
    rows = data.get('restrictions')
    if data.get('errors') or not isinstance(rows, list):
        raise ProviderFailure('Restriction response invalid')
    codes = set()
    details = []
    for row in rows:
        if (not isinstance(row, dict) or row.get('marketplaceId') != context.marketplace_id
                or row.get('conditionType') not in (None, context.condition)):
            raise ProviderFailure('Restriction context mismatch')
        reasons = row.get('reasons', [])
        if not isinstance(reasons, list):
            raise ProviderFailure('Restriction reasons invalid')
        for reason in reasons:
            if not isinstance(reason, dict):
                raise ProviderFailure('Restriction reason invalid')
            code = reason.get('reasonCode')
            codes.add(code if isinstance(code, str) else 'OTHER')
            details.append({key: reason[key] for key in ('reasonCode', 'message', 'links') if key in reason})
    now = datetime.now(timezone.utc)
    # This narrow boolean implements the eligibility evidence interface, while
    # catalog.seller_eligible remains unknown: listing permission is not a buy gate.
    evidence = Evidence(not rows, now, 'Amazon SP-API Listings Restrictions; US; new_new; operator-supplied seller; no restrictions is not purchase approval', is_mock)
    return {'listing_permission': asdict(evidence), 'restriction_count': len(rows),
            'reason_codes': sorted(codes), 'reasons': details,
            'approval_instructions': [r for r in details if r.get('message') or r.get('links')] or None, 'approval_required': True if 'APPROVAL_REQUIRED' in codes else (False if not rows else None),
            'purchase_approved': False,
            'fulfillment_eligibility': None}


def details_once(credentials: dict, context: SellerContext, price: Decimal, *, transport=request_json,
                 is_mock: bool = False, report: dict | None = None) -> dict:
    if context.marketplace_id != MARKETPLACE or context.condition != 'new_new' or not re.fullmatch(r'[A-Z0-9]{1,32}', context.seller_id):
        raise ValueError('Explicit authorized US seller and new_new condition required')
    proposed_price(str(price))
    report = report if report is not None else {}
    report.update(status='running', asin=ASIN, marketplace_id=MARKETPLACE, condition='new_new',
                  fulfillment='FBA', proposed_fee_price=price, buyer_shipping_scenario=Decimal('0'),
                  requests_attempted=0, purchase_approved=False, seller_eligible=None,
                  pricing=None, fees=None, restrictions=None, catalog=None, is_mock=is_mock,
                  response_diagnostics={})
    def call(request):
        if report['requests_attempted'] >= MAX_REQUESTS:
            raise ProviderFailure('Request cap reached')
        report['requests_attempted'] += 1
        return transport(request)
    def stage_call(name, request, parser):
        document = call(request)
        report['response_diagnostics'][name] = response_metadata(document)
        try:
            return parser(document)
        except ProviderFailure as error:
            raise AmazonFailure('Amazon response validation failed', reason='response_validation_failed',
                http_status=getattr(document, 'http_status', None), codes=error_codes(document),
                validation_label=getattr(error, 'label', None)) from None
    with operation('lwa_exchange'):
        access = exchange_token(credentials, call)
    with operation('catalog_details'):
        report['catalog'] = asdict(stage_call('catalog_details', catalog_request(access),
            lambda data: parse_catalog(data, is_mock=is_mock, secrets=(*credentials.values(), access))))
    with operation('current_pricing'):
        report['pricing'] = asdict(stage_call('current_pricing', amazon_request(access,
            '/products/pricing/v0/items/' + ASIN + '/offers',
            {'MarketplaceId': MARKETPLACE, 'ItemCondition': 'New', 'CustomerType': 'Consumer'}),
            lambda data: parse_pricing(data, is_mock=is_mock)))
    identifier = uuid4().hex
    body = {'FeesEstimateRequest': {'MarketplaceId': MARKETPLACE, 'IsAmazonFulfilled': True,
        'Identifier': identifier, 'PriceToEstimateFees': {'ListingPrice': {'CurrencyCode': 'USD', 'Amount': float(price)},
        'Shipping': {'CurrencyCode': 'USD', 'Amount': 0}}}}
    with operation('estimated_fees'):
        report['fees'] = stage_call('estimated_fees', amazon_request(access,
            '/products/fees/v0/items/' + ASIN + '/feesEstimate', body=body),
            lambda data: parse_fees(data, context, price, identifier, is_mock=is_mock))
    with operation('listing_restrictions'):
        report['restrictions'] = stage_call('listing_restrictions', amazon_request(access, '/listings/2021-08-01/restrictions',
            {'asin': ASIN, 'sellerId': context.seller_id, 'marketplaceIds': MARKETPLACE,
             'conditionType': 'new_new', 'reasonLocale': 'en_US'}),
            lambda data: parse_restrictions(data, context, is_mock=is_mock))
    report['status'] = 'success'
    return report


def prompt_seller_id() -> str:
    with operation('seller_hidden_prompt'):
        with open('/dev/tty', 'w') as terminal:
            if not terminal.isatty():
                raise ValueError('Hidden terminal input required')
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                seller = getpass.getpass('Authorized Amazon seller ID: ', stream=terminal)
        if not re.fullmatch(r'[A-Z0-9]{1,32}', seller):
            raise ValueError('Invalid seller ID')
        return seller


def serialize(value):
    if isinstance(value, Decimal):
        return str(value)
    return value.isoformat()


def run_details(price: Decimal, path: Path = DIRECTORY) -> None:
    proposed_price(str(price))
    directory = private_directory(path)
    try:
        with operation('details_report_create'):
            output_fd = create_file(directory, REPORT_NAME)
        with os.fdopen(output_fd, 'w') as output:
            report = {'status': 'failed', 'reason': 'not_started_no_retry', 'requests_attempted': 0}
            # Keep interactive input outside the network deadline. The report is
            # reserved first, so re-running can never silently make more calls.
            previous = None
            try:
                context = SellerContext(prompt_seller_id(), MARKETPLACE, 'new_new')
                previous = signal.signal(signal.SIGALRM, deadline)
                signal.alarm(60)
                with operation('credential_load'):
                    credentials = load_credentials(directory)
                details_once(credentials, context, price, report=report)
            except (Exception, KeyboardInterrupt) as error:
                report.update(status='failed', reason='operation_failed_no_retry',
                              failed_operation=getattr(error, '_amazon_operation', 'details_pilot'),
                              failure_diagnostics=failure_metadata(error))
                raise
            finally:
                if previous is not None:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, previous)
                # Persist only normalized fields. Seller ID is not included in
                # the report; no raw responses, tokens, messages or URLs survive.
                if report.get('fees'):
                    report['fees']['quote']['value']['context']['seller_id'] = '[operator supplied seller]'
                json.dump(report, output, default=serialize, indent=2)
                output.flush()
                os.fsync(output.fileno())
    finally:
        os.close(directory)
