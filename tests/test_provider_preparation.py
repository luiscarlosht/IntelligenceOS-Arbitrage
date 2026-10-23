from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.config import Config
from app.connectors import CsvConnector
from app.marketplace import MockAmazonProvider, match_listings
from app.mock_evidence import MockEvidenceProvider
from app.provider_contracts import DemandSignal, Evidence, FeeQuote, SellerContext
from app.provider_runtime import (BudgetExceeded, Operation, Policy, Provider,
                                  ProviderFailure, Response, UsageLedger, execute_read)

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def test_mock_contracts_preserve_unknown_and_context(tmp_path):
    config = Config.from_env()
    product = next(CsvConnector(config.amazon_fixture.parent / 'discovery.csv').products())
    listing = MockAmazonProvider(config.amazon_fixture).listings[0]
    seller = SellerContext('fictional-seller', 'US')
    fees = FeeQuote(listing.asin, seller, Decimal('30'), 'FBA', None, Decimal('4'))
    provider = MockEvidenceProvider(NOW, (replace(listing, is_mock=False),), (fees,),
                                    {(listing.asin, seller): False},
                                    (DemandSignal(listing.asin, 'US', 100, 'bought_past_month_lower_bound'),))
    candidates = provider.candidates(product)
    assert len(candidates) == 1 and candidates[0].is_mock
    assert candidates[0].value.is_mock and candidates[0].value.seller_eligible is None
    assert match_listings(product, (candidates[0].value,)).exact
    assert provider.eligibility(listing.asin, seller).value is False
    assert provider.eligibility(listing.asin, replace(seller, seller_id='other')).value is None
    assert provider.eligibility(listing.asin, replace(seller, condition='used_good')).value is None
    assert provider.quote(listing.asin, seller, Decimal('30'), 'FBA').value.referral_fee is None
    assert provider.quote(listing.asin, seller, Decimal('31'), 'FBA').value is None
    assert provider.quote(listing.asin, seller, Decimal('30'), 'FBM').value is None
    assert provider.demand(listing.asin, 'US').value.monthly_units_lower_bound == 100
    assert provider.demand(listing.asin, 'CA').value is None
    assert not candidates[0].fresh(NOW + timedelta(days=2))
    assert not candidates[0].fresh(NOW - timedelta(seconds=1))
    assert candidates[0].fresh(NOW)
    assert not match_listings(replace(product, package_quantity=2), (candidates[0].value,)).exact
    assert not match_listings(product, (candidates[0].value, candidates[0].value)).exact


def test_evidence_rejects_bad_inputs():
    with pytest.raises(ValueError):
        Evidence(None, NOW.replace(tzinfo=None), 'MOCK')
    with pytest.raises(ValueError):
        Evidence(None, NOW, '')
    with pytest.raises(ValueError):
        DemandSignal('MOCK', 'US', 30, 'unknown')
    with pytest.raises(ValueError):
        FeeQuote('MOCK', SellerContext('seller', 'US'), Decimal('30'), 'FBA', Decimal('NaN'), None)


class ScriptedTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.timeouts = []

    def read(self, *, timeout_seconds):
        self.timeouts.append(timeout_seconds)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def call(tmp_path, responses, **kwargs):
    transport = ScriptedTransport(responses)
    ledger = UsageLedger(tmp_path / 'usage.sqlite3')
    delays = []
    result = execute_read(transport, ledger, provider=Provider.KEEPA, operation=Operation.DEMAND,
                          units_per_attempt=2, monthly_limit=kwargs.pop('monthly_limit', 20),
                          clock=lambda: NOW, sleep=delays.append, **kwargs)
    return result, transport, ledger, delays


def test_timeout_throttle_retry_and_persistent_usage(tmp_path):
    result, transport, ledger, delays = call(tmp_path, [TimeoutError('secret'), Response(429, 4), Response(200)])
    assert result.status == 200 and transport.timeouts == [10, 10, 10]
    assert delays == [1, 4]
    with ledger.connect() as db:
        assert db.execute('SELECT units,outcome FROM provider_usage').fetchall() == [(2, 'timeout'), (2, 'throttled'), (2, 'success')]
        assert 'secret' not in str(db.execute('SELECT * FROM provider_usage').fetchall())
    reopened = UsageLedger(ledger.path)
    with pytest.raises(BudgetExceeded):
        reopened.reserve(Provider.KEEPA, Operation.DEMAND, 1, 6, NOW)
    assert reopened.reserve(Provider.KEEPA, Operation.DEMAND, 1, 6, NOW + timedelta(days=31))


@pytest.mark.parametrize('status', [400, 401, 402, 403, 404, 405, 501])
def test_permanent_errors_not_retried(tmp_path, status):
    transport = ScriptedTransport([Response(status), Response(200)])
    with pytest.raises(ProviderFailure):
        execute_read(transport, UsageLedger(tmp_path / 'u.db'), provider=Provider.SP_API,
                     operation=Operation.FEES, units_per_attempt=1, monthly_limit=3, sleep=lambda _: pytest.fail('must not sleep'))
    assert len(transport.timeouts) == 1


@pytest.mark.parametrize('retry_after', [61, float('nan'), -1])
def test_retry_after_never_shortened(tmp_path, retry_after):
    with pytest.raises(ProviderFailure, match='deferred'):
        call(tmp_path, [Response(429, retry_after)])


def test_attempt_and_budget_bounds(tmp_path):
    with pytest.raises(ProviderFailure, match='attempt limit'):
        call(tmp_path, [Response(503)] * 3)
    with pytest.raises(BudgetExceeded):
        call(tmp_path / 'cap', [Response(500)] * 3, monthly_limit=2)
    with pytest.raises(ValueError):
        Policy(max_attempts=6)
    with pytest.raises(ValueError):
        Policy(timeout_seconds=float('inf'))
    with pytest.raises(ValueError):
        UsageLedger(tmp_path / 'bad.db').reserve('secret', Operation.FEES, 1, 10, NOW)


def test_unknown_adapter_errors_redacted(tmp_path):
    with pytest.raises(ProviderFailure) as failure:
        call(tmp_path, [RuntimeError('credential')])
    assert 'credential' not in str(failure.value) and failure.value.__suppress_context__


def test_live_provider_selection_remains_disabled(monkeypatch):
    monkeypatch.setenv('AMAZON_PROVIDER', 'sp_api')
    with pytest.raises(ValueError, match='mock'):
        Config.from_env()


def test_concurrent_reservations_cannot_overspend(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path = tmp_path / 'shared.db'
    UsageLedger(path)

    def reserve(_):
        try:
            UsageLedger(path).reserve(Provider.KEEPA, Operation.DEMAND, 1, 3, NOW)
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=4) as workers:
        assert sum(workers.map(reserve, range(10))) == 3
