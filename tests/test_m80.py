"""M80 synthetic-only execution. No production credentials or external calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.request import Request
import pytest
from app import m80_contract as c, m80_evidence as e, m80_execution as x
from app.m80 import export, authorize, main
from app.m80_demo import Clock, plan as demo_plan, replies, SyntheticTransport, demonstrate
from app.m80_journal import Journal, inspect
from app.observations import fingerprint

NOW=datetime(2026,11,3,tzinfo=timezone.utc)


@pytest.fixture
def prepared(tmp_path):
    private=tmp_path/'private'; private.mkdir(mode=0o700)
    contract=demo_plan(private)
    targets=contract['targets']
    source=tmp_path/'source'; source.mkdir(mode=0o700)
    handoff=source/'M79_walmart_handoff.json'
    c.write(handoff,dict(ready_for_walmart_sourcing=False,all_asins=targets,priority20=targets))
    creds={'client_id':'SYNTHETIC-ID','client_secret':'SYNTHETIC-SECRET','refresh_token':'SYNTHETIC-REFRESH'}
    c.write(private/'credentials.json',creds)
    c.write(private/'candidate-execution.lock',{})
    c.write(private/c.ACCOUNT,dict(schema=1,operation_id=c.OPERATION,seller_id='SYNTHETICSELLER',
        marketplace_id='ATVPDKIKX0DER',condition='new_new',credentials_sha256=hashlib.sha256((private/'credentials.json').read_bytes()).hexdigest()))
    digest=hashlib.sha256(handoff.read_bytes()).hexdigest()
    contract=c.prepare(handoff,digest,private); c.write(private/c.PLAN,contract)
    return private,handoff,contract


def simulation(tmp_path, mutate=None, callback=None):
    root=tmp_path/'run'; root.mkdir(mode=0o700)
    contract=demo_plan(root); clock=Clock(); transport=SyntheticTransport(contract)
    if mutate: mutate(transport,contract,clock)
    journal=Journal(root/'pilot.sqlite3',dict(plan=contract,authorization_sha256='0'*64,synthetic=True))
    x.run_claimed(journal,transport,contract,before_request=callback or (lambda:None),
                  pacer=x.Pacer(clock.monotonic,clock.sleep),monotonic=clock.monotonic,utcnow=clock.utcnow)
    journal.close()
    return inspect(root/'pilot.sqlite3'),transport,clock,root


def test_preparation_reads_no_secret_values(prepared,monkeypatch):
    private,handoff,contract=prepared
    old=Path.read_bytes
    def guarded(path):
        if path.name=='credentials.json': pytest.fail('credential content read during preflight')
        return old(path)
    monkeypatch.setattr(Path,'read_bytes',guarded)
    snapshot={p:p.stat().st_mtime_ns for p in private.iterdir()}
    assert c.prepare(handoff,contract['handoff_sha256'],private)==contract
    assert x.preflight(private,hashlib.sha256((private/c.PLAN).read_bytes()).hexdigest())==contract
    assert snapshot=={p:p.stat().st_mtime_ns for p in private.iterdir()}
    assert not (private/c.LEDGER).exists()


@pytest.mark.parametrize('kind',['asin','duplicate','method','body','marketplace','budget','boolean_budget','rate','code','target'])
def test_frozen_contract_refuses_drift(tmp_path,kind):
    p=demo_plan(tmp_path)
    if kind=='asin': p['asins'][0]='B900000001'
    elif kind=='duplicate': p['asins'][1]=p['asins'][0]
    elif kind=='method': p['requests'][2]['method']='DELETE'
    elif kind=='body': p['requests'][21]['body']['requests'].append(p['requests'][21]['body']['requests'][0])
    elif kind=='marketplace': p['marketplace_id']='OTHER'
    elif kind=='budget': p['budget']['http_maximum']=43
    elif kind=='boolean_budget': p['budget']['authentication']=True
    elif kind=='rate': p['rates']['catalog']=2.0
    elif kind=='code': p['implementation_sha256']={}
    else: p['targets'][0]['permanently_excluded']=True
    with pytest.raises(ValueError): c.validate(p)


@pytest.mark.parametrize('change',['old_m77','expired','future','budget','asins','extra','long','bool'])
def test_authorization_exact_scope_and_expiry(tmp_path,change):
    p=demo_plan(tmp_path); a=c.permission(p,'manual:test',NOW)
    if change=='old_m77': a['operation_id']='M77-US-CATALOG-EXPLORE31-ONCE'
    elif change=='expired': a['expires_at']=NOW.isoformat()
    elif change=='future': a['issued_at']=(NOW+timedelta(seconds=1)).isoformat()
    elif change=='budget': a['budget']['http_maximum']=43
    elif change=='asins': a['asins']=list(reversed(a['asins']))
    elif change=='extra': a['retry']=True
    elif change=='long': a['expires_at']=(NOW+timedelta(seconds=601)).isoformat()
    else: a['budget']['authentication']=True
    with pytest.raises(ValueError): c.check_permission(a,p,NOW)


def test_permission_does_not_alias_plan(tmp_path):
    p=demo_plan(tmp_path); a=c.permission(p,'manual:test',NOW)
    a['asins'].reverse()
    assert p['asins'][0]=='B800000000'


def test_explicit_live_flag_precedes_all_reads(tmp_path,monkeypatch):
    monkeypatch.setattr(x,'read',lambda *a:pytest.fail('read before flag'))
    with pytest.raises(PermissionError): x.execute(tmp_path,'x',tmp_path/'auth','x',execute_live=False)


def test_interactive_owner_only(prepared,monkeypatch):
    private,_,_=prepared
    monkeypatch.setattr('sys.stdin.isatty',lambda:False)
    sha=hashlib.sha256((private/c.PLAN).read_bytes()).hexdigest()
    with pytest.raises(PermissionError): authorize(private,sha,'manual:test',private/'m80-owner-authorization-test.json')
    assert not list(private.glob('m80-owner-authorization*'))


def test_exact_42_intents_durable_before_dispatch(tmp_path):
    def mutate(t,p,clock):
        original=t.send
        def send(request,definition):
            before=inspect(tmp_path/'run/pilot.sqlite3')
            assert before['requests_consumed']==definition['slot']
            assert definition['slot'] in before['uncertain_slots']
            return original(request,definition)
        t.send=send
    snapshot,t,clock,_=simulation(tmp_path,mutate)
    assert snapshot['status']=='COMPLETED_NO_REPLAY'
    assert t.calls==list(range(1,43)) and not snapshot['uncertain_slots']
    assert t.token is None and t.credentials=={}
    assert clock.seconds>=38
    assert set(snapshot['responses'][1]['body'])=={'authenticated','expires_in'}
    report=e.analyze(snapshot,clock.utcnow())
    assert len(report['rows'])==20 and report['synthetic']
    assert sum(r['review_ready'] for r in report['rows'])==17
    assert all(r['estimated_monthly_unit_sales']=='UNKNOWN' and r['price_stability']=='UNKNOWN'
               and not r['sourcing_allowed'] and not r['purchase_authorized'] for r in report['rows'])
    assert len(report['category_groups'])==2


@pytest.mark.parametrize('failure',['http','retry_after','timeout','batch_member','batch_missing','catalog_asin',
                                     'restrictions_asin','expired_token','lower_rate','bad_rate'])
def test_failure_stops_without_retry(tmp_path,failure):
    def mutate(t,p,clock):
        original=t.send
        if failure=='batch_member': t.fixtures[22]['responses'][7]['status']['statusCode']=429
        elif failure=='batch_missing': t.fixtures[22]['responses'].pop()
        elif failure=='catalog_asin': t.fixtures[2]['asin']='B999999999'
        elif failure=='restrictions_asin': t.fixtures[23]={'restrictions':[dict(asin='B999999999',marketplaceId='ATVPDKIKX0DER')]}
        elif failure=='expired_token': t.fixtures[1]['expires_in']=6
        def send(request,d):
            if failure=='timeout' and d['slot']==3:
                t.calls.append(3); raise TimeoutError('never leak this text')
            result=original(request,d)
            if d['slot']==2:
                if failure=='http': result['status']=403
                if failure=='retry_after': result['headers']={'Retry-After':'60'}
                if failure=='lower_rate': result['headers']={'x-amzn-RateLimit-Limit':'0.001'}
                if failure=='bad_rate': result['headers']={'x-amzn-RateLimit-Limit':'nan'}
            return result
        t.send=send
    s,t,clock,_=simulation(tmp_path,mutate)
    assert s['status']=='STOPPED_NO_REPLAY'
    assert len(t.calls)<=42 and len(set(t.calls))==len(t.calls)
    if failure.startswith('batch'): assert t.calls[-1]==22
    if failure=='timeout': assert s['uncertain_slots']==[3]
    if failure=='http': assert t.calls==[1,2] and s['responses'][2]['http_status']==403
    assert all(not r['review_ready'] for r in e.analyze(s,clock.utcnow())['rows'])


def test_cancellation_and_partial_claim_no_resume(tmp_path):
    root=tmp_path/'run';root.mkdir(mode=0o700);p=demo_plan(root)
    j=Journal(root/'pilot.sqlite3',{'plan':p,'synthetic':True,'authorization_sha256':'0'*64})
    j.start();j.consume(p['requests'][0]);j.close()
    assert inspect(root/'pilot.sqlite3')['uncertain_slots']==[1]
    with pytest.raises(FileExistsError): Journal(root/'pilot.sqlite3',{'plan':p})
    jdb=sqlite3.connect(root/'pilot.sqlite3')
    with pytest.raises(sqlite3.IntegrityError): jdb.execute('DELETE FROM events')
    jdb.close()


@pytest.mark.parametrize('mutation',['extra_header','url','method','data','redirect_header'])
def test_transport_refuses_request_mutation(tmp_path,mutation):
    p=demo_plan(tmp_path);t=SyntheticTransport(p);t.accept_authentication(t.fixtures[1]);d=p['requests'][21]
    request=t.build(d)
    if mutation=='extra_header': request.add_header('Cookie','unsafe')
    elif mutation=='url': request.full_url='https://example.invalid/'
    elif mutation=='method': request.method='PUT'
    elif mutation=='data': request.data=b'{}'
    else: request.add_unredirected_header('Host','example.invalid')
    with pytest.raises(ValueError): t.validate(request,d)


def test_missing_metrics_stay_unknown(tmp_path):
    p=demo_plan(tmp_path);body=replies(p)[2];body.pop('salesRanks');body.pop('summaries')
    assert e.catalog(body,p['asins'][0]).ranks==()
    pricing=replies(p)[22]['responses'][0]['body'];pricing['payload']['Summary']={};pricing['payload'].pop('Offers')
    observed=e.offers(pricing,p['asins'][0]);assert observed.new_count is None and observed.total_count is None
    assert observed.prices==() and observed.buy_box_winner_observed is None
    with pytest.raises(ValueError): e.restrictions({},p['asins'][0])


@pytest.mark.parametrize('bad',[0,-1,True,1.5])
def test_invalid_bsr(tmp_path,bad):
    p=demo_plan(tmp_path);body=replies(p)[2];body['salesRanks'][0]['displayGroupRanks'][0]['rank']=bad
    with pytest.raises(ValueError): e.catalog(body,p['asins'][0])


def test_price_and_scope_validation(tmp_path):
    p=demo_plan(tmp_path);a=p['asins'][0];body=replies(p)[22]['responses'][0]['body']
    body['payload']['Summary']['LowestPrices'][0]['LandedPrice']['CurrencyCode']='EUR'
    with pytest.raises(ValueError): e.offers(body,a)
    body=replies(p)[22]['responses'][0]['body'];body['payload']['Identifier']['ItemCondition']='Used'
    with pytest.raises(ValueError): e.offers(body,a)


def test_stale_metrics_not_ranked_or_eligible(tmp_path):
    snapshot,t,clock,_=simulation(tmp_path)
    report=e.analyze(snapshot,clock.utcnow()+timedelta(days=2))
    assert all(not r['review_ready'] and r['listing_permission']=='UNKNOWN' and not r['ranks'] for r in report['rows'])


def test_redaction_no_auth_tokens_or_seller_ids_in_evidence(tmp_path):
    def mutate(t,p,clock):
        t.fixtures[2]['extra']={'sellerId':'SYNTHETICSELLER','value':'SYNTHETIC-CLIENT-SECRET'}
    snapshot,_,_,root=simulation(tmp_path,mutate)
    raw=(root/'pilot.sqlite3').read_bytes()
    for secret in (b'SYNTHETIC-NOT-A-REAL-TOKEN',b'SYNTHETIC-CLIENT-SECRET',b'SYNTHETICSELLER'):
        assert secret not in raw


def test_synthetic_export_determinism_and_no_overwrite(tmp_path):
    snapshot,_,clock,_=simulation(tmp_path)
    first=export(snapshot,tmp_path/'first',clock.utcnow()); export(snapshot,tmp_path/'second',clock.utcnow())
    assert first['synthetic']
    assert {p.name:p.read_bytes() for p in (tmp_path/'first').iterdir()}=={p.name:p.read_bytes() for p in (tmp_path/'second').iterdir()}
    with pytest.raises(ValueError): export(snapshot,tmp_path/'first',clock.utcnow())


def test_live_entrypoint_with_injected_synthetic_transport_only(prepared,monkeypatch):
    private,_,contract=prepared
    now=datetime.now(timezone.utc)
    auth=c.permission(contract,'manual:synthetic-test',now)
    auth_path=private/'m80-owner-authorization-synthetic.json';c.write(auth_path,auth)
    plan_sha=hashlib.sha256((private/c.PLAN).read_bytes()).hexdigest()
    auth_sha=hashlib.sha256(auth_path.read_bytes()).hexdigest()
    fake=SyntheticTransport(contract); clock=Clock()
    monkeypatch.setattr(x,'Transport',lambda *_:fake)
    real_pacer=x.Pacer
    monkeypatch.setattr(x,'Pacer',lambda:real_pacer(clock.monotonic,clock.sleep))
    import resource
    monkeypatch.setattr(resource,'setrlimit',lambda *_:None)
    snapshot=x.execute(private,plan_sha,auth_path,auth_sha,execute_live=True)
    assert snapshot['status']=='COMPLETED_NO_REPLAY' and fake.calls==list(range(1,43))
    assert (private/c.LEDGER).exists()
    original=x.read
    def no_credentials(path):
        if path.name=='credentials.json':pytest.fail('replay reached credentials')
        return original(path)
    monkeypatch.setattr(x,'read',no_credentials)
    with pytest.raises(ValueError,match='permanently blocks'):
        x.execute(private,plan_sha,auth_path,auth_sha,execute_live=True)


@pytest.mark.parametrize('kind',['expired','wrong_digest','m77','wrong_plan'])
def test_live_invalid_permission_never_reads_credentials(prepared,monkeypatch,kind):
    private,_,contract=prepared
    auth=c.permission(contract,'manual:synthetic',datetime.now(timezone.utc))
    if kind=='expired':auth['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    if kind=='m77':auth['operation_id']='M77-US-CATALOG-EXPLORE31-ONCE'
    if kind=='wrong_plan':auth['plan_sha256']='0'*64
    path=private/'m80-owner-authorization-test.json';c.write(path,auth)
    sha=hashlib.sha256(path.read_bytes()).hexdigest() if kind!='wrong_digest' else '0'*64
    original=x.read
    def no_credentials(p):
        if p.name=='credentials.json':pytest.fail('unauthorized credential read')
        return original(p)
    monkeypatch.setattr(x,'read',no_credentials)
    with pytest.raises(ValueError):x.execute(private,hashlib.sha256((private/c.PLAN).read_bytes()).hexdigest(),path,sha,execute_live=True)
    assert not (private/c.LEDGER).exists()


@pytest.mark.parametrize('kind',['empty','corrupt','symlink'])
def test_existing_any_ledger_refuses_preflight(prepared,kind):
    private,_,_=prepared;path=private/c.LEDGER
    if kind=='symlink':path.symlink_to(private/c.PLAN)
    else:c.write(path,{} if kind=='empty' else {'corrupt':True})
    with pytest.raises(ValueError,match='permanently blocks'):x.preflight(private,hashlib.sha256((private/c.PLAN).read_bytes()).hexdigest())


def test_chain_corruption_and_false_completion_refused(tmp_path):
    snapshot,_,_,root=simulation(tmp_path)
    db=sqlite3.connect(root/'pilot.sqlite3')
    db.execute('DROP TRIGGER immutable_events_UPDATE')
    db.execute("UPDATE events SET payload='{}' WHERE kind='ATTEMPT' AND slot=2");db.commit();db.close()
    with pytest.raises(ValueError):inspect(root/'pilot.sqlite3')


def test_account_and_source_drift_refused(prepared):
    private,handoff,p=prepared
    handoff.write_text('{}');handoff.chmod(0o600)
    with pytest.raises(ValueError,match='Reviewed M79 handoff digest mismatch'):c.check_inputs(p)


def test_lower_rate_never_accelerates_and_ambiguous_limits_refused():
    clock=Clock();pacer=x.Pacer(clock.monotonic,clock.sleep)
    pacer.acquire('catalog',600);pacer.observe('catalog',{'x-amzn-RateLimit-Limit':'0.5'})
    pacer.acquire('catalog',600)
    assert clock.seconds>=4
    pacer.observe('catalog',{'x-amzn-RateLimit-Limit':'100'})
    assert pacer.rates['catalog']==0.25
    with pytest.raises(ValueError):pacer.observe('catalog',{'x-amzn-RateLimit-Limit':'1','X-AMZN-RATELIMIT-LIMIT':'0.01'})


def test_zero_count_does_not_coexist_with_new_prices(tmp_path):
    p=demo_plan(tmp_path);body=replies(p)[22]['responses'][0]['body']
    body['payload']['Summary']['TotalOfferCount']=0;body['payload']['Summary']['NumberOfOffers']=[];body['payload']['Offers']=[]
    with pytest.raises(ValueError):e.offers(body,p['asins'][0])


def test_category_ranks_cannot_be_pooled_into_global_demand(tmp_path):
    snapshot,_,clock,_=simulation(tmp_path)
    report=e.analyze(snapshot,clock.utcnow())
    assert len(report['category_groups'])==2
    assert 'global_rank' not in report
    assert report['rows'][0]['category_relative_ranks'][0]['rank_within_pilot']==1
    assert report['rows'][1]['category_relative_ranks'][0]['rank_within_pilot']==1


@pytest.mark.parametrize('kind',['sidecar','dangling_result'])
def test_ambiguous_storage_blocks_before_any_claim(prepared,kind):
    private,_,_=prepared
    if kind=='sidecar':(private/(c.LEDGER+'-journal')).write_bytes(b'partial')
    else:(private/'m80-results').symlink_to(private/'missing')
    with pytest.raises(ValueError):x.preflight(private,hashlib.sha256((private/c.PLAN).read_bytes()).hexdigest())
    assert not (private/c.LEDGER).exists()


def test_account_lock_busy_prevents_credential_reads(prepared,monkeypatch):
    import fcntl,os
    private,_,p=prepared;auth=c.permission(p,'manual:lock-test',datetime.now(timezone.utc))
    path=private/'m80-owner-authorization-lock.json';c.write(path,auth)
    fd=os.open(private/'candidate-execution.lock',os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    old=x.read
    def guarded(path):
        if path.name=='credentials.json':pytest.fail('busy lock reached credentials')
        return old(path)
    monkeypatch.setattr(x,'read',guarded)
    try:
        with pytest.raises(BlockingIOError):x.execute(private,hashlib.sha256((private/c.PLAN).read_bytes()).hexdigest(),path,
            hashlib.sha256(path.read_bytes()).hexdigest(),execute_live=True)
    finally:os.close(fd)
    assert not (private/c.LEDGER).exists()


@pytest.mark.parametrize('kind',['mode','symlink','hardlink','duplicate','acl'])
def test_private_record_integrity(prepared,monkeypatch,kind):
    private,_,_=prepared;path=private/c.ACCOUNT
    if kind=='mode':path.chmod(0o644)
    elif kind=='symlink':
        path.unlink();path.symlink_to(private/c.PLAN)
    elif kind=='hardlink':
        import os
        os.link(path,private/'alias')
    elif kind=='duplicate':path.write_text('{"schema":1,"schema":1}')
    else:
        original=c.os.listxattr
        monkeypatch.setattr(c.os,'listxattr',lambda p,**kw:['system.posix_acl_access'] if p==path else original(p,**kw))
    with pytest.raises(ValueError):c.account(private)


def test_prepare_does_not_open_credential_fd(prepared,monkeypatch):
    private,handoff,p=prepared;original=c.os.open
    def guarded(path,*args,**kwargs):
        if Path(path).name=='credentials.json':pytest.fail('credential fd opened in prepare')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(c.os,'open',guarded)
    assert c.prepare(handoff,p['handoff_sha256'],private)==p


def test_transport_refuses_unallowlisted_definition(tmp_path):
    p=demo_plan(tmp_path);t=SyntheticTransport(p);bad=deepcopy(p['requests'][0]);bad['host']='example.invalid'
    with pytest.raises(ValueError):t.build(bad)


def test_http_primitive_is_single_verified_no_proxy_send(tmp_path,monkeypatch):
    import io
    p=demo_plan(tmp_path);t=SyntheticTransport(p)
    class Response(io.BytesIO):
        status=200; headers={}
    calls=[]
    class Opener:
        def open(self,request,timeout):
            calls.append((request,timeout));return Response(b'{"access_token":"FAKE-TOKEN","token_type":"bearer","expires_in":3600}')
    def opener(*handlers):
        assert any(isinstance(h,x.ProxyHandler) and h.proxies=={} for h in handlers)
        assert any(isinstance(h,x.NoRedirect) for h in handlers)
        handler=next(h for h in handlers if isinstance(h,x.HTTPSHandler))
        assert handler._context.check_hostname and handler._context.verify_mode==x.ssl.CERT_REQUIRED
        return Opener()
    monkeypatch.setattr(x,'build_opener',opener)
    result=x.Transport.send(t,t.build(p['requests'][0]),p['requests'][0])
    assert result['status']==200 and len(calls)==1 and calls[0][1]==10


def test_malformed_json_does_not_retry(tmp_path,monkeypatch):
    import io
    p=demo_plan(tmp_path);t=SyntheticTransport(p);calls=[]
    class Response(io.BytesIO):status=200;headers={}
    class Opener:
        def open(self,*args,**kwargs):calls.append(1);return Response(b'{"x":1,"x":2}')
    monkeypatch.setattr(x,'build_opener',lambda *a:Opener())
    with pytest.raises(ValueError):x.Transport.send(t,t.build(p['requests'][0]),p['requests'][0])
    assert len(calls)==1


def test_response_phase_size_bound_stops_run(tmp_path,monkeypatch):
    def mutate(t,p,clock):
        original=t.send
        def send(req,d):
            result=original(req,d)
            if d['slot']==2:result['body']['too_big']='x'*(1024*1024)
            return result
        t.send=send
    snapshot,t,_,_=simulation(tmp_path,mutate)
    assert snapshot['status']=='STOPPED_NO_REPLAY' and t.calls==[1,2]
    assert snapshot['uncertain_slots']==[2]


def test_recovery_never_reads_private_credentials(prepared,tmp_path,monkeypatch):
    snapshot,_,clock,_=simulation(tmp_path)
    old=c.read
    def guarded(path):
        if path.name in ('credentials.json',c.ACCOUNT):pytest.fail('recovery accessed account secrets')
        return old(path)
    monkeypatch.setattr(c,'read',guarded)
    export(snapshot,tmp_path/'recovered',clock.utcnow())
    assert (tmp_path/'recovered/M80_completion.json').exists()


def test_report_refuses_protected_history_and_private_subdirs(tmp_path):
    snapshot,_,clock,root=simulation(tmp_path)
    history=Path(snapshot['binding']['plan']['protected_roots'][0]);history.mkdir(mode=0o700)
    with pytest.raises(ValueError):export(snapshot,history/'new',clock.utcnow())
    with pytest.raises(ValueError):export(snapshot,root/'old-history'/'new',clock.utcnow())
    assert not (history/'new').exists()


def test_batch_member_retry_after_is_not_lost_during_redaction(tmp_path):
    def mutate(t,p,clock):
        t.fixtures[22]['responses'][0]['headers']={'Retry-After':'60','x-amz-access-token':'SYNTHETIC-NOT-A-REAL-TOKEN'}
    snapshot,t,_,_=simulation(tmp_path,mutate)
    assert t.calls[-1]==22 and snapshot['status']=='STOPPED_NO_REPLAY'
    headers=snapshot['responses'][22]['body']['responses'][0]['headers']
    assert headers=={'Retry-After':'60'}


def test_optional_batch_echo_defaults_preserve_exact_scope(tmp_path):
    p=demo_plan(tmp_path);body=replies(p)[22]
    for response in body['responses']:
        response['request'].pop('CustomerType'); response['request']['headers']={}
    assert len(e.batch(body,p['requests'][21]['body']['requests']))==20
    body['responses'][0]['request']['MarketplaceId']='OTHER'
    with pytest.raises(ValueError):e.batch(body,p['requests'][21]['body']['requests'])


def test_changed_identity_blocks_review_even_with_no_listing_restrictions(tmp_path):
    def mutate(t,p,clock):t.fixtures[2]['summaries'][0]['brand']='Changed brand'
    snapshot,_,clock,_=simulation(tmp_path,mutate)
    first=e.analyze(snapshot,clock.utcnow())['rows'][0]
    assert 'CHANGED_BRAND' in first['identity_issues'] and not first['review_ready']


def test_source_synthetic_flag_refused_on_preflight_not_only_prepare(prepared):
    private,handoff,p=prepared
    data=json.loads(handoff.read_text());data['synthetic']=True
    handoff.write_text(json.dumps(data));handoff.chmod(0o600)
    p['handoff_sha256']=hashlib.sha256(handoff.read_bytes()).hexdigest()
    with pytest.raises(ValueError):c.check_inputs(p)


def test_hidden_confirmation_never_falls_back_to_echo(prepared,monkeypatch):
    import warnings,getpass
    private,_,_=prepared
    monkeypatch.setattr('sys.stdin.isatty',lambda:True);monkeypatch.setattr('sys.stdout.isatty',lambda:True)
    def unavailable(*_):warnings.warn('no hidden terminal',getpass.GetPassWarning)
    monkeypatch.setattr(getpass,'getpass',unavailable)
    output=private/'m80-owner-authorization-fallback.json'
    with pytest.raises(getpass.GetPassWarning):authorize(private,hashlib.sha256((private/c.PLAN).read_bytes()).hexdigest(),'manual:test',output)
    assert not output.exists()


def test_exact_human_ack_required(prepared,monkeypatch):
    private,_,_=prepared
    monkeypatch.setattr('sys.stdin.isatty',lambda:True);monkeypatch.setattr('sys.stdout.isatty',lambda:True)
    monkeypatch.setattr('getpass.getpass',lambda *_:'SYNTHETICSELLER')
    monkeypatch.setattr('builtins.input',lambda *_:'no')
    output=private/'m80-owner-authorization-no.json'
    with pytest.raises(PermissionError):authorize(private,hashlib.sha256((private/c.PLAN).read_bytes()).hexdigest(),'manual:test',output)
    assert not output.exists()


def test_deployment_volume_refused_before_private_reads(monkeypatch):
    monkeypatch.setattr(x,'read',lambda *_:pytest.fail('deployment-volume read'))
    with pytest.raises(ValueError,match='outside deployment volumes'):x.preflight(Path('/mnt/m80-not-authorized'),'0'*64)
