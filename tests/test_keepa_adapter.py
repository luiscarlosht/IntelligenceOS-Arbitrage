"""Fictional offline Keepa contracts. Never use credentials or real HTTP."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from app.config import Config
from app.keepa_adapter import (KeepaAdapter, KeepaRequest, KeepaResponse,
    MAX_RESPONSE_BYTES, US_MARKETPLACE)
from app.keepa_http import KeepaHttpTransport
from app.models import RetailProduct
from app.provider_contracts import SellerContext
from app.provider_runtime import BudgetExceeded, Policy, ProviderFailure, UsageLedger

NOW = datetime(2026,10,23,12,tzinfo=timezone.utc)
ASIN = 'B000000001'


def minute(stamp): return int(stamp.timestamp()/60) - 21564000


def product(**changes):
    row = {'asin': ASIN, 'domainId': 1, 'productType': 0,
        'lastUpdate': minute(NOW-timedelta(minutes=5)),
        'manufacturer':'FICTIONAL', 'model':'TEST', 'packageQuantity':1,
        'csv':[[minute(NOW-timedelta(minutes=10)),2500],None,None,[minute(NOW-timedelta(minutes=20)),9000]],
        'monthlySold':100, 'lastSoldUpdate':minute(NOW-timedelta(hours=2))}
    row.update(changes);return row


def response(rows=None, status=200, **changes):
    payload={'products': [product()] if rows is None else rows,'tokensLeft':29,'tokensConsumed':1}
    payload.update(changes)
    return KeepaResponse(status,json.dumps(payload).encode())


class Transport:
    is_mock = True
    def __init__(self,*replies): self.replies=list(replies or (response(),));self.calls=[]
    def product(self,request,**kwargs):
        self.calls.append((request,kwargs))
        result=self.replies.pop(0)
        if isinstance(result,Exception):raise result
        return result


def adapter(tmp_path, transport=None, **kwargs):
    return KeepaAdapter(transport or Transport(),UsageLedger(tmp_path/'usage.db'),
        enabled=True,initial_tokens=30,clock=lambda:NOW,sleep=lambda s:None,**kwargs)


def test_off_by_default_and_no_live_key_loading(tmp_path,monkeypatch):
    with pytest.raises(ValueError):KeepaAdapter(Transport(),UsageLedger(tmp_path/'usage.db'))
    loaded=[]
    live=KeepaHttpTransport(lambda:loaded.append(True))
    with pytest.raises(ValueError):adapter(tmp_path,live)
    with pytest.raises(ProviderFailure):live.product(KeepaRequest(ASIN),timeout_seconds=10,maximum_bytes=1024)
    assert loaded==[]
    monkeypatch.setenv('AMAZON_PROVIDER','keepa')
    with pytest.raises(ValueError):Config.from_env()


def test_contract_timestamps_provenance_unknowns_and_rank(tmp_path):
    a=adapter(tmp_path);record=a.lookup(ASIN)
    assert record.amazon_price.value==Decimal('25')
    assert record.amazon_price.observed_at==NOW-timedelta(minutes=10)
    assert record.sales_rank.value==9000
    assert record.bought_past_month.value.monthly_units_lower_bound==100
    assert record.bought_past_month.value.basis=='bought_past_month_lower_bound'
    assert record.bought_past_month.observed_at==NOW-timedelta(hours=2)
    listing=record.catalog.value
    assert listing.monthly_sales is None and listing.sale_price is None
    assert listing.seller_eligible is None and listing.package_quantity is None
    assert listing.offer_count is None and listing.costs=={} and listing.variation==''
    assert record.catalog.is_mock and 'KEEPA MOCK' in record.catalog.provenance
    context=SellerContext('seller',US_MARKETPLACE)
    assert a.eligibility(ASIN,context).value is None
    assert a.quote(ASIN,context,Decimal('25'),'FBA').value is None
    assert len(a.transport.calls)==1  # Unknown fees/eligibility do not issue requests.


@pytest.mark.parametrize('changes',[
    {'monthlySold':None},{'monthlySold':-1},{'monthlySold':True},
    {'lastSoldUpdate':None},{'lastSoldUpdate':minute(NOW+timedelta(minutes=1))}])
def test_rank_never_becomes_monthly_sales(tmp_path,changes):
    record=adapter(tmp_path,Transport(response([product(**changes)]))).lookup(ASIN)
    assert record.bought_past_month is None
    assert record.sales_rank.value==9000
    assert record.catalog.value.monthly_sales is None


@pytest.mark.parametrize('changes',[{'productType':5},{'productType':4},
    {'lastUpdate':None},{'lastUpdate':minute(NOW+timedelta(minutes=1))}])
def test_parent_missing_future_catalog_blocked(tmp_path,changes):
    record=adapter(tmp_path,Transport(response([product(**changes)]))).lookup(ASIN)
    assert record.catalog is None and record.amazon_price is None


@pytest.mark.parametrize('series',[[1],None,[],[minute(NOW),-1],
    [minute(NOW),False],[minute(NOW+timedelta(minutes=1)),500],
    [minute(NOW),500,minute(NOW-timedelta(hours=1)),400]])
def test_bad_price_history_not_zero_or_refreshed(tmp_path,series):
    row=product(csv=[series])
    assert adapter(tmp_path,Transport(response([row]))).lookup(ASIN).amazon_price is None


def test_cache_permission_expiry_staleness_and_revocation(tmp_path):
    with pytest.raises(ValueError):adapter(tmp_path,cache_ttl_seconds=60)
    with pytest.raises(ValueError):adapter(tmp_path,cache_ttl_seconds=61,approved_retention_seconds=60,cache_permission_reference='MOCK terms')
    transport=Transport(response(),response())
    a=adapter(tmp_path,transport,cache_ttl_seconds=60,approved_retention_seconds=60,cache_permission_reference='MOCK terms')
    first=a.lookup(ASIN);a.clock=lambda:NOW+timedelta(seconds=30)
    assert a.lookup(ASIN) is first and len(transport.calls)==1
    assert first.amazon_price.observed_at==NOW-timedelta(minutes=10)
    assert not first.amazon_price.fresh(NOW+timedelta(days=2))
    a.clock=lambda:NOW+timedelta(seconds=61)
    second=a.lookup(ASIN)
    assert second.fetched_at>first.fetched_at and second.amazon_price.observed_at==first.amazon_price.observed_at
    a.close()
    assert not a.cache
    with pytest.raises(ProviderFailure):a.lookup(ASIN)
    assert len(transport.calls)==2


def test_retries_reserve_each_attempt_and_fixed_request(tmp_path):
    transport=Transport(TimeoutError('secret'),response(status=503),response())
    a=adapter(tmp_path,transport)
    record=a.lookup(ASIN)
    assert record.catalog
    with a.ledger.connect() as db:
        assert db.execute('SELECT SUM(units) FROM provider_usage').fetchone()[0]==3
    assert len(transport.calls)==3
    for request,kwargs in transport.calls:
        assert request.update==-1 and request.history==1 and request.days==1 and request.domain==1
        assert kwargs=={'timeout_seconds':10,'maximum_bytes':MAX_RESPONSE_BYTES}


@pytest.mark.parametrize('status',[400,402,405])
def test_no_retry_access_payment_bad_request(tmp_path,status):
    transport=Transport(response(status=status));a=adapter(tmp_path,transport)
    with pytest.raises(ProviderFailure):a.lookup(ASIN)
    assert len(transport.calls)==1


def test_monthly_budget_pacing_and_no_optimistic_refill(tmp_path):
    a=adapter(tmp_path,Transport(response(),response()),monthly_token_limit=1)
    a.lookup(ASIN)
    with pytest.raises(BudgetExceeded):a.lookup(ASIN)
    assert len(a.transport.calls)==1
    other=adapter(tmp_path,Transport(response()),policy=Policy(max_delay_seconds=.5),minimum_interval_seconds=.5)
    with pytest.raises(ProviderFailure):other.lookup(ASIN)
    assert len(other.transport.calls)==0  # Shared pacing blocks a second process.
    fresh=tmp_path/'other';fresh.mkdir()
    b=adapter(fresh,Transport(response(status=429,tokensLeft=-3,refillIn=61000)))
    with pytest.raises(ProviderFailure):b.lookup(ASIN)
    assert b.tokens==0 and len(b.transport.calls)==1


@pytest.mark.parametrize('reply',[
    KeepaResponse(200,b'x'*(MAX_RESPONSE_BYTES+1)),KeepaResponse(200,b'not json'),
    response([product(asin='B000000002')]),response([product(domainId=3)]),
    response([product(),product()]),response(error={'message':'SECRET: do not log'}),
    response(tokensConsumed=12)])
def test_malformed_ambiguous_overbudget_responses_redacted(tmp_path,reply):
    a=adapter(tmp_path,Transport(reply))
    with pytest.raises(ProviderFailure) as error:a.lookup(ASIN)
    assert 'SECRET' not in str(error.value)
    assert 'do not log' not in str(error.value)


def test_no_upc_lookup_or_price_promotion(tmp_path):
    a=adapter(tmp_path)
    source=RetailProduct('MOCK','FICTIONAL','https://example.org','00036000291452',
        'FICTIONAL','TEST',1,Decimal('8'),'in_stock',NOW,'MOCK source')
    assert a.candidates(source)==() and not a.transport.calls
    rows=a.candidates(replace(source,asin_hint=ASIN))
    assert len(rows)==1 and rows[0].value.gtin==''
    assert rows[0].value.sale_price is None and rows[0].value.package_quantity is None


def test_absent_demand_and_misses_remain_unknown(tmp_path):
    a=adapter(tmp_path,Transport(response([])))
    signal=a.demand(ASIN,US_MARKETPLACE)
    assert signal.value is None and 'no observation' in signal.provenance
    with pytest.raises(ValueError):a.demand(ASIN,'OTHER')
    with pytest.raises(ValueError):a.lookup('invalid')


def test_dormant_http_gzip_tls_and_redacted_errors(monkeypatch):
    import gzip,ssl
    from app import keepa_adapter, keepa_http
    calls=[]
    class Reply:
        code=200
        headers={'Content-Encoding':'gzip'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):return gzip.compress(b'{"products":[]}')
    class Opener:
        def open(self,req,timeout):
            calls.append((req,timeout));return Reply()
    handlers=[]
    def build(*args):handlers.extend(args);return Opener()
    # Fake the entire opener before temporarily exercising the otherwise dead branch.
    monkeypatch.setattr(keepa_http,'build_opener',build)
    monkeypatch.setattr(keepa_adapter,'LIVE_CALLS_ENABLED',True)
    transport=KeepaHttpTransport(lambda:'FICTIONAL-TEST-KEY')
    reply=transport.product(KeepaRequest(ASIN),timeout_seconds=10,maximum_bytes=1024)
    assert reply.body==b'{"products":[]}' and calls[0][1]==10
    assert calls[0][0].get_header('Accept-encoding')=='gzip'
    tls=next(h for h in handlers if isinstance(h,keepa_http.HTTPSHandler))
    assert tls._context.check_hostname and tls._context.verify_mode==ssl.CERT_REQUIRED
    assert any(isinstance(h,keepa_http.NoRedirect) for h in handlers)
    def broken(*args):raise RuntimeError('https://api.keepa.com/?key=FICTIONAL-TEST-KEY')
    monkeypatch.setattr(keepa_http,'build_opener',broken)
    with pytest.raises(ProviderFailure) as error:transport.product(KeepaRequest(ASIN),timeout_seconds=10,maximum_bytes=1024)
    assert 'FICTIONAL-TEST-KEY' not in str(error.value)


def test_dormant_http_decompression_bound(monkeypatch):
    import gzip
    from app import keepa_adapter,keepa_http
    class Reply:
        code=200;headers={'Content-Encoding':'gzip'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):return gzip.compress(b'x'*10000)
    monkeypatch.setattr(keepa_http,'build_opener',lambda *args:SimpleNamespace(open=lambda *a,**kw:Reply()))
    monkeypatch.setattr(keepa_adapter,'LIVE_CALLS_ENABLED',True)
    with pytest.raises(ProviderFailure):KeepaHttpTransport(lambda:'FICTIONAL').product(KeepaRequest(ASIN),timeout_seconds=10,maximum_bytes=1024)


def test_cache_is_bounded_and_clock_rollback_expires_entries(tmp_path):
    class Many(Transport):
        def product(self,request,**kwargs):return response([product(asin=request.asin)],tokensLeft=1000)
    a=adapter(tmp_path,Many(),monthly_token_limit=1000,cache_ttl_seconds=3600,
        approved_retention_seconds=3600,cache_permission_reference='MOCK terms')
    a.tokens=1000
    for i in range(65):
        a.clock=lambda i=i:NOW+timedelta(seconds=i*2)
        a.lookup('B'+str(i).zfill(9))
    assert len(a.cache)==64
    a.clock=lambda:NOW-timedelta(seconds=1)
    with pytest.raises(ProviderFailure):a.lookup(ASIN)  # Clock rollback refuses unsafe pacing.
    assert len(a.cache)==0


def test_wrapped_http_timeout_is_retryable_and_redacted(monkeypatch):
    from urllib.error import URLError
    from app import keepa_adapter,keepa_http
    def broken(*args,**kwargs):raise URLError(TimeoutError('FICTIONAL-SECRET-URL'))
    monkeypatch.setattr(keepa_http,'build_opener',lambda *args:SimpleNamespace(open=broken))
    monkeypatch.setattr(keepa_adapter,'LIVE_CALLS_ENABLED',True)
    with pytest.raises(TimeoutError) as error:
        KeepaHttpTransport(lambda:'FICTIONAL').product(KeepaRequest(ASIN),timeout_seconds=10,maximum_bytes=1024)
    assert 'SECRET' not in str(error.value)
