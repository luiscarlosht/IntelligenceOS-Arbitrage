"""Synthetic M88 transport tests. Never uses credentials or real HTTP."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import json, os
import pytest
from app import m88
from app.m88_state import write,read,sha,ledger,Journal,lock
from app.m88_evidence import match,product,search_result,US
from app.amazon_diagnostics import AmazonFailure
from test_amazon_details import catalog,pricing,fees,CREDS


def setup(tmp_path,monkeypatch,*,exact=False,account=False):
    private=tmp_path/'private';private.mkdir(mode=0o700)
    write(private/'credentials.json',CREDS)
    evidence=tmp_path/'source';evidence.mkdir(mode=0o700)
    baseline=evidence/'ledger.json'
    write(baseline,dict(pilot='m88-real-six-pilot',ceiling=49,attempts_used=0,
        includes_authentication_and_retries=True,attempts=[],purchase_authorized=False))
    doc=catalog();doc['summaries'][1]['brand']='Example'
    canonical=product(doc,doc['asin'],())
    batch=dict(schema='walmart_pilot_batch_v1',name='m88-real-six-pilot',batch_kind='NEW_PILOT',
        other_cost_basis='excludes_retailer_shipping',purchase_authorized=False,observations=[],delivery_context='Sacramento, CA 95829')
    for i in range(6):
        p=deepcopy(canonical);p.pop('asin');p['walmart_item_id']=str(900001+i)
        p['url']='https://www.walmart.com/ip/'+p['walmart_item_id'];p['pack_description']='Synthetic test two-pack'
        if not exact: p.update(gtin='UNKNOWN',verified=False,variation='UNKNOWN')
        batch['observations'].append(dict(source_candidate_id='test:'+str(i),walmart_product=p,
             acquisition=dict(purchase=dict(value='1.00'),retailer_shipping=dict(value='UNKNOWN'))))
    input_path=evidence/'input.json';write(input_path,batch)
    preview=evidence/'preview.json';write(preview,dict(name='m88-real-six-pilot',maximum_http_attempts=31,absolute_ceiling=49))
    context=None
    if account:
        context=private/'account.json';write(context,dict(seller_id='SYNTHETICSELLER',credentials_sha256=sha(private/'credentials.json')))
    # No test sleeps; production still uses the existing strict operation pacer.
    monkeypatch.setattr(m88,'OperationPacer',lambda **_: type('P',(),{'call':lambda self,request,transport:transport(request)})())
    operation=tmp_path/'operation'
    plan=m88.prepare(input_path,sha(input_path),preview,baseline,private,operation,context)
    return plan,operation,baseline,doc


class Fake:
    def __init__(self,ledger_path,doc,*,fail=None,interrupt=False,offers=False):
        self.ledger=ledger_path;self.doc=doc;self.calls=[];self.fail=fail;self.interrupt=interrupt;self.offers=offers
    def __call__(self,request):
        state=ledger(self.ledger)
        assert state['attempts'][-1]['status']=='RESERVED'  # Durable before dispatch.
        self.calls.append(request)
        if self.interrupt and len(self.calls)==2: raise KeyboardInterrupt()
        if self.fail==len(self.calls):
            raise AmazonFailure('synthetic-secret should never be logged',reason='http_error',http_status=403,codes=('AccessDenied',))
        path=urlsplit(request.full_url).path
        if path=='/auth/o2/token': return dict(access_token='synthetic-access',token_type='bearer',expires_in=3600)
        if path=='/catalog/2022-04-01/items': return dict(numberOfResults=1,items=[self.doc])
        if path.startswith('/catalog/2022-04-01/items/'): return self.doc
        if path.endswith('/offers'):
            p=pricing()
            p['payload']['Summary']['BuyBoxPrices']=[dict(condition='New',fulfillmentChannel='Amazon',
                ListingPrice=dict(CurrencyCode='USD',Amount=25),Shipping=dict(CurrencyCode='USD',Amount=0))]
            p['payload']['Summary']['NumberOfOffers']=[dict(condition='new',fulfillmentChannel='Amazon',OfferCount=3)]
            return p
        if path.endswith('/feesEstimate'):
            body=json.loads(request.data)['FeesEstimateRequest']; f=fees(body['Identifier'])
            identifier=f['payload']['FeesEstimateResult']['FeesEstimateIdentifier']
            identifier['IsAmazonFulfilled']=body['IsAmazonFulfilled']
            return f
        raise AssertionError('Unallowlisted endpoint')


def test_prepare_zero_accounting_and_metadata_only(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch)
    assert ledger(path)['attempts_used']==0 and 'm88_operation' not in ledger(path)
    assert len(plan['requests'])==31 and plan['cumulative_ceiling']==49
    assert plan['credential_readiness']['status']=='METADATA_READY_VALUES_UNREAD'
    assert all(secret not in (operation/'plan.json').read_text() for secret in CREDS.values())


def test_unresolved_searches_no_details_offers_fees_and_recovery(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch); original=Path(plan['source_path']).read_bytes()
    transport=Fake(path,doc)
    m88.execute(operation/'plan.json',sha(operation/'plan.json'),transport=transport)
    assert len(transport.calls)==7 and ledger(path)['attempts_used']==7
    assert all(a['status']=='COMPLETE' for a in ledger(path)['attempts'])
    with pytest.raises(PermissionError): m88.execute(operation/'plan.json',sha(operation/'plan.json'),transport=transport)
    summary=m88.report(plan,operation,tmp_path/'report')
    assert summary['exact_matches']==0 and summary['searches_completed']==6
    assert (tmp_path/'report'/'comparison.xlsx').is_file()
    assert not read(tmp_path/'report'/'comparison.json')['purchase_authorized']
    assert Path(plan['source_path']).read_bytes()==original
    assert all(v=='INSUFFICIENT_DATA' for v in summary['financial_assessments'].values())
    all_receipts=''.join(p.read_text() for p in operation.glob('receipt-*.json'))
    assert not any(s in all_receipts for s in [*CREDS.values(),'synthetic-access'])


@pytest.mark.parametrize('failure',[1,2,4])
def test_failures_count_stop_no_retry(tmp_path,monkeypatch,failure):
    plan,operation,path,doc=setup(tmp_path,monkeypatch); transport=Fake(path,doc,fail=failure)
    with pytest.raises(m88.Stop): m88.execute(operation/'plan.json',sha(operation/'plan.json'),transport=transport)
    assert len(transport.calls)==failure and ledger(path)['attempts_used']==failure
    assert ledger(path)['attempts'][-1]['status']=='FAILED'
    assert 'synthetic-secret' not in path.read_text()
    summary=m88.report(plan,operation,tmp_path/'recovered')
    assert summary['failed_attempts']==[failure]


def test_caught_interrupt_charged_and_not_replayed(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch); transport=Fake(path,doc,interrupt=True)
    with pytest.raises(m88.Stop): m88.execute(operation/'plan.json',sha(operation/'plan.json'),transport=transport)
    assert ledger(path)['attempts_used']==2
    with pytest.raises(PermissionError): m88.execute(operation/'plan.json',sha(operation/'plan.json'),transport=transport)


def test_hard_interruption_reservation_recovery_no_refund(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch)
    j=Journal(path,sha(operation/'plan.json'));j.start();j.reserve('authentication',None)
    before=path.read_bytes()
    summary=m88.report(plan,operation,tmp_path/'recovery')
    assert summary['unknown_outcome_attempts']==[1] and ledger(path)['attempts_used']==1
    assert path.read_bytes()==before
    with pytest.raises(PermissionError): j.start()


def test_absolute_ceiling_and_ledger_integrity(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch)
    j=Journal(path,'a'*64)
    number=j.reserve('authentication',None);j.finish(number,'COMPLETE',receipt_sha256='0'*64)
    for phase in ('search','detail','offers','fees_FBA','fees_FBM'):
        for i in range(6):
            number=j.reserve(phase,str(i));j.finish(number,'COMPLETE',receipt_sha256='0'*64)
    with pytest.raises(PermissionError): j.reserve('search','extra')
    state=ledger(path);state['attempts_used']=48
    write(path,state,replace=True)
    with pytest.raises(ValueError): ledger(path)


def test_cumulative_prior_attempts_reduce_budget(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch)
    state=ledger(path)
    state['attempts']=[dict(number=i,status='COMPLETE') for i in range(1,20)]
    state['attempts_used']=19;write(path,state,replace=True)
    with pytest.raises(PermissionError): Journal(path,'a'*64).start()
    state['attempts']=[dict(number=i,status='COMPLETE') for i in range(1,50)]
    state['attempts_used']=49;write(path,state,replace=True)
    with pytest.raises(PermissionError): Journal(path,'a'*64).reserve('authentication',None)


@pytest.mark.parametrize('field,value',[('brand','Wrong'),('size','Wrong'),('model','Wrong'),('variation','Wrong'),('pack_quantity',99),('gtin','UNKNOWN'),('verified',False)])
def test_exact_identity_rejection(tmp_path,monkeypatch,field,value):
    plan,operation,path,doc=setup(tmp_path,monkeypatch,exact=True)
    batch=read(Path(plan['source_path'])); p=batch['observations'][0]['walmart_product']
    target=product(doc,doc['asin'],())
    assert match(p,target,datetime.now(timezone.utc))['exact']
    p[field]=value
    assert not match(p,target,datetime.now(timezone.utc))['exact']


def test_ambiguous_or_partial_search_never_selects(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch,exact=True)
    source=read(Path(plan['source_path']))['observations'][0]['walmart_product']
    second=deepcopy(doc);second['asin']='B000000003'
    assert search_result(dict(numberOfResults=2,items=[doc,second]),source,())['selected_asin'] is None
    assert search_result(dict(numberOfResults=20,items=[doc]),source,())['selected_asin'] is None


def test_complete_maximum_path_base_estimates_not_confirmed_profit(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch,exact=True,account=True)
    transport=Fake(path,doc)
    m88.execute(operation/'plan.json',sha(operation/'plan.json'),transport=transport)
    assert len(transport.calls)==31 and ledger(path)['attempts_used']==31
    summary=m88.report(plan,operation,tmp_path/'report')
    assert summary['exact_matches']==6
    data=read(tmp_path/'report'/'enriched-batch.json')
    row=data['observations'][0]['amazon']
    assert row['market']['competing_offers']['value']==3
    assert row['financials']['FBA']['base']['selling_price']['assumed']
    assert 'conservative' not in row['financials']['FBA']
    assert 'fulfillment_fee' not in row['financials']['FBM']['base']
    assert all(v=='INSUFFICIENT_DATA' for v in summary['financial_assessments'].values())


def test_tampered_plan_or_source_stops_before_credentials(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch)
    write(Path(plan['source_path']),dict(corrupt=True),replace=True)
    monkeypatch.setattr(m88.pilot,'load_credentials',lambda *_:pytest.fail('Must not read credentials'))
    with pytest.raises(ValueError):m88.execute(operation/'plan.json',sha(operation/'plan.json'),transport=Fake(path,doc))
    assert ledger(path)['attempts_used']==0


def test_concurrent_lock_exclusion(tmp_path):
    tmp_path.chmod(0o700)
    with lock(tmp_path/'scope.lock'):
        with pytest.raises(BlockingIOError):
            with lock(tmp_path/'scope.lock'):pass


def test_parser_failure_is_counted_and_stops(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch)
    fake=Fake(path,doc)
    def corrupt(request):
        value=fake(request)
        return value if len(fake.calls)==1 else {'numberOfResults':'invalid','items':[]}
    with pytest.raises(m88.Stop):m88.execute(operation/'plan.json',sha(operation/'plan.json'),transport=corrupt)
    assert ledger(path)['attempts_used']==2
    assert ledger(path)['attempts'][-1]['failure']['reason']=='response_validation_failed'


def test_receipt_drift_prevents_recovery(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch)
    m88.execute(operation/'plan.json',sha(operation/'plan.json'),transport=Fake(path,doc))
    write(operation/'receipt-2.json',{'tampered':True},replace=True)
    with pytest.raises(ValueError):m88.report(plan,operation,tmp_path/'report')
    assert not (tmp_path/'report').exists()


def test_no_repeat_and_no_exploratory_slots(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch)
    j=Journal(path,'a'*64)
    with pytest.raises(ValueError):j.reserve('exploration','test:0')
    number=j.reserve('authentication',None);j.finish(number,'COMPLETE')
    with pytest.raises(PermissionError):j.reserve('authentication',None)
    assert ledger(path)['attempts_used']==1


def test_provider_echo_redaction(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch)
    doc['summaries'][1]['itemName']='synthetic-secret synthetic-access'
    doc['summaries'][1]['brand']='synthetic-client'
    m88.execute(operation/'plan.json',sha(operation/'plan.json'),transport=Fake(path,doc))
    receipts=''.join(p.read_text() for p in operation.glob('receipt-*.json'))
    assert all(s not in receipts for s in [*CREDS.values(),'synthetic-access'])


def test_symlink_ledger_and_bad_hash_refused(tmp_path,monkeypatch):
    plan,operation,path,doc=setup(tmp_path,monkeypatch)
    link=path.with_name('alias.json');link.symlink_to(path)
    with pytest.raises(ValueError):ledger(link)
    with pytest.raises(ValueError):m88.execute(operation/'plan.json','0'*64,transport=Fake(path,doc))
    assert ledger(path)['attempts_used']==0
