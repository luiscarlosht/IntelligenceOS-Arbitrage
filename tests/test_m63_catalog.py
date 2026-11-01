"""Synthetic transports only; no private runtime or network access."""
import csv
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest

from app import m63_catalog as m
from app.m63_history import audit, sha256
from app.amazon_diagnostics import AmazonFailure, ResponseDocument


@pytest.fixture(autouse=True)
def no_live(monkeypatch):
    monkeypatch.setattr(m.socket,'create_connection',lambda *_args,**_kwargs:pytest.fail('Network connection'))
    monkeypatch.setattr(m.pilot,'load_credentials',lambda *_:pytest.fail('Real credentials'))
    monkeypatch.setattr(m.pilot,'_request_json',lambda *_:pytest.fail('Live API'))


def item(number, query=None, **summary):
    query=query or m.plan(audit_empty())['queries'][0]
    s=dict(marketplaceId=m.MARKETPLACE, itemName=query['brand']+' '+query['keywords'],
           brand=query['brand'],modelNumber='M'+str(number),packageQuantity=1,
           itemClassification='BASE_PRODUCT',browseClassification=dict(displayName='Test category'))
    s.update(summary)
    return dict(asin=f'B{number:09d}',summaries=[s],
                identifiers=[dict(marketplaceId=m.MARKETPLACE,identifiers=[dict(identifierType='UPC',identifier='012345678905')])],
                relationships=[dict(marketplaceId=m.MARKETPLACE,relationships=[])],
                attributes=dict(number_of_items=[dict(value=1,marketplace_id=m.MARKETPLACE)]))


def audit_empty():
    return dict(schema=1,reports=[],ledger_operations=[],excluded_asins=sorted(m.EXCLUSIONS),
                immutable_exclusions=sorted(m.EXCLUSIONS),policy='test')


class Clock:
    def __init__(self):self.value=0
    def time(self):return self.value
    def sleep(self, seconds):self.value+=seconds


def setup(tmp_path):
    private=tmp_path/'private'
    private.mkdir(mode=0o700)
    out=tmp_path/'prepared'
    info=m.prepare(out,private)
    clock=Clock()
    return private,out/'catalog-manifest.json',info['manifest_sha256'],clock


def execute(tmp_path, transport):
    private,path,digest,clock=setup(tmp_path)
    report=m.run(path,digest,private=private,transport=transport,
                 credential_loader=lambda _:dict(client_id='secret-client',client_secret='secret-key',refresh_token='secret-refresh'),
                 monotonic=clock.time,sleep=clock.sleep)
    return report,private,path,digest,clock


def test_prepare_no_credentials_or_network_and_bound_manifest(tmp_path):
    private,path,digest,clock=setup(tmp_path)
    doc=json.loads(path.read_bytes())
    assert doc['budget']==dict(keyword=24,identity=5,catalog_total=29,authentication=1,
                                restrictions=0,pricing=0,fees=0,retailer=0,browser=0,retries=0)
    doc['budget']['catalog_total']=30
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):m.run(path,sha256(path),private=private,credential_loader=lambda _:pytest.fail())


