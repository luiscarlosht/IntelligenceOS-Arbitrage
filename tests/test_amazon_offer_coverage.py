"""Synthetic 5/1 reproduction and conservative aggregate/detail separation."""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path

import pytest

from app import amazon_details as details
from app import amazon_pricing_diagnostic as diagnostic
from app.amazon_diagnostics import ResponseDocument
from app.amazon_pricing_shape import PricingValidationError
from app.models import Match, MarketplaceListing

ASIN = 'B0G1MJ24B4'
FIXTURE = Path(__file__).parent / 'fixtures' / 'amazon_pricing_five_total_one_detail.json'


def response():
    return json.loads(FIXTURE.read_text())


def parse(data=None):
    return details.parse_pricing(response() if data is None else data, expected_asin=ASIN, is_mock=True)


def groups():
    return [{'condition': 'New', 'fulfillmentChannel': 'Merchant', 'OfferCount': 2},
            {'condition': 'Used', 'fulfillmentChannel': 'Amazon', 'OfferCount': 3}]


def test_five_total_one_detail_is_preserved_as_partial_unknown_price():
    snapshot = parse().value
    assert snapshot.total_offer_count == 5
    coverage = snapshot.offer_coverage
    assert coverage.returned_offer_count == 1
    assert coverage.documented_expected_offer_count == 5
    assert not coverage.documented_count_matches
    assert coverage.incomplete_coverage and coverage.coverage == 'partial'
    assert coverage.number_of_offers is None and coverage.buy_box_eligible_offers is None
    assert snapshot.prices == () and snapshot.price_unknown
    assert snapshot.exclude_from_profitability_ranking
    assert snapshot.customer_type == 'Consumer' and not snapshot.overall_lowest_price_verified
    # A fictional detail price must not be promoted to the summary or sale quote.
    assert 'ListingPrice' not in json.dumps(asdict(snapshot), default=details.serialize)


def test_condition_channel_breakdowns_are_preserved_without_explaining_live_discrepancy():
    data = response()
    data['payload']['Summary']['NumberOfOffers'] = groups()
    data['payload']['Summary']['BuyBoxEligibleOffers'] = [
        {'condition': 'Used', 'fulfillmentChannel': 'Amazon', 'OfferCount': 1}]
    coverage = parse(data).value.offer_coverage
    assert [(g.condition, g.fulfillment_channel, g.offer_count) for g in coverage.number_of_offers] == [
        ('new', 'Merchant', 2), ('used', 'Amazon', 3)]
    assert coverage.returned_offer_count == 1 and coverage.incomplete_coverage
    assert coverage.buy_box_eligible_offers[0].offer_count == 1
    # NumberOfOffers has no customer-type field; we do not invent one.
    assert 'customer_type' not in asdict(coverage.number_of_offers[0])


@pytest.mark.parametrize('total,returned,coverage,matched,incomplete', [
    (0, 0, 'count_matched', True, False), (1, 1, 'count_matched', True, False),
    (5, 5, 'count_matched', True, False), (20, 20, 'count_matched', True, False),
    (21, 20, 'capped', True, True), (27, 1, 'partial', False, True)])
def test_coverage_states_are_explicit(total, returned, coverage, matched, incomplete):
    data = response()
    data['payload']['Summary']['TotalOfferCount'] = total
    data['payload']['Offers'] = [deepcopy(data['payload']['Offers'][0]) for _ in range(returned)]
    result = parse(data).value
    assert result.offer_coverage.coverage == coverage
    assert result.offer_coverage.documented_count_matches is matched
    assert result.offer_coverage.incomplete_coverage is incomplete
    assert not result.overall_lowest_price_verified


@pytest.mark.parametrize('total,returned', [(0, 1), (5, 0), (1, 2), (5, 6), (21, 21)])
def test_excess_and_contradictory_empty_counts_fail(total, returned):
    data = response()
    data['payload']['Summary']['TotalOfferCount'] = total
    data['payload']['Offers'] *= returned
    with pytest.raises(PricingValidationError, match='pricing_offer_count_inconsistent'):
        parse(data)


