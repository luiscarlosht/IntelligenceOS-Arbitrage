"""Injected read-only transport policy and redacted usage reservations.

No network implementation is supplied. A future adapter must enforce the passed
timeout at socket/response level and verified TLS, and bound response sizes.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import math
from pathlib import Path
import sqlite3
import time
from typing import Callable, Protocol


class Provider(StrEnum):
    SP_API = 'sp_api'
    KEEPA = 'keepa'
    RETAILER = 'authorized_retailer'


class Operation(StrEnum):
    CATALOG = 'catalog'
    FEES = 'fees'
    ELIGIBILITY = 'eligibility'
    DEMAND = 'demand'
    FEED = 'feed'


@dataclass(frozen=True)
class Response:
    status: int
    retry_after_seconds: float | None = None


class ReadTransport(Protocol):
    def read(self, *, timeout_seconds: float) -> Response: ...


@dataclass(frozen=True)
class Policy:
    timeout_seconds: float = 10
    max_attempts: int = 3
    base_delay_seconds: float = 1
    max_delay_seconds: float = 30

    def __post_init__(self) -> None:
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 5:
            raise ValueError('Attempts must be between one and five')
        for number in (self.timeout_seconds, self.base_delay_seconds, self.max_delay_seconds):
            if not math.isfinite(number) or number <= 0:
                raise ValueError('Policy durations must be positive and finite')
        if self.timeout_seconds > 60 or self.max_delay_seconds > 60:
            raise ValueError('Timeout and delay cannot exceed 60 seconds')


class BudgetExceeded(RuntimeError):
    pass


class ProviderFailure(RuntimeError):
    pass


class UsageLedger:
    """Reserve worst-case request/token units before every attempt, including retries.

    Reservations are intentionally never refunded: ambiguous failures can bill.
    This is a local cap, not vendor billing or a cross-application quota tracker.
    """
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS provider_usage (
                id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL,
                provider TEXT NOT NULL, operation TEXT NOT NULL,
                units INTEGER NOT NULL, outcome TEXT NOT NULL)''')

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def reserve(self, provider: Provider, operation: Operation, units: int,
                monthly_limit: int, now: datetime) -> int:
        if not isinstance(provider, Provider) or not isinstance(operation, Operation):
            raise ValueError('Only fixed redacted provider/operation labels allowed')
        if any(type(v) is not int or v <= 0 for v in (units, monthly_limit)) or now.utcoffset() is None:
            raise ValueError('Positive explicit usage budget and aware clock required')
        stamp = now.astimezone(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            total = db.execute('SELECT COALESCE(SUM(units),0) FROM provider_usage WHERE provider=? AND substr(observed_at,1,7)=?',
                               (provider.value, stamp[:7])).fetchone()[0]
            if total + units > monthly_limit:
                raise BudgetExceeded('Provider monthly reservation cap reached')
            return db.execute('INSERT INTO provider_usage(observed_at,provider,operation,units,outcome) VALUES (?,?,?,?,?)',
                              (stamp, provider.value, operation.value, units, 'reserved')).lastrowid

    def finish(self, reservation: int, outcome: str) -> None:
        if outcome not in ('success', 'timeout', 'throttled', 'server_error', 'rejected', 'adapter_error'):
            raise ValueError('Invalid redacted outcome')
        with self.connect() as db:
            db.execute('UPDATE provider_usage SET outcome=? WHERE id=?', (outcome, reservation))


def execute_read(transport: ReadTransport, ledger: UsageLedger, *, provider: Provider,
                 operation: Operation, units_per_attempt: int, monthly_limit: int,
                 policy: Policy = Policy(), sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> Response:
    """Retry only read-only transient failures; abort rather than shorten Retry-After."""
    for attempt in range(policy.max_attempts):
        reservation = ledger.reserve(provider, operation, units_per_attempt, monthly_limit, clock())
        retry_after = None
        try:
            response = transport.read(timeout_seconds=policy.timeout_seconds)
        except TimeoutError:
            ledger.finish(reservation, 'timeout')
        except Exception:
            ledger.finish(reservation, 'adapter_error')
            raise ProviderFailure('Provider adapter failed') from None
        else:
            if 200 <= response.status < 300:
                ledger.finish(reservation, 'success')
                return response
            retryable = response.status in (429, 500, 502, 503, 504)
            ledger.finish(reservation, 'throttled' if response.status == 429 else
                          'server_error' if retryable else 'rejected')
            if not retryable:
                raise ProviderFailure('Non-retryable provider response')
            retry_after = response.retry_after_seconds
        if attempt + 1 == policy.max_attempts:
            break
        delay = min(policy.base_delay_seconds * 2 ** attempt, policy.max_delay_seconds)
        if retry_after is not None:
            if not math.isfinite(retry_after) or retry_after < 0 or retry_after > policy.max_delay_seconds:
                raise ProviderFailure('Retry deferred beyond bounded policy')
            delay = max(delay, retry_after)
        sleep(delay)
    raise ProviderFailure('Provider attempt limit reached')
