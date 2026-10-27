"""Synthetic errors only; tests must never open the operator's credentials/report."""
import io
import json
from decimal import Decimal
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import pytest

from app import amazon_pilot as pilot
from app import amazon_details as details
from app.amazon_diagnostics import (AmazonFailure, MAX_ERROR_BYTES, ResponseDocument,
    error_codes, failure_metadata, response_metadata)
from app.provider_contracts import SellerContext

SECRET = 'synthetic-do-not-disclose'


def http_error(status, document):
    return HTTPError('https://example.invalid/' + SECRET, status, SECRET,
                     {'PrivateHeader': SECRET}, io.BytesIO(json.dumps(document).encode()))


@pytest.mark.parametrize('status,code', [(400, 'InvalidInput'), (401, 'Unauthorized'),
    (403, 'AccessDenied'), (429, 'QuotaExceeded'), (500, 'InternalError')])
def test_http_failure_preserves_status_and_allowlisted_code_only(status, code):
    opener = Mock()
    opener.open.side_effect = http_error(status, {'errors': [
        {'code': code, 'message': SECRET, 'details': SECRET}, {'code': SECRET}]})
    with patch.object(pilot, 'build_opener', return_value=opener):
        with pytest.raises(AmazonFailure) as failure:
            pilot.request_json(pilot.Request('https://example.invalid'))
    safe = failure_metadata(failure.value)
    assert safe['http_status'] == status
    assert safe['amazon_error_codes'] == sorted([code, 'OTHER'])
    assert safe['reason'] == 'http_error'
    assert SECRET not in json.dumps(safe)
    assert SECRET not in pilot.failure_diagnostic(failure.value)
    assert SECRET not in str(failure.value)
    assert opener.open.call_count == 1


@pytest.mark.parametrize('body', [b'<html>synthetic-do-not-disclose</html>', b'{invalid json',
    b'x' * (MAX_ERROR_BYTES + 1)])
def test_invalid_or_oversized_error_body_retains_status_without_body(body):
    opener = Mock()
    stream = io.BytesIO(body)
    opener.open.side_effect = HTTPError('https://example.invalid', 503, SECRET, {}, stream)
    with patch.object(pilot, 'build_opener', return_value=opener):
        with pytest.raises(AmazonFailure) as failure:
            pilot.request_json(pilot.Request('https://example.invalid'))
    assert failure.value.http_status == 503
    assert failure.value.amazon_error_codes == ()
    assert stream.closed
    assert SECRET not in pilot.failure_diagnostic(failure.value)
    assert opener.open.call_count == 1


def test_error_body_read_failure_preserves_http_status():
    stream = Mock()
    stream.read.side_effect = TimeoutError(SECRET)
    opener = Mock()
    opener.open.side_effect = HTTPError('https://example.invalid', 403, SECRET, {}, stream)
    with patch.object(pilot, 'build_opener', return_value=opener):
        with pytest.raises(AmazonFailure) as failure:
            pilot.request_json(pilot.Request('https://example.invalid'))
    stream.read.assert_called_once_with(MAX_ERROR_BYTES + 1)
    assert failure.value.http_status == 403
    assert failure.value.amazon_error_codes == ()


def test_transport_failure_does_not_invent_http_status():
    opener = Mock()
    opener.open.side_effect = URLError(SECRET)
    with patch.object(pilot, 'build_opener', return_value=opener):
        with pytest.raises(AmazonFailure) as failure:
            pilot.request_json(pilot.Request('https://example.invalid'))
    safe = failure_metadata(failure.value)
    assert safe['http_status'] is None and safe['amazon_error_codes'] == []
    assert safe['reason'] == 'transport_error'
    assert SECRET not in pilot.failure_diagnostic(failure.value)


class FakeResponse(io.BytesIO):
    status = 200


@pytest.mark.parametrize('body,reason', [(b'{bad-json', 'invalid_json'), (b'[]', 'invalid_response'),
                                       (b'x' * (pilot.MAX_BYTES + 1), 'response_too_large')])
