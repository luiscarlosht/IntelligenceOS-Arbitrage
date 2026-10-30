"""Representative SP-API shapes; all data is synthetic, never a live response."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
import os
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from app import amazon_pilot as pilot
from app import amazon_details as details
from app.amazon_catalog import ASIN, MARKETPLACE, AmazonCatalogAdapter, parse_catalog
from app.models import RetailProduct
from app.normalization import gtin
from app.provider_contracts import SellerContext
from app.provider_runtime import ProviderFailure

CREDS = dict(client_id='synthetic-client', client_secret='synthetic-secret', refresh_token='synthetic-refresh')
CONTEXT = SellerContext('SYNTHETICSELLER', MARKETPLACE)
PRICE = Decimal('25.00')


def catalog():
    return {'asin': ASIN, 'summaries': [
        {'marketplaceId': 'OTHER', 'itemName': 'Wrong market', 'packageQuantity': 99},
        {'marketplaceId': MARKETPLACE, 'itemName': 'Illustrative blue two-pack',
         'manufacturer': 'Example manufacturer', 'modelNumber': 'Example model',
         'packageQuantity': 2, 'color': 'Blue', 'size': 'Small', 'itemClassification': 'BASE_PRODUCT'}],
        'identifiers': [{'marketplaceId': 'OTHER', 'identifiers': [{'identifierType': 'UPC', 'identifier': '036000291452'}]},
            {'marketplaceId': MARKETPLACE, 'identifiers': [
                {'identifierType': 'UPC', 'identifier': '012345678905'},
                {'identifierType': 'EAN', 'identifier': '0012345678905'}]}],
        'relationships': [{'marketplaceId': MARKETPLACE, 'relationships': [
            {'type': 'VARIATION', 'parentAsins': ['B000000001'],
             'variationTheme': {'theme': 'COLOR_NAME/SIZE_NAME', 'attributes': ['color', 'size']}}]}]}


def pricing():
    return {'payload': {'status': 'Success', 'ASIN': ASIN, 'marketplaceId': MARKETPLACE, 'ItemCondition': 'New',
        'Identifier': {'ASIN': ASIN, 'MarketplaceId': MARKETPLACE, 'ItemCondition': 'New'},
        'Offers': [{}, {}, {}], 'Summary': {'TotalOfferCount': 3,
        'LowestPrices': [{'condition': 'new', 'fulfillmentChannel': 'Amazon',
            'ListingPrice': {'CurrencyCode': 'USD', 'Amount': 24},
            'Shipping': {'CurrencyCode': 'USD', 'Amount': 1},
            'LandedPrice': {'CurrencyCode': 'USD', 'Amount': 25}}],
        'BuyBoxPrices': [{'condition': 'New', 'LandedPrice': {'CurrencyCode': 'USD', 'Amount': 26}}]}}}


def fees(identifier='test-correlation'):
    return {'payload': {'FeesEstimateResult': {'Status': 'Success',
        'FeesEstimateIdentifier': {'MarketplaceId': MARKETPLACE, 'SellerId': CONTEXT.seller_id,
            'IdType': 'ASIN', 'IdValue': ASIN, 'IsAmazonFulfilled': True, 'SellerInputIdentifier': identifier,
            'PriceToEstimateFees': {'ListingPrice': {'CurrencyCode': 'USD', 'Amount': 25},
                                  'Shipping': {'CurrencyCode': 'USD', 'Amount': 0}}},
        'FeesEstimate': {'TimeOfFeesEstimation': '2026-10-26T12:00:00Z',
            'TotalFeesEstimate': {'CurrencyCode': 'USD', 'Amount': 8},
            'FeeDetailList': [{'FeeType': 'ReferralFee', 'FinalFee': {'CurrencyCode': 'USD', 'Amount': 3}},
                {'FeeType': 'FBAFees', 'FinalFee': {'CurrencyCode': 'USD', 'Amount': 5},
                 'IncludedFeeDetailList': [{'FeeType': 'FBAPickAndPack',
                                           'FinalFee': {'CurrencyCode': 'USD', 'Amount': 5}}]}]}}}}


def source(listing):
    return RetailProduct('authorized fixture', listing.title, 'https://example.invalid/product', listing.gtin,
        listing.manufacturer, listing.model, 2, Decimal('10'), 'in_stock', listing.retrieved_at,
        'synthetic fixture', asin_hint=ASIN, variation=listing.variation)


def test_complete_catalog_mapping_and_requests():
    result = parse_catalog(catalog(), is_mock=True)
    listing = result.value
    assert result.is_mock and listing.is_mock
    assert listing.title == 'Illustrative blue two-pack'
    assert listing.gtin == gtin('012345678905')
    assert len(listing.identifiers) == 2
    assert listing.package_quantity == 2
    assert listing.relationships[0].parent_asins == ('B000000001',)
    assert listing.relationships[0].theme_attributes == ('color', 'size')
    assert not listing.mapping_issues and not listing.missing_fields
    assert AmazonCatalogAdapter(result).match(source(listing)).exact
    assert not AmazonCatalogAdapter(result).match(replace(source(listing), variation='Red')).exact
    params = parse_qs(urlsplit(pilot.catalog_request('synthetic-access').full_url).query)
    assert set(params['includedData'][0].split(',')) == {'summaries', 'identifiers', 'relationships'}
    assert params['marketplaceIds'] == [MARKETPLACE]


@pytest.mark.parametrize('quantity', [None, 0, -1, True, '2', 2.5])
def test_missing_or_invalid_quantity_is_not_a_match(quantity):
    data = catalog()
    data['summaries'][1]['packageQuantity'] = quantity
    listing = parse_catalog(data, is_mock=True)
    assert listing.value.package_quantity is None
    assert not AmazonCatalogAdapter(listing).match(source(listing.value)).exact


def test_number_of_items_does_not_invent_package_quantity():
    data = catalog()
    del data['summaries'][1]['packageQuantity']
    data['attributes'] = {'number_of_items': [{'marketplace_id': MARKETPLACE, 'value': 6}]}
    assert parse_catalog(data, is_mock=True).value.package_quantity is None


@pytest.mark.parametrize('key', ['identifiers', 'relationships'])
def test_missing_datasets_remain_missing_and_never_default_to_standard(key):
    data = catalog()
    del data[key]
    evidence = parse_catalog(data, is_mock=True)
    if key == 'identifiers':
        assert evidence.value.gtin == ''
        product = replace(source(evidence.value), manufacturer='', model='')
    else:
        assert evidence.value.variation == ''
        product = source(evidence.value)
    assert not AmazonCatalogAdapter(evidence).match(product).exact


@pytest.mark.parametrize('change', ['invalid_gtin', 'ambiguous_gtin', 'parent', 'package', 'unsupported_theme'])
def test_ambiguous_or_incomplete_catalog_blocks_match(change):
    data = catalog()
    if change == 'invalid_gtin':
        data['identifiers'][1]['identifiers'][0]['identifier'] = '012345678906'
    elif change == 'ambiguous_gtin':
        data['identifiers'][1]['identifiers'].append({'identifierType': 'UPC', 'identifier': '036000291452'})
    elif change == 'parent':
        data['summaries'][1]['itemClassification'] = 'VARIATION_PARENT'
        data['relationships'][0]['relationships'][0]['childAsins'] = ['B000000002']
    elif change == 'package':
        data['relationships'][0]['relationships'].append({'type': 'PACKAGE_HIERARCHY', 'parentAsins': ['B000000003']})
    else:
        data['relationships'][0]['relationships'][0]['variationTheme']['attributes'].append('scent')
    evidence = parse_catalog(data, is_mock=True)
    assert evidence.value.mapping_issues
    assert not AmazonCatalogAdapter(evidence).match(source(evidence.value)).exact


def test_catalog_secrets_redacted_and_wrong_market_not_used():
    data = catalog()
    data['summaries'][1]['itemName'] = 'synthetic-secret\nname'
    evidence = parse_catalog(data, is_mock=True, secrets=('synthetic-secret',))
    assert evidence.value.title == '[REDACTED]name'
    assert evidence.value.package_quantity == 2
    data['summaries'].append(deepcopy(data['summaries'][1]))
    with pytest.raises(ProviderFailure):
        parse_catalog(data, is_mock=True)


def test_pricing_snapshot_separates_price_components_and_missing_shipping():
    evidence = details.parse_pricing(pricing(), is_mock=True)
    assert evidence.is_mock
    assert evidence.value.total_offer_count == 3
    assert evidence.value.prices[0].listing_price == 24
    assert evidence.value.prices[0].shipping == 1
    assert evidence.value.prices[0].landed_price == 25
    assert evidence.value.prices[1].listing_price is None
    assert evidence.value.prices[1].shipping is None


@pytest.mark.parametrize('change', ['currency', 'asin', 'marketplace', 'status', 'errors'])
def test_invalid_pricing_not_accepted(change):
    data = pricing()
    if change == 'currency':
        data['payload']['Summary']['LowestPrices'][0]['LandedPrice']['CurrencyCode'] = 'CAD'
    elif change == 'asin':
        data['payload']['ASIN'] = 'B000000001'
    elif change == 'marketplace':
        data['payload']['marketplaceId'] = 'OTHER'
    elif change == 'status':
        data['payload']['status'] = 'ClientError'
    else:
        data['errors'] = [{'message': 'synthetic-secret'}]
    with pytest.raises(ProviderFailure):
        details.parse_pricing(data, is_mock=True)


def test_empty_pricing_is_unknown_not_zero():
    data = pricing()
    data['payload']['Summary'] = {}
    with pytest.raises(ProviderFailure, match='pricing_count_missing_or_invalid'):
        details.parse_pricing(data, is_mock=True)


def test_fee_final_aggregates_no_nested_double_counting():
    result = details.parse_fees(fees(), CONTEXT, PRICE, 'test-correlation', is_mock=True)
    assert result['quote']['value']['referral_fee'] == 3
    assert result['quote']['value']['fulfillment_fee'] == 5
    assert result['total_fees_estimate'] == 8
    data = fees()
    data['payload']['FeesEstimateResult']['FeesEstimate']['FeeDetailList'] = []
    result = details.parse_fees(data, CONTEXT, PRICE, 'test-correlation', is_mock=True)
    assert result['quote']['value']['referral_fee'] is None
    assert result['quote']['value']['fulfillment_fee'] is None
    assert result['total_fees_estimate'] == 8


@pytest.mark.parametrize('field,value', [('SellerId', 'WRONG'), ('MarketplaceId', 'OTHER'),
    ('IdValue', 'B000000001'), ('IsAmazonFulfilled', False), ('SellerInputIdentifier', 'WRONG')])
def test_fee_context_mismatch_rejected(field, value):
    data = fees()
    data['payload']['FeesEstimateResult']['FeesEstimateIdentifier'][field] = value
    with pytest.raises(ProviderFailure):
        details.parse_fees(data, CONTEXT, PRICE, 'test-correlation', is_mock=True)


def test_fee_application_error_is_not_http_success():
    data = fees()
    data['payload']['FeesEstimateResult']['Status'] = 'ClientError'
    with pytest.raises(ProviderFailure):
        details.parse_fees(data, CONTEXT, PRICE, 'test-correlation', is_mock=True)


def test_restrictions_empty_is_narrow_listing_permission_only():
    result = details.parse_restrictions({'restrictions': []}, CONTEXT, is_mock=True)
    assert result['listing_permission']['value'] is True
    assert not result['purchase_approved']
    assert result['fulfillment_eligibility'] is None
    blocked = details.parse_restrictions({'restrictions': [{'marketplaceId': MARKETPLACE,
        'conditionType': 'new_new', 'reasons': [{'reasonCode': 'APPROVAL_REQUIRED',
            'message': 'synthetic-secret', 'links': [{'resource': 'https://example.invalid'}]}]}]}, CONTEXT, is_mock=True)
    assert blocked['listing_permission']['value'] is False
    assert blocked['reason_codes'] == ['APPROVAL_REQUIRED']
    assert blocked['reasons'][0]['message'] == 'synthetic-secret'
    assert blocked['reasons'][0]['links'] == [{'resource': 'https://example.invalid'}]
    with pytest.raises(ProviderFailure):
        details.parse_restrictions({}, CONTEXT, is_mock=True)
    with pytest.raises(ProviderFailure):
        details.parse_restrictions({'restrictions': [{'marketplaceId': 'OTHER'}]}, CONTEXT, is_mock=True)


class MockTransport:
    def __init__(self, failure_at=None):
        self.calls = []
        self.failure_at = failure_at

    def __call__(self, request):
        self.calls.append(request)
        index = len(self.calls)
        if index == self.failure_at:
            raise ProviderFailure('synthetic-secret')
        if index == 1:
            return {'access_token': 'synthetic-access', 'token_type': 'bearer'}
        if index == 2:
            return catalog()
        if index == 3:
            return pricing()
        if index == 4:
            body = json.loads(request.data)
            return fees(body['FeesEstimateRequest']['Identifier'])
        if index == 5:
            return {'restrictions': []}
        pytest.fail('Exceeded request cap')


def test_bounded_read_only_details_requests_and_unknown_economics():
    transport = MockTransport()
    report = details.details_once(CREDS, CONTEXT, PRICE, transport=transport, is_mock=True)
    assert report['status'] == 'success' and report['requests_attempted'] == 5
    assert [r.get_method() for r in transport.calls] == ['POST', 'GET', 'GET', 'POST', 'GET']
    assert urlsplit(transport.calls[3].full_url).path == '/products/fees/v0/items/' + ASIN + '/feesEstimate'
    fee_request = json.loads(transport.calls[3].data)['FeesEstimateRequest']
    assert fee_request['IsAmazonFulfilled'] is True
    assert fee_request['PriceToEstimateFees']['ListingPrice']['Amount'] == 25
    assert fee_request['PriceToEstimateFees']['Shipping']['Amount'] == 0
    params = parse_qs(urlsplit(transport.calls[4].full_url).query)
    assert params['sellerId'] == [CONTEXT.seller_id]
    assert params['conditionType'] == ['new_new']
    assert report['catalog']['value']['seller_eligible'] is None
    assert report['catalog']['value']['sale_price'] is None
    assert report['seller_eligible'] is None and not report['purchase_approved']
    assert report['catalog']['is_mock'] and report['fees']['quote']['is_mock']


@pytest.mark.parametrize('failure_at', [1, 2, 3, 4, 5])
def test_details_stop_on_first_failure_without_retry(failure_at):
    transport = MockTransport(failure_at)
    report = {}
    with pytest.raises(ProviderFailure):
        details.details_once(CREDS, CONTEXT, PRICE, transport=transport, is_mock=True, report=report)
    assert len(transport.calls) == failure_at
    assert report['requests_attempted'] == failure_at


def test_existing_details_report_prevents_credential_load_and_network(tmp_path):
    path = tmp_path / 'amazon'
    directory = pilot.private_directory(path)
    os.close(pilot.create_file(directory, details.REPORT_NAME))
    os.close(directory)
    with patch.object(details, 'load_credentials') as load, patch.object(details, 'prompt_seller_id') as prompt:
        with pytest.raises(FileExistsError):
            details.run_details(PRICE, path)
        load.assert_not_called()
        prompt.assert_not_called()


@pytest.mark.parametrize('price', ['0', '-1', 'NaN', 'Infinity', '1.001', '1e2', '1000000'])
def test_invalid_proposed_price_before_any_io(price):
    with pytest.raises(ValueError):
        details.proposed_price(price)


def test_invalid_context_before_network():
    transport = MockTransport()
    with pytest.raises(ValueError):
        details.details_once(CREDS, SellerContext('SELLER', 'OTHER'), PRICE, transport=transport, is_mock=True)
    assert not transport.calls


def test_details_report_private_redacted_and_signal_restored(tmp_path):
    path = tmp_path / 'amazon'
    transport = MockTransport()
    real = details.details_once
    def mock_details(credentials, context, price, report):
        return real(credentials, context, price, transport=transport, is_mock=True, report=report)
    with patch.object(details, 'load_credentials', return_value=CREDS), \
         patch.object(details, 'prompt_seller_id', return_value=CONTEXT.seller_id), \
         patch.object(details, 'details_once', side_effect=mock_details), \
         patch.object(details.signal, 'signal', return_value=details.signal.SIG_DFL) as handler, \
         patch.object(details.signal, 'alarm') as alarm:
        details.run_details(PRICE, path)
    content = (path / details.REPORT_NAME).read_text()
    assert all(secret not in content for secret in (*CREDS.values(), 'synthetic-access', CONTEXT.seller_id))
    assert json.loads(content)['status'] == 'success'
    assert (path / details.REPORT_NAME).stat().st_mode & 0o777 == 0o600
    assert alarm.call_args_list[0].args == (60,)
    assert alarm.call_args_list[-1].args == (0,)
    assert handler.call_args_list[-1].args == (details.signal.SIGALRM, details.signal.SIG_DFL)


def test_details_partial_failure_saved_without_raw_exception_or_retries(tmp_path):
    path = tmp_path / 'amazon'
    transport = MockTransport(failure_at=3)
    real = details.details_once
    def mock_details(credentials, context, price, report):
        return real(credentials, context, price, transport=transport, is_mock=True, report=report)
    with patch.object(details, 'load_credentials', return_value=CREDS), \
         patch.object(details, 'prompt_seller_id', return_value=CONTEXT.seller_id), \
         patch.object(details, 'details_once', side_effect=mock_details):
        with pytest.raises(ProviderFailure):
            details.run_details(PRICE, path)
    content = (path / details.REPORT_NAME).read_text()
    report = json.loads(content)
    assert report['status'] == 'failed' and report['failed_operation'] == 'current_pricing'
    assert report['catalog'] is not None
    assert report['fees'] is None and report['restrictions'] is None
    assert report['requests_attempted'] == 3 and len(transport.calls) == 3
    assert 'synthetic-secret' not in content


def test_details_timeout_is_redacted_and_preserves_unknowns(tmp_path):
    path = tmp_path / 'amazon'
    with patch.object(details, 'prompt_seller_id', return_value=CONTEXT.seller_id), \
         patch.object(details, 'load_credentials', side_effect=TimeoutError('synthetic-secret')):
        with pytest.raises(TimeoutError):
            details.run_details(PRICE, path)
    content = (path / details.REPORT_NAME).read_text()
    report = json.loads(content)
    assert report['requests_attempted'] == 0
    assert report['failed_operation'] == 'credential_load'
    assert 'synthetic-secret' not in content


def test_seller_hidden_input_failure_before_credential_load(tmp_path):
    from unittest.mock import mock_open
    terminal = mock_open()
    terminal.return_value.isatty.return_value = True
    with patch('builtins.open', terminal), \
         patch.object(details.getpass, 'getpass', side_effect=details.getpass.GetPassWarning('synthetic-secret')), \
         patch.object(details, 'load_credentials') as load:
        with pytest.raises(details.getpass.GetPassWarning):
            details.run_details(PRICE, tmp_path / 'amazon')
        load.assert_not_called()
    content = (tmp_path / 'amazon' / details.REPORT_NAME).read_text()
    assert json.loads(content)['failed_operation'] == 'seller_hidden_prompt'
    assert 'synthetic-secret' not in content


def test_actual_report_not_overwritten_and_credentials_never_modified(tmp_path):
    path = tmp_path / 'amazon'
    path.mkdir(mode=0o700)
    credential = path / 'credentials.json'
    credential.write_text('synthetic sentinel')
    before = credential.stat()
    (path / details.REPORT_NAME).write_text('synthetic existing report')
    with pytest.raises(FileExistsError):
        details.run_details(PRICE, path)
    assert credential.read_text() == 'synthetic sentinel'
    assert credential.stat().st_mtime_ns == before.st_mtime_ns
    assert (path / details.REPORT_NAME).read_text() == 'synthetic existing report'
