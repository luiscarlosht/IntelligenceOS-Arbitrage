"""Synthetic offline fixtures only; no production evidence required."""
import json
import socket
import sqlite3

import pytest
from openpyxl import load_workbook
from app import m76, m76_analysis, m76_evidence
from app.m70_identity import observation, merge
from app.m70_sources import file_hash, ingest
from app.m75_registry import Registry, inspect
from app.observations import fingerprint
from test_m75 import expansion, run as run_expansion
from test_m74 import ready
from test_m73 import completed, no_network
from test_m72 import pilot
from test_m69 import fixture as history_fixture, offline
from test_m67 import cohort


def obs(n, **fields):
    return observation(dict(asin=f'B{n:09d}',marketplace='ATVPDKIKX0DER',brand='Fixture',**fields),
        role='amazon',reference=f'local:fixture:{n}:{fingerprint(fields)}',source_hash='a'*64,
        source_class='local_json',observed_at='2026-11-01T00:00:00Z')


@pytest.fixture
def catalog():
    prior=dict(catalog=[merge([obs(n)]) for n in range(377)],exclusions=[],source_coverage={})
    observations=[obs(n) for n in range(377,777)]
    manifest=dict(permanently_excluded_asins=[f'B{n:09d}' for n in range(97)],
        previously_checked_asins=[f'B{n:09d}' for n in range(40)],executed_query_ids=[],queries=[
            dict(query_id=f'q{n}',keywords=f'fixture phrase {n}',category_intent=f'intent{n%10}',review_order=n)
            for n in range(51)])
    pages=[dict(request_slot=n+2,query_reference=f'q{n}',items=[dict(asin=o['asin']) for o in observations[n*20:(n+1)*20]])
           for n in range(20)]
    return prior,observations,pages,manifest,'b'*64


def test_union_gaps_provenance_proposal(catalog):
    report=m76_analysis.analyze(*catalog)
    assert len(report['catalog'])==777
    assert report['summary']['missing_fields']['condition']==777
    assert report['summary']['purchase_ready_inventory']==0
    assert len(report['proposal']['queries'])==31
    assert len(report['proposal']['selected_query_ids'])==23
    assert report['proposal']['projected_incremental']==230
    assert sum(r['incremental'] for r in report['coverage'])==400
    assert report['catalog'][0]['historical_m73_record']==catalog[0]['catalog'][0]
    assert report['catalog'][400]['historical_m73_record'] is None
    assert report['annotations'][0]['previously_checked_seller_specific']
    assert not any(q['execution_authorized'] for q in report['proposal']['queries'])


@pytest.mark.parametrize('mutation',['duplicate_baseline','duplicate_new','overlap','missing','excluded','retailer'])
def test_fail_closed_counts(catalog,mutation):
    prior,observations,_,manifest,_=catalog
    if mutation=='duplicate_baseline': prior['catalog'].append(prior['catalog'][0])
    if mutation=='duplicate_new': observations[-1]=observations[0]
    if mutation=='overlap': observations[-1]=obs(0)
    if mutation=='missing': observations.pop()
    if mutation=='excluded': manifest['permanently_excluded_asins'][-1]=observations[0]['asin']
    if mutation=='retailer': observations[0]['role']='retailer'
    with pytest.raises(ValueError): m76_analysis.analyze(*catalog)


def test_conflicts_and_original_provenance_preserved(catalog):
    p=catalog[0]['catalog'][0]
    changed=merge([obs(0,model='A'),obs(0,model='B')])
    p.update(changed)
    report=m76_analysis.analyze(*catalog)
    assert report['catalog'][0]['model'] is None
    assert report['catalog'][0]['identity_conflicts']==['model']
    assert report['catalog'][0]['historical_m73_record']['field_provenance']==changed['field_provenance']
    assert report['conflicts'][0]['resolution']=='UNRESOLVED'


def test_export_deterministic_formula_safe_no_overwrite(catalog,tmp_path,monkeypatch):
    report=m76_analysis.analyze(*catalog)
    def forbidden(*a,**kw):raise AssertionError('Network forbidden')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(socket,'getaddrinfo',forbidden)
    code=m76.implementation()
    for name in ('one','two'): m76.export(report,tmp_path/name,{'fixture':'a'*64},code,lambda:None)
    one={p.name:file_hash(p) for p in (tmp_path/'one').iterdir()}
    assert one=={p.name:file_hash(p) for p in (tmp_path/'two').iterdir()}
    manifest=json.loads((tmp_path/'one/M76_evidence_manifest.json').read_text())
    assert all(one[k]==v for k,v in manifest['output_sha256'].items())
    assert load_workbook(tmp_path/'one/M76_catalog_review.xlsx')['catalog'].max_row==778
    assert all(p.stat().st_mode&0o777==0o600 for p in (tmp_path/'one').iterdir())
    with pytest.raises(FileExistsError):m76.export(report,tmp_path/'one',{},code,lambda:None)