def test_http_200_invalid_response_records_actual_status(body, reason):
    opener = Mock()
    opener.open.return_value = FakeResponse(body)
    with patch.object(pilot, 'build_opener', return_value=opener):
        with pytest.raises(AmazonFailure) as failure:
            pilot.request_json(pilot.Request('https://example.invalid'))
    assert failure.value.http_status == 200
    assert failure.value.reason == reason
    assert opener.open.call_count == 1


def test_successful_transport_preserves_metadata_without_modifying_json():
    opener = Mock()
    opener.open.return_value = FakeResponse(b'{"payload":{"status":"Success"}}')
    with patch.object(pilot, 'build_opener', return_value=opener):
        document = pilot.request_json(pilot.Request('https://example.invalid'))
    assert document == {'payload': {'status': 'Success'}}
    assert document.http_status == 200
    assert response_metadata(document)['http_status'] == 200


def test_unknown_and_lwa_error_codes_are_allowlisted():
    assert error_codes({'error': 'invalid_grant', 'error_description': SECRET}) == ('invalid_grant',)
    assert error_codes({'errors': [{'code': SECRET}]}) == ('OTHER',)
    assert error_codes({'errors': [{'code': {'secret': SECRET}}]}) == ()
    assert error_codes({'errors': SECRET}) == ()


def synthetic_catalog():
    return {'asin': pilot.ASIN, 'summaries': [{'marketplaceId': pilot.MARKETPLACE,
        'itemName': 'Synthetic catalog item', 'packageQuantity': 1}]}


@pytest.mark.parametrize('failure_mode', ['http', 'validation', 'application'])
def test_details_report_retains_safe_failure_and_partial_evidence(tmp_path, failure_mode):
    calls = []
    def transport(request):
        calls.append(request)
        if len(calls) == 1:
            return ResponseDocument({'access_token': SECRET, 'token_type': 'bearer'}, 200)
        if len(calls) == 2:
            return ResponseDocument(synthetic_catalog(), 200)
        if failure_mode == 'http':
            raise AmazonFailure('forbidden', reason='http_error', http_status=403, codes=('Unauthorized',))
        if failure_mode == 'application':
            return ResponseDocument({'errors': [{'code': 'InvalidInput', 'message': SECRET}]}, 200)
        return ResponseDocument({'payload': {'status': 'Success', 'ASIN': 'WRONG'}}, 200)
    real_once = details.details_once
    def fake_once(credentials, context, price, report):
        return real_once(credentials, context, price, transport=transport, is_mock=True, report=report)
    with patch.object(details, 'load_credentials', return_value=dict(client_id='synthetic-client',
         client_secret='synthetic-secret', refresh_token='synthetic-refresh')), \
         patch.object(details, 'prompt_seller_id', return_value='SYNTHETICSELLER'), \
         patch.object(details, 'details_once', side_effect=fake_once):
        with pytest.raises(AmazonFailure):
            details.run_details(Decimal('25.00'), tmp_path / 'amazon')
    content = (tmp_path / 'amazon' / details.REPORT_NAME).read_text()
    report = json.loads(content)
    diagnostic = report['failure_diagnostics']
    assert report['requests_attempted'] == 3 and len(calls) == 3
    assert report['failed_operation'] == 'current_pricing'
    assert report['catalog']['value']['title'] == 'Synthetic catalog item'
    assert all(report[key] is None for key in ('pricing', 'fees', 'restrictions'))
    assert diagnostic['http_status'] == (403 if failure_mode == 'http' else 200)
    assert diagnostic['amazon_error_codes'] == (['Unauthorized'] if failure_mode == 'http' else
                                               ['InvalidInput'] if failure_mode == 'application' else [])
    if failure_mode != 'http':
        assert report['response_diagnostics']['current_pricing']['http_status'] == 200
        assert diagnostic['reason'] == 'response_validation_failed'
    assert SECRET not in content
    assert 'SYNTHETICSELLER' not in content


def test_plain_mock_document_does_not_invent_a_status():
    assert response_metadata({'payload': {'status': SECRET}}) == {
        'http_status': None, 'amazon_error_codes': [], 'application_status': 'OTHER'}