def test_stop_at_100_diversity_csv_sample_and_replay(tmp_path):
    calls=[]
    def transport(request):
        u=urlsplit(request.full_url)
        calls.append(u.path)
        if u.hostname=='api.amazon.com':return dict(access_token='secret-access',token_type='bearer')
        assert u.path==m.PATH and request.get_method()=='GET'
        params=parse_qs(u.query)
        assert params['marketplaceIds']==[m.MARKETPLACE] and params['pageSize']==['20']
        q=next(q for q in m.plan(audit_empty())['queries'] if q['brand']==params['brandNames'][0])
        base=len(calls)*100
        return ResponseDocument(dict(items=[item(base+i,q) for i in range(20)],numberOfResults=20),200)
    report,private,path,digest,clock=execute(tmp_path,transport)
    assert report['status']=='target_reached' and len(report['candidates'])==100
    assert len(calls)==13
    assert len({v['brand'] for v in report['candidates'].values()})==12
    summary=m.export(report,tmp_path/'export')
    assert summary['keyword_requests']==12 and summary['identity_requests']==0
    rows=list(csv.DictReader((tmp_path/'export/M63_amazon_candidates_100.csv').open(encoding='utf-8-sig')))
    assert len(rows)==100 and len({r['asin'] for r in rows})==100
    manifest=json.loads((tmp_path/'export/M63_eligibility_manifest_20.json').read_bytes())
    assert len(manifest['asins'])==20 and len(set(manifest['asins']))==20
    assert manifest['execution_authorized'] is False and manifest['budget']['restrictions']==20
    assert not set(manifest['asins']) & m.EXCLUSIONS
    payload=(private/'m63-catalog-discovery-01.json').read_text()
    assert all(secret not in payload for secret in ('secret-access','secret-key','secret-client','secret-refresh'))
    with pytest.raises(FileExistsError):
        m.run(path,digest,private=private,transport=lambda _:pytest.fail(),credential_loader=lambda _:pytest.fail())
    # New output/manifest path cannot renew the authorization.
    renamed=tmp_path/'renamed.json'
    renamed.write_bytes(path.read_bytes())
    with pytest.raises(FileExistsError):m.run(renamed,digest,private=private,transport=lambda _:pytest.fail(),credential_loader=lambda _:pytest.fail())


def test_duplicate_shortfall_and_identity_only_when_missing(tmp_path):
    count=0
    def transport(request):
        nonlocal count
        if urlsplit(request.full_url).hostname=='api.amazon.com':return dict(access_token='test-access',token_type='bearer')
        count+=1
        params=parse_qs(urlsplit(request.full_url).query)
        if 'identifiers' in params:
            q=m.plan(audit_empty())['queries'][0]
            values=[item(1,q)]
        else:
            q=next(q for q in m.plan(audit_empty())['queries'] if q['brand']==params['brandNames'][0])
            # Only one query produces a missing-model repeated ASIN.
            values=[item(1,q,modelNumber=''),item(1,q,modelNumber='')] if q['brand']=='OXO' else []
        return dict(items=values,numberOfResults=len(values),pagination=dict(nextToken='private-cursor'))
    report,private,*_=execute(tmp_path,transport)
    counts={kind:sum(a['kind']==kind for a in report['attempts']) for kind in ('keyword','identity')}
    assert counts==dict(keyword=24,identity=1) and count==25
    assert len(report['candidates'])==1 and report['rejected']['duplicate_observation']==4
    assert 'private-cursor' not in (private/'m63-catalog-discovery-01.json').read_text()


@pytest.mark.parametrize('failure',[AmazonFailure('private payload',http_status=429,reason='http_error'),
                                    AmazonFailure('private payload',http_status=403,reason='http_error'),
                                    TimeoutError('private payload')])
def test_errors_no_retry_and_durable_attempt(tmp_path,failure):
    calls=[]
    def transport(request):
        calls.append(request)
        if len(calls)==1:return dict(access_token='test-access',token_type='bearer')
        raise failure
    report,private,*_=execute(tmp_path,transport)
    assert report['status']=='stopped_no_retry' and len(calls)==2
    assert report['attempts'][-1]['status']=='failed'
    with sqlite3.connect(private/'m63-catalog-accounting-01.sqlite3') as db:
        assert db.execute('SELECT kind,state FROM attempts ORDER BY ordinal').fetchall()==[('authentication','response_received'),('keyword','failed')]
    assert 'private payload' not in (private/'m63-catalog-discovery-01.json').read_text()


def test_auth_failure_never_searches(tmp_path):
    report,*_=execute(tmp_path,lambda _:(_ for _ in ()).throw(TimeoutError('secret')))
    assert len(report['attempts'])==1 and not report['candidates']


def test_malformed_response_stops_without_retry(tmp_path):
    calls=[]
    def transport(request):
        calls.append(request)
        return dict(access_token='token',token_type='bearer') if len(calls)==1 else dict(items='bad',numberOfResults=1)
    report,*_=execute(tmp_path,transport)
    assert report['status']=='stopped_no_retry' and len(calls)==2


