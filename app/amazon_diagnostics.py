"""Fixed-label SP-API diagnostics; never retain response messages or raw codes."""
import json

from app.provider_runtime import ProviderFailure
from app.amazon_pricing_shape import LABELS

MAX_ERROR_BYTES = 16 * 1024
ERROR_CODES = frozenset({
    'InvalidInput', 'Unauthorized', 'Forbidden', 'AccessDenied', 'InvalidSignature',
    'QuotaExceeded', 'Throttling', 'TooManyRequests', 'InternalError', 'ServiceUnavailable',
    'RequestTimeout', 'InvalidAccessToken', 'ExpiredToken',
    'invalid_client', 'invalid_grant', 'invalid_request', 'unauthorized_client', 'unsupported_grant_type',
})
FAILURE_REASONS = frozenset({'http_error', 'transport_error', 'response_too_large',
    'invalid_json', 'invalid_response', 'response_validation_failed'})


def status_number(value: object) -> int | None:
    return value if type(value) is int and 100 <= value <= 599 else None


def error_codes(document: object) -> tuple[str, ...]:
    if not isinstance(document, dict):
        return ()
    codes = []
    rows = document.get('errors', [])
    if isinstance(rows, list):
        codes.extend(row.get('code') for row in rows[:20] if isinstance(row, dict))
    codes.append(document.get('error'))  # LWA uses a singular error code.
    return tuple(sorted({code if code in ERROR_CODES else 'OTHER'
                         for code in codes if isinstance(code, str) and code}))


def bounded_error_codes(body: bytes) -> tuple[str, ...]:
    if len(body) > MAX_ERROR_BYTES:
        return ()
    try:
        return error_codes(json.loads(body))
    except (ValueError, UnicodeError):
        return ()


class ResponseDocument(dict):
    """HTTP metadata is out-of-band; no private keys added to Amazon JSON."""
    def __init__(self, document: dict, http_status: int):
        super().__init__(document)
        self.http_status = status_number(http_status)


class AmazonFailure(ProviderFailure):
    def __init__(self, message: str, *, reason: str, http_status: int | None = None,
                 codes: tuple[str, ...] = (), validation_label: str | None = None):
        super().__init__(message)
        self.validation_label = validation_label if validation_label in LABELS else None
        self.reason = reason if reason in FAILURE_REASONS else 'response_validation_failed'
        self.http_status = status_number(http_status)
        self.amazon_error_codes = tuple(sorted({c if c in ERROR_CODES else 'OTHER' for c in codes}))


def response_metadata(document: dict) -> dict:
    payload = document.get('payload')
    status = payload.get('status') if isinstance(payload, dict) else None
    return {'http_status': status_number(getattr(document, 'http_status', None)),
            'amazon_error_codes': list(error_codes(document)),
            'application_status': status if status in ('Success', 'ClientError', 'ServiceError')
                                  else 'OTHER' if isinstance(status, str) else None}


def failure_metadata(error: BaseException) -> dict:
    number = getattr(error, 'errno', None)
    data = {'exception': type(error).__name__, 'errno': number if type(number) is int else None,
            'http_status': None, 'amazon_error_codes': [], 'reason': 'operation_failed'}
    if isinstance(error, AmazonFailure):
        data.update(http_status=status_number(error.http_status),
                    amazon_error_codes=[c if c in ERROR_CODES else 'OTHER' for c in error.amazon_error_codes],
                    reason=error.reason if error.reason in FAILURE_REASONS else 'operation_failed')
        if error.validation_label in LABELS:
            data['validation_label'] = error.validation_label
    return data