@pytest.mark.parametrize('key,value,label', [
    ('NumberOfOffers', {}, 'pricing_summary_counts_invalid'),
    ('NumberOfOffers', [{'OfferCount': True}], 'pricing_summary_counts_invalid'),
    ('NumberOfOffers', [{'OfferCount': -1}], 'pricing_summary_counts_invalid'),
    ('NumberOfOffers', [{'OfferCount': 6}], 'pricing_summary_counts_invalid'),
    ('NumberOfOffers', [], 'pricing_summary_counts_inconsistent'),
    ('NumberOfOffers', [{'OfferCount': 4}], 'pricing_summary_counts_inconsistent'),
    ('NumberOfOffers', [{'OfferCount': 5, 'condition': 'invented'}], 'pricing_summary_counts_invalid'),
    ('NumberOfOffers', [{'OfferCount': 5, 'fulfillmentChannel': 'invented'}], 'pricing_summary_counts_invalid'),
    ('BuyBoxEligibleOffers', [{'OfferCount': 6}], 'pricing_summary_counts_invalid'),
    ('BuyBoxEligibleOffers', [{'OfferCount': 3}, {'OfferCount': 3}], 'pricing_summary_counts_inconsistent')])
def test_invalid_or_conflicting_aggregate_counts_fail(key, value, label):
    data = response()
    data['payload']['Summary'][key] = value
    with pytest.raises(PricingValidationError, match=label):
        parse(data)


def test_duplicate_buckets_and_eligible_bucket_overflow_fail():
    data = response()
    data['payload']['Summary']['NumberOfOffers'] = [
        {'condition': 'new', 'fulfillmentChannel': 'Amazon', 'OfferCount': 2},
        {'condition': 'New', 'fulfillmentChannel': 'Amazon', 'OfferCount': 3}]
    with pytest.raises(PricingValidationError, match='pricing_summary_counts_inconsistent'):
        parse(data)
    data['payload']['Summary']['NumberOfOffers'] = groups()
    data['payload']['Summary']['BuyBoxEligibleOffers'] = [
        {'condition': 'New', 'fulfillmentChannel': 'Merchant', 'OfferCount': 3}]
    with pytest.raises(PricingValidationError, match='pricing_summary_counts_inconsistent'):
        parse(data)


def test_schema_optional_bucket_labels_are_not_inferred():
    data = response()
    data['payload']['Summary']['NumberOfOffers'] = [{'OfferCount': 5}]
    group = parse(data).value.offer_coverage.number_of_offers[0]
    assert group.condition is None and group.fulfillment_channel is None


@pytest.mark.parametrize('breakdown', [
    [{'condition': 'Used', 'fulfillmentChannel': 'Merchant', 'OfferCount': 5}],
    [{'condition': 'New', 'fulfillmentChannel': 'Amazon', 'OfferCount': 5}]])
def test_known_breakdown_cannot_contradict_returned_condition_channel(breakdown):
    data = response()
    data['payload']['Summary']['NumberOfOffers'] = breakdown
    with pytest.raises(PricingValidationError, match='pricing_summary_counts_inconsistent'):
        parse(data)


def test_documented_lowercase_detail_condition_is_still_new():
    data = response()
    data['payload']['Offers'][0]['SubCondition'] = 'new'
    assert parse(data).value.offer_coverage.coverage == 'partial'


def test_count_matched_details_still_validate_supplied_money():
    data = response()
    data['payload']['Summary']['TotalOfferCount'] = 1
    data['payload']['Offers'][0]['Shipping']['CurrencyCode'] = 'EUR'
    with pytest.raises(PricingValidationError, match='pricing_currency_not_usd'):
        parse(data)


@pytest.mark.parametrize('field', ['ListingPrice', 'Shipping'])
@pytest.mark.parametrize('invalid', [None, {}, {'CurrencyCode': 'EUR', 'Amount': 10},
    {'CurrencyCode': 'USD', 'Amount': -1}, {'CurrencyCode': 'USD', 'Amount': True},
    {'CurrencyCode': 'USD', 'Amount': '10'}, {'CurrencyCode': 'USD', 'Amount': float('nan')}])