@pytest.mark.parametrize('changes,reason',[
    (dict(brand='Other'),'missing_or_different_brand_title'),
    (dict(itemName='OXO measuring cups aerosol'),'excluded_or_obvious_risk'),
    (dict(itemClassification='VARIATION_PARENT'),'variation_parent')])
def test_screen_risks_and_parents(changes,reason):
    q=m.plan(audit_empty())['queries'][0]
    snap,error=m.screen(item(1,q,**changes),q,m.now(),'synthetic',is_mock=True)
    assert snap is None and error==reason


def test_history_failed_reserved_attempts_ledger_and_immutable_exclusions(tmp_path):
    root=tmp_path/'history'
    root.mkdir()
    doc=dict(is_mock=False,attempts=[dict(stage='restrictions',asin='B000000001',status='failed'),
        dict(kind='detail',asin='B000000002',status='reserved'),dict(kind='search',asin='B000000003',status='response_received')])
    (root/'candidate-test.json').write_text(json.dumps(doc))
    # Invalid secret file proves the audit never opens it.
    (root/'credentials.json').write_text('not JSON')
    with sqlite3.connect(root/'candidate-executions.sqlite3') as db:
        db.execute('CREATE TABLE candidate_operations(request_key TEXT,kind TEXT,asin TEXT,state TEXT)')
        db.execute("INSERT INTO candidate_operations VALUES ('key','restrictions','B000000004','claimed_not_attempted')")
    result=audit(root)
    assert set(result['excluded_asins'])==m.EXCLUSIONS|{'B000000001','B000000002','B000000004'}
    before=sha256(root/'candidate-test.json')
    audit(root)
    assert sha256(root/'candidate-test.json')==before
    (root/'candidate-bad.json').write_text('invalid')
    with pytest.raises(ValueError):audit(root)


def test_historical_drift_rejected_before_credentials(tmp_path):
    private,path,digest,_=setup(tmp_path)
    (private/'candidate-new.json').write_text('{}')
    with pytest.raises(ValueError):m.run(path,digest,private=private,credential_loader=lambda _:pytest.fail())


def test_csv_formula_safety_and_literal_identifiers():
    assert m.csv_value(' =WEBSERVICE("x")').startswith("'")
    assert m.csv_value('012345678905')=='012345678905'


def test_full_29_catalog_budget_and_no_30th_request(tmp_path):
    keyword=identity=0
    def transport(request):
        nonlocal keyword,identity
        if urlsplit(request.full_url).hostname=='api.amazon.com':
            return dict(access_token='test-access',token_type='bearer')
        params=parse_qs(urlsplit(request.full_url).query)
        if 'identifiers' in params:
            identity+=1
            return dict(items=[],numberOfResults=0)
        keyword+=1
        q=next(q for q in m.plan(audit_empty())['queries'] if q['brand']==params['brandNames'][0])
        # Nine products per query, missing model, in three categories => 75
        # candidates, plus 9 home improvement candidates => 84 and 5 batches.
        values=[] if q['category']=='home_improvement' and q['brand']!='Command' else [item(100*keyword+i,q,modelNumber='') for i in range(9)]
        return dict(items=values,numberOfResults=len(values),pagination=dict(nextToken='next'))
    report,*_=execute(tmp_path,transport)
    assert keyword==24 and identity==5
    assert len(report['attempts'])==30 and report['status']=='completed_bounded_shortfall'


def test_offline_saved_keeps_timestamp_and_provenance(tmp_path,monkeypatch):
    private=tmp_path/'private'
    private.mkdir(mode=0o700)
    q=m.plan(audit_empty())['queries'][2]
    snap,_=m.screen(item(1,q),q,'2026-10-25T12:00:00+00:00','synthetic-origin',is_mock=False)
    snap['kind']='saved_search_summary'
    monkeypatch.setattr(m,'audit_saved',lambda _ :([snap],dict(reports=[])))
    report=m.saved_report(private)
    assert len(report['candidates'])==1 and not report['attempts']
    value=next(iter(report['candidates'].values()))
    assert value['observed_at']=='2026-10-25T12:00:00+00:00'
    assert value['evidence_refs'][0]['provenance']=='synthetic-origin'
    assert 'Saved search summary' in value['catalog']['mapping_issues'][-1]


