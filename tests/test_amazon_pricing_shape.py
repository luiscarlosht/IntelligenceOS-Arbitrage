"""Schema-shaped synthetic regressions, never stored live payloads."""
from dataclasses import asdict
from decimal import Decimal
import json
from unittest.mock import patch

import pytest

from app import amazon_details as details
from app import amazon_pilot as pilot
from app import amazon_pricing_diagnostic as diagnostic
from app.amazon_pricing_shape import PricingValidationError, pricing_shape
from app.amazon_diagnostics import AmazonFailure, ResponseDocument, failure_metadata

SECRET = 'synthetic-sensitive-value'
CREDS = dict(client_id='synthetic-client', client_secret='synthetic-secret', refresh_token='synthetic-refresh')


def response():
    return {'payload': {'status': 'Success', 'marketplaceId': pilot.MARKETPLACE,
        'ASIN': pilot.ASIN, 'ItemCondition': 'New',
        'Identifier': {'ASIN': pilot.ASIN, 'MarketplaceId': pilot.MARKETPLACE, 'ItemCondition': 'New'},
        'Summary': {'TotalOfferCount': 1, 'LowestPrices': [{'condition': 'new',
            'fulfillmentChannel': 'Amazon', 'ListingPrice': {'CurrencyCode': 'USD', 'Amount': 12.34}}]},
        'Offers': []}}


@pytest.mark.parametrize('location', ['payload', 'Identifier'])
def test_optional_duplicate_asin_not_required_but_identity_retained(location):
    data = response()
    del (data['payload'] if location == 'payload' else data['payload']['Identifier'])['ASIN']
    evidence = details.parse_pricing(data, is_mock=True)
    assert evidence.value.asin == pilot.ASIN
    assert evidence.value.prices[0].listing_price == Decimal('12.34')
    assert evidence.value.prices[0].shipping is None
    assert evidence.value.prices[0].landed_price is None


@pytest.mark.parametrize('location', ['payload', 'Identifier'])
def test_any_explicit_identity_conflict_rejected(location):
    data = response()
    (data['payload'] if location == 'payload' else data['payload']['Identifier'])['ASIN'] = 'B000000001'
    with pytest.raises(PricingValidationError, match='pricing_asin_mismatch'):
        details.parse_pricing(data, is_mock=True)


def test_no_response_identity_is_not_assumed_from_request():
    data = response()
    del data['payload']['ASIN']
    del data['payload']['Identifier']['ASIN']
    with pytest.raises(PricingValidationError, match='pricing_asin_missing'):
        details.parse_pricing(data, is_mock=True)


@pytest.mark.parametrize('status', ['success', 'SUCCESS', 'NoOffer', 'ActiveButTooSoonForProcessing', SECRET, None, 200])
def test_only_explicit_success_is_accepted(status):
    data = response()
    data['payload']['status'] = status
    with pytest.raises(PricingValidationError) as error:
        details.parse_pricing(data, is_mock=True)
    assert error.value.label == 'pricing_status_not_success'
    assert SECRET not in str(error.value)


def test_saved_other_status_shape_cannot_identify_first_rejection():
    data = response()
    data['payload']['status'] = SECRET
    assert pricing_shape(data)['status_label'] == 'OTHER'
    with pytest.raises(PricingValidationError, match='pricing_status_not_success'):
        details.parse_pricing(data, is_mock=True)
    data['errors'] = [{'message': SECRET}]  # Same previous metadata: codes=[], status=OTHER.
    with pytest.raises(PricingValidationError, match='pricing_errors_present'):
        details.parse_pricing(data, is_mock=True)


