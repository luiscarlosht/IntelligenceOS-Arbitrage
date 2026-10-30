"""Sequential, operation-scoped SP-API pacing; no retries or credential storage."""
import math
import json
import sqlite3
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
                 utcnow=lambda: datetime.now(timezone.utc), headroom=None, state_path=None):
        self.headroom = positive(headroom if headroom is not None else os.environ.get('AMAZON_RATE_HEADROOM', '.5'))
        if self.headroom is None or self.headroom >= 1:
            raise ValueError('Rate headroom must be between zero and one')
        self.state_path = state_path
        self.rates = dict(DEFAULT_RATES)
        for name in self.rates:
            value = (rates or {}).get(name, os.environ.get('AMAZON_RATE_'+name.upper(), self.rates[name]))
            rate = positive(value)
            if rate is None:
                raise ValueError('Invalid Amazon operation rate: '+name)
            self.rates[name] = min(self.rates[name], rate)
        self.monotonic, self.sleep, self.utcnow = monotonic, sleep, utcnow
        self.not_before = {}
        self.last = {}
        if state_path is not None:
            with sqlite3.connect(state_path) as db:
                db.execute('CREATE TABLE IF NOT EXISTS amazon_cooldowns (operation TEXT PRIMARY KEY, not_before_utc TEXT NOT NULL, diagnostics TEXT NOT NULL)')
                for name, utc, diagnostics in db.execute('SELECT operation,not_before_utc,diagnostics FROM amazon_cooldowns'):
                    self.restore_cooldown(name, utc)
                    saved_rate = positive(json.loads(diagnostics).get('rate_limit'))
                    if saved_rate and name in self.rates:
                        self.rates[name] = min(self.rates[name], saved_rate)

    def restore_cooldown(self, name, utc):
        delay = max(0, (datetime.fromisoformat(utc)-self.utcnow()).total_seconds())
        self.not_before[name] = max(self.not_before.get(name, 0), self.monotonic()+delay)


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
        self.not_before[name] = max(self.not_before.get(name, 0), now+1/(self.rates[name]*self.headroom))

    def observe(self, name, status, headers):
        if name is None:
            return {}
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        rate = positive(headers.get('x-amzn-ratelimit-limit'))
        if rate:
            self.rates[name] = min(self.rates[name], rate)
            self.not_before[name] = max(self.not_before.get(name, 0), self.last.get(name, self.monotonic())+1/(self.rates[name]*self.headroom))
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
            self.not_before[name] = max(self.not_before.get(name, 0), self.monotonic()+(delay if delay is not None else max(60, 1/(self.rates[name]*self.headroom))))
        try:
            utc = datetime.fromtimestamp(self.utcnow().timestamp()+max(0,self.not_before.get(name,0)-self.monotonic()), timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            utc = None
        metadata = dict(operation=name, rate_limit=self.rates[name], reported_rate_limit=rate, headroom=self.headroom, http_status=status, retry_after_seconds=delay,
                    not_before_monotonic=self.not_before.get(name),
                    not_before_utc=utc)
        if self.state_path is not None and utc:
            with sqlite3.connect(self.state_path) as db:
                db.execute("INSERT INTO amazon_cooldowns VALUES (?,?,?) ON CONFLICT(operation) DO UPDATE SET not_before_utc=max(not_before_utc,excluded.not_before_utc), diagnostics=CASE WHEN ?=429 THEN excluded.diagnostics ELSE diagnostics END", (name, utc, json.dumps(metadata), status))
        return metadata

    def call(self, request, transport, *, deadline=None):
        name = operation_for(request)
        self.acquire(name, deadline)
        try:
            document = transport(request)
        except AmazonFailure as error:
            error.pacing = self.observe(name, error.http_status, getattr(error, 'rate_headers', {}))
            if self.state_path is not None and name and error.http_status == 429:
                from app.amazon_diagnostics import failure_metadata
                diagnostics = dict(error.pacing, failure=failure_metadata(error))
                with sqlite3.connect(self.state_path) as db:
                    db.execute('UPDATE amazon_cooldowns SET diagnostics=? WHERE operation=?',
                               (json.dumps(diagnostics), name))
            raise
        metadata = self.observe(name, getattr(document, 'http_status', 200), getattr(document, 'rate_headers', {}))
        if hasattr(document, '__dict__'):
            document.pacing = metadata
        return document