def cohort(tmp_path):
    private=tmp_path/'private'
    private.mkdir(mode=0o700)
    candidates={}
    for i in range(20):
        q=m.plan(audit_empty())['queries'][i//2]
        snap,_=m.screen(item(i+1,q),q,m.now(),'synthetic',is_mock=True)
        snap['evidence_refs']=[dict(attempt=i+1,item_sha256='synthetic')]
        candidates[snap['catalog']['asin']]=snap
    report=dict(mode='SYNTHETIC_TEST',manifest=m.plan(audit(private)),candidates=candidates,attempts=[],status='synthetic',is_mock=True)
    m.export(report,tmp_path/'export')
    path=tmp_path/'export/M63_eligibility_manifest_20.json'
    return private,path,sha256(path)


def test_restrictions_proposal_validation_only_and_twenty_bound(tmp_path):
    from ops import m63_restrictions as r
    private,path,digest=cohort(tmp_path)
    manifest=r.validate(path,digest,private)
    assert len(manifest['asins'])==20
    with pytest.raises(ValueError):r.run(path,digest,21,private=private)
    assert not (private/'m63-eligibility-authorization-01.json').exists()
    manifest['asins'].append('B000000099')
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):r.validate(path,sha256(path),private)


def test_future_restrictions_runner_synthetic_scope_replay_and_redaction(tmp_path):
    from ops import m63_restrictions as r
    private,path,digest=cohort(tmp_path)
    calls=[]
    def transport(request):
        calls.append(request)
        if len(calls)==1:return dict(access_token='test-access',token_type='bearer')
        u=urlsplit(request.full_url)
        assert u.path=='/listings/2021-08-01/restrictions'
        params=parse_qs(u.query)
        assert params['conditionType']==['new_new']
        return dict(restrictions=[dict(marketplaceId=m.MARKETPLACE,conditionType='new_new',reasons=[dict(reasonCode='APPROVAL_REQUIRED',message='MOCKSELLERID',links=[dict(resource='https://example.com/MOCKSELLERID')])])])
    report=r.run(path,digest,20,private=private,transport=transport,
                 credential_loader=lambda _:dict(client_id='mock-client',client_secret='mock-key',refresh_token='mock-refresh'),
                 seller_prompt=lambda:'MOCKSELLERID',is_mock=True,sleep=lambda _:None)
    assert len(calls)==21
    assert all(row['restrictions']['data']['approval_required'] is True for row in report['rows'])
    assert 'MOCKSELLERID' not in json.dumps(report)
    with pytest.raises(ValueError):r.run(path,digest,20,private=private,transport=lambda _:pytest.fail())


def test_sample_excludes_previously_attempted_and_brand_alias():
    assert m.brand_key('PHILIPS')==m.brand_key('Philips LED')
    candidates={}
    for n in range(4):
        q=m.plan(audit_empty())['queries'][0]
        snap,_=m.screen(item(n+1,q),q,m.now(),'synthetic',is_mock=True)
        candidates[snap['catalog']['asin']]=snap
    chosen=m.select_sample(candidates,{'B000000001'})
    assert len(chosen)==2 and all(v['catalog']['asin']!='B000000001' for v in chosen)


def test_network_preflight_failure_does_not_reserve_or_read_credentials(tmp_path,monkeypatch):
    private,path,digest,_=setup(tmp_path)
    monkeypatch.setattr(m,'runtime_preflight',lambda:(_ for _ in ()).throw(OSError('DNS unavailable')))
    with pytest.raises(OSError):
        m.run(path,digest,private=private,credential_loader=lambda _:pytest.fail())
    assert not (private/'m63-catalog-discovery-01.json').exists()
    assert not (private/'m63-catalog-accounting-01.sqlite3').exists()


def test_summary_manifest_hash_is_actual_file_hash(tmp_path):
    _,path,_=cohort(tmp_path)
    summary=json.loads((path.parent/'M63_discovery_summary.json').read_bytes())
    assert summary['manifest_sha256']==sha256(path)
