"""M77 pinned evidence boundaries, using synthetic M76 exports only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest
from app import m76, m76_analysis, m77_policy as policy
from app.m70_sources import file_hash
from app.observations import canonical, fingerprint
from test_m76 import catalog


@pytest.fixture(autouse=True)
def sockets_blocked(monkeypatch):
    def forbidden(*a,**kw):raise AssertionError('network prohibited')
    for name in ('connect','connect_ex'):
        monkeypatch.setattr(socket.socket,name,forbidden)
    for name in ('create_connection','getaddrinfo'):
        monkeypatch.setattr(socket,name,forbidden)


@pytest.fixture
def original(catalog,tmp_path,monkeypatch):
    prior,observations,pages,manifest,digest=catalog
    for i,q in enumerate(manifest['queries']):
        old=q['query_id'];q['query_id']=f'q{i:03}'
        for p in pages:
            if p['query_reference']==old:p['query_reference']=q['query_id']
        if i>=20:q['keywords']=policy.KEYWORDS[i-20]
    hashes={'m73:M73_report.json':digest}
    report=m76_analysis.analyze(prior,observations,pages,manifest,digest)
    report['source_coverage']=dict(m73=prior['source_coverage'],m75={})
    directory=tmp_path/'m76'
    m76.export(report,directory,hashes,m76.implementation(),lambda:None)
    monkeypatch.setattr(policy,'COMPLETION_SHA256',file_hash(directory/'M76_evidence_manifest.json'))
    monkeypatch.setattr(policy,'CONTRACT_SHA256',file_hash(directory/'M76_M77_proposal.json'))
    monkeypatch.setattr(policy,'load',lambda *a,**kw:(prior,observations,pages,manifest,hashes,{},lambda:None))
    return directory


def test_exact_reconstruction_and_immutable_inputs(original):
    before={p.name:file_hash(p) for p in original.iterdir()}
    result=policy.completion(original,Path('unused'),{})
    assert len(result['report']['catalog'])==777
    assert result['report']['summary']['remaining_asins']==223
    assert result['manifest']['manifest_sha256']==policy.CANONICAL_SHA256
    result['guard']()
    assert before=={p.name:file_hash(p) for p in original.iterdir()}


@pytest.mark.parametrize('name',[
 'M76_evidence_manifest.json','M76_digest_report.txt','M76_report.json','M76_summary.json',
 'M76_M77_proposal.json','M76_catalog_review.xlsx','M76_catalog.csv',
 'M76_identity_gaps_conflicts.json','M76_historical_annotations.json'])
def test_original_output_corruption_rejected(original,name):
    p=original/name;p.write_bytes(p.read_bytes()+b' ')
    with pytest.raises(ValueError):policy.completion(original,Path('unused'),{})


@pytest.mark.parametrize('change',['phrase','order','id','rank','missing','extra'])
def test_all_exact_reviewed_candidates_required(original,monkeypatch,change):
    p=original/'M76_M77_proposal.json';proposal=json.loads(p.read_text())
    if change=='phrase':proposal['queries'][30]['keywords']='substituted phrase'
    elif change=='order':proposal['queries'].reverse()
    elif change=='id':proposal['queries'][0]['query_id']='q000'
    elif change=='rank':proposal['queries'][0]['rank']=2
    elif change=='missing':proposal['queries'].pop()
    else:proposal['queries'].append(proposal['queries'][0])
    p.write_text(canonical(proposal)+'\n')
    m=original/'M76_evidence_manifest.json';doc=json.loads(m.read_text())
    doc['output_sha256'][p.name]=file_hash(p);m.write_text(canonical(doc)+'\n')
    monkeypatch.setattr(policy,'CONTRACT_SHA256',file_hash(p))
    monkeypatch.setattr(policy,'COMPLETION_SHA256',file_hash(m))
    # Rebind digest report too, proving the semantic scope check independently.
    (original/'M76_digest_report.txt').write_text('M76_evidence_manifest.json  '+file_hash(m)+'\n'+''.join(
        f'{k}  {v}\n' for k,v in doc['output_sha256'].items()))
    with pytest.raises(ValueError,match='31 reviewed'):policy.completion(original,Path('unused'),{})


def test_historical_guard_detects_post_validation_mutation(original):
    historical=policy.completion(original,Path('unused'),{})
    p=original/'M76_summary.json';p.write_bytes(p.read_bytes()+b' ')
    with pytest.raises(ValueError):historical['guard']()


def test_original_implementation_drift_rejected(original,monkeypatch):
    code=policy.implementation();code['m76.py']='0'*64
    monkeypatch.setattr(policy,'implementation',lambda:code)
    with pytest.raises(ValueError):policy.completion(original,Path('unused'),{})


def test_exact_request_manifest():
    from app.m71_manifest import DATA, AUTH_URL
    definitions=policy.requests()
    assert len(definitions)==31 and definitions[0]['slot']==2 and definitions[-1]['slot']==32
    assert [d['query_id'] for d in definitions]==[f'q{i:03}' for i in range(20,51)]
    assert definitions[-1]['parameters']['keywords']=='cosmetic brush holder'
    for d in definitions:
        assert d['method']=='GET' and d['host']=='sellingpartnerapi-na.amazon.com'
        assert d['path']=='/catalog/2022-04-01/items'
        assert set(d['parameters'])=={'keywords','marketplaceIds','includedData','pageSize'}
        assert d['parameters']['marketplaceIds']=='ATVPDKIKX0DER'
        assert d['parameters']['includedData']==','.join(DATA) and d['parameters']['pageSize']=='20'
    artifact=json.loads(Path('docs/M77_REQUEST_MANIFEST.json').read_text())
    assert artifact['requests']==definitions and artifact['budget']==policy.BUDGET
    assert artifact['request_definitions_sha256']==fingerprint(definitions)


@pytest.mark.parametrize('operation',[
 "socket.socket()", "socket.getaddrinfo('example.com',443)",
 "open('/tmp/credentials.json','rb')", "open('/tmp/m77-owner-authorization-test.json','rb')"])
def test_offline_guard_forbids_network_and_credential_artifacts(operation):
    script="import sys,socket;from ops.m77_offline import prohibit;sys.addaudithook(prohibit);"+operation
    result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True)
    assert result.returncode!=0 and 'PermissionError' in result.stderr


def test_offline_entrypoint_cannot_select_authorize_or_execute(tmp_path):
    for action in ('authorize','execute'):
        result=subprocess.run([sys.executable,'-m','ops.m77_offline',action],capture_output=True,text=True)
        assert result.returncode==2
