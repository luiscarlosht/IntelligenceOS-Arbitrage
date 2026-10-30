"""Sequential, operation-scoped SP-API pacing; no retries or credential storage."""
import math
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from app.amazon_diagnostics import AmazonFailure

DEFAULT_RATES = {'getCatalogItem': 2., 'searchCatalogItems': 2.,
                 'getItemOffers': .5, 'getMyFeesEstimateForASIN': 1.,
                 'getListingsRestrictions': 5.}


def operation_for(request):
    parsed = urlsplit(request.full_url)
    if parsed.hostname != 'sellingpartnerapi-na.amazon.com':
        return None
    path = parsed.path
    if path.startswith('/catalog/2022-04-01/items'):
        return 'getCatalogItem' if path.startswith('/catalog/2022-04-01/items/') else 'searchCatalogItems'
    if path.startswith('/products/pricing/v0/items/') and path.endswith('/offers'):
        return 'getItemOffers'
    if path.startswith('/products/fees/v0/items/') and path.endswith('/feesEstimate'):
        return 'getMyFeesEstimateForASIN'
    if path == '/listings/2021-08-01/restrictions':
        return 'getListingsRestrictions'
    return None


def positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 and math.isfinite(1/number) else None
    except (TypeError, ValueError, OverflowError):
        return None


class OperationPacer:
    def __init__(self, rates=None, *, monotonic=time.monotonic, sleep=time.sleep,
                 utcnow=lambda: datetime.now(timezone.utc)):
        self.rates = dict(DEFAULT_RATES)
        for name in self.rates:
            value = (rates or {}).get(name, os.environ.get('AMAZON_RATE_'+name.upper(), self.rates[name]))
            rate = positive(value)
            if rate is None:
                raise ValueError('Invalid Amazon operation rate: '+name)
            self.rates[name] = rate
        self.monotonic, self.sleep, self.utcnow = monotonic, sleep, utcnow
        self.not_before = {}
        self.last = {}

    def acquire(self, name, deadline=None):
        if name is None:
            return
        if deadline is not None and max(self.monotonic(), self.not_before.get(name, 0)) >= deadline:
            error = AmazonFailure('Operation deferred; no request', reason='pacing_deferred')
            error.pacing = self.observe(name, None, {})
            raise error
        if self.monotonic() < self.not_before.get(name, 0):
            self.sleep(self.not_before[name]-self.monotonic())
        now = self.monotonic()
        self.last[name] = now
        self.not_before[name] = max(self.not_before.get(name, 0), now+1/self.rates[name])

    def observe(self, name, status, headers):
        if name is None:
            return {}
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        rate = positive(headers.get('x-amzn-ratelimit-limit'))
        if rate:
            self.rates[name] = rate
            self.not_before[name] = max(self.not_before.get(name, 0), self.last.get(name, self.monotonic())+1/rate)
        delay = None
        raw = headers.get('retry-after')
        try:
            delay = float(raw)
        except (TypeError, ValueError, OverflowError):
            try:
                date = parsedate_to_datetime(raw)
                delay = (date-self.utcnow()).total_seconds()
            except (TypeError, ValueError, OverflowError):
                pass
        if delay is not None and (not math.isfinite(delay) or delay < 0):
            delay = None
        if status == 429 or delay is not None:
            self.not_before[name] = max(self.not_before.get(name, 0), self.monotonic()+(delay if delay is not None else 1/self.rates[name]))
        try:
            utc = datetime.fromtimestamp(self.utcnow().timestamp()+max(0,self.not_before.get(name,0)-self.monotonic()), timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            utc = None
        return dict(operation=name, rate_limit=self.rates[name], retry_after_seconds=delay,
                    not_before_monotonic=self.not_before.get(name),
                    not_before_utc=utc)

    def call(self, request, transport, *, deadline=None):
        name = operation_for(request)
        self.acquire(name, deadline)
        try:
            document = transport(request)
        except AmazonFailure as error:
            error.pacing = self.observe(name, error.http_status, getattr(error, 'rate_headers', {}))
            raise
        metadata = self.observe(name, getattr(document, 'http_status', 200), getattr(document, 'rate_headers', {}))
        if hasattr(document, '__dict__'):
            document.pacing = metadata
        return document
