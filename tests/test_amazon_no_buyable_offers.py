"""Documented NoBuyableOffers semantics and selected-ASIN pilot, all mocked."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from app import amazon_pilot as pilot
from app import amazon_details as details
from app import amazon_pricing_diagnostic as diagnostic
from app.amazon_pricing_shape import pricing_shape, PricingValidationError
from app.amazon_diagnostics import ResponseDocument, response_metadata
from app.config import Config
from app.discovery import screen
from app.marketplace import match_listings
from app.models import MarketplaceListing, RetailProduct
from app.normalization import gtin
from app.profitability import COST_FIELDS

SELECTED = 'B000000123'  # Synthetic fixture, not a claim of a live offer.
CREDS = dict(client_id='synthetic-client', client_secret='synthetic-secret', refresh_token='synthetic-refresh')
TOKEN = 'synthetic-access'


def response(asin=pilot.ASIN):
    return {'payload': {'status': 'NoBuyableOffers', 'ASIN': asin, 'marketplaceId': pilot.MARKETPLACE,
        'ItemCondition': 'New', 'Identifier': {'ASIN': asin, 'MarketplaceId': pilot.MARKETPLACE, 'ItemCondition': 'New'},
        'Summary': {'TotalOfferCount': 0}, 'Offers': []}}


def test_no_offers_retains_safe_status_and_completes_without_price():
    data = response()
    assert response_metadata(data)['application_status'] == 'NoBuyableOffers'
    assert pricing_shape(data)['status_label'] == 'NoBuyableOffers'
    snapshot = details.parse_pricing(data, is_mock=True).value
    assert snapshot.lookup_status == 'NoBuyableOffers'
    assert snapshot.total_offer_count == 0 and snapshot.prices == ()
    assert snapshot.price_unknown and snapshot.exclude_from_profitability_ranking


@pytest.mark.parametrize('change', ['asin', 'identifier_asin', 'missing_asins', 'marketplace',
    'identifier_marketplace', 'condition', 'identifier_condition', 'count', 'missing_count',
    'boolean_count', 'offers', 'missing_offers', 'lowest', 'buybox', 'count_rows', 'eligible_count', 'errors'])
def test_no_offers_requires_consistent_validated_context(change):
    data = response()
    payload = data['payload']
    if change == 'asin': payload['ASIN'] = SELECTED
    elif change == 'identifier_asin': payload['Identifier']['ASIN'] = SELECTED
    elif change == 'missing_asins':
        del payload['ASIN']; del payload['Identifier']['ASIN']
    elif change == 'marketplace': payload['marketplaceId'] = 'OTHER'
    elif change == 'identifier_marketplace': payload['Identifier']['MarketplaceId'] = 'OTHER'
    elif change == 'condition': payload['ItemCondition'] = 'Used'
    elif change == 'identifier_condition': payload['Identifier']['ItemCondition'] = 'Used'
    elif change == 'count': payload['Summary']['TotalOfferCount'] = 1
    elif change == 'missing_count': del payload['Summary']['TotalOfferCount']
    elif change == 'boolean_count': payload['Summary']['TotalOfferCount'] = False
    elif change == 'offers': payload['Offers'] = [{}]
    elif change == 'missing_offers': del payload['Offers']
    elif change == 'lowest': payload['Summary']['LowestPrices'] = [{'condition': 'used'}]
    elif change == 'buybox': payload['Summary']['BuyBoxPrices'] = [{}]
    elif change == 'count_rows': payload['Summary']['NumberOfOffers'] = [{'OfferCount': 1}]
    elif change == 'eligible_count': payload['Summary']['BuyBoxEligibleOffers'] = [{'OfferCount': 1}]
    else: data['errors'] = [{'code': 'InvalidInput'}]
    with pytest.raises(PricingValidationError):
        details.parse_pricing(data, is_mock=True)


@pytest.mark.parametrize('status', ['nobuyableoffers', 'NoBuyableOffers ', 'NoOffer', 'ActiveButTooSoonForProcessing', 'invented'])
def test_unknown_statuses_still_rejected(status):
    data = response()
    data['payload']['status'] = status
    with pytest.raises(PricingValidationError, match='pricing_status_not_success'):
        details.parse_pricing(data, is_mock=True)


def test_otherwise_profitable_candidate_is_excluded_and_old_price_cleared(tmp_path):
    now = datetime.now(timezone.utc)
    product = RetailProduct('Synthetic authorized source', 'Widget', 'https://example.invalid/item',
        gtin('036000291452'), 'Acme', 'Model', 1, Decimal('8'), 'in_stock', now, 'synthetic source', variation='blue')
    costs = dict.fromkeys(COST_FIELDS, Decimal('0'))
    costs.update(referral_fee=Decimal('3'), fulfillment_fee=Decimal('4'))
    listing = MarketplaceListing(pilot.ASIN, product.gtin, 'Acme', 'Model', 1, 'blue', True,
        Decimal('25'), costs, monthly_sales=60, offer_count=4, retrieved_at=now,
        provenance='Synthetic quote', verified_costs=tuple(COST_FIELDS))
    config = Config(tmp_path/'source.csv', tmp_path/'report.xlsx', tmp_path/'history.db', mode='discovery')
    match = match_listings(product, (listing,))
    assert screen(product, match, config, now)['status'] == 'REVIEW'
    gated = details.apply_pricing_gate(match, details.parse_pricing(response(), is_mock=True))
    assert gated.listing.sale_price is None and listing.sale_price == 25
    row = screen(product, gated, config, now)
    assert row['status'] == 'REJECT' and row['ranking_score'] == 0
    assert 'No buyable offers' in row['reason'] and 'Missing sale price' in row['reason']
    assert row['profit'] is None and not row['purchase_ready']
    wrong = replace(details.parse_pricing(response(), is_mock=True),
                    value=replace(details.parse_pricing(response(), is_mock=True).value, asin=SELECTED))
    with pytest.raises(PricingValidationError, match='pricing_asin_mismatch'):
        details.apply_pricing_gate(match, wrong)


class Transport:
    def __init__(self, asin=pilot.ASIN, offers=False, fail=False):
        self.asin = asin
        self.offers = offers
        self.fail = fail
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        if self.fail:
            from app.amazon_diagnostics import AmazonFailure
            raise AmazonFailure('fixed', reason='http_error', http_status=429, codes=('QuotaExceeded',))
        if len(self.calls) == 1:
            return ResponseDocument({'access_token': TOKEN, 'token_type': 'bearer'}, 200)
        assert len(self.calls) == 2
        data = response(self.asin)
        if self.offers:
            data['payload']['status'] = 'Success'
            data['payload']['Offers'] = [{}]
            data['payload']['Summary'] = {'TotalOfferCount': 1, 'LowestPrices': [
                {'condition': 'new', 'ListingPrice': {'CurrencyCode': 'USD', 'Amount': 25}}]}
        return ResponseDocument(data, 200)


@pytest.mark.parametrize('shape_only', [False, True])
def test_no_offers_is_completed_lookup_not_failure(shape_only):
    transport = Transport()
    report = diagnostic.pricing_once(CREDS, transport=transport, is_mock=True, shape_only=shape_only)
    assert report['status'] == 'success' and report['requests_attempted'] == 2
    assert report['stages']['current_pricing'] == 'completed'
    assert report['lookup_status'] == 'NoBuyableOffers'
    assert report['validation_label'] == 'pricing_no_buyable_offers_validated'
    assert report['price_unknown'] and report['exclude_from_profitability_ranking']
    assert not report['purchase_approved'] and report['fees'] is None and report['seller_eligible'] is None
    if not shape_only:
        assert report['pricing']['value']['prices'] == ()
    else:
        assert report['pricing'] is None


@pytest.mark.parametrize('has_offers', [False, True])
def test_selected_asin_is_used_for_request_parser_and_report(has_offers):
    transport = Transport(SELECTED, offers=has_offers)
    report = diagnostic.pricing_once(CREDS, transport=transport, is_mock=True, asin=SELECTED)
    request = transport.calls[1]
    assert urlsplit(request.full_url).path == '/products/pricing/v0/items/' + SELECTED + '/offers'
    assert parse_qs(urlsplit(request.full_url).query) == {'MarketplaceId': [pilot.MARKETPLACE],
        'ItemCondition': ['New'], 'CustomerType': ['Consumer']}
    assert [r.get_method() for r in transport.calls] == ['POST', 'GET']
    assert report['asin'] == SELECTED and report['pricing']['value']['asin'] == SELECTED
    assert report['price_unknown'] is (not has_offers)
    assert report['exclude_from_profitability_ranking'] is (not has_offers)
    assert not report['purchase_approved']
    with pytest.raises(PricingValidationError, match='pricing_asin_mismatch'):
        details.parse_pricing(response(), is_mock=True, expected_asin=SELECTED)


def test_selected_private_report_and_prior_evidence_preserved(tmp_path):
    path = tmp_path / 'amazon'
    path.mkdir(mode=0o700)
    prior = ('credentials.json', 'catalog-pilot.json', 'catalog-details-pilot.json',
             diagnostic.REPORT_NAME, diagnostic.SHAPE_REPORT_NAME)
    for name in prior:
        (path/name).write_text('synthetic prior ' + name)
    before = {name: (path/name).stat() for name in prior}
    transport = Transport(SELECTED, offers=True)
    real = diagnostic.pricing_once
    def fake(credentials, report, asin):
        return real(credentials, report=report, asin=asin, transport=transport, is_mock=True)
    with patch.object(diagnostic, 'load_credentials', return_value=CREDS), \
         patch.object(diagnostic, 'pricing_once', side_effect=fake):
        diagnostic.run_pricing_diagnostic(path, selected_asin=SELECTED)
    report_path = path / ('pricing-selected-pilot-' + SELECTED + '-01.json')
    content = report_path.read_text()
    assert json.loads(content)['asin'] == SELECTED
    assert report_path.stat().st_mode & 0o777 == 0o600
    assert all(secret not in content for secret in (*CREDS.values(), TOKEN))
    for name in prior:
        assert (path/name).read_text() == 'synthetic prior ' + name
        assert (path/name).stat().st_mtime_ns == before[name].st_mtime_ns
    with patch.object(diagnostic, 'load_credentials') as load, patch.object(diagnostic, 'pricing_once') as call:
        with pytest.raises(FileExistsError):
            diagnostic.run_pricing_diagnostic(path, selected_asin=SELECTED)
    load.assert_not_called(); call.assert_not_called()


@pytest.mark.parametrize('asin', ['', '../escape', 'B00000012', 'b000000123', 'B000000123/extra'])
def test_invalid_selected_asin_fails_before_private_io(asin):
    with patch.object(diagnostic, 'private_directory') as directory:
        with pytest.raises(ValueError):
            diagnostic.run_pricing_diagnostic(selected_asin=asin)
    directory.assert_not_called()


def test_selected_cli_dispatch():
    with patch('sys.argv', ['amazon_pilot', 'pricing-selected-pilot', '--asin', SELECTED]), \
         patch.object(diagnostic, 'run_pricing_diagnostic') as run:
        assert pilot.main() == 0
    run.assert_called_once_with(selected_asin=SELECTED)


@pytest.mark.parametrize('arguments', [['pricing-selected-pilot'], ['pricing-diagnostic', '--asin', SELECTED]])
def test_asin_option_is_explicit_and_cannot_repurpose_old_report(arguments):
    with patch('sys.argv', ['amazon_pilot', *arguments]), \
         patch.object(diagnostic, 'run_pricing_diagnostic') as run:
        with pytest.raises(SystemExit):
            pilot.main()
    run.assert_not_called()


def test_selected_failure_no_retry():
    transport = Transport(SELECTED, fail=True)
    with pytest.raises(Exception):
        diagnostic.pricing_once(CREDS, transport=transport, is_mock=True, asin=SELECTED)
    assert len(transport.calls) == 1


@pytest.mark.parametrize('count,returned', [(1, 0), (2, 1), (21, 19), (20, 21)])
def test_success_count_and_returned_offers_must_agree(count, returned):
    data = response()
    data['payload']['status'] = 'Success'
    data['payload']['Summary'] = {'TotalOfferCount': count}
    data['payload']['Offers'] = [{}] * returned
    with pytest.raises(PricingValidationError, match='pricing_offer_count_inconsistent'):
        details.parse_pricing(data, is_mock=True)


def test_documented_twenty_offer_cap_is_not_a_count_mismatch():
    data = response()
    data['payload']['status'] = 'Success'
    data['payload']['Summary'] = {'TotalOfferCount': 27}
    data['payload']['Offers'] = [{}] * 20
    snapshot = details.parse_pricing(data, is_mock=True).value
    assert snapshot.total_offer_count == 27 and snapshot.price_unknown