def test_drift_no_completion_manifest(catalog,tmp_path):
    report=m76_analysis.analyze(*catalog)
    def drift():raise ValueError('Source drift')
    with pytest.raises(ValueError):m76.export(report,tmp_path/'out',{},m76.implementation(),drift)
    assert not (tmp_path/'out/M76_evidence_manifest.json').exists()


@pytest.mark.parametrize('kind',['empty','partial','corrupt','missing'])
def test_registry_fail_closed(tmp_path,kind):
    path=tmp_path/'registry.sqlite3'
    if kind=='empty':path.touch(mode=0o600)
    elif kind in ('partial','corrupt'):
        registry=Registry(path,dict(preflight={}))
        registry.close()
        if kind=='corrupt':
            db=sqlite3.connect(path)
            db.execute('DROP TRIGGER immutable_m75_events_UPDATE')
            db.execute("UPDATE m75_events SET event_sha256=?",('a'*64,));db.commit();db.close()
    if kind=='partial':assert inspect(path)['status']!='COMPLETED_NO_REPLAY'
    else:
        with pytest.raises((ValueError,sqlite3.DatabaseError,FileNotFoundError)):inspect(path)


def test_m75_corrupted_source_and_checkpoint_rejected(expansion,tmp_path,monkeypatch):
    # Reuse prior milestone validators and a real immutable fixture registry.
    e=expansion;snapshot,_,_,path=run_expansion(e,tmp_path)
    assert snapshot['checkpoint_sha256'] != file_hash(path)
    from app.m75_reporting import export
    output=tmp_path/'source'
    export(snapshot,e['prepared'].manifest,e['prepared'].baseline,output)
    source=output/'M75_M70_sources.json'; observations,_=ingest(source)
    assert observations
    pages=output/'M75_catalog_pages.json';pages.write_bytes(pages.read_bytes()+b' ')
    with pytest.raises(ValueError,match='digest'):ingest(source)


def test_cli_missing_evidence_fails_without_network(tmp_path,monkeypatch):
    def forbidden(*a,**kw):raise AssertionError('Network forbidden')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    argv=[]
    for name in ('m74-dir','m73-dir','baseline-dir','proposal','private','sources','summary','store','m67-manifest','output'):
        argv.extend(['--'+name,str(tmp_path/name)])
    for name in ('m73-digests-sha256','baseline-report-sha256','checkpoint','m67-sha256'):argv.extend(['--'+name,'0'*64])
    assert m76.main(argv)==2
    assert not (tmp_path/'output').exists()


def test_run_integration_no_network(catalog,tmp_path,monkeypatch):
    prior,observations,pages,manifest,digest=catalog
    monkeypatch.setattr(m76,'load',lambda *a,**kw:(prior,observations,pages,manifest,
        {'m73:M73_report.json':digest},{},lambda:None))
    def forbidden(*a,**kw): raise AssertionError('Network forbidden')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)
    monkeypatch.setattr(socket,'getaddrinfo',forbidden)
    kwargs={k:tmp_path/k for k in ('m73_dir','baseline_dir','private','sources')}
    kwargs['sources']=tmp_path/'historical'/'sources.json'
    result=m76.run(output=tmp_path/'new',m74_dir=tmp_path/'m74',**kwargs)
    assert result['real_asins']==777 and result['actual_requests']==0
    with pytest.raises(ValueError):m76.run(output=kwargs['private']/'new',m74_dir=tmp_path/'m74',**kwargs)


@pytest.mark.parametrize('kind',['checkpoint','status','requests','uncertain','preflight','digest'])
def test_evidence_fails_before_import(expansion,tmp_path,monkeypatch,kind):
    e=expansion;snapshot,_,_,registry=run_expansion(e,tmp_path)
    from app.m75_reporting import export
    private=e['private']
    import shutil
    shutil.copyfile(registry,private/'m75-catalog-discovery.sqlite3')
    (private/'m75-catalog-discovery.sqlite3').chmod(0o600)
    export(snapshot,e['prepared'].manifest,e['prepared'].baseline,private/'m75-catalog-expansion-output')
    monkeypatch.setattr(m76_evidence,'CHECKPOINT',snapshot['checkpoint_sha256'])
    if kind=='checkpoint': snapshot['checkpoint_sha256']='0'*64
    elif kind=='status':snapshot['status']='STOPPED_NO_REPLAY'
    elif kind=='requests':snapshot['requests_consumed']=20
    elif kind=='uncertain':snapshot['uncertain_slots']=[21]
    elif kind=='preflight':snapshot['binding']['preflight']['requests']=[]
    else:
        p=private/'m75-catalog-expansion-output/M75_summary.json';p.write_bytes(p.read_bytes()+b' ')
    monkeypatch.setattr(m76_evidence,'inspect',lambda p:snapshot)
    def forbidden(*a,**kw):raise AssertionError('Must reject before import')
    monkeypatch.setattr(m76_evidence,'ingest',forbidden)
    monkeypatch.setattr(m76_evidence,'reproduce',forbidden)
    with pytest.raises(ValueError):m76_evidence.load(e['directory'],**e['evidence'])
