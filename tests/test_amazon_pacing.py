from datetime import datetime, timezone
from urllib.error import HTTPError
from io import BytesIO
import pytest

from app.amazon_pacing import OperationPacer
from app.amazon_pilot import amazon_request, request_json
from app.amazon_diagnostics import AmazonFailure, ResponseDocument, failure_metadata


class Clock:
    value = 0.
    def now(self): return self.value
    def sleep(self, seconds): self.value += seconds


def test_independent_operations_headers_and_reservations():
    clock = Clock()
    pacer = OperationPacer(monotonic=clock.now, sleep=clock.sleep)
    pacer.acquire('getItemOffers')
    pacer.acquire('getMyFeesEstimateForASIN')
    assert clock.value == 0
    pacer.observe('getItemOffers', 200, {'X-Amzn-RateLimit-Limit': '.25'})
    pacer.acquire('getItemOffers')
    assert clock.value == 4
    reserved = pacer.not_before['getItemOffers']
    pacer.observe('getItemOffers', 200, {'x-amzn-ratelimit-limit': '100'})
    assert pacer.not_before['getItemOffers'] == reserved


def test_429_no_replay_and_sanitized_diagnostic(monkeypatch):
    clock = Clock()
    pacer = OperationPacer(monotonic=clock.now, sleep=clock.sleep)
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            raise HTTPError(request.full_url, 429, 'private message',
                            {'Retry-After': '12', 'x-amzn-RateLimit-Limit': '.2', 'secret': 'private'},
                            BytesIO(b'{"errors":[{"code":"QuotaExceeded","message":"private"}]}'))
    monkeypatch.setattr('app.amazon_pilot.build_opener', lambda *args: Opener())
    with pytest.raises(AmazonFailure) as caught:
        request_json(amazon_request('fake', '/products/pricing/v0/items/B000000001/offers'), pacer=pacer)
    assert len(calls) == 1
    diagnostic = failure_metadata(caught.value)
    assert diagnostic['amazon_error_codes'] == ['QuotaExceeded']
    assert diagnostic['pacing']['not_before_monotonic'] == 12
    assert 'private' not in str(diagnostic)
    pacer.acquire('getListingsRestrictions')
    assert clock.value == 0
    pacer.acquire('getItemOffers')
    assert clock.value == 12


def test_retry_after_date_and_invalid_headers():
    clock = Clock()
    pacer = OperationPacer(monotonic=clock.now, sleep=clock.sleep,
                           utcnow=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    pacer.acquire('getCatalogItem')
    pacer.observe('getCatalogItem', 200, {'Retry-After': 'Thu, 01 Jan 2026 00:00:10 GMT'})
    assert pacer.not_before['getCatalogItem'] == 10
    for value in ('nan', 'inf', '-1', 'bad'):
        pacer.observe('getCatalogItem', 429, {'Retry-After': value, 'x-amzn-ratelimit-limit': value})
    assert pacer.rates['getCatalogItem'] == 2
    assert pacer.not_before['getCatalogItem'] == 10


def test_configurable_rates():
    with pytest.raises(ValueError): OperationPacer({'getItemOffers': 0})
    assert OperationPacer({'getItemOffers': .1}).rates['getItemOffers'] == .1
