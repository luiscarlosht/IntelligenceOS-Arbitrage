"""Offline-only pilot checks; synthetic HTTP/credentials and temporary private storage."""
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app import amazon_pilot as pilot
from ops import saved_target_restrictions as runner

CREDS = dict(client_id='mock-client', client_secret='mock-secret', refresh_token='mock-refresh')


@pytest.fixture(autouse=True)
def no_live_io(monkeypatch):
    monkeypatch.setattr(pilot, 'load_credentials', lambda *_: pytest.fail('Real credential access'))
    monkeypatch.setattr(pilot, '_request_json', lambda *_: pytest.fail('Live request'))


def case(tmp_path, count=4):
    targets = [dict(asin=f'B{i:09d}', target_id=f'amazon:ATVPDKIKX0DER:B{i:09d}',
        brand=f'Brand{i}', identifiers=[dict(kind='UPC', value=f'{i:012d}')],
        historical_metrics=dict(mapping_issues=[])) for i in range(count)]
    source=tmp_path/'targets.json';source.write_text(json.dumps(targets))
    evidence=tmp_path/'negative.json';evidence.write_text(json.dumps(dict(excluded_targets=[])))
    manifest=runner.prepare(source,evidence,[t['asin'] for t in targets][:10],[])
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest))
    return path,runner.digest(path),manifest


def run(path, sha, manifest, private, calls, fail_at=None):
    def transport(request):
        calls.append(request)
        if len(calls)==fail_at:raise RuntimeError('synthetic failure')
        url=urlsplit(request.full_url)
        if url.hostname=='api.amazon.com':return dict(access_token='mock-access',token_type='bearer')
        assert request.get_method()=='GET'
        assert url.path=='/listings/2021-08-01/restrictions'
        params=parse_qs(url.query)
        assert params['sellerId']==['MOCKSELLER']
        assert params['conditionType']==['new_new']
        assert params['marketplaceIds']==['ATVPDKIKX0DER']
        return dict(restrictions=[dict(marketplaceId='ATVPDKIKX0DER', conditionType='new_new',
            reasons=[dict(reasonCode='APPROVAL_REQUIRED', message='Apply for permission',
                links=[dict(resource='https://sellercentral.amazon.com/test',verb='GET',title='Apply')])])])
    return runner.execute(path,sha,manifest['budget']['maximum_requests'],private,
        transport=transport,credential_loader=lambda _:CREDS,seller_prompt=lambda:'MOCKSELLER',
        is_mock=True,sleep=lambda _:None)


@pytest.mark.parametrize('count',[1,4,10])
def test_only_restrictions_bound_and_approval_details(tmp_path,count):
    p,h,m=case(tmp_path,count);calls=[]
    report=run(p,h,m,tmp_path/'private',calls)
    assert len(calls)==1+count
    assert [a['stage'] for a in report['attempts']]==['authentication']+['restrictions']*count
    assert report['live_requests']==0
    for row in report['rows']:
        d=row['restrictions']['data']
        assert d['listing_permission']['value'] is False
        assert d['fulfillment_eligibility'] is None
        assert d['approval_instructions'][0]['links'][0]['resource']=='https://sellercentral.amazon.com/test'
        assert row['pricing']==row['fees']==dict(status='not_requested',data=None)
    # Reservation prevents replay, including when credentials would otherwise be loaded.
    with pytest.raises(FileExistsError):run(p,h,m,tmp_path/'private',calls)
    assert len(calls)==count+1


def test_source_change_and_exact_budget_rejected_before_io(tmp_path):
    p,h,m=case(tmp_path);Path(m['source']).write_text('[]')
    with pytest.raises((ValueError,KeyError)):runner.execute(p,h,5,tmp_path/'private')
    assert not (tmp_path/'private').exists()
    p,h,m=case(tmp_path)
    with pytest.raises(ValueError,match='ceiling'):runner.validate(p,h,11)
    with pytest.raises(ValueError,match='checksum'):runner.validate(p,'0'*64,5)


def test_approval_exclusion_and_sharpie_scope(tmp_path):
    p,h,m=case(tmp_path)
    e=Path(m['exclusion_evidence']);e.write_text(json.dumps(dict(excluded_targets=[dict(asin=m['asins'][0]) ])))
    with pytest.raises(ValueError,match='Excluded'):runner.prepare(m['source'],e,m['asins'],[])
    e.write_text(json.dumps(dict(excluded_targets=[])))
    s=Path(m['source']);targets=json.loads(s.read_text());targets[0]['brand']='Sharpie';s.write_text(json.dumps(targets))
    with pytest.raises(ValueError,match='Excluded'):runner.prepare(s,e,m['asins'],[])


def test_failure_is_retained_no_retry_and_auth_failure_stops(tmp_path):
    p,h,m=case(tmp_path);calls=[]
    r=run(p,h,m,tmp_path/'failed-stage',calls,fail_at=2)
    assert len(calls)==5
    assert r['rows'][0]['restrictions']['status']=='failed'
    assert r['rows'][0]['restrictions']['data'] is None
    assert all(row['fulfillment_eligibility'] is None for row in r['rows'])
    calls=[];r=run(p,h,m,tmp_path/'failed-auth',calls,fail_at=1)
    assert len(calls)==1 and r['status']=='stopped_no_retry'
    assert all(row['restrictions']['status']=='not_attempted' for row in r['rows'])


