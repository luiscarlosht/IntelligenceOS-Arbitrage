"""Synthetic private stores and in-memory transports. No approved artifact files."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.request import Request

import pytest

from app import m65_batch, m66_discovery, m66_experiments
from app.amazon_diagnostics import ResponseDocument, AmazonFailure
from app.amazon_pacing import OperationPacer
from app.m65_intelligence import US, CONDITION, build_audit, sha256
from app.m66_verification import VerificationStore, ACCOUNT
from app.m67_policy import preflight, authorize, implementation, LEDGER, CONTEXT
from app.m67_state import Ledger, ReadOnlyStore, ledger_snapshot
from app.m67_execution import run_reserved, outcome, execute
from app.m67_transport import AmazonTransport
from app.m67_reporting import report, import_results
from app.observations import canonical, fingerprint

DATE = '2026-01-02T12:00:00+00:00'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*a, **kw):
        pytest.fail('Network or credential reads forbidden')
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    from app import amazon_pilot
    monkeypatch.setattr(amazon_pilot, '_request_json', blocked)
    monkeypatch.setattr(amazon_pilot, 'load_credentials', blocked)


def write(path, value):
    path.write_text(canonical(value))
    path.chmod(0o600)


@pytest.fixture
def cohort(tmp_path):
    private = tmp_path/'private'; private.mkdir(mode=0o700)
    write(private/'m63-eligibility-authorization-01.json', dict(
        asins=[f'B{i:09d}' for i in range(20)], maximum_checks=20, state='claimed_no_replay'))
    db = sqlite3.connect(private/'candidate-executions.sqlite3')
    db.executescript('CREATE TABLE candidate_operations(request_key TEXT,kind TEXT,asin TEXT,state TEXT); CREATE TABLE amazon_cooldowns(operation TEXT,not_before_utc TEXT,diagnostics TEXT);')
    db.close(); (private/'candidate-executions.sqlite3').chmod(0o600)
    write(private/'credentials.json', {})  # metadata only, not usable credentials
    write(private/CONTEXT, dict(account_reference=ACCOUNT,marketplace_id=US,condition=CONDITION,
          seller_id='SYNTHETICSELLER',credentials_sha256='a'*64))
    store_path = tmp_path/'derived/store.sqlite3'; store = VerificationStore(store_path)
    source = tmp_path/'source.json'
    write(source, [dict(asin=f'B{i:09d}',brand=f'Example{i%18}',category=f'Category{i%4}',marketplace=US,
        observed_at=DATE,provenance='synthetic:fixture',product_type='TYPE',
        catalog=dict(asin=f'B{i:09d}',title='Example',model='MODEL',package_quantity=1,
                     identifiers=[dict(kind='UPC',value='012345678905')]),summary_fields=dict(size='small')) for i in range(60)])
    manifest, ranking, _ = m66_discovery.build([source],store,private,as_of=datetime.fromisoformat(DATE))
    path = tmp_path/'M66_review_manifest.json'; write(path,manifest)
    write(tmp_path/'M66_candidate_ranking.json',ranking)
    yield dict(private=private,store=store,store_path=store_path,source=source,manifest=manifest,
               inner=manifest['restrictions_proposal'],path=path,digest=sha256(path),ranking=ranking)
    store.db.close()


def check(c):
    return preflight(c['path'],c['digest'],[c['source']],c['store_path'],c['private'])


def temporary_claims(c):
    ledger = Ledger(c['private']/LEDGER)
    ledger.reserve(c['digest'],c['inner'])
    # Only synthetic temporary reservations. No human authorization file exists.
    with c['store'].db:
        c['store'].db.execute('INSERT INTO batch_claims VALUES (?,?)',(c['digest'],canonical(c['inner'])))
        for asin in c['inner']['asins']:
            c['store'].db.execute('INSERT INTO asin_claims VALUES (?,?)',(US+':'+CONDITION+':'+asin,c['digest']))
    return ledger


class Fake(AmazonTransport):
    def __init__(self, replies=None, fail_at=None, error=None, duplicate=False):
        super().__init__(dict(client_id='SYNTHETICCLIENT',client_secret='SYNTHETICSECRET',refresh_token='SYNTHETICREFRESH'), 'SYNTHETICSELLER')
        self.calls = []; self.replies = replies or []; self.fail_at = fail_at; self.error = error
        self.duplicate = duplicate

    def send(self, req, kind, asin):
        self.validate(req,kind,asin)
        self.calls.append((kind,asin))
        if len(self.calls) == self.fail_at:
            raise self.error
        raw = (dict(access_token='SYNTHETICTOKEN',token_type='bearer') if kind == 'authentication'
               else self.replies[len(self.calls)-2] if len(self.calls)-2 < len(self.replies) else dict(restrictions=[]))
        reply = ResponseDocument(raw,200); reply.rate_headers = {}
        return reply


def run(c, ledger, adapter):
    return run_reserved(c['store'],ledger,c['inner'],c['digest'],adapter,before_request=lambda:None,
                        pacer=OperationPacer(sleep=lambda n:None),deadline=time.monotonic()+60)


def review(c, p):
    now = datetime.now(timezone.utc)
    # In-memory validator input only: never an approved artifact on disk.
    return dict(schema=1,approved=True,execution_permission=True,manifest_sha256=c['digest'],
        asins=c['inner']['asins'],account_reference=ACCOUNT,account_binding_sha256=p['account_binding_sha256'],
        marketplace_id=US,condition=CONDITION,budget=c['inner']['budget'],no_retry=True,
        review_reference='manual:synthetic-test-only',reviewed_at=(now-timedelta(minutes=1)).isoformat(),
        expires_at=(now+timedelta(minutes=5)).isoformat(),implementation_sha256=implementation(),preflight_sha256=fingerprint(p))


def test_preflight_readonly_original_reservations_and_no_credentials(cohort):
    c=cohort
    before={p:str(sha256(p)) for p in c['private'].iterdir()}
    revision=c['store'].revision()
    p=check(c)
    assert p['ready'] and p['budget']['maximum_requests']==21
    assert p['historical_exclusions']==22  # synthetic twenty plus immutable M60/M58
    assert c['store'].revision()==revision
    assert before=={p:str(sha256(p)) for p in c['private'].iterdir()}
    assert not (c['private']/LEDGER).exists()
    assert 'SYNTHETICSELLER' not in canonical(p)
    ro=ReadOnlyStore(c['store_path'])
    with pytest.raises(sqlite3.OperationalError):ro.db.execute('DELETE FROM intelligence_events')
    ro.db.close()


def test_missing_binding_blocks_without_creating_it(cohort):
    (cohort['private']/CONTEXT).unlink()
    assert not check(cohort)['ready']
    assert not (cohort['private']/CONTEXT).exists()


@pytest.mark.parametrize('change',['bytes','sha','source','order','scope','budget','history','missing-proof','missing-ledger','code','maximum'])
def test_preflight_drift_fails_closed(cohort,change,monkeypatch):
    c=cohort
    if change=='bytes':c['path'].write_text(c['path'].read_text()+' ')
    elif change=='sha':c['digest']='0'*64
    elif change=='source':c['source'].write_text('[]')
    elif change=='history':write(c['private']/'m60-new.json',dict(asin=c['inner']['asins'][0],requests_attempted=1))
    elif change=='missing-proof':(c['private']/'m63-eligibility-authorization-01.json').unlink()
    elif change=='missing-ledger':(c['private']/'candidate-executions.sqlite3').unlink()
    elif change=='code':monkeypatch.setattr(m66_discovery,'implementation',lambda:{})
    else:
        m=c['manifest']
        if change=='order':m['restrictions_proposal']['asins'].reverse()
        elif change=='scope':m['restrictions_proposal']['marketplace_id']='WRONG'
        elif change=='maximum':m['restrictions_proposal']['maximum_checks']=21
        else:m['restrictions_proposal']['budget']['retries']=1
        write(c['path'],m);c['digest']=sha256(c['path'])
    with pytest.raises((ValueError,FileNotFoundError)):check(c)
    assert not (c['private']/LEDGER).exists()


@pytest.mark.parametrize('change',['missing','execute','expired','account','marketplace','condition','asins','budget','binding','code','permission','preflight','retry','extra'])
def test_authorization_rejects_drift_without_reservation(cohort,change):
    c=cohort;p=check(c);a=review(c,p);flag=True
    if change=='missing':a=None
    elif change=='execute':flag=False
    elif change=='expired':a['expires_at']='2026-01-01T00:00:00+00:00'
    elif change=='account':a['account_reference']='OTHER'
    elif change=='marketplace':a['marketplace_id']='OTHER'
    elif change=='condition':a['condition']='used'
    elif change=='asins':a['asins']=list(reversed(a['asins']))
    elif change=='budget':a['budget']=dict(a['budget'],authentication=2)
    elif change=='binding':a['account_binding_sha256']='0'*64
    elif change=='code':a['implementation_sha256']={}
    elif change=='permission':a['execution_permission']=False
    elif change=='preflight':a['preflight_sha256']='0'*64
    elif change=='retry':a['no_retry']=False
    else:a['seller_id']='PRIVATE'
    with pytest.raises(ValueError):authorize(c['manifest'],c['digest'],a,execute=flag,
        audit=build_audit(c['private'],c['store']),preflight_report=p)
    assert not (c['private']/LEDGER).exists()


def test_separate_in_memory_review_validation_and_execute_flag(cohort):
    c=cohort;p=check(c)
    authorize(c['manifest'],c['digest'],review(c,p),execute=True,
              audit=build_audit(c['private'],c['store']),preflight_report=p)
    with pytest.raises(ValueError):execute(c['path'],c['digest'],[c['source']],c['store_path'],c['private'],
                                          Path('ABSENT'), '0'*64,execution_flag=False)


def test_happy_path_exact_budget_and_frozen_reporting(cohort):
    c=cohort;l=temporary_claims(c);a=Fake()
    assert run(c,l,a)==dict(status='COMPLETED',requests_consumed=21)
    assert a.calls==[('authentication',None)]+[('restrictions',v) for v in c['inner']['asins']]
    r=report(c['path'],c['digest'],c['store_path'],c['private']/LEDGER)
    assert r['overall']['NO_REPORTED_RESTRICTIONS']==20 and r['overall']['operation_succeeded']==20
    assert len(r['by_brand'])==18 and len(r['by_category'])==4
    assert r['request_accounting']['total']==21
    assert all(not v['selling_authorization_confirmed'] and not v['fba_inbound_evidence_evaluated'] for v in r['rows'])
    assert import_results(c['path'],c['digest'],c['store'],c['private']/LEDGER)['imported']==20
    assert import_results(c['path'],c['digest'],c['store'],c['private']/LEDGER)['duplicates']==20
    with pytest.raises((ValueError,sqlite3.IntegrityError)):l.consume(c['digest'],'authentication')
    with pytest.raises(sqlite3.IntegrityError):l.reserve(c['digest'],c['inner'])
    with pytest.raises(ValueError):check(c)
    encoded=canonical(ledger_snapshot(c['private']/LEDGER))
    assert not any(v in encoded for v in ('SYNTHETICTOKEN','SYNTHETICSECRET','SYNTHETICSELLER'))
    l.db.close()


@pytest.mark.parametrize('http',[401,403,429,500,502,503,504])
@pytest.mark.parametrize('at',[1,2,4])
def test_http_failures_stop_without_retry_or_refresh(cohort,http,at):
    c=cohort;l=temporary_claims(c);a=Fake(fail_at=at,error=AmazonFailure('SYNTHETICSECRET',reason='http_error',http_status=http))
    r=run(c,l,a)
    assert r['status']=='STOPPED_NO_REPLAY' and len(a.calls)==at
    assert r['requests_consumed']==at
    result=report(c['path'],c['digest'],c['store_path'],c['private']/LEDGER)
    assert result['overall']['failed_or_uncertain']==(0 if at==1 else 1)
    if at==1:assert result['overall']['observed_no_restrictions_fraction'] is None
    assert 'SYNTHETICSECRET' not in canonical(ledger_snapshot(c['private']/LEDGER))
    l.db.close()


@pytest.mark.parametrize('error',[TimeoutError('PRIVATE'),KeyboardInterrupt('PRIVATE'),ConnectionResetError('PRIVATE'),SystemExit('PRIVATE')])
def test_uncertain_interruptions_are_consumed_and_never_replayed(cohort,error):
    c=cohort;l=temporary_claims(c);a=Fake(fail_at=3,error=error)
    assert run(c,l,a)['requests_consumed']==3
    assert len(a.calls)==3
    l.db.close();l=Ledger(c['private']/LEDGER)
    with pytest.raises(sqlite3.IntegrityError):l.reserve(c['digest'],c['inner'])
    with pytest.raises(ValueError):l.consume(c['digest'],'restrictions',c['inner']['asins'][2])
    assert report(c['path'],c['digest'],c['store_path'],c['private']/LEDGER)['overall']['failed_or_uncertain']==1
    l.db.close()


@pytest.mark.parametrize('raw,state',[
    (dict(restrictions=[]),'NO_REPORTED_RESTRICTIONS'),(dict(restrictions=[{}]),'NO_REPORTED_RESTRICTIONS'),
    ({},'UNKNOWN'),(dict(restrictions=None),'UNKNOWN'),(dict(restrictions=[{},{}]),'UNKNOWN'),
    (dict(restrictions=[dict(marketplaceId='WRONG')]),'UNKNOWN'),
    (dict(restrictions=[dict(marketplaceId=US)]),'OTHER_RESTRICTED'),
    (dict(restrictions=[dict(marketplaceId=US,reasons=[dict(reasonCode='APPROVAL_REQUIRED')])]),'APPROVAL_REQUIRED'),
    (dict(restrictions=[dict(marketplaceId=US,reasons=[dict(reasonCode='NOT_ELIGIBLE')])]),'NOT_ELIGIBLE'),
    (dict(restrictions=[],errors=[dict(code='PRIVATE')]),'UNKNOWN')])
def test_conservative_response_shapes(cohort,raw,state):
    c=cohort;l=temporary_claims(c);a=Fake(replies=[raw]);run(c,l,a)
    r=report(c['path'],c['digest'],c['store_path'],c['private']/LEDGER)
    assert r['rows'][0]['api_state']==state
    assert len(a.calls)==(2 if state=='UNKNOWN' else 21)
    l.db.close()


def test_no_checks_fraction_null_and_frozen_snapshot(cohort):
    c=cohort;r=report(c['path'],c['digest'],c['store_path'],c['private']/LEDGER)
    assert r['overall']['checked']==0 and r['overall']['observed_no_restrictions_fraction'] is None
    assert r['request_accounting']['total']==0
    ranking=json.loads((c['path'].parent/'M66_candidate_ranking.json').read_text())
    ranking['rows'][0]['brand']='CHANGED';write(c['path'].parent/'M66_candidate_ranking.json',ranking)
    with pytest.raises(ValueError):report(c['path'],c['digest'],c['store_path'],c['private']/LEDGER)


def test_durable_pretransport_crash_and_no_resume(cohort):
    c=cohort;l=temporary_claims(c);l.db.close()
    script='from app.m67_state import Ledger; import os,sys; from pathlib import Path; l=Ledger(Path(sys.argv[1])); l.consume(sys.argv[2],"authentication"); os._exit(17)'
    result=subprocess.run([sys.executable,'-c',script,str(c['private']/LEDGER),c['digest']],check=False)
    assert result.returncode==17
    snap=ledger_snapshot(c['private']/LEDGER)
    assert len(snap['attempts'])==1 and not snap['outcomes']
    l=Ledger(c['private']/LEDGER)
    with pytest.raises(ValueError):l.consume(c['digest'],'authentication')
    with pytest.raises(sqlite3.IntegrityError):l.reserve(c['digest'],c['inner'])
    l.db.close()


def test_global_claim_prevents_replay_after_derived_restore(cohort):
    c=cohort;l=Ledger(c['private']/LEDGER);l.reserve(c['digest'],c['inner']);l.db.close()
    # The M66 database is unchanged, yet global permanent claims block it.
    with pytest.raises(ValueError):check(c)
    assert not c['store'].db.execute('SELECT 1 FROM batch_claims').fetchone()


def test_no_local_proof_is_reported_without_inventing_claims(cohort):
    c=cohort;l=Ledger(c['private']/LEDGER);l.reserve(c['digest'],c['inner'])
    key=l.consume(c['digest'],'authentication');l.finish(key,outcome('SUCCEEDED'))
    l.consume(c['digest'],'restrictions',c['inner']['asins'][0])
    result=import_results(c['path'],c['digest'],c['store'],c['private']/LEDGER)
    assert result['missing_local_attempt_proof']==1 and result['imported']==0
    assert not c['store'].db.execute('SELECT 1 FROM request_attempts').fetchone()
    assert report(c['path'],c['digest'],c['store_path'],c['private']/LEDGER)['overall']['UNKNOWN']==1
    l.db.close()


@pytest.mark.parametrize('table',['batches','claims','attempts','outcomes','stops'])
def test_accounting_immutable(cohort,table):
    l=temporary_claims(cohort)
    key=l.consume(cohort['digest'],'authentication');l.finish(key,outcome('SUCCEEDED'))
    l.stop(cohort['digest'])
    with pytest.raises(sqlite3.IntegrityError):l.db.execute(f'DELETE FROM m67_{table}')
    with pytest.raises(sqlite3.IntegrityError):l.db.execute(f'UPDATE m67_{table} SET '+('id=id' if table in ('attempts','outcomes') else 'asin=asin' if table=='claims' else 'digest=digest'))
    l.db.close()


@pytest.mark.parametrize('variant',['wrong-host','redirect-target','wrong-asins','extra-query','wrong-method','userinfo','port','fragment','auth-extra','auth-other-endpoint'])
def test_transport_allowlist(variant):
    from app import amazon_pilot
    adapter=Fake(); adapter.access='SYNTHETICTOKEN'
    kind='restrictions';asin='B000000021'
    req=amazon_pilot.amazon_request(adapter.access,m65_batch.PATH,dict(asin=asin,sellerId=adapter.seller_id,
        marketplaceIds=US,conditionType=CONDITION,reasonLocale='en_US'))
    url=req.full_url
    if variant=='wrong-host':url=url.replace('sellingpartnerapi-na.amazon.com','example.com')
    elif variant=='redirect-target':url='http://sellingpartnerapi-na.amazon.com'+m65_batch.PATH
    elif variant=='wrong-asins':url=url.replace(asin,'B000000022')
    elif variant=='extra-query':url+='&asin='+asin
    elif variant=='wrong-method':req=Request(url,data=b'{}')
    elif variant=='userinfo':url=url.replace('https://','https://private@')
    elif variant=='port':url=url.replace('.com/','.com:443/')
    elif variant=='fragment':url+='#private'
    else:
        kind='authentication';asin=None
        from urllib.parse import urlencode
        values=dict(grant_type='refresh_token',**adapter.credentials)
        if variant=='auth-extra':values['scope']='extra'
        url='https://api.amazon.com/auth/o2/token' if variant=='auth-extra' else 'https://example.com/token'
        req=Request(url,data=urlencode(values).encode())
    if variant not in ('wrong-method','auth-extra','auth-other-endpoint'):req=Request(url)
    with pytest.raises(ValueError):adapter.validate(req,kind,asin)


def test_zero_retry_on_multiple_transport_callbacks(cohort):
    c=cohort;l=temporary_claims(c)
    class Double(Fake):
        def request(self,kind,asin,dispatch):
            if kind=='authentication':return super().request(kind,asin,dispatch)
            from app.amazon_pilot import amazon_request
            req=amazon_request(self.access,m65_batch.PATH,dict(asin=asin,sellerId=self.seller_id,
                  marketplaceIds=US,conditionType=CONDITION,reasonLocale='en_US'))
            dispatch(req);return dispatch(req)
    a=Double();assert run(c,l,a)['requests_consumed']==2
    assert len(a.calls)==2
    l.db.close()


def test_invalid_auth_token_stops_at_one_request(cohort):
    c=cohort;l=temporary_claims(c)
    class Invalid(Fake):
        def send(self,*args):
            self.calls.append(('authentication',None))
            return ResponseDocument(dict(token_type='bearer'),200)
    a=Invalid();assert run(c,l,a)['requests_consumed']==1
    assert len(a.calls)==1
    l.db.close()


def test_retry_after_even_http_200_stops(cohort):
    c=cohort;l=temporary_claims(c)
    class Deferred(Fake):
        def send(self,*args):
            r=super().send(*args)
            if len(self.calls)==2:r.rate_headers={'Retry-After':'1'}
            return r
    a=Deferred();assert run(c,l,a)['requests_consumed']==2
    assert len(a.calls)==2
    l.db.close()


def test_deadline_before_first_transport(cohort):
    c=cohort;l=temporary_claims(c);a=Fake()
    r=run_reserved(c['store'],l,c['inner'],c['digest'],a,before_request=lambda:None,
                   pacer=OperationPacer(),deadline=time.monotonic()-1)
    assert r['requests_consumed']==0 and not a.calls
    l.db.close()


def test_ledger_budget_and_order_defense(cohort):
    c=cohort;l=temporary_claims(c)
    with pytest.raises(ValueError):l.consume(c['digest'],'restrictions',c['inner']['asins'][0])
    key=l.consume(c['digest'],'authentication')
    with pytest.raises(ValueError):l.consume(c['digest'],'restrictions',c['inner']['asins'][0])
    l.finish(key,outcome('SUCCEEDED'))
    with pytest.raises(ValueError):l.consume(c['digest'],'restrictions',c['inner']['asins'][1])
    with pytest.raises(ValueError):l.consume(c['digest'],'pricing',c['inner']['asins'][0])
    l.db.close()


def test_conflicting_local_and_global_evidence_remains_unknown(cohort):
    c=cohort;l=temporary_claims(c);run(c,l,Fake())
    m66_discovery.record_result(c['store'],c['digest'],c['inner']['asins'][0],'SUCCEEDED','NOT_ELIGIBLE','a'*64,DATE)
    r=report(c['path'],c['digest'],c['store_path'],c['private']/LEDGER)
    assert r['rows'][0]['conflicting_evidence'] and r['rows'][0]['api_state']=='UNKNOWN'
    with pytest.raises(ValueError):import_results(c['path'],c['digest'],c['store'],c['private']/LEDGER)
    l.db.close()


def test_global_consumption_precedes_local_failure_and_no_send(cohort,monkeypatch):
    c=cohort;l=temporary_claims(c);a=Fake()
    def fail(*args,**kwargs):raise OSError('PRIVATE')
    monkeypatch.setattr(m65_batch,'consume_attempt',fail)
    assert run(c,l,a)['requests_consumed']==1
    assert not a.calls
    assert len(ledger_snapshot(c['private']/LEDGER)['attempts'])==1
    l.db.close()


@pytest.mark.parametrize('case',['permissions','symlink','missing-trigger','active-journal','unsafe-credential'])
def test_unsafe_storage_is_blocked(cohort,case):
    c=cohort
    if case=='permissions':c['private'].chmod(0o755)
    elif case=='symlink':
        (c['private']/CONTEXT).rename(c['private']/'binding-original.json')
        (c['private']/CONTEXT).symlink_to('binding-original.json')
    elif case=='missing-trigger':c['store'].db.execute('DROP TRIGGER no_event_delete');c['store'].db.commit()
    elif case=='active-journal':Path(str(c['store_path'])+'-journal').write_bytes(b'unsafe')
    else:(c['private']/'credentials.json').chmod(0o644)
    with pytest.raises((ValueError,sqlite3.DatabaseError)):check(c)


def test_cli_help_and_preflight_never_import_executor_or_send(cohort,capsys):
    from app.m67 import main
    with pytest.raises(SystemExit) as result:main(['--help'])
    assert result.value.code==0
    c=cohort
    assert main(['preflight','--manifest',str(c['path']),'--manifest-sha256',c['digest'],
                 '--catalog',str(c['source']),'--store',str(c['store_path']),'--private-dir',str(c['private'])])==0
    assert 'SYNTHETICSELLER' not in capsys.readouterr().out
    assert not (c['private']/LEDGER).exists()


def test_no_listing_or_purchase_operations_exposed():
    from app.m67 import main
    for action in ('purchase','listing','approve','catalog','fees','pricing'):
        with pytest.raises(SystemExit):main([action,'--manifest','x','--manifest-sha256','0'*64,'--store','x'])


def test_existing_one_shot_adapter_accounting_before_raw_transport(cohort,monkeypatch):
    from app import amazon_pilot
    c=cohort;l=temporary_claims(c);calls=[]
    def raw(req):
        calls.append(req.get_method())
        assert l.db.execute('SELECT count(*) FROM m67_attempts').fetchone()[0]==len(calls)
        assert c['store'].db.execute('SELECT count(*) FROM request_attempts').fetchone()[0]==len(calls)
        reply=ResponseDocument(dict(access_token='SYNTHETICTOKEN',token_type='bearer') if len(calls)==1 else dict(restrictions=[]),200)
        reply.rate_headers={}
        return reply
    monkeypatch.setattr(amazon_pilot,'_request_json',raw)
    a=AmazonTransport(dict(client_id='SYNTHETICCLIENT',client_secret='SYNTHETICSECRET',refresh_token='SYNTHETICREFRESH'),'SYNTHETICSELLER')
    assert run(c,l,a)['status']=='COMPLETED'
    assert calls==['POST']+['GET']*20
    l.db.close()


@pytest.mark.parametrize('field,value',[
    ('api_state','SELLING_PERMISSION_CONFIRMED'),('api_state','SYNTHETICSECRET'),
    ('reason_codes',['SYNTHETICSECRET']),('failure','SYNTHETICSECRET'),
    ('observed_at','SYNTHETICSECRET'),('source_sha256','SYNTHETICSECRET'),
    ('http_status','SYNTHETICSECRET'),('operation_status','SYNTHETICSECRET')])
def test_secret_payloads_cannot_be_persisted(cohort,field,value):
    c=cohort;l=temporary_claims(c);key=l.consume(c['digest'],'authentication')
    row=outcome('SUCCEEDED');row[field]=value
    with pytest.raises(ValueError):l.finish(key,row)
    assert not l.db.execute('SELECT 1 FROM m67_outcomes').fetchone()
    l.db.close()


def test_missing_immutable_global_trigger_never_repaired(cohort):
    c=cohort;l=temporary_claims(c)
    l.db.execute('DROP TRIGGER immutable_m67_claims_DELETE');l.db.commit();l.db.close()
    with pytest.raises(ValueError):Ledger(c['private']/LEDGER)
    with pytest.raises(ValueError):check(c)


def test_report_csv_exports_and_formula_safety(cohort,tmp_path):
    from app.m66_experiments import export
    c=cohort;r=report(c['path'],c['digest'],c['store_path'],c['private']/LEDGER)
    out=tmp_path/'export';out.mkdir(mode=0o700)
    export(r,out)
    assert len(list(out.glob('*.csv')))==3
    assert json.loads((out/'M66_experiment_outcomes.json').read_text())['overall']['observed_no_restrictions_fraction'] is None
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in out.iterdir())
    with pytest.raises(FileExistsError):export(r,out)


def test_manual_approval_conflict_is_separate_from_api_outcome(cohort):
    c=cohort;l=temporary_claims(c);run(c,l,Fake())
    asin=c['inner']['asins'][0]
    c['store'].append_verifications([dict(asin=asin,brand='Example',marketplace=US,condition=CONDITION,
        account_reference=ACCOUNT,observed_at=DATE,verification_method='MANUAL_APPROVAL_SCREEN',
        seller_central_states=['APPROVAL_APPLICATION_REQUIRED'],fba_state='FBA_UNKNOWN',invoice_required=True,
        minimum_invoiced_units=100,restriction_scope='ASIN',source_reference='manual:synthetic')])
    row=report(c['path'],c['digest'],c['store_path'],c['private']/LEDGER)['rows'][0]
    assert row['api_state']=='NO_REPORTED_RESTRICTIONS'
    assert row['seller_verification_conflict_requires_review']
    assert row['fba_state']=='FBA_UNKNOWN' and not row['listing_review_gate_complete']
    l.db.close()


def test_wal_preflight_never_creates_sidecars(cohort):
    c=cohort
    c['store'].db.execute('PRAGMA journal_mode=WAL');c['store'].db.commit();c['store'].db.close()
    before={p.name for p in c['store_path'].parent.iterdir()}
    with pytest.raises(ValueError):check(c)
    assert before=={p.name for p in c['store_path'].parent.iterdir()}


def test_report_and_import_refuse_active_execution_lock(cohort):
    import fcntl
    c=cohort;l=temporary_claims(c)
    path=c['private']/'candidate-execution.lock';path.touch(mode=0o600)
    fd=os.open(path,os.O_RDWR)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):report(c['path'],c['digest'],c['store_path'],c['private']/LEDGER)
        with pytest.raises(BlockingIOError):import_results(c['path'],c['digest'],c['store'],c['private']/LEDGER)
    finally:os.close(fd);l.db.close()


def test_review_hashes_reserved_atomically_and_immutable(cohort):
    c=cohort;l=Ledger(c['private']/LEDGER)
    review=dict(authorization_sha256='a'*64,account_binding_sha256='b'*64,
                preflight_sha256='c'*64,implementation_sha256='d'*64)
    l.reserve(c['digest'],c['inner'],review)
    assert json.loads(l.db.execute('SELECT payload FROM m67_reviews').fetchone()[0])==review
    with pytest.raises(sqlite3.IntegrityError):l.db.execute('DELETE FROM m67_reviews')
    with pytest.raises(ValueError):l.reserve('e'*64,c['inner'],dict(review,seller_id='PRIVATE'))
    assert l.db.execute('SELECT count(*) FROM m67_batches').fetchone()[0]==1
    l.db.close()


def test_new_private_cooldown_persists_without_touching_legacy(cohort):
    c=cohort;legacy=c['private']/'candidate-executions.sqlite3';before=sha256(legacy)
    l=temporary_claims(c)
    a=Fake(fail_at=2,error=AmazonFailure('PRIVATE',reason='http_error',http_status=429))
    r=run_reserved(c['store'],l,c['inner'],c['digest'],a,before_request=lambda:None,
        pacer=OperationPacer(state_path=c['private']/LEDGER),deadline=time.monotonic()+60)
    assert r['requests_consumed']==2
    assert l.db.execute('SELECT count(*) FROM amazon_cooldowns').fetchone()[0]==1
    assert sha256(legacy)==before
    l.db.close()


def test_unknown_cannot_be_a_successful_restriction_outcome(cohort):
    c=cohort;l=temporary_claims(c)
    key=l.consume(c['digest'],'authentication');l.finish(key,outcome('SUCCEEDED'))
    key=l.consume(c['digest'],'restrictions',c['inner']['asins'][0])
    with pytest.raises(ValueError):l.finish(key,outcome('SUCCEEDED','UNKNOWN'))
    with pytest.raises(ValueError):l.consume(c['digest'],'restrictions',c['inner']['asins'][1])
    l.db.close()
