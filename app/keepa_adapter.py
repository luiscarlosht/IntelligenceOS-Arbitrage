"""Opt-in offline Keepa contract adapter. No HTTP client, credentials or live selector."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import math
import re
import time
from typing import Callable, Literal, Protocol
from types import MappingProxyType

from app.models import MarketplaceListing, RetailProduct
from app.provider_contracts import DemandSignal, Evidence, FeeQuote, SellerContext
from app.provider_runtime import (BudgetExceeded, Operation, Policy, Provider,
                                  ProviderFailure, Response, UsageLedger, execute_read)

ASIN = re.compile(r'[A-Z0-9]{10}')
US_MARKETPLACE = 'ATVPDKIKX0DER'
MAX_RESPONSE_BYTES = 512 * 1024
LIVE_CALLS_ENABLED = False  # Requires a separately authorized code change, not an env flag.


@dataclass(frozen=True)
class KeepaRequest:
    asin: str
    domain: int = 1
    update: int = -1
    history: int = 1
    days: int = 1

    def __post_init__(self):
        if (not isinstance(self.asin, str) or not ASIN.fullmatch(self.asin)
                or any(type(v) is not int for v in (self.domain, self.update, self.history, self.days))
                or (self.domain, self.update, self.history, self.days) != (1, -1, 1, 1)):
            raise ValueError('Only fixed basic US ASIN requests are supported')


@dataclass(frozen=True)
class KeepaResponse:
    status: int
    body: bytes


class KeepaTransport(Protocol):
    is_mock: bool

    def product(self, request: KeepaRequest, *, timeout_seconds: float,
                maximum_bytes: int) -> KeepaResponse: ...


@dataclass(frozen=True)
class KeepaRecord:
    asin: str
    fetched_at: datetime
    catalog: Evidence[MarketplaceListing] | None
    amazon_price: Evidence[Decimal] | None
    sales_rank: Evidence[int] | None
    bought_past_month: Evidence[DemandSignal] | None


def keepa_time(value) -> datetime | None:
    if type(value) is not int or value <= 0:
        return None
    try:
        return datetime.fromtimestamp((value + 21564000) * 60, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def history_point(series, now: datetime):
    if not isinstance(series, list) or not series or len(series) % 2:
        return None
    # Reject malformed, reordered or future evidence; never stamp it with fetch time.
    previous = None
    for minute, value in zip(series[::2], series[1::2]):
        stamp = keepa_time(minute)
        if stamp is None or stamp > now or (previous and stamp < previous) or type(value) is not int:
            return None
        previous = stamp
    return (previous, series[-1]) if series[-1] >= 0 else None


class KeepaAdapter:
    """Catalog/demand/fee/eligibility contracts through an explicit mock-only seam.

    Monthly reservations are durable and never refunded. Server token balance is
    conservative per instance: no speculative refill. All instances for one future
    account must share the ledger. No price is promoted to an assured sale price.
    """
    def __init__(self, transport: KeepaTransport, ledger: UsageLedger, *, enabled=False,
                 monthly_token_limit: int = 30, initial_tokens: int = 0,
                 policy: Policy = Policy(), minimum_interval_seconds: float = 1,
                 cache_ttl_seconds: float = 0, approved_retention_seconds: float = 0,
                 cache_permission_reference: str = '',
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 sleep: Callable[[float], None] = time.sleep):
        if not enabled or (getattr(transport, 'is_mock', False) is not True and not LIVE_CALLS_ENABLED):
            raise ValueError('Keepa is opt-in and restricted to mock transports; live calls disabled')
        if type(monthly_token_limit) is not int or monthly_token_limit <= 0 or type(initial_tokens) is not int or initial_tokens < 0:
            raise ValueError('Explicit positive token cap and nonnegative token balance required')
        for value in (minimum_interval_seconds, cache_ttl_seconds, approved_retention_seconds):
            if not math.isfinite(value) or value < 0:
                raise ValueError('Invalid pacing/cache policy')
        if not 0 < minimum_interval_seconds <= policy.max_delay_seconds:
            raise ValueError('Pacing must fit the bounded delay policy')
        if cache_ttl_seconds and (not cache_permission_reference.strip() or cache_ttl_seconds > approved_retention_seconds):
            raise ValueError('Cache requires explicit permission and approved retention limit')
        self.enabled = True
        self.transport, self.ledger, self.policy = transport, ledger, policy
        self.monthly_token_limit, self.tokens = monthly_token_limit, initial_tokens
        self.interval, self.ttl = minimum_interval_seconds, cache_ttl_seconds
        self.clock, self.sleep = clock, sleep
        self.cache: dict[str, tuple[datetime, KeepaRecord]] = {}
        with ledger.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS keepa_pacing (id INTEGER PRIMARY KEY CHECK(id=1), next_at REAL NOT NULL)')

    def _now(self):
        now = self.clock()
        if now.utcoffset() is None:
            raise ValueError('Aware Keepa clock required')
        return now

    def _pace(self):
        # Shared atomic pacing across processes using this ledger; waits are bounded.
        now = self._now().timestamp()
        with self.ledger.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT next_at FROM keepa_pacing WHERE id=1').fetchone()
            delay = max(0, (row[0] if row else now) - now)
            if delay > self.policy.max_delay_seconds:
                raise ProviderFailure('Keepa pacing deferred beyond bounded policy')
            db.execute('INSERT OR REPLACE INTO keepa_pacing VALUES (1, ?)', (now + delay + self.interval,))
        if delay:
            self.sleep(delay)

    def _read(self, request: KeepaRequest):
        adapter = self
        class Read:
            payload = None
            def read(self, *, timeout_seconds):
                if adapter.tokens < 1:
                    raise BudgetExceeded('Keepa token balance unavailable; no speculative refill')
                adapter._pace()
                adapter.tokens -= 1  # Ambiguous failures may bill; never refund.
                reply = adapter.transport.product(request, timeout_seconds=timeout_seconds,
                                                  maximum_bytes=MAX_RESPONSE_BYTES)
                if type(reply.status) is not int or not isinstance(reply.body, bytes) or len(reply.body) > MAX_RESPONSE_BYTES:
                    raise ValueError('Invalid/bounded Keepa response required')
                payload = json.loads(reply.body)
                if not isinstance(payload, dict): raise ValueError('Keepa object required')
                self.payload = payload
                balance = payload.get('tokensLeft')
                if type(balance) is int:
                    adapter.tokens = min(adapter.tokens, max(0, balance))
                consumed = payload.get('tokensConsumed')
                if type(consumed) is int and consumed > 1:
                    adapter.tokens = 0
                    raise ValueError('Keepa cost exceeds fixed basic request reservation')
                refill = payload.get('refillIn')
                retry = refill / 1000 if reply.status == 429 and type(refill) is int else None
                return Response(reply.status, retry)
        reader = Read()
        execute_read(reader, self.ledger, provider=Provider.KEEPA, operation=Operation.CATALOG,
                     units_per_attempt=1, monthly_limit=self.monthly_token_limit,
                     policy=self.policy, sleep=self.sleep, clock=self._now)
        return reader.payload

    def lookup(self, asin: str) -> KeepaRecord:
        if not self.enabled:
            raise ProviderFailure('Keepa adapter closed')
        request = KeepaRequest(asin)
        now = self._now()
        # Drop expired normalized entries; raw vendor payloads are never cached.
        self.cache = {key: entry for key, entry in self.cache.items()
                      if 0 <= (now - entry[0]).total_seconds() < self.ttl}
        if asin in self.cache:
            return self.cache[asin][1]
        try:
            payload = self._read(request)
            if payload.get('error'):
                raise ValueError('Partial provider error')
            products = payload.get('products')
            if not isinstance(products, list) or len(products) > 1:
                raise ValueError('Ambiguous or invalid product response')
            now = self._now()
            record = self._parse(asin, products[0] if products else None, now)
        except (ProviderFailure, BudgetExceeded):
            raise
        except Exception:
            raise ProviderFailure('Invalid Keepa evidence response') from None
        if self.ttl:
            if len(self.cache) >= 64:
                self.cache.pop(next(iter(self.cache)))
            self.cache[asin] = (now, record)
        return record

    def _parse(self, asin: str, row, now: datetime) -> KeepaRecord:
        if row is None:
            return KeepaRecord(asin, now, None, None, None, None)
        if (not isinstance(row, dict) or row.get('asin') != asin or type(row.get('domainId')) is not int or row.get('domainId') != 1
                or type(row.get('productType')) is not int):
            raise ValueError('Wrong product identity/domain/type')
        mode = 'KEEPA MOCK contract' if self.transport.is_mock else 'Keepa API'
        provenance = f'{mode}; domain=1; asin={asin}; fetched_at={now.isoformat()}'
        def evidence(value, stamp, field):
            return Evidence(value, stamp, provenance + '; field=' + field, is_mock=self.transport.is_mock)
        catalog = price = rank = demand = None
        updated = keepa_time(row.get('lastUpdate'))
        if row['productType'] == 0 and updated and updated <= now:
            if any(not isinstance(row.get(field) or '', str) for field in ('manufacturer', 'model')):
                raise ValueError('Invalid catalog text field')
            listing = MarketplaceListing(asin, '', row.get('manufacturer') or '', row.get('model') or '',
                None, '', None, None, costs=MappingProxyType({}), retrieved_at=updated, provenance=provenance,
                monthly_sales=None, offer_count=None, is_mock=self.transport.is_mock)
            catalog = evidence(listing, updated, 'lastUpdate')
            histories = row.get('csv')
            if isinstance(histories, list):
                for index, field in ((0, 'csv.AMAZON'), (3, 'csv.SALES')):
                    point = history_point(histories[index], now) if len(histories) > index else None
                    if point:
                        stamp, value = point
                        if index == 0 and value > 0: price = evidence(Decimal(value) / 100, stamp, field)
                        elif index == 3 and value > 0: rank = evidence(value, stamp, field)
            sold = row.get('monthlySold')
            sold_at = keepa_time(row.get('lastSoldUpdate'))
            if type(sold) is int and sold >= 0 and sold_at and sold_at <= now:
                demand = evidence(DemandSignal(asin, US_MARKETPLACE, sold,
                    'bought_past_month_lower_bound'), sold_at, 'monthlySold/lastSoldUpdate')
        return KeepaRecord(asin, now, catalog, price, rank, demand)

    def candidates(self, product: RetailProduct) -> tuple[Evidence[MarketplaceListing], ...]:
        # No code searches or identity/package inference. Explicit ASIN hint required.
        if not ASIN.fullmatch(product.asin_hint): return ()
        record = self.lookup(product.asin_hint)
        return (record.catalog,) if record.catalog else ()

    def demand(self, asin: str, marketplace_id: str) -> Evidence[DemandSignal]:
        if marketplace_id != US_MARKETPLACE: raise ValueError('US marketplace only')
        result = self.lookup(asin)
        return result.bought_past_month or Evidence(None, result.fetched_at,
            'KEEPA MOCK: demand unavailable; retrieval time only; no observation', is_mock=self.transport.is_mock)

    def eligibility(self, asin: str, context: SellerContext) -> Evidence[bool]:
        KeepaRequest(asin)
        return Evidence(None, self._now(), 'KEEPA MOCK: seller eligibility unavailable; no observation', is_mock=self.transport.is_mock)

    def quote(self, asin: str, context: SellerContext, sale_price: Decimal,
              fulfillment: Literal['FBA', 'FBM']) -> Evidence[FeeQuote]:
        KeepaRequest(asin)
        return Evidence(None, self._now(), 'KEEPA MOCK: seller-specific fees unavailable; no observation', is_mock=self.transport.is_mock)

    def clear_cache(self):
        self.cache.clear()

    def close(self):
        self.clear_cache()
        self.enabled = False