@pytest.mark.parametrize('data,label', [
    ({'payload': []}, 'pricing_payload_not_object'),
    ({'Payload': {}}, 'pricing_payload_not_object'),
    ({'status': 'Success', 'Summary': {}}, 'pricing_payload_not_object'),
    ({'payload': None}, 'pricing_payload_not_object'),
    ({'errors': [{'code': 'InvalidInput'}]}, 'pricing_errors_present'),
])
def test_no_payload_unwrapping_or_guessed_nesting(data, label):
    with pytest.raises(PricingValidationError) as error:
        details.parse_pricing(data, is_mock=True)
    assert error.value.label == label


def test_documented_explicit_zero_offer_case_has_no_price():
    data = response()
    data['payload']['Summary'] = {'TotalOfferCount': 0}
    evidence = details.parse_pricing(data, is_mock=True)
    assert evidence.value.total_offer_count == 0  # Explicit observed count, not inferred.
    assert evidence.value.prices == ()
    assert '0' not in json.dumps([asdict(row) for row in evidence.value.prices])


@pytest.mark.parametrize('missing', ['Offers', 'Summary'])
def test_missing_required_container_is_not_no_offers(missing):
    data = response()
    del data['payload'][missing]
    with pytest.raises(PricingValidationError):
        details.parse_pricing(data, is_mock=True)


@pytest.mark.parametrize('count', [None, True, -1, '0', 1.5])
def test_required_count_not_defaulted(count):
    data = response()
    data['payload']['Summary']['TotalOfferCount'] = count
    with pytest.raises(PricingValidationError, match='pricing_count_missing_or_invalid'):
        details.parse_pricing(data, is_mock=True)


def test_explicit_zero_count_with_prices_is_inconsistent():
    data = response()
    data['payload']['Summary']['TotalOfferCount'] = 0
    with pytest.raises(PricingValidationError, match='pricing_no_offers_inconsistent'):
        details.parse_pricing(data, is_mock=True)


def test_optional_summary_prices_can_be_absent_without_inventing_price():
    data = response()
    data['payload']['Summary'] = {'TotalOfferCount': 1}
    assert details.parse_pricing(data, is_mock=True).value.prices == ()


@pytest.mark.parametrize('amount', [True, -1, float('nan'), float('inf'), '12.34', {}, []])
def test_schema_numeric_finite_nonnegative_prices_only(amount):
    data = response()
    data['payload']['Summary']['LowestPrices'][0]['ListingPrice']['Amount'] = amount
    with pytest.raises(PricingValidationError, match='pricing_amount_invalid'):
        details.parse_pricing(data, is_mock=True)


@pytest.mark.parametrize('amount', [0, 12, 12.34, Decimal('12.340000000000001')])
def test_explicit_valid_amount_is_preserved_as_decimal(amount):
    data = response()
    data['payload']['Summary']['LowestPrices'][0]['ListingPrice']['Amount'] = amount
    assert details.parse_pricing(data, is_mock=True).value.prices[0].listing_price == Decimal(str(amount))


@pytest.mark.parametrize('currency', ['CAD', SECRET, None])
def test_currency_not_guessed_from_marketplace(currency):
    data = response()
    data['payload']['Summary']['LowestPrices'][0]['ListingPrice']['CurrencyCode'] = currency
    with pytest.raises(PricingValidationError, match='pricing_currency_not_usd'):
        details.parse_pricing(data, is_mock=True)


def test_missing_amount_remains_unknown():
    data = response()
    del data['payload']['Summary']['LowestPrices'][0]['ListingPrice']['Amount']
    assert details.parse_pricing(data, is_mock=True).value.prices[0].listing_price is None


def test_shape_records_no_arbitrary_keys_or_values_and_bounds_samples():
    data = response()
    data[SECRET] = SECRET
    data['payload']['status'] = SECRET
    data['payload']['ASIN'] = SECRET
    data['payload']['Identifier']['ASIN'] = SECRET
    row = data['payload']['Summary']['LowestPrices'][0]
    row['ListingPrice'] = {'CurrencyCode': SECRET, 'Amount': SECRET}
    row['SellerId'] = SECRET
    row[SECRET] = SECRET
    data['payload']['Summary']['LowestPrices'] = [row] * 100
    shape = pricing_shape(data)
    assert shape['price_groups']['LowestPrices']['count'] == 100
    assert len(shape['price_groups']['LowestPrices']['sample']) == 3
    assert shape['status_label'] == 'OTHER'
    assert shape['context']['payload_asin_matches'] is False
    content = json.dumps(shape)
    assert SECRET not in content and '12.34' not in content
    assert 'SellerId' not in content


