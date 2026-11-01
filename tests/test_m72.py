"""Synthetic offline security fixtures only; never authorize or call a real account."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import csv
import json
from pathlib import Path
import sqlite3
from urllib.request import Request

import pytest
from test_m69 import fixture as history_fixture,offline,write,protected
from test_m67 import cohort
from test_m70 import raw_item
from test_m71 import Clock
from app import m72,m72_policy as policy,m72_execution as execution,m72_reporting as reporting
from app.m72_registry import Registry,inspect
from app.m72_transport import PilotTransport
from app.m71_manifest import prepare
from app.m65_intelligence import sha256
from app.observations import fingerprint,canonical

CREDS=dict(client_id='SYNTHETICCLIENT',client_secret='SYNTHETICSECRET',refresh_token='SYNTHETICREFRESH')


@pytest.fixture
def pilot(history_fixture,tmp_path,monkeypatch):
    c=history_fixture
    from app.m69_history import consolidate
    h=consolidate(c['private'],c['store_path'],c['path'],c['digest'],[])
    db=sqlite3.connect(c['ledger'])
    for i in range(97-len(h['excluded_asins'])):
        db.execute('INSERT INTO m67_claims VALUES (?,?)',(f'B{10000+i:09d}',c['digest']))
    db.commit();db.close()
    write(c['private']/'credentials.json',CREDS)
    context_path=c['private']/'m67-account-context.json';context=json.loads(context_path.read_text())
    context['credentials_sha256']=sha256(c['private']/'credentials.json');write(context_path,context)
    proposal=prepare(c['private'],c['store_path'],c['path'],c['digest'])
    source=tmp_path/'M71_manifest.json';write(source,proposal)
    for module in (policy,m72,execution,reporting):
        monkeypatch.setattr(module,'PROPOSAL_SHA256',proposal['proposal_sha256'],raising=False)
        monkeypatch.setattr(module,'MANIFEST_SHA256',sha256(source),raising=False)
    baseline=tmp_path/'M70_catalog_1000.csv'
    with baseline.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['asin','identity_complete','eligibility','source_sha256']);w.writeheader()
        w.writerow(dict(asin='B000001000',identity_complete=False,eligibility='UNKNOWN',source_sha256='a'*64))
    args=(source,c['store_path'],c['private'],c['path'],c['digest'],baseline)
    report=policy.preflight(*args)
    c.update(proposal=proposal,proposal_path=source,baseline=baseline,args=args,report=report)
    return c


def auth(c,now=None):
    # Synthetic in-memory authorization only. No production artifact is created.
    return policy.owner_authorization(c['report'],'manual:synthetic-test-only',now=now)


class Fake(PilotTransport):
    def __init__(self,registry,reply=None):
        super().__init__(CREDS,seller_id='SYNTHETICSELLER');self.registry=registry;self.requests=[];self.reply=reply
    def send_slot(self,req,slot):
        self.validate_slot(req,slot)
        assert self.registry.count()==slot
        self.requests.append(req.full_url)
        if slot==1:body=dict(access_token='SYNTHETICACCESS',token_type='bearer',expires_in=3600)
        elif self.reply is not None:return self.reply(req,slot)
        else:body=dict(items=[raw_item(1000),raw_item(1001),raw_item(0)],pagination={'nextToken':'PRIVATECURSOR'})
        return dict(status=200,headers={},body=body)


def run(c,tmp_path,reply=None,before=lambda:None,deadline=120):
    path=tmp_path/'run.sqlite3'
    registry=Registry(path,dict(operation_id=policy.OPERATION,preflight=c['report'],authorization_sha256='a'*64))
    fake=Fake(registry,reply);clock=Clock()
    from app.amazon_pacing import OperationPacer
    pacer=OperationPacer(headroom=.5,monotonic=clock.time,sleep=clock.sleep)
    execution.run_claimed(registry,fake,c['proposal'],c['report'],before_request=before,pacer=pacer,
        deadline=deadline,monotonic=clock.time)
    registry.close()
    return inspect(path),fake,clock,path


def test_pinned_preflight_readonly_no_credentials_or_registry(pilot,monkeypatch):
    c=pilot;before=protected(c);calls=[];original=policy.private_json
    def read(path):calls.append(path.name);assert path.name!='credentials.json';return original(path)
    monkeypatch.setattr(policy,'private_json',read)
    assert policy.preflight(*c['args'])==c['report']
    assert protected(c)==before and calls==['m67-account-context.json']
    assert not (c['private']/policy.REGISTRY).exists()
    assert not (c['private']/policy.RESULTS).exists()
    assert c['report']['historical_exclusions']==97 and c['report']['checked_eligibility_asins']==40
    assert [q['id'] for q in c['report']['queries']]==[f'q{i:03}' for i in range(1,10)]
    assert c['report']['budget']['total']==10 and c['report']['actual_requests']==0


@pytest.mark.parametrize('key,value',[
 ('approved',False),('execution_permission',False),('operation_id','M67'),('proposal_sha256','b'*64),
 ('manifest_file_sha256','c'*64),('account_reference','OTHER'),('marketplace_id','OTHER'),
 ('account_binding_sha256','d'*64),('preflight_sha256','e'*64),('implementation_sha256',{}),
 ('no_retry',False),('no_replay',False),('query_ids',['q010']),('schema',True),('mode','M67_AUTHORIZATION'),
 ('review_reference','owner secret text')])
def test_authorization_exact_scope_required(pilot,key,value):
    a=auth(pilot);a[key]=value
    with pytest.raises(ValueError):policy.check_authorization(a,pilot['report'])


@pytest.mark.parametrize('key,value',[('total',11),('keyword',10),('authentication',2),('identifier',1),
 ('pages',1),('retries',1),('refreshes',1),('restrictions',1),('pricing',1),('fees',1),('fba',1),('listings',1),
 ('purchases',1),('approvals',1),('authentication',True)])
def test_no_budget_expansion_or_other_operations(pilot,key,value):
    a=auth(pilot);a['budget'][key]=value
    with pytest.raises(ValueError):policy.check_authorization(a,pilot['report'])


@pytest.mark.parametrize('which',['expired','future','long','naive','missing'])
def test_fresh_short_lived_authorization_only(pilot,which):
    now=datetime.now(timezone.utc);a=auth(pilot,now)
    if which=='expired':a['expires_at']=(now-timedelta(seconds=1)).isoformat()
    elif which=='future':a['reviewed_at']=(now+timedelta(seconds=1)).isoformat()
    elif which=='long':a['expires_at']=(now+timedelta(minutes=16)).isoformat()
    elif which=='naive':a['reviewed_at']=now.replace(tzinfo=None).isoformat()
    else:a.pop('no_replay')
    with pytest.raises(ValueError):policy.check_authorization(a,pilot['report'],now)


def test_ten_requests_first_pages_only_partial_m70_quality(pilot,tmp_path):
    snapshot,fake,clock,path=run(pilot,tmp_path)
    assert snapshot['status']=='COMPLETED_NO_REPLAY' and snapshot['requests_consumed']==10
    assert len(snapshot['pages'])==9 and all(p['page_index']==0 for p in snapshot['pages'])
    assert len(fake.requests)==10 and not any('pageToken=' in q or 'identifiers=' in q for q in fake.requests)
    assert len(clock.sleeps)==8 and sum(clock.sleeps)>=8
    assert not fake._credentials and fake._access is None
    out=tmp_path/'export';report=reporting.export(snapshot,pilot['proposal'],{'B000001000'},out)
    assert report['distinct_new_asins']==1 and report['distinct_unclaimed_asins']==2
    assert report['distinct_excluded_asins']==1 and report['historical_exclusions']==97
    assert report['duplicate_observations']==24 and report['identity_complete']==0
    assert report['source_coverage']['sources'][0]['partial_query_windows']==9
    assert report['eligibility']=='UNKNOWN' and report['new_asin_reservations']==0
    assert all(secret not in canonical(report) for secret in [*CREDS.values(),'SYNTHETICACCESS','PRIVATECURSOR'])
    assert all(p.stat().st_mode&0o777==0o600 for p in out.iterdir())
    with pytest.raises(FileExistsError):Registry(path,{})


@pytest.mark.parametrize('status',[401,403,408,429,500,503])
def test_failures_burn_slot_stop_no_retry(pilot,tmp_path,status):
    snapshot,fake,_,path=run(pilot,tmp_path,lambda *a:dict(status=status,headers={'Retry-After':'60'},body={'secret':'SYNTHETICSECRET'}))
    assert snapshot['requests_consumed']==2 and snapshot['status']=='STOPPED_NO_REPLAY'
    assert snapshot['uncertain_slots']==[2] and len(fake.requests)==2 and not snapshot['pages']
    assert 'SYNTHETICSECRET' not in canonical(snapshot)


@pytest.mark.parametrize('error',[KeyboardInterrupt,SystemExit,TimeoutError,RuntimeError])
def test_interrupted_uncertain_dispatch_no_replay(pilot,tmp_path,error):
    def reply(*args):raise error('SYNTHETICSECRET')
    snapshot,fake,_,path=run(pilot,tmp_path,reply)
    assert snapshot['requests_consumed']==2 and snapshot['uncertain_slots']==[2]
    assert snapshot['status']=='STOPPED_NO_REPLAY' and not fake._credentials
    with pytest.raises(FileExistsError):Registry(path,{})


def test_interruption_before_authentication_burns_operation_not_request(pilot,tmp_path):
    def stop():raise KeyboardInterrupt
    snapshot,fake,_,path=run(pilot,tmp_path,before=stop)
    assert snapshot['requests_consumed']==0 and snapshot['status']=='STOPPED_NO_REPLAY' and not fake.requests
    with pytest.raises(FileExistsError):Registry(path,{})


def test_deadline_during_pacing_stops_before_new_dispatch(pilot,tmp_path):
    snapshot,fake,_,_=run(pilot,tmp_path,deadline=.1)
    assert snapshot['requests_consumed']==2 and len(fake.requests)==2


def test_hard_kill_checkpoint_uncertain_and_immutable(pilot,tmp_path):
    path=tmp_path/'hard-kill.sqlite3';r=Registry(path,dict(preflight=pilot['report']))
    r.consume(1,'a'*64);r.close()
    before=sha256(path);snap=inspect(path)
    assert snap['status']=='UNCERTAIN_NO_REPLAY' and snap['uncertain_slots']==[1]
    assert sha256(path)==before
    with pytest.raises(FileExistsError):Registry(path,{})
    db=sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM m72_operation')
    with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE m72_events SET payload=payload')
    db.close()


def test_registry_strict_order_budget_and_terminal(pilot,tmp_path):
    r=Registry(tmp_path/'r.sqlite3',dict(preflight=pilot['report']))
    with pytest.raises(ValueError):r.consume(2,'a'*64)
    for slot in range(1,11):
        r.consume(slot,'a'*64)
        with pytest.raises(ValueError):r.consume(slot,'a'*64)
        r.response(slot,None,'b'*64)
    with pytest.raises(ValueError):r.consume(11,'a'*64)
    r.finish(True)
    with pytest.raises(ValueError):r.consume(11,'a'*64)
    r.close()


@pytest.mark.parametrize('url',[
 'http://sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items',
 'https://sellingpartnerapi-na.amazon.com:443/catalog/2022-04-01/items',
 'https://evil.example/catalog/2022-04-01/items',
 'https://sellingpartnerapi-na.amazon.com/listings/2021-08-01/restrictions',
 'https://sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items/B000001000'])
def test_endpoint_allowlisting(url):
    transport=PilotTransport(CREDS);transport._access='SYNTHETICACCESS'
    with pytest.raises(ValueError):transport.validate_slot(Request(url),2)


@pytest.mark.parametrize('parameter,value',[('pageToken','NEXT'),('identifiers','B000001000'),('sellerId','SELLER'),
 ('marketplaceIds','OTHER'),('keywords','unreviewed keyword'),('productTypes','TYPE')])
def test_no_extra_pages_queries_or_scope_parameters(parameter,value):
    from urllib.parse import parse_qsl,urlencode,urlsplit,urlunsplit
    t=PilotTransport(CREDS);t._access='SYNTHETICACCESS';req=t.build_slot(2);parts=urlsplit(req.full_url)
    params=dict(parse_qsl(parts.query));params[parameter]=value
    changed=Request(urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(params),'')),headers={'x-amz-access-token':'SYNTHETICACCESS'})
    with pytest.raises(ValueError):t.validate_slot(changed,2)


def test_throttle_success_header_stops(pilot,tmp_path):
    snap,_,_,_=run(pilot,tmp_path,lambda *a:dict(status=200,headers={'Retry-After':'2'},body=dict(items=[])))
    assert snap['requests_consumed']==2 and snap['status']=='STOPPED_NO_REPLAY'


def test_invalid_page_scope_preserves_previous_success(pilot,tmp_path):
    def reply(req,slot):
        item=raw_item(1001)
        if slot==3:item['summaries'][0]['marketplaceId']='OTHER'
        return dict(status=200,headers={},body=dict(items=[item]))
    snap,_,_,_=run(pilot,tmp_path,reply)
    assert snap['requests_consumed']==3 and len(snap['pages'])==1 and snap['uncertain_slots']==[3]


def test_current_file_and_history_drift_blocked_before_accounting(pilot):
    c=pilot;original=c['proposal_path'].read_bytes();c['proposal_path'].write_bytes(original+b' ')
    with pytest.raises(ValueError):policy.preflight(*c['args'])
    c['proposal_path'].write_bytes(original)
    context=c['private']/'m67-account-context.json';doc=json.loads(context.read_text());doc['marketplace_id']='OTHER';write(context,doc)
    with pytest.raises(ValueError):policy.preflight(*c['args'])


def test_permanent_registry_blocks_new_authorization_or_changed_output(pilot):
    c=pilot;r=Registry(c['private']/policy.REGISTRY,dict(preflight=c['report']));r.finish(False);r.close()
    with pytest.raises(ValueError):policy.preflight(*c['args'])


def test_cli_dryrun_no_auth_and_execute_requires_both_gates(pilot,tmp_path,capsys):
    c=pilot;args=['--proposal',str(c['proposal_path']),'--store',str(c['store_path']),'--private',str(c['private']),
        '--m67-manifest',str(c['path']),'--m67-sha256',c['digest'],'--baseline-catalog',str(c['baseline'])]
    out=tmp_path/'preflight.json'
    assert m72.main(['dry-run',*args,'--output',str(out)])==0
    assert not (c['private']/policy.REGISTRY).exists()
    assert not list(c['private'].glob('m72-owner-authorization-*'))
    assert m72.main(['execute',*args])==2
    assert m72.main(['execute',*args,'--execute-live'])==2
    assert m72.main(['dry-run',*args,'--execute-live','--output',str(tmp_path/'bad')])==2
    assert m72.main(['authorize',*args,'--output',str(c['private']/'m72-owner-authorization-test.json')])==2
    assert 'SYNTHETICSECRET' not in capsys.readouterr().out


def test_execute_missing_flag_or_authorization_creates_no_live_state(pilot,tmp_path):
    c=pilot
    with pytest.raises(ValueError):execution.execute(*c['args'],tmp_path/'absent','a'*64,execution_flag=False)
    with pytest.raises(FileNotFoundError):execution.execute(*c['args'],tmp_path/'absent','a'*64,execution_flag=True)
    assert not (c['private']/policy.REGISTRY).exists()


def test_production_gate_runs_under_lock_with_only_synthetic_transport(pilot,monkeypatch,tmp_path):
    c=pilot;a=auth(c);authorization=c['private']/'m72-owner-authorization-synthetic.json';write(authorization,a)
    sent=[]
    class Synthetic(PilotTransport):
        def send_slot(self,req,slot):
            self.validate_slot(req,slot)
            snapshot=inspect(c['private']/policy.REGISTRY)
            assert snapshot['requests_consumed']==slot
            sent.append(slot)
            body=dict(access_token='SYNTHETICACCESS',token_type='bearer',expires_in=3600) if slot==1 else dict(items=[raw_item(1001)])
            return dict(status=200,headers={},body=body)
    from app.amazon_pacing import OperationPacer
    clock=Clock()
    monkeypatch.setattr(execution,'PilotTransport',Synthetic)
    monkeypatch.setattr(execution,'OperationPacer',lambda **kw:OperationPacer(**kw,monotonic=clock.time,sleep=clock.sleep))
    before=protected(c)
    result=execution.execute(*c['args'],authorization,sha256(authorization),execution_flag=True)
    assert result['requests_consumed']==10 and sent==list(range(1,11))
    assert result['distinct_new_asins']==1 and protected(c)==before
    with pytest.raises(ValueError):execution.execute(*c['args'],authorization,sha256(authorization),execution_flag=True)
    assert sent==list(range(1,11))


def test_global_account_lock_blocks_synthetic_execution_before_claim(pilot,tmp_path):
    import fcntl,os
    c=pilot;a=auth(c);authorization=c['private']/'m72-owner-authorization-synthetic.json';write(authorization,a)
    lock=os.open(c['private']/'candidate-execution.lock',os.O_WRONLY|os.O_CREAT,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):execution.execute(*c['args'],authorization,sha256(authorization),execution_flag=True)
        assert not (c['private']/policy.REGISTRY).exists()
    finally:os.close(lock)


def test_credential_content_mismatch_fails_after_auth_before_registry(pilot,tmp_path):
    c=pilot;a=auth(c);authorization=c['private']/'m72-owner-authorization-synthetic.json';write(authorization,a)
    # Preserve metadata by changing the stored binding to the wrong hash before
    # deriving the new report/authorization, so the live content comparison is tested.
    context=c['private']/'m67-account-context.json';doc=json.loads(context.read_text());doc['credentials_sha256']='f'*64;write(context,doc)
    c['report']=policy.preflight(*c['args']);write(authorization,auth(c))
    with pytest.raises(ValueError):execution.execute(*c['args'],authorization,sha256(authorization),execution_flag=True)
    assert not (c['private']/policy.REGISTRY).exists()


def test_authorization_expiry_or_drift_after_auth_stops_before_next_slot(pilot,tmp_path):
    calls=0
    def revalidate():
        nonlocal calls
        calls+=1
        if calls>=3:raise ValueError('SYNTHETICSECRET authorization expired')
    snapshot,fake,_,_=run(pilot,tmp_path,before=revalidate)
    assert snapshot['requests_consumed']==1 and snapshot['status']=='STOPPED_NO_REPLAY'


def test_registry_tampering_or_missing_file_cannot_be_treated_as_unused(pilot,tmp_path):
    snapshot,_,_,path=run(pilot,tmp_path)
    db=sqlite3.connect(path);db.execute('DROP TRIGGER immutable_m72_events_UPDATE')
    db.execute("UPDATE m72_events SET payload='{}' WHERE kind='ATTEMPT'");db.commit();db.close()
    with pytest.raises(ValueError):inspect(path)
    corrupt=pilot['private']/policy.REGISTRY;corrupt.write_bytes(b'');corrupt.chmod(0o600)
    with pytest.raises(ValueError):policy.preflight(*pilot['args'])


def test_credentials_account_tokens_redacted_in_catalog_and_summary(pilot,tmp_path):
    def reply(req,slot):
        item=raw_item(1001);item['sellerId']='OTHERPRIVATESELLER'
        item['summaries'][0]['modelNumber']='SYNTHETICSELLER'
        item['attributes']['private_copy']=[dict(value='OTHERPRIVATESELLER')]
        return dict(status=200,headers={},body=dict(items=[item],access_token='SYNTHETICACCESS'))
    snapshot,_,_,_=run(pilot,tmp_path,reply)
    text=canonical(snapshot)
    assert 'SYNTHETICSELLER' not in text and 'OTHERPRIVATESELLER' not in text and 'SYNTHETICACCESS' not in text


def test_transport_uses_only_existing_bounded_tls_primitive(monkeypatch):
    from app import amazon_pilot
    class Reply(dict):
        http_status=200;rate_headers={}
    calls=[]
    def send(req):calls.append(req.full_url);return Reply(access_token='SYNTHETICACCESS',token_type='bearer',expires_in=3600)
    monkeypatch.setattr(amazon_pilot,'_request_json',send)
    transport=PilotTransport(CREDS)
    reply=transport.send_slot(transport.build_slot(1),1)
    assert len(calls)==1 and reply['status']==200
    transport.accept_authentication(reply['body'])
    for slot in (0,11,True):
        with pytest.raises(ValueError):transport.build_slot(slot)
    assert len(calls)==1


def test_help_and_dry_import_do_not_load_credentials_transport_or_executor():
    import subprocess,sys
    script="import sys;sys.modules['app.amazon_pilot']=None;sys.modules['app.m72_execution']=None;from app.m72 import main;main(['--help'])"
    result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True)
    assert result.returncode==0 and '--execute-live' in result.stdout


def test_raw_asin_counts_survive_identity_import_rejections(pilot,tmp_path):
    snapshot,_,_,_=run(pilot,tmp_path,lambda *a:dict(status=200,headers={},body=dict(items=[dict(asin='B000001001'),dict(asin='B000000000')])) )
    report=reporting.export(snapshot,pilot['proposal'],set(),tmp_path/'quality')
    assert report['distinct_new_asins']==1 and report['distinct_excluded_asins']==1
    assert report['returned_product_observations']==18 and report['normalized_product_observations']==0
    assert report['missing_fields']['model']==1 and report['identity_complete']==0


def test_locked_history_inventory_detects_new_attempt_file(pilot):
    c=pilot;write(c['private']/'selected-validation-new.json',dict(asin='B000001001',requests_attempted=1))
    with pytest.raises(ValueError):policy.preflight(*c['args'],_locked_report=c['report'])
