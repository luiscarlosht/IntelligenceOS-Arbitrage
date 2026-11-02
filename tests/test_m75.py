"""Synthetic accounts/permissions/transports only. Never authorize or call production."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.request import Request

import pytest
from test_m67 import cohort
from test_m69 import fixture as history_fixture, offline
from test_m72 import pilot, CREDS, Clock
from test_m73 import completed, no_network
from test_m74 import ready
from test_m70 import raw_item

from app import m74, m75, m75_policy as policy, m75_execution as execution
from app.m75_authorization import owner_authorization, check
from app.m75_registry import Registry, inspect
from app.m75_transport import Transport
from app.m75_reporting import export
from app.m70_sources import file_hash
from app.m65_intelligence import sha256
from app.amazon_pacing import OperationPacer
from app.observations import canonical, fingerprint


def write(path,value):path.write_text(canonical(value)+'\n');path.chmod(0o600)


@pytest.fixture
def expansion(ready,monkeypatch):
    c,k=ready;m74.run(**k)
    directory=k['output'];manifest=json.loads((directory/'M74_query_manifest.json').read_text())
    monkeypatch.setattr(policy,'CANONICAL_SHA256',manifest['manifest_sha256'])
    monkeypatch.setattr(policy,'MANIFEST_SHA256',file_hash(directory/'M74_query_manifest.json'))
    monkeypatch.setattr(policy,'COMPLETION_SHA256',file_hash(directory/'M74_evidence_digests.json'))
    monkeypatch.setattr(policy,'CONTRACT_SHA256',file_hash(directory/'M74_M75_contract_proposal.json'))
    evidence={name:value for name,value in k.items() if name!='output'}
    prepared=policy.preflight(directory,evidence)
    return dict(c=c,directory=directory,evidence=evidence,prepared=prepared,private=evidence['private'])


class Fake(Transport):
    def __init__(self,registry,reply=None):
        super().__init__(CREDS,seller_id='SYNTHETICSELLER');self.registry=registry;self.reply=reply;self.sent=[]
    def send_slot(self,request,slot):
        self.validate_slot(request,slot)
        assert self.registry.count()==slot
        self.sent.append(request.full_url)
        if self.reply is not None:
            response=self.reply(slot)
            if response is not None:return response
        body=dict(access_token='SYNTHETICACCESS',token_type='bearer',expires_in=3600) if slot==1 else dict(
            items=[raw_item(1000),raw_item(1002),raw_item(0)],pagination=dict(nextToken='PRIVATECURSOR'))
        return dict(status=200,headers={},body=body)


def run(e,tmp_path,reply=None,before=lambda:None,deadline=120):
    path=tmp_path/'test-run.sqlite3';r=Registry(path,dict(preflight=e['prepared'].report))
    fake=Fake(r,reply);clock=Clock()
    execution.run_claimed(r,fake,e['prepared'].report,before_request=before,
        pacer=OperationPacer(monotonic=clock.time,sleep=clock.sleep),deadline=deadline,monotonic=clock.time)
    r.close();return inspect(path),fake,clock,path


def permission(e):return owner_authorization(e['prepared'].report,'manual:synthetic-test-only')


def test_preflight_exact_plan_private_readonly_no_credentials(expansion,monkeypatch):
    e=expansion;before={p:sha256(p) for p in (e['private']/policy.REGISTRY.replace('m75','m72'),) if p.exists()}
    original=policy.account
    def account(private):return original(private)
    monkeypatch.setattr(policy,'account',account)
    p=policy.preflight(e['directory'],e['evidence'])
    assert p.report==e['prepared'].report and p.report['budget']['total']==21
    assert p.report['requests']==policy.requests() and len(p.report['requests'])==20
    assert p.report['credential_content_verification']=='DEFERRED_UNTIL_NEW_OWNER_AUTHORIZATION'
    assert p.report['actual_requests']==p.report['actual_authentication']==0
    assert not (e['private']/policy.REGISTRY).exists()
    assert not list(e['private'].glob('m75-owner-authorization-*'))
    assert before=={p:sha256(p) for p in before}


def test_full_21_accounted_first_pages_partial_cursors_and_privacy(expansion,tmp_path):
    e=expansion;snap,fake,clock,path=run(e,tmp_path)
    assert snap['status']=='COMPLETED_NO_REPLAY' and snap['requests_consumed']==21 and len(snap['pages'])==20
    assert len(fake.sent)==21 and sum(clock.sleeps)>=19
    assert not any('pageToken=' in url or 'identifiers=' in url or '/restrictions' in url for url in fake.sent)
    assert [p['query_reference'] for p in snap['pages']]==[r['query_id'] for r in policy.requests()]
    assert all(p['page_index']==0 for p in snap['pages']) and not fake._credentials
    report=export(snap,e['prepared'].manifest,e['prepared'].baseline,tmp_path/'out')
    assert report['distinct_new_asins']==1 and report['duplicate_observations']==57
    assert report['distinct_excluded_asins']==1 and report['historical_exclusions']==97
    assert report['eligibility']==report['economics']=='UNKNOWN' and report['purchases']==0
    assert report['source_coverage']['sources'][0]['partial_query_windows']==20
    assert all(s not in canonical(report) for s in (*CREDS.values(),'SYNTHETICACCESS','SYNTHETICSELLER','PRIVATECURSOR'))
    assert all(p.stat().st_mode&0o777==0o600 for p in (tmp_path/'out').iterdir())
    with pytest.raises(FileExistsError):Registry(path,{})


@pytest.mark.parametrize('field,value',[
 ('schema',True),('mode','M72_EXPLICIT_OWNER_AUTHORIZATION'),('operation_id','M72-US-CATALOG-FIRST9-ONCE'),
 ('approved',False),('execution_permission',False),('no_retry',False),('no_replay',False),
 ('manifest_sha256','a'*64),('manifest_file_sha256','a'*64),('completion_file_sha256','a'*64),
 ('contract_file_sha256','a'*64),('preflight_sha256','a'*64),('implementation_sha256',{}),
 ('evidence_sha256','a'*64),('account_binding_sha256','a'*64),('account_reference','OTHER'),
 ('marketplace_id','OTHER'),('request_definitions_sha256','a'*64),('review_reference','sensitive arbitrary text')])
def test_authorization_exact_bindings(expansion,field,value):
    auth=permission(expansion);auth[field]=value
    with pytest.raises(ValueError):check(auth,expansion['prepared'].report)


@pytest.mark.parametrize('field',['authentication','keyword','total','identifier','additional_pages','retries','refreshes',
    'eligibility','pricing','fees','fba','retailer','listings','purchases','approvals'])
def test_no_budget_or_operation_expansion(expansion,field):
    auth=permission(expansion);auth['budget'][field]+=1
    with pytest.raises(ValueError):check(auth,expansion['prepared'].report)


@pytest.mark.parametrize('kind',['expired','future','long','naive','missing','boolean_budget'])
def test_authorization_freshness(expansion,kind):
    now=datetime.now(timezone.utc);a=permission(expansion)
    if kind=='expired':a['expires_at']=(now-timedelta(seconds=1)).isoformat()
    elif kind=='future':a['issued_at']=(now+timedelta(seconds=2)).isoformat()
    elif kind=='long':a['expires_at']=(now+timedelta(minutes=11)).isoformat()
    elif kind=='naive':a['issued_at']=now.replace(tzinfo=None).isoformat()
    elif kind=='missing':a.pop('no_replay')
    else:a['budget']['authentication']=True
    with pytest.raises(ValueError):check(a,expansion['prepared'].report,now)


@pytest.mark.parametrize('slot',[1,2,10,21])
@pytest.mark.parametrize('error',[TimeoutError,KeyboardInterrupt,SystemExit,RuntimeError])
def test_uncertain_dispatch_consumed_once_stops(expansion,tmp_path,slot,error):
    def reply(index):
        if index==slot:raise error('SYNTHETICSECRET')
    snap,fake,_,path=run(expansion,tmp_path,reply)
    assert snap['status']=='STOPPED_NO_REPLAY' and snap['requests_consumed']==slot
    assert len(fake.sent)==slot and snap['uncertain_slots']==[slot]
    assert len(snap['pages'])==max(0,slot-2) and not fake._credentials
    with pytest.raises(FileExistsError):Registry(path,{})


@pytest.mark.parametrize('status',[401,403,408,429,500,503])
def test_http_failure_no_retry(expansion,tmp_path,status):
    def reply(slot):
        if slot==3:return dict(status=status,headers={'Retry-After':'60'},body={'message':'SYNTHETICSECRET'})
    snap,fake,_,_=run(expansion,tmp_path,reply)
    assert snap['requests_consumed']==3 and len(snap['pages'])==1 and len(fake.sent)==3
    assert 'SYNTHETICSECRET' not in canonical(snap)


def test_interruption_before_and_after_accounting(expansion,tmp_path):
    count=0
    def boundary():
        nonlocal count
        count+=1
        if count==3:raise KeyboardInterrupt
    snap,fake,_,_=run(expansion,tmp_path,before=boundary)
    assert snap['requests_consumed']==1 and not fake.sent and snap['uncertain_slots']==[1]
    assert snap['status']=='STOPPED_NO_REPLAY'


def test_stop_before_authentication_burns_zero_request_operation(expansion,tmp_path):
    def stop():raise KeyboardInterrupt
    snap,fake,_,_=run(expansion,tmp_path,before=stop)
    assert snap['requests_consumed']==0 and not fake.sent and snap['status']=='STOPPED_NO_REPLAY'


def test_pacing_deadline_stops_before_another_dispatch(expansion,tmp_path):
    snap,fake,_,_=run(expansion,tmp_path,deadline=.1)
    assert snap['requests_consumed']==2 and len(fake.sent)==2


@pytest.mark.parametrize('change',['retry_after','bad_scope','malformed','bad_token'])
def test_bad_success_envelopes_stop_permanently(expansion,tmp_path,change):
    def reply(slot):
        if change=='bad_token' and slot==1:return dict(status=200,headers={},body=dict(access_token='bad\ntoken',token_type='bearer',expires_in=3600))
        if slot==2:
            if change=='retry_after':return dict(status=200,headers={'Retry-After':'0'},body=dict(items=[]))
            if change=='malformed':return dict(status=200,headers={},body=dict(items='invalid'))
            if change=='bad_scope':
                item=raw_item();item['summaries'][0]['marketplaceId']='OTHER'
                return dict(status=200,headers={},body=dict(items=[item]))
    snap,_,_,_=run(expansion,tmp_path,reply)
    assert snap['status']=='STOPPED_NO_REPLAY' and snap['requests_consumed']==(1 if change=='bad_token' else 2)


@pytest.mark.parametrize('url',[
 'http://sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items',
 'https://sellingpartnerapi-na.amazon.com:443/catalog/2022-04-01/items',
 'https://evil.example/catalog/2022-04-01/items',
 'https://sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items/B000001001',
 'https://sellingpartnerapi-na.amazon.com/listings/2021-08-01/restrictions'])
def test_endpoint_allowlist(url):
    t=Transport(CREDS);t._access='SYNTHETICACCESS'
    with pytest.raises(ValueError):t.validate_slot(Request(url,headers={'x-amz-access-token':'SYNTHETICACCESS'}),2)


@pytest.mark.parametrize('key,value',[('pageToken','NEXT'),('identifiers','B000001001'),('sellerId','SELLER'),
    ('keywords','plant support clips'),('marketplaceIds','OTHER')])
def test_exact_query_allowlist(key,value):
    from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
    t=Transport(CREDS);t._access='SYNTHETICACCESS';parts=urlsplit(t.build_slot(2).full_url)
    params=dict(parse_qsl(parts.query));params[key]=value
    req=Request(urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(params),'')),headers={'x-amz-access-token':'SYNTHETICACCESS'})
    with pytest.raises(ValueError):t.validate_slot(req,2)


def test_extra_host_header_and_slot_bounds():
    t=Transport(CREDS);t._access='SYNTHETICACCESS';req=t.build_slot(2);req.add_header('Host','evil.example')
    with pytest.raises(ValueError):t.validate_slot(req,2)
    for slot in (0,22,True):
        with pytest.raises(ValueError):t.build_slot(slot)


def test_registry_accounting_order_and_strict_ceiling(expansion,tmp_path):
    r=Registry(tmp_path/'registry.sqlite3',dict(preflight=expansion['prepared'].report))
    with pytest.raises(ValueError):r.consume(1)
    r.start()
    with pytest.raises(sqlite3.IntegrityError):r.start()
    with pytest.raises(ValueError):r.consume(2)
    for slot in range(1,22):
        r.consume(slot)
        with pytest.raises(ValueError):r.consume(slot)
        page=None if slot==1 else dict(query_reference=policy.requests()[slot-2]['query_id'],page_index=0,page_token=None,
            operation_id=policy.OPERATION,request_slot=slot,response_sha256='a'*64,
            request_definition_sha256=fingerprint(policy.requests()[slot-2]),
            manifest_sha256=expansion['prepared'].report['manifest_sha256'],
            marketplace_id=expansion['prepared'].report['marketplace_id'],http_status=200,items=[],pagination={},
            observed_at=datetime.now(timezone.utc).isoformat())
        r.response(slot,page,'a'*64)
    with pytest.raises(ValueError):r.consume(22)
    r.finish(True)
    with pytest.raises(ValueError):r.consume(21)
    r.close()


def test_hard_kill_persists_uncertain_claim(tmp_path):
    path=tmp_path/'killed.sqlite3'
    script="from pathlib import Path;import os,signal,sys;from app.m75_registry import Registry;r=Registry(Path(sys.argv[1]),{});r.start();r.consume(1);os.kill(os.getpid(),signal.SIGKILL)"
    result=subprocess.run([sys.executable,'-c',script,str(path)],capture_output=True)
    assert result.returncode==-9
    snap=inspect(path);assert snap['requests_consumed']==1 and snap['status']=='UNCERTAIN_NO_REPLAY'
    assert snap['uncertain_slots']==[1]
    with pytest.raises(FileExistsError):Registry(path,{})


def test_missing_flags_and_permission_no_state(expansion,tmp_path):
    e=expansion
    with pytest.raises(ValueError):execution.execute(e['directory'],e['evidence'],tmp_path/'missing','a'*64,execute_live=False)
    with pytest.raises(ValueError):execution.execute(e['directory'],e['evidence'],tmp_path/'missing','a'*64,execute_live=True)
    assert not (e['private']/policy.REGISTRY).exists()


def test_full_gated_execution_synthetic_only_no_historical_mutations(expansion,monkeypatch):
    e=expansion;auth=e['private']/'m75-owner-authorization-synthetic.json';write(auth,permission(e))
    sent=[]
    class Synthetic(Transport):
        def send_slot(self,req,slot):
            self.validate_slot(req,slot);snap=inspect(e['private']/policy.REGISTRY)
            assert snap['requests_consumed']==slot;sent.append(slot)
            body=dict(access_token='SYNTHETICACCESS',token_type='bearer',expires_in=3600) if slot==1 else dict(items=[raw_item(1002)])
            return dict(status=200,headers={},body=body)
    clock=Clock();monkeypatch.setattr(execution,'Transport',Synthetic)
    monkeypatch.setattr(execution,'OperationPacer',lambda **kw:OperationPacer(**kw,monotonic=clock.time,sleep=clock.sleep))
    protected=list(e['directory'].iterdir())+list(e['evidence']['m73_dir'].iterdir())
    before={p:sha256(p) for p in protected}
    result=execution.execute(e['directory'],e['evidence'],auth,sha256(auth),execute_live=True)
    assert result['requests_consumed']==21 and result['distinct_new_asins']==1
    assert sent==list(range(1,22)) and before=={p:sha256(p) for p in protected}
    with pytest.raises(ValueError):execution.execute(e['directory'],e['evidence'],auth,sha256(auth),execute_live=True)
    assert len(sent)==21


def test_global_lock_contention_blocks_before_claim(expansion):
    import fcntl,os
    e=expansion;path=e['private']/'m75-owner-authorization-synthetic.json';write(path,permission(e))
    fd=os.open(e['private']/'candidate-execution.lock',os.O_RDWR)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):execution.execute(e['directory'],e['evidence'],path,sha256(path),execute_live=True)
        assert not (e['private']/policy.REGISTRY).exists()
    finally:os.close(fd)


@pytest.mark.parametrize('name',['M74_query_manifest.json','M74_M75_contract_proposal.json','M74_evidence_digests.json','M74_discovery_plan.xlsx'])
def test_frozen_plan_file_drift_blocks(expansion,name):
    e=expansion;p=e['directory']/name;p.write_bytes(p.read_bytes()+b' ')
    with pytest.raises(ValueError):policy.preflight(e['directory'],e['evidence'])
    assert not (e['private']/policy.REGISTRY).exists()


def test_existing_even_empty_registry_permanently_blocks(expansion):
    e=expansion;p=e['private']/policy.REGISTRY;p.touch(mode=0o600)
    with pytest.raises(ValueError):policy.preflight(e['directory'],e['evidence'])


def test_guard_under_lock_detects_new_history_evidence(expansion):
    e=expansion;write(e['private']/'selected-validation-new.json',dict(asin='B000001001',requests_attempted=1))
    with pytest.raises(ValueError):e['prepared'].guard()


def test_registry_tampering_and_immutability(expansion,tmp_path):
    snap,_,_,path=run(expansion,tmp_path)
    db=sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM m75_operation')
    with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE m75_events SET payload=payload')
    db.execute('DROP TRIGGER immutable_m75_events_UPDATE');db.execute("UPDATE m75_events SET payload='{}' WHERE kind='ATTEMPT'")
    db.commit();db.close()
    with pytest.raises(ValueError):inspect(path)


def test_privacy_in_saved_products(expansion,tmp_path):
    def reply(slot):
        if slot>1:
            item=raw_item();item['sellerId']='OTHERPRIVATESELLER'
            item['summaries'][0]['modelNumber']='SYNTHETICSELLER'
            item['attributes']['private_copy']=[dict(value='OTHERPRIVATESELLER')]
            return dict(status=200,headers={},body=dict(items=[item],access_token='SYNTHETICACCESS'))
    snap,_,_,_=run(expansion,tmp_path,reply)
    assert all(value not in canonical(snap) for value in ('OTHERPRIVATESELLER','SYNTHETICSELLER','SYNTHETICACCESS'))


def cli(e):
    args=['--m74-dir',str(e['directory'])]
    for name,value in e['evidence'].items():args += ['--'+name.replace('_','-'),str(value)]
    return args


def test_cli_dryrun_and_missing_execute_gates(expansion,tmp_path):
    e=expansion;args=cli(e)
    assert m75.main(['dry-run',*args,'--output',str(tmp_path/'review.json')])==0
    assert m75.main(['execute',*args])==2 and m75.main(['execute',*args,'--execute-live'])==2
    assert m75.main(['authorize',*args,'--output',str(e['private']/'m75-owner-authorization-no.json')])==2
    assert not (e['private']/policy.REGISTRY).exists() and not list(e['private'].glob('m75-owner-authorization-*'))


def test_import_and_help_do_not_load_executor_or_credentials():
    script="import sys;sys.modules['app.amazon_pilot']=None;sys.modules['app.m75_execution']=None;from app.m75 import main;main(['--help'])"
    result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True)
    assert result.returncode==0 and '--execute-live' in result.stdout


def synthetic_execute(e,monkeypatch,callback=None):
    path=e['private']/'m75-owner-authorization-synthetic.json';write(path,permission(e))
    sent=[]
    class Synthetic(Transport):
        def send_slot(self,request,slot):
            self.validate_slot(request,slot);assert inspect(e['private']/policy.REGISTRY)['requests_consumed']==slot
            sent.append(slot)
            if callback:callback(slot,path)
            body=dict(access_token='SYNTHETICACCESS',token_type='bearer',expires_in=3600) if slot==1 else dict(items=[raw_item(1002)])
            return dict(status=200,headers={},body=body)
    clock=Clock();monkeypatch.setattr(execution,'Transport',Synthetic)
    monkeypatch.setattr(execution,'OperationPacer',lambda **kw:OperationPacer(**kw,monotonic=clock.time,sleep=clock.sleep))
    return execution.execute(e['directory'],e['evidence'],path,sha256(path),execute_live=True),sent


def test_credential_content_drift_with_preserved_metadata_fails_before_claim(expansion):
    import os
    e=expansion;auth=e['private']/'m75-owner-authorization-synthetic.json';write(auth,permission(e))
    p=e['private']/'credentials.json';stat=p.stat();data=p.read_bytes()
    p.write_bytes(data.replace(CREDS['client_id'].encode(),b'X'*len(CREDS['client_id'])))
    os.utime(p,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    with pytest.raises(ValueError):execution.execute(e['directory'],e['evidence'],auth,sha256(auth),execute_live=True)
    assert not (e['private']/policy.REGISTRY).exists()


@pytest.mark.parametrize('kind',['authorization','credentials'])
def test_mid_run_revocation_stops_preserves_partial_no_replay(expansion,monkeypatch,kind):
    e=expansion
    def drift(slot,auth):
        if slot==2:
            p=auth if kind=='authorization' else e['private']/'credentials.json'
            p.write_bytes(p.read_bytes()+b' ')
    result,sent=synthetic_execute(e,monkeypatch,drift)
    assert result['status']=='STOPPED_NO_REPLAY' and result['requests_consumed']==2 and sent==[1,2]
    assert result['successful_keyword_pages']==1
    with pytest.raises(ValueError):policy.preflight(e['directory'],e['evidence'])


def test_recovery_report_reads_no_authorization_or_credentials(expansion,tmp_path,monkeypatch):
    import shutil
    e=expansion;snap,_,_,path=run(e,tmp_path)
    shutil.copy2(path,e['private']/policy.REGISTRY)
    def forbidden(*a,**kw):raise AssertionError('Recovery must be read-only and credential-free')
    monkeypatch.setattr(execution,'execute',forbidden);monkeypatch.setattr(execution,'private_json',forbidden)
    assert m75.main(['report',*cli(e),'--output',str(tmp_path/'recovery')])==0
    report=json.loads((tmp_path/'recovery/M75_summary.json').read_text())
    assert report['requests_consumed']==21 and report['checkpoint_sha256']==snap['checkpoint_sha256']


@pytest.mark.parametrize('failure',['tty','seller','ack','warning'])
def test_interactive_authorization_failures_create_no_artifact(expansion,tmp_path,monkeypatch,failure):
    import warnings
    e=expansion;review=tmp_path/'review.json';write(review,e['prepared'].report)
    monkeypatch.setattr(m75.sys.stdin,'isatty',lambda:failure!='tty')
    seller=json.loads((e['private']/'m67-account-context.json').read_text())['seller_id']
    def hidden(*a,**kw):
        if failure=='warning':warnings.warn('fallback unavailable',m75.getpass.GetPassWarning)
        return 'WRONG' if failure=='seller' else seller
    monkeypatch.setattr(m75.getpass,'getpass',hidden)
    monkeypatch.setattr('builtins.input',lambda prompt:'WRONG' if failure=='ack' else 'AUTHORIZE M75 21 REQUESTS NO REPLAY')
    out=e['private']/'m75-owner-authorization-synthetic.json'
    assert m75.main(['authorize',*cli(e),'--reviewed-preflight',str(review),'--preflight-sha256',file_hash(review),
        '--review-reference','manual:synthetic-test','--output',str(out)])==2
    assert not out.exists() and not (e['private']/policy.REGISTRY).exists()


def test_synthetic_interactive_authorization_and_code_binding(expansion,tmp_path,monkeypatch):
    e=expansion;review=tmp_path/'review.json';write(review,e['prepared'].report)
    monkeypatch.setattr(m75.sys.stdin,'isatty',lambda:True)
    seller=json.loads((e['private']/'m67-account-context.json').read_text())['seller_id']
    monkeypatch.setattr(m75.getpass,'getpass',lambda prompt:seller)
    monkeypatch.setattr('builtins.input',lambda prompt:'AUTHORIZE M75 21 REQUESTS NO REPLAY')
    out=e['private']/'m75-owner-authorization-synthetic.json'
    assert m75.main(['authorize',*cli(e),'--reviewed-preflight',str(review),'--preflight-sha256',file_hash(review),
        '--review-reference','manual:synthetic-test','--output',str(out)])==0
    check(json.loads(out.read_text()),e['prepared'].report)
    assert out.stat().st_mode&0o777==0o600 and not (e['private']/policy.REGISTRY).exists()
    monkeypatch.setattr(policy,'implementation',lambda:{'changed.py':'f'*64})
    with pytest.raises(ValueError):e['prepared'].guard()


def test_token_expiry_never_refreshes(expansion,tmp_path):
    def reply(slot):
        if slot==1:return dict(status=200,headers={},body=dict(access_token='SYNTHETICACCESS',token_type='bearer',expires_in=1))
    snap,fake,_,_=run(expansion,tmp_path,reply)
    assert snap['status']=='STOPPED_NO_REPLAY' and snap['requests_consumed']==2 and len(fake.sent)==2


def test_cursor_cannot_persist_known_credentials(expansion,tmp_path):
    def reply(slot):
        if slot>1:return dict(status=200,headers={},body=dict(items=[raw_item()],pagination={'nextToken':'SYNTHETICACCESS'}))
    snap,_,_,_=run(expansion,tmp_path,reply)
    assert 'SYNTHETICACCESS' not in canonical(snap)
    assert snap['pages'][0]['pagination']['nextToken']=='[REDACTED]'


def test_transport_uses_existing_tls_primitive_only(monkeypatch):
    from app import amazon_pilot
    class Reply(dict):http_status=200;rate_headers={}
    calls=[]
    def send(request):
        calls.append(request.full_url);return Reply(access_token='SYNTHETICACCESS',token_type='bearer',expires_in=3600)
    monkeypatch.setattr(amazon_pilot,'_request_json',send)
    transport=Transport(CREDS)
    reply=transport.send_slot(transport.build_slot(1),1)
    transport.accept_authentication(reply['body'])
    assert calls==['https://api.amazon.com/auth/o2/token'] and reply['status']==200
    assert transport.scope(21)[1]['keywords']==policy.requests()[-1]['parameters']['keywords']
    transport.clear()


def test_lower_response_rate_stops_at_deadline_without_retry(expansion,tmp_path):
    def reply(slot):
        if slot>1:return dict(status=200,headers={'x-amzn-RateLimit-Limit':'.01'},body=dict(items=[]))
    snap,fake,_,_=run(expansion,tmp_path,reply)
    assert snap['requests_consumed']==2 and len(fake.sent)==2 and snap['status']=='STOPPED_NO_REPLAY'


def test_authentication_payload_cannot_be_persisted(tmp_path):
    r=Registry(tmp_path/'auth.sqlite3',{});r.start();r.consume(1)
    with pytest.raises(ValueError):r.response(1,dict(access_token='SYNTHETICACCESS'),'a'*64)
    r.finish(False);r.close()
    assert 'SYNTHETICACCESS' not in canonical(inspect(tmp_path/'auth.sqlite3'))