def test_shape_casing_comparison_is_diagnostic_only():
    data = response()
    data['payload']['status'] = 'SUCCESS'
    shape = pricing_shape(data)
    assert shape['status_exact_success'] is False and shape['status_casefold_success'] is True
    with pytest.raises(PricingValidationError):
        details.parse_pricing(data, is_mock=True)


class ShapeTransport:
    def __init__(self, malformed=False):
        self.calls = []
        self.malformed = malformed

    def __call__(self, request):
        self.calls.append(request)
        if len(self.calls) == 1:
            return ResponseDocument({'access_token': SECRET, 'token_type': 'bearer'}, 200)
        assert len(self.calls) == 2
        data = response()
        if self.malformed:
            data['payload']['status'] = SECRET
        return ResponseDocument(data, 200)


@pytest.mark.parametrize('malformed', [False, True])
def test_shape_only_report_has_no_prices_or_tokens(tmp_path, malformed):
    path = tmp_path / 'amazon'
    path.mkdir(mode=0o700)
    prior = path / diagnostic.REPORT_NAME
    prior.write_text('synthetic prior evidence')
    transport = ShapeTransport(malformed)
    real = diagnostic.pricing_once
    def mock_once(credentials, report, shape_only):
        return real(credentials, report=report, shape_only=shape_only, transport=transport, is_mock=True)
    with patch.object(diagnostic, 'load_credentials', return_value=CREDS), \
         patch.object(diagnostic, 'pricing_once', side_effect=mock_once):
        if malformed:
            with pytest.raises(AmazonFailure) as error:
                diagnostic.run_pricing_diagnostic(path, shape_only=True)
            assert failure_metadata(error.value)['validation_label'] == 'pricing_status_not_success'
            assert 'validation_label=pricing_status_not_success' in pilot.failure_diagnostic(error.value)
        else:
            diagnostic.run_pricing_diagnostic(path, shape_only=True)
    assert len(transport.calls) == 2
    content = (path / diagnostic.SHAPE_REPORT_NAME).read_text()
    report = json.loads(content)
    assert report['pricing'] is None and report['shape_only'] is True
    assert report['validation_label'] == ('pricing_status_not_success' if malformed else 'pricing_validated')
    assert report['response_diagnostics']['current_pricing']['http_status'] == 200
    assert SECRET not in content and '12.34' not in content
    assert prior.read_text() == 'synthetic prior evidence'
    assert (path / diagnostic.SHAPE_REPORT_NAME).stat().st_mode & 0o777 == 0o600


def test_existing_shape_report_blocks_all_credentials_and_calls(tmp_path):
    path = tmp_path / 'amazon'
    path.mkdir(mode=0o700)
    (path / diagnostic.SHAPE_REPORT_NAME).write_text('synthetic previous shape')
    with patch.object(diagnostic, 'load_credentials') as load, patch.object(diagnostic, 'pricing_once') as call:
        with pytest.raises(FileExistsError):
            diagnostic.run_pricing_diagnostic(path, shape_only=True)
    load.assert_not_called()
    call.assert_not_called()
    assert (path / diagnostic.SHAPE_REPORT_NAME).read_text() == 'synthetic previous shape'


def test_shape_cli_dispatch_is_explicit():
    with patch('sys.argv', ['amazon_pilot', 'pricing-shape-diagnostic']), \
         patch.object(diagnostic, 'run_pricing_diagnostic') as run:
        assert pilot.main() == 0
    run.assert_called_once_with(shape_only=True)