def test_partial_details_do_not_bypass_money_validation(field, invalid):
    data = response()
    data['payload']['Offers'][0][field] = invalid
    with pytest.raises(PricingValidationError):
        parse(data)


@pytest.mark.parametrize('field', ['ListingPrice', 'Shipping', 'ShippingTime', 'SubCondition', 'IsFulfilledByAmazon'])
def test_partial_details_require_real_shape(field):
    data = response()
    del data['payload']['Offers'][0][field]
    with pytest.raises(PricingValidationError):
        parse(data)


@pytest.mark.parametrize('field,value,label', [
    ('SubCondition', 'Used', 'pricing_offer_condition_mismatch'),
    ('offerType', 'B2B', 'pricing_offer_customer_type_mismatch'),
    ('ASIN', 'B000000001', 'pricing_asin_mismatch'),
    ('marketplaceId', 'OTHER', 'pricing_marketplace_mismatch'),
    ('ItemCondition', 'Used', 'pricing_condition_mismatch')])
def test_partial_context_checks_remain_strict(field, value, label):
    data = response()
    if field in ('SubCondition', 'offerType'):
        data['payload']['Offers'][0][field] = value
    else:
        data['payload'][field] = value
    with pytest.raises(PricingValidationError, match=label):
        parse(data)


def test_no_buyable_offers_does_not_gain_partial_exception():
    data = response()
    data['payload']['status'] = 'NoBuyableOffers'
    with pytest.raises(PricingValidationError, match='pricing_no_offers_inconsistent'):
        parse(data)


def test_summary_prices_remain_observations_and_partial_coverage_blocks_ranking():
    data = response()
    data['payload']['Summary']['LowestPrices'] = [{'condition': 'new', 'fulfillmentChannel': 'Merchant',
        'ListingPrice': {'CurrencyCode': 'USD', 'Amount': 15}}]
    evidence = parse(data)
    assert evidence.value.prices[0].listing_price == Decimal('15')
    assert not evidence.value.price_unknown and evidence.value.exclude_from_profitability_ranking
    listing = MarketplaceListing(ASIN, None, '', '', 1, '', True, Decimal('25'), {})
    match = Match(listing, True, 1, ())
    gated = details.apply_pricing_gate(match, evidence)
    assert gated.listing.sale_price is None
    assert any('Incomplete offer coverage' in reason for reason in gated.reasons)
    data['payload']['Summary']['LowestPrices'][0]['ListingPrice']['CurrencyCode'] = 'EUR'
    with pytest.raises(PricingValidationError, match='pricing_currency_not_usd'):
        parse(data)


@pytest.mark.parametrize('key', ['LowestPrices', 'BuyBoxPrices'])
def test_business_summary_price_is_not_a_consumer_quote(key):
    data = response()
    data['payload']['Summary'][key] = [{'condition': 'new', 'offerType': 'B2B',
        'ListingPrice': {'CurrencyCode': 'USD', 'Amount': 15}}]
    with pytest.raises(PricingValidationError, match='pricing_offer_customer_type_mismatch'):
        parse(data)


def test_partial_diagnostic_exposes_coverage_label_without_offer_details():
    calls = []
    def transport(request):
        calls.append(request)
        return ResponseDocument({'access_token': 'synthetic', 'token_type': 'bearer'}
                                if len(calls) == 1 else response(), 200)
    report = diagnostic.pricing_once(dict(client_id='synthetic', client_secret='synthetic', refresh_token='synthetic'),
        transport=transport, is_mock=True, asin=ASIN, shape_only=True, count_only=True)
    assert len(calls) == 2 and report['status'] == 'success'
    assert report['validation_label'] == 'pricing_partial_coverage_validated'
    assert report['offer_coverage']['returned_offer_count'] == 1
    assert report['offer_coverage']['incomplete_coverage']
    assert report['exclude_from_profitability_ranking'] and report['pricing'] is None
    assert not report['overall_lowest_price_verified']
    assert 'ListingPrice' not in json.dumps(report, default=details.serialize)
