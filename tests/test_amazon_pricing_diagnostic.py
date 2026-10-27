"""Pricing-only diagnostic tested solely with synthetic credentials/responses."""
import json
import os
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from app import amazon_pilot as pilot
from app import amazon_pricing_diagnostic as pricing
from app.amazon_diagnostics import AmazonFailure, ResponseDocument

CREDS = dict(client_id='synthetic-client', client_secret='synthetic-secret', refresh_token='synthetic-refresh')
TOKEN = 'synthetic-access'


def offers():
    return ResponseDocument({'payload': {'status': 'Success', 'ASIN': pilot.ASIN,
        'marketplaceId': pilot.MARKETPLACE, 'ItemCondition': 'New',
        'Identifier': {'ASIN': pilot.ASIN, 'MarketplaceId': pilot.MARKETPLACE, 'ItemCondition': 'New'},
        'Summary': {'TotalOfferCount': 1, 'LowestPrices': [{'condition': 'new',
            'fulfillmentChannel': 'Amazon', 'LandedPrice': {'CurrencyCode': 'USD', 'Amount': 25}}]},
        'Offers': [{}]}}, 200)


class Transport:
    def __init__(self, failure_at=None, validation=False, token_invalid=False):
        self.requests = []
        self.failure_at = failure_at
        self.validation = validation
        self.token_invalid = token_invalid

    def __call__(self, request):
        self.requests.append(request)
        if len(self.requests) == self.failure_at:
            raise AmazonFailure('fixed', reason='http_error', http_status=403, codes=('Unauthorized',))
        if len(self.requests) == 1:
            return ResponseDocument({'access_token': '' if self.token_invalid else TOKEN, 'token_type': 'bearer'}, 200)
        if self.validation:
            return ResponseDocument({'errors': [{'code': 'InvalidInput', 'message': TOKEN}]}, 200)
        if len(self.requests) == 2:
            return offers()
        pytest.fail('More than two requests')


def test_exactly_token_and_offers_with_fixed_scope():
    transport = Transport()
    report = pricing.pricing_once(CREDS, transport=transport, is_mock=True)
    assert len(transport.requests) == report['requests_attempted'] == 2
    token, offer = transport.requests
    assert token.full_url == 'https://api.amazon.com/auth/o2/token'
    assert token.get_method() == 'POST'
    assert b'grant_type=refresh_token' in token.data
    assert urlsplit(offer.full_url).path == '/products/pricing/v0/items/B002XQ1R06/offers'
    assert urlsplit(offer.full_url).netloc == 'sellingpartnerapi-na.amazon.com'
    assert parse_qs(urlsplit(offer.full_url).query) == {
        'MarketplaceId': [pilot.MARKETPLACE], 'ItemCondition': ['New'], 'CustomerType': ['Consumer']}
    assert offer.get_method() == 'GET'
    assert offer.get_header('X-amz-access-token') == TOKEN
    assert report['status'] == 'success'
    assert set(report['stages'].values()) == {'completed'}
    assert report['pricing']['is_mock']
    assert report['response_diagnostics']['current_pricing']['http_status'] == 200
    assert report['pricing']['value']['prices'][0]['landed_price'] == 25
    assert report['pricing']['value']['prices'][0]['shipping'] is None
    assert report['fees'] is None and report['seller_eligible'] is None
    assert not report['purchase_approved']
    assert TOKEN not in json.dumps(report, default=pricing.serialize)


@pytest.mark.parametrize('failure_at', [1, 2])
def test_http_error_stops_without_retry(failure_at):
    transport = Transport(failure_at=failure_at)
    report = {}
    with pytest.raises(AmazonFailure) as failure:
        pricing.pricing_once(CREDS, transport=transport, is_mock=True, report=report)
    assert report['requests_attempted'] == len(transport.requests) == failure_at
    assert report['pricing'] is None
    assert failure.value.http_status == 403
    assert report['stages']['lwa_exchange' if failure_at == 1 else 'current_pricing'] == 'failed'
    if failure_at == 1:
        assert report['stages']['current_pricing'] == 'not_attempted'


@pytest.mark.parametrize('mode', ['token', 'offers'])
def test_http_200_validation_failure_preserves_status_and_codes(mode):
    transport = Transport(token_invalid=mode == 'token', validation=mode == 'offers')
    report = {}
    with pytest.raises(AmazonFailure) as failure:
        pricing.pricing_once(CREDS, transport=transport, is_mock=True, report=report)
    assert failure.value.http_status == 200
    assert failure.value.reason == 'response_validation_failed'
    assert failure.value.amazon_error_codes == (() if mode == 'token' else ('InvalidInput',))
    assert len(transport.requests) == (1 if mode == 'token' else 2)
    assert TOKEN not in str(failure.value)


