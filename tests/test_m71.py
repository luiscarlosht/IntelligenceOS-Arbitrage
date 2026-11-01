"""Offline-only injected transport tests; no real authentication or ASIN claims."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from urllib.request import Request

import pytest
from test_m69 import fixture as history_fixture, offline, protected
from test_m67 import cohort
from test_m70 import raw_item
from app import m71, m71_manifest as policy
from app.m71_journal import Journal
from app.m71_adapter import CatalogTransport, parameters, rehearse, save_catalog, validate_page
from app.m70_sources import ingest
from app.m65_intelligence import US, sha256
from app.observations import fingerprint, canonical

CREDS=dict(client_id='PRIVATECLIENT',client_secret='PRIVATESECRET',refresh_token='PRIVATEREFRESH')


@pytest.fixture
def proposal(history_fixture):
    c=history_fixture
    return policy.prepare(c['private'],c['store_path'],c['path'],c['digest'])


class Clock:
    def __init__(self):self.now=0;self.sleeps=[]
    def time(self):return self.now
    def sleep(self,n):self.sleeps.append(n);self.now+=n


class Fake(CatalogTransport):
    def __init__(self,reply=None):
        super().__init__(CREDS);self.requests=[];self.reply=reply;self.journal=None
    def send(self,req):
        assert self.journal.count()==len(self.requests)+1  # before dispatch, including auth
        self.requests.append(req.full_url)
        if req.full_url==policy.AUTH_URL:
            body=dict(access_token='PRIVATEACCESS',expires_in=3600)
        elif self.reply is not None:
            return self.reply(req,len(self.requests))
        else:body=dict(items=[raw_item(1000)],pagination={})
        return dict(status=200,headers={},body=body)


def run(tmp_path,proposal,fake=None,**kwargs):
    journal=Journal(tmp_path/'accounting.sqlite3',proposal)
    fake=fake or Fake();fake.journal=journal;clock=Clock()
    result=rehearse(proposal,journal,fake,monotonic=clock.time,sleep=clock.sleep,**kwargs)
    return result,journal,fake,clock


def resign(doc):
    copy=dict(doc);copy.pop('proposal_sha256',None);doc['proposal_sha256']=fingerprint(copy)
    return doc


def test_deterministic_proposal_history_and_preview(proposal,history_fixture):
    c=history_fixture;before=protected(c)
    assert proposal==policy.prepare(c['private'],c['store_path'],c['path'],c['digest'])
    assert protected(c)==before
    assert len(proposal['queries'])==50 and len({q['category_intent'] for q in proposal['queries']})==10
    assert len({q['keywords'] for q in proposal['queries']})==50
    assert len(proposal['checked_eligibility_asins'])==40
    assert set(proposal['checked_eligibility_asins'])<=set(proposal['excluded_asins'])
    assert all(not q['classification_ids'] and q['product_type_filter'] is None for q in proposal['queries'])
    assert len({q['category_intent'] for q in proposal['queries'][:10]})==10
    text=policy.preview(proposal)
    assert '251' in text and '202' in text and 'pageToken' in text
    from app.m65_ranking import PREVIOUS_SEED_BRANDS
    import re
    assert not any(re.search(r'\b'+re.escape(brand)+r'\b',q['keywords'].casefold()) for q in proposal['queries'] for brand in PREVIOUS_SEED_BRANDS)


@pytest.mark.parametrize('change',[
    dict(execution_authorized=True),dict(live_enabled=True),dict(marketplace='WRONG'),dict(page_size=21),
    dict(maximum_pages_per_query=5),dict(target_distinct_asins=2000),dict(included_data=['pricing']),
    dict(endpoint=dict(method='GET',host=policy.HOST,path='/listings/2021-08-01/restrictions')),
    dict(excluded_asins=[]),dict(checked_eligibility_asins=[]),dict(queries=[]),dict(implementation_sha256={})])
def test_resigned_scope_tampering_rejected(proposal,change):
    doc=deepcopy(proposal);doc.update(change)
    with pytest.raises(ValueError):policy.validate(resign(doc))


@pytest.mark.parametrize('phase,value',[('total',252),('keyword',201),('identifier',51),('authentication',2),
    ('retries',1),('restrictions',1),('pricing',1),('fees',1),('fba',1),('offers',1),('approvals',1),('purchases',1)])
def test_absolute_budget_cannot_be_raised_or_reassigned(proposal,phase,value):
    doc=deepcopy(proposal);doc['budget'][phase]=value
    with pytest.raises(ValueError):policy.validate(resign(doc))


def test_account_before_send_pacing_no_replay_and_m70_import(tmp_path,proposal):
    result,j,fake,clock=run(tmp_path,proposal)
    assert result['status']=='COMPLETED_NO_REPLAY' and result['requests_consumed']==52
    assert result['distinct_unclaimed_asins']==1
    assert len(clock.sleeps)==50 and sum(clock.sleeps)>=50
    assert not fake._credentials and fake._access is None
    events=j.db.execute("SELECT payload FROM m71_events WHERE kind='RESPONSE'").fetchall()
    text=canonical(events)
    assert all(secret not in text for secret in [*CREDS.values(),'PRIVATEACCESS'])
    with pytest.raises(sqlite3.IntegrityError):rehearse(proposal,j,Fake())
    with pytest.raises(sqlite3.IntegrityError):j.db.execute('DELETE FROM m71_events')
    out=tmp_path/'saved';save_catalog(result,out)
    rows,coverage=ingest(out/'M71_M70_sources.json')
    assert len(rows)==51 and len({r['asin'] for r in rows})==1
    assert coverage['sources'][0]['adapter']=='amazon_catalog_pages'
    assert all(p.stat().st_mode&0o777==0o600 for p in out.iterdir())
    j.close()
    with pytest.raises(FileExistsError):Journal(tmp_path/'accounting.sqlite3',proposal)


def test_account_absolute_ceiling_enforced_even_without_transport(tmp_path,proposal):
    j=Journal(tmp_path/'a.sqlite3',proposal);j.start();j.consume('authentication','a'*64)
    for _ in range(200):j.consume('keyword','b'*64)
    with pytest.raises(ValueError):j.consume('keyword','c'*64)
    for _ in range(50):j.consume('identifier','d'*64)
    assert j.count()==251
    for phase in ('authentication','keyword','identifier','restrictions'):
        with pytest.raises(ValueError):j.consume(phase,'e'*64)
    j.finish('STOP')
    with pytest.raises(ValueError):j.consume('keyword','f'*64)
    j.close()


@pytest.mark.parametrize('status',[401,403,408,429,500,503])
def test_http_failure_stops_no_retry(tmp_path,proposal,status):
    result,j,fake,_=run(tmp_path,proposal,Fake(lambda *a:dict(status=status,headers={'Retry-After':'60'},body={'secret':'PRIVATESECRET'})))
    assert result['status']=='STOPPED_NO_REPLAY' and result['requests_consumed']==2
    assert len(fake.requests)==2 and not result['pages']
    assert 'PRIVATESECRET' not in canonical(result)
    j.close()


@pytest.mark.parametrize('error',[KeyboardInterrupt,SystemExit,TimeoutError,RuntimeError])
def test_interruption_burns_uncertain_slot_and_clears_private_data(tmp_path,proposal,error):
    def reply(*args):raise error('PRIVATESECRET PRIVATEACCESS')
    result,j,fake,_=run(tmp_path,proposal,Fake(reply))
    assert result['status']=='STOPPED_NO_REPLAY' and j.count()==2
    assert not fake._credentials and fake._access is None
    assert 'PRIVATESECRET' not in canonical(result)
    assert j.db.execute("SELECT count(*) FROM m71_events WHERE kind='STOP'").fetchone()[0]==1
    assert j.db.execute("SELECT count(*) FROM m71_events WHERE kind='ATTEMPT'").fetchone()[0]==2
    j.close()


def test_interruption_before_dispatch_does_not_consume(tmp_path,proposal):
    def stop():raise KeyboardInterrupt
    result,j,fake,_=run(tmp_path,proposal,before_request=stop)
    assert result['status']=='STOPPED_NO_REPLAY' and j.count()==0 and not fake.requests
    j.close()


def test_stale_deadline_during_pacing_stops_before_accounting(tmp_path,proposal):
    result,j,fake,_=run(tmp_path,proposal,maximum_seconds=.1)
    assert result['status']=='STOPPED_NO_REPLAY' and j.count()==2
    j.close()


def test_repeated_pagination_token_stops_retains_partial_page(tmp_path,proposal):
    def reply(req,n):return dict(status=200,headers={},body=dict(items=[raw_item(1000)],pagination={'nextToken':'PRIVATECURSOR'}))
    result,j,fake,_=run(tmp_path,proposal,Fake(reply))
    assert result['status']=='STOPPED_NO_REPLAY' and result['requests_consumed']==52
    assert len(result['pages'])==50
    out=tmp_path/'partial';save_catalog(result,out)
    rows,coverage=ingest(out/'M71_M70_sources.json')
    assert len(rows)==50 and coverage['sources'][0]['partial_query_windows']==50
    assert 'PRIVATECURSOR' not in canonical({k:v for k,v in result.items() if k!='pages'})
    j.close()


@pytest.mark.parametrize('body',[{},dict(items=[{'asin':'invented'}]),dict(items=[] ,pagination={'nextToken':''}),
    dict(items=[],pagination={'nextToken':3}),dict(items=[raw_item()]*21),
    dict(items=[dict(asin='B000001000',summaries=[dict(marketplaceId='WRONG')])])])
def test_malformed_response_stops(tmp_path,proposal,body):
    result,j,_,_=run(tmp_path,proposal,Fake(lambda *a:dict(status=200,headers={},body=body)))
    assert result['status']=='STOPPED_NO_REPLAY' and result['requests_consumed']==2
    j.close()


def test_exclusions_never_admitted_or_explicitly_enriched(tmp_path,proposal):
    excluded=proposal['checked_eligibility_asins'][0]
    def reply(req,n):return dict(status=200,headers={},body=dict(items=[dict(asin=excluded)],pagination={}))
    result,j,fake,_=run(tmp_path,proposal,Fake(reply))
    assert result['distinct_unclaimed_asins']==0 and result['excluded_observations']==50
    assert result['requests_consumed']==51
    assert not any('identifiers=' in url for url in fake.requests)
    j.close()


def test_full_251_ceiling_with_sparse_pagination_and_identifier_batches(tmp_path,proposal):
    # 5 new ASINs/page x 200 pages = 1,000; no query page can be skipped.
    next_id=10000
    def reply(req,n):
        nonlocal next_id
        from urllib.parse import parse_qs,urlsplit
        params=parse_qs(urlsplit(req.full_url).query)
        if 'identifiers' in params:
            items=[dict(asin=a) for a in params['identifiers'][0].split(',')];pagination={}
        else:
            items=[dict(asin=f'B{i:09d}') for i in range(next_id,next_id+5)];next_id+=5
            pagination=dict(nextToken=str(n))
        return dict(status=200,headers={},body=dict(items=items,pagination=pagination))
    result,j,fake,clock=run(tmp_path,proposal,Fake(reply))
    assert result['status']=='COMPLETED_NO_REPLAY' and j.count()==251
    assert result['distinct_unclaimed_asins']==1000 and len(result['pages'])==250
    j.close()


def test_identifier_new_asin_or_continuation_rejected():
    with pytest.raises(ValueError):validate_page(dict(items=[raw_item(1001)]),prior_tokens=set(),asins=['B000001000'])
    with pytest.raises(ValueError):validate_page(dict(items=[],pagination={'nextToken':'more'}),prior_tokens=set(),asins=['B000001000'])


@pytest.mark.parametrize('url',[
 'http://sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items',
 'https://sellingpartnerapi-na.amazon.com:443/catalog/2022-04-01/items',
 'https://evil.example/catalog/2022-04-01/items',
 'https://sellingpartnerapi-na.amazon.com/products/pricing/v0/items/X/offers',
 'https://sellingpartnerapi-na.amazon.com/listings/2021-08-01/restrictions',
 'https://sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items/B000001000',
])
def test_endpoint_allowlist_rejects_all_other_operations(url):
    transport=CatalogTransport(CREDS);transport._access='PRIVATEACCESS'
    with pytest.raises(ValueError):transport.validate(Request(url), 'keyword',parameters(policy.queries()[0]))
    with pytest.raises(PermissionError):transport.send(Request(url))


def test_throttle_header_stops_even_on_http_200(tmp_path,proposal):
    result,j,_,_=run(tmp_path,proposal,Fake(lambda *a:dict(status=200,headers={'rEtRy-AfTeR':'1'},body=dict(items=[]))))
    assert result['status']=='STOPPED_NO_REPLAY' and j.count()==2;j.close()


def test_privacy_product_fields_and_rate_header_lowering(tmp_path,proposal):
    def reply(req,n):
        item=raw_item(1000);item['sellerId']='SELLERPRIVATE';item['summaries'][0]['modelNumber']='PRIVATEACCESS'
        return dict(status=200,headers={'x-amzn-RateLimit-Limit':'.25'},body=dict(items=[item]))
    result,j,_,clock=run(tmp_path,proposal,Fake(reply))
    text=canonical(result)
    assert 'SELLERPRIVATE' not in text and 'PRIVATEACCESS' not in text and 'PRIVATESECRET' not in text
    assert sum(clock.sleeps)>=400
    j.close()


def test_cli_prepare_validate_no_execution_and_evidence_unchanged(tmp_path,history_fixture,capsys):
    c=history_fixture;before=protected(c)
    args=['--store',str(c['store_path']),'--history-dir',str(c['private']),
        '--m67-manifest',str(c['path']),'--m67-sha256',c['digest']]
    out=tmp_path/'proposal'
    assert m71.main(['prepare',*args,'--output',str(out)])==0
    manifest=out/'M71_manifest.json'
    assert m71.main(['validate',*args,'--manifest',str(manifest),'--sha256',sha256(manifest)])==0
    assert m71.main(['validate',*args,'--manifest',str(manifest),'--sha256','0'*64])==2
    assert m71.main(['prepare',*args,'--output',str(out)])==2
    for action in ('execute','discover','authenticate','authorize','reserve','resume'):
        with pytest.raises(SystemExit):m71.main([action,*args])
    assert protected(c)==before
    assert 'PRIVATESECRET' not in capsys.readouterr().out


def test_checkpoint_recovers_committed_partial_pages_and_uncertain_slots(tmp_path,proposal):
    from app.m71_journal import checkpoint
    result,j,_,_=run(tmp_path,proposal,Fake(lambda *a:(_ for _ in ()).throw(KeyboardInterrupt())))
    j.close();path=tmp_path/'accounting.sqlite3';before=sha256(path)
    recovered=checkpoint(path,proposal)
    assert recovered['requests_consumed']==2 and recovered['uncertain_slots']==[2]
    assert recovered['status']=='STOPPED_NO_REPLAY' and sha256(path)==before
    other=tmp_path/'killed.sqlite3';journal=Journal(other,proposal);journal.start()
    journal.consume('authentication','a'*64);journal.close()
    recovered=checkpoint(other,proposal)
    assert recovered['status']=='UNCERTAIN_NO_REPLAY' and recovered['uncertain_slots']==[1]
    with pytest.raises(FileExistsError):Journal(other,proposal)


def test_checkpoint_detects_forced_tampering(tmp_path,proposal):
    from app.m71_journal import checkpoint
    result,j,_,_=run(tmp_path,proposal)
    j.db.execute('DROP TRIGGER immutable_m71_update')
    j.db.execute("UPDATE m71_events SET payload='{}' WHERE kind='ATTEMPT'");j.db.commit();j.close()
    with pytest.raises(ValueError):checkpoint(tmp_path/'accounting.sqlite3',proposal)


def test_no_late_discovery_after_first_identifier_phase(tmp_path,proposal):
    # A repeated terminal journal cannot be used for another authentication/query batch.
    j=Journal(tmp_path/'x.sqlite3',proposal);j.start();j.consume('authentication','a'*64);j.finish('STOP')
    with pytest.raises(ValueError):j.consume('identifier','b'*64)
    j.close()


def test_unknown_account_history_prevents_freezing(proposal):
    from app.m71_manifest import freeze
    with pytest.raises(ValueError):freeze(dict(history_complete=False,excluded_asins=[],original_m63_asins=[],original_m67_asins=[]))


def test_environment_rate_change_invalidates_current_proposal(history_fixture,proposal,monkeypatch):
    c=history_fixture;monkeypatch.setenv('AMAZON_RATE_SEARCHCATALOGITEMS','.25')
    changed=policy.prepare(c['private'],c['store_path'],c['path'],c['digest'])
    assert changed['proposal_sha256']!=proposal['proposal_sha256']


def test_help_import_has_no_authentication_or_live_transport_dependencies():
    import subprocess,sys
    code="import sys;sys.modules['app.amazon_pilot']=None;sys.modules['app.m67_execution']=None;from app.m71 import main;main(['--help'])"
    r=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
    assert r.returncode==0 and 'preparation-only' in r.stdout


@pytest.mark.parametrize('batch',[[],['invalid'],['B000001000']*2,[f'B{i:09d}' for i in range(21)]])
def test_identifier_batch_bounds_before_dispatch(batch):
    transport=CatalogTransport(CREDS);transport._access='PRIVATEACCESS'
    params=parameters(asins=batch);req=transport.build('identifier',params)
    with pytest.raises(ValueError):transport.validate(req,'identifier',params)


def test_mismatched_journal_manifest_rejected_before_any_dispatch(tmp_path,proposal):
    j=Journal(tmp_path/'a.sqlite3',proposal)
    altered=deepcopy(proposal);altered['history_evidence_sha256']='b'*64;resign(altered)
    transport=Fake();transport.journal=j
    with pytest.raises(ValueError):rehearse(altered,j,transport)
    assert j.count()==0 and not transport.requests
    j.close()


def test_missing_or_conflicting_history_never_creates_proposal_directory(tmp_path,history_fixture):
    c=history_fixture;args=['--store',str(c['store_path']),'--history-dir',str(c['private']),
        '--m67-manifest',str(c['path']),'--m67-sha256','0'*64,'--output',str(tmp_path/'out')]
    assert m71.main(['prepare',*args])==2 and not (tmp_path/'out').exists()


def test_credential_constructor_does_not_read_files_and_live_send_is_disabled():
    with pytest.raises(ValueError):CatalogTransport(dict(client_id='PRIVATECLIENT'))
    transport=CatalogTransport(CREDS)
    request=transport.build('authentication',{})
    transport.validate(request,'authentication',{})
    with pytest.raises(PermissionError):transport.send(request)
    assert 'PRIVATESECRET' not in repr(transport)


def test_read_only_checkpoint_reconstructs_completed_m70_pages(tmp_path,proposal):
    from app.m71_journal import checkpoint
    result,j,_,_=run(tmp_path,proposal);j.close()
    recovered=checkpoint(tmp_path/'accounting.sqlite3',proposal)
    assert recovered['pages']==result['pages'] and recovered['requests_consumed']==52
    assert recovered['uncertain_slots']==[] and recovered['status']=='COMPLETED_NO_REPLAY'


def test_authentication_failure_is_accounted_and_never_repeated(tmp_path,proposal):
    class BadAuth(Fake):
        def send(self,req):
            assert self.journal.count()==1
            self.requests.append(req.full_url)
            return dict(status=200,headers={},body=dict(access_token='PRIVATEACCESS'))
    result,j,fake,_=run(tmp_path,proposal,BadAuth())
    assert result['requests_consumed']==1 and result['status']=='STOPPED_NO_REPLAY'
    assert len(fake.requests)==1 and fake._access is None
    j.close()


def test_changed_request_url_rejected_before_accounting(tmp_path,proposal):
    class Misroute(Fake):
        def build(self,phase,params):return Request('https://evil.example/')
    result,j,fake,_=run(tmp_path,proposal,Misroute())
    assert result['requests_consumed']==0 and result['status']=='STOPPED_NO_REPLAY' and not fake.requests
    j.close()