def test_no_restrictions_does_not_establish_fba_eligibility(tmp_path):
    p,h,m=case(tmp_path,1);calls=[]
    def transport(request):
        calls.append(request)
        return dict(access_token='mock-access',token_type='bearer') if len(calls)==1 else dict(restrictions=[])
    r=runner.execute(p,h,2,tmp_path/'private',transport=transport,
        credential_loader=lambda _:CREDS,seller_prompt=lambda:'MOCKSELLER',is_mock=True,sleep=lambda _:None)
    data=r['rows'][0]['restrictions']['data']
    assert data['listing_permission']['value'] is True
    assert data['approval_required'] is False
    assert data['fulfillment_eligibility'] is None and data['purchase_approved'] is False


def reviewed_case(tmp_path, count=20):
    p,_,m=case(tmp_path,count)
    source=Path(m['source']);targets=json.loads(source.read_text())
    records=[]
    for t in targets:
        t.update(model='MODEL-'+t['asin'],title=t['brand']+' one specified retail pack',exact_package_evidence={})
        records.append(dict(asin=t['asin'],target_sha256=hashlib.sha256(json.dumps(t,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            identity_supported=True,unresolved_identity_contradictions=[],reviewed_mapping_issues=[],
            brand_label=t['brand'],pack='One specified retail pack',category='Synthetic category',
            review_rationale='Synthetic source identity reviewed',multi_value_fields={}))
    source.write_text(json.dumps(targets))
    review=tmp_path/'review.json';review.write_text(json.dumps(dict(targets=records)))
    m=runner.prepare(source,m['exclusion_evidence'],[t['asin'] for t in targets],[],identity_review=review,stop_after_no_restrictions=3)
    p.write_text(json.dumps(m))
    return p,runner.digest(p),m


def test_twenty_checks_stop_after_three_and_preserve_unattempted(tmp_path):
    p,h,m=reviewed_case(tmp_path);calls=[]
    def transport(request):
        calls.append(request)
        return dict(access_token='mock-access',token_type='bearer') if len(calls)==1 else dict(restrictions=[])
    r=runner.execute(p,h,21,tmp_path/'private',transport=transport,
        credential_loader=lambda _:CREDS,seller_prompt=lambda:'MOCKSELLER',is_mock=True,sleep=lambda _:None)
    assert len(calls)==4 and len(r['rows'])==20
    assert r['no_restrictions_asins']==m['asins'][:3]
    assert r['status']=='stopped_listing_permission_goal'
    assert all(row['restrictions']==dict(status='not_attempted',data=None,reason='listing_permission_goal_reached') for row in r['rows'][3:])
    assert r['sourcing_document_acceptability'] is None
    assert all(row['fulfillment_eligibility'] is None for row in r['rows'])
    saved=json.loads(next((tmp_path/'private').glob('saved-target-restrictions-*.json')).read_text())
    assert saved==r
    with pytest.raises(FileExistsError):runner.execute(p,h,21,tmp_path/'private')


def test_twenty_all_restricted_respects_twenty_one_request_cap(tmp_path):
    p,h,m=reviewed_case(tmp_path);calls=[]
    r=run(p,h,m,tmp_path/'private',calls)
    assert len(calls)==21 and r['no_restrictions_asins']==[]
    assert all(row['restrictions']['data']['approval_required'] is True for row in r['rows'])


def test_early_stop_counts_only_successfully_parsed_empty_restrictions(tmp_path):
    p,h,m=reviewed_case(tmp_path);calls=[]
    def transport(request):
        calls.append(request);n=len(calls)
        if n==1:return dict(access_token='mock-access',token_type='bearer')
        if n==2:raise RuntimeError('synthetic transport failure')
        if n==3:return dict(restrictions=[dict(marketplaceId='ATVPDKIKX0DER',conditionType='new_new',reasons=[dict(reasonCode='APPROVAL_REQUIRED',message='Apply')])])
        if n==5:return dict(errors=[dict(code='BadResponse')])
        return dict(restrictions=[])
    r=runner.execute(p,h,21,tmp_path/'private',transport=transport,
        credential_loader=lambda _:CREDS,seller_prompt=lambda:'MOCKSELLER',is_mock=True,sleep=lambda _:None)
    assert len(calls)==7
    assert r['no_restrictions_asins']==[m['asins'][i] for i in [2,4,5]]
    assert [r['rows'][i]['restrictions']['status'] for i in [0,3]]==['failed','failed']
    assert all(row['restrictions']['status']=='not_attempted' for row in r['rows'][6:])


def test_review_drift_and_contradiction_fail_before_credentials(tmp_path):
    p,h,m=reviewed_case(tmp_path)
    review=Path(m['identity_review']);data=json.loads(review.read_text())
    data['targets'][0]['unresolved_identity_contradictions']=['wrong pack']
    review.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='Unsupported'):runner.execute(p,h,21,tmp_path/'private')
    assert not (tmp_path/'private').exists()


def test_twenty_one_targets_and_wrong_goal_rejected(tmp_path):
    p,h,m=case(tmp_path,21)
    with pytest.raises(ValueError):runner.prepare(m['source'],m['exclusion_evidence'],[t['asin'] for t in json.loads(Path(m['source']).read_text())],[],identity_review=tmp_path/'not-read.json',stop_after_no_restrictions=3)