def run_with_transport(path, transport):
    real = pricing.pricing_once
    def mock_once(credentials, report):
        return real(credentials, report=report, transport=transport, is_mock=True)
    with patch.object(pricing, 'load_credentials', return_value=CREDS), \
         patch.object(pricing, 'pricing_once', side_effect=mock_once):
        pricing.run_pricing_diagnostic(path)


def test_private_report_and_original_reports_preserved(tmp_path):
    path = tmp_path / 'amazon'
    path.mkdir(mode=0o700)
    originals = ('credentials.json', 'catalog-pilot.json', 'catalog-details-pilot.json')
    for name in originals:
        (path / name).write_text('synthetic sentinel ' + name)
    before = {name: (path / name).stat() for name in originals}
    run_with_transport(path, Transport())
    for name in originals:
        assert (path / name).read_text() == 'synthetic sentinel ' + name
        assert (path / name).stat().st_mtime_ns == before[name].st_mtime_ns
        assert (path / name).stat().st_ino == before[name].st_ino
    content = (path / pricing.REPORT_NAME).read_text()
    report = json.loads(content)
    assert report['status'] == 'success' and report['requests_attempted'] == 2
    assert report['started_at'].endswith('+00:00') and report['finished_at'].endswith('+00:00')
    assert all(secret not in content for secret in (*CREDS.values(), TOKEN))
    assert (path / pricing.REPORT_NAME).stat().st_mode & 0o777 == 0o600
    assert path.stat().st_mode & 0o777 == 0o700


def test_existing_report_prevents_credentials_or_requests(tmp_path):
    path = tmp_path / 'amazon'
    directory = pilot.private_directory(path)
    os.close(pilot.create_file(directory, pricing.REPORT_NAME))
    os.close(directory)
    with patch.object(pricing, 'load_credentials') as load, patch.object(pricing, 'pricing_once') as call:
        with pytest.raises(FileExistsError) as failure:
            pricing.run_pricing_diagnostic(path)
    assert failure.value._amazon_operation == 'pricing_report_create'
    load.assert_not_called()
    call.assert_not_called()
    assert (path / pricing.REPORT_NAME).read_bytes() == b''


def test_report_symlink_refused_without_following_or_overwriting(tmp_path):
    path = tmp_path / 'amazon'
    path.mkdir(mode=0o700)
    target = tmp_path / 'sentinel'
    target.write_text('synthetic sentinel')
    (path / pricing.REPORT_NAME).symlink_to(target)
    with patch.object(pricing, 'load_credentials') as load:
        with pytest.raises(FileExistsError):
            pricing.run_pricing_diagnostic(path)
    load.assert_not_called()
    assert target.read_text() == 'synthetic sentinel'


def test_failure_report_retains_only_safe_metadata(tmp_path):
    path = tmp_path / 'amazon'
    with pytest.raises(AmazonFailure):
        run_with_transport(path, Transport(failure_at=2))
    content = (path / pricing.REPORT_NAME).read_text()
    report = json.loads(content)
    assert report['status'] == 'failed'
    assert report['failed_operation'] == 'current_pricing'
    assert report['requests_attempted'] == 2
    assert report['failure_diagnostics']['http_status'] == 403
    assert report['failure_diagnostics']['amazon_error_codes'] == ['Unauthorized']
    assert all(secret not in content for secret in (*CREDS.values(), TOKEN))


def test_deadline_and_handler_restored_on_failure(tmp_path):
    with patch.object(pricing, 'load_credentials', side_effect=TimeoutError(TOKEN)), \
         patch.object(pricing.signal, 'signal', return_value=pricing.signal.SIG_DFL) as handler, \
         patch.object(pricing.signal, 'alarm') as alarm:
        with pytest.raises(TimeoutError):
            pricing.run_pricing_diagnostic(tmp_path / 'amazon')
    assert [call.args for call in alarm.call_args_list] == [(30,), (0,)]
    assert handler.call_args_list[-1].args == (pricing.signal.SIGALRM, pricing.signal.SIG_DFL)
    content = (tmp_path / 'amazon' / pricing.REPORT_NAME).read_text()
    assert TOKEN not in content
    assert json.loads(content)['requests_attempted'] == 0


def test_cli_dispatch_without_seller_id_or_fee_price():
    with patch('sys.argv', ['amazon_pilot', 'pricing-diagnostic']), \
         patch.object(pricing, 'run_pricing_diagnostic') as run:
        assert pilot.main() == 0
    run.assert_called_once_with()


def test_cli_rejects_fee_price_before_any_io():
    with patch('sys.argv', ['amazon_pilot', 'pricing-diagnostic', '--fee-price', '25.00']), \
         patch.object(pricing, 'run_pricing_diagnostic') as run:
        with pytest.raises(SystemExit):
            pilot.main()
    run.assert_not_called()
