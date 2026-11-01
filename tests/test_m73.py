"""Offline synthetic evidence fixtures; never production execution or authorization."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest
from openpyxl import load_workbook

from test_m67 import cohort
from test_m69 import fixture as history_fixture, offline
from test_m70 import observe, product, raw_item
from test_m72 import pilot, Fake, Clock
from app import m73, m73_analysis as analysis, m73_evidence as evidence
from app.m70 import export as export_baseline
from app.m70_identity import merge
from app.m70_sources import file_hash
from app.m72_policy import preflight, REGISTRY
from app.m72_registry import Registry, inspect
from app.m72_execution import run_claimed
from app.m72_reporting import export as export_pilot
from app.amazon_pacing import OperationPacer
from app.observations import canonical, fingerprint


def write(path, value):
    path.write_text(canonical(value)+'\n'); path.chmod(0o600)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('M73 must remain offline')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    from app import amazon_pilot
    monkeypatch.setattr(amazon_pilot, '_request_json', forbidden)
    monkeypatch.setattr(amazon_pilot, 'load_credentials', forbidden)


@pytest.fixture
def completed(pilot, tmp_path, monkeypatch):
    c = pilot
    (c['private']/'candidate-execution.lock').touch(mode=0o600)
    p = merge([observe(product(1000))])
    p.update(retailer_match_status='UNKNOWN', permanently_excluded=False)
    from app.m70_discovery import implementation
    prior = dict(implementation_sha256=implementation(), mode='M70_OFFLINE_REPORT', catalog=[p], history=dict(excluded_asins=c['proposal']['excluded_asins']),
                 ranking=[], summary={}, source_coverage={})
    baseline_dir = tmp_path/'baseline'; export_baseline(prior, baseline_dir)
    args = (*c['args'][:-1], baseline_dir/'M70_catalog_1000.csv')
    report = preflight(*args)
    registry = Registry(c['private']/REGISTRY, dict(operation_id=evidence.OPERATION, preflight=report))
    transport = Fake(registry); clock = Clock()
    run_claimed(registry, transport, c['proposal'], report, before_request=lambda:None,
                pacer=OperationPacer(monotonic=clock.time,sleep=clock.sleep), deadline=120, monotonic=clock.time)
    registry.close()
    snapshot = inspect(c['private']/REGISTRY)
    saved = c['private']/'pilot-output'; export_pilot(snapshot,c['proposal'],{'B000001000'},saved)
    monkeypatch.setattr(evidence,'PROPOSAL_SHA256',c['proposal']['proposal_sha256'])
    monkeypatch.setattr(evidence,'MANIFEST_SHA256',file_hash(c['proposal_path']))
    kwargs = dict(baseline_dir=baseline_dir,baseline_report_sha256=file_hash(baseline_dir/'M70_report.json'),
        proposal=c['proposal_path'],private=c['private'],checkpoint=snapshot['checkpoint_sha256'],
        sources=saved/'M72_M70_sources.json',summary=saved/'M72_summary.json',store=c['store_path'],
        m67_manifest=c['path'],m67_sha256=c['digest'],output=tmp_path/'result')
    return c, kwargs


def load(kwargs):
    return evidence.load(kwargs['baseline_dir']/'M70_catalog_1000.csv',kwargs['baseline_dir']/'M70_report.json',
        kwargs['baseline_report_sha256'],kwargs['proposal'],kwargs['private']/REGISTRY,kwargs['checkpoint'],
        kwargs['sources'],kwargs['summary'],kwargs['store'],kwargs['private'],kwargs['m67_manifest'],kwargs['m67_sha256'])


def test_completed_union_provenance_immutability_private_excel(completed):
    c,k=completed
    protected=list(k['private'].rglob('*'))+list(k['baseline_dir'].iterdir())+[k['proposal'],k['store'],k['m67_manifest']]
    before={str(p):(file_hash(p) if p.is_file() and not any(s in p.name for s in ('credential','authorization','account-context')) else None,
                   p.stat().st_size,p.stat().st_mode,p.stat().st_mtime_ns) for p in protected}
    summary=m73.run(**k)
    assert summary['real_asins']==3 and summary['cross_cohort_duplicates']==1
    assert not summary['expected_count_reconciled'] and summary['count_difference']==-374
    assert summary['actual_requests']==summary['actual_authentication']==0
    assert summary['permanent_exclusions']==97 and summary['previously_checked_asins']==40
    report=json.loads((k['output']/'M73_report.json').read_text())
    p=next(p for p in report['catalog'] if p['asin']=='B000001000')
    assert p['cohorts']==['M70','M72'] and p['baseline_field_provenance']
    assert len(p['source_sha256'])==2
    assert p['baseline_source_references'] and p['identity_sha256']
    assert all(not p['identity_verified'] and p['eligibility']=='UNKNOWN' for p in report['catalog'])
    assert not next(r for r in report['ranking'] if r['asin']=='B000000000')['research_reviewable']
    assert sum(r['previously_checked_seller_specific'] for r in report['exclusions'])==40
    wb=load_workbook(k['output']/'M73_review.xlsx')
    assert set(wb.sheetnames)==set(m73.TABLES)|{'summary','audit'}
    assert wb['catalog'].max_row==4
    assert all(p.stat().st_mode&0o777==0o600 for p in k['output'].iterdir())
    assert k['output'].stat().st_mode&0o777==0o700
    after={str(p):(file_hash(p) if p.is_file() and not any(s in p.name for s in ('credential','authorization','account-context')) else None,
                   p.stat().st_size,p.stat().st_mode,p.stat().st_mtime_ns) for p in protected}
    assert before==after
    text=canonical(report)
    assert all(secret not in text for secret in ('SYNTHETICSECRET','SYNTHETICSELLER','SYNTHETICACCESS','PRIVATECURSOR'))
    with pytest.raises(FileExistsError): m73.run(**k)


@pytest.mark.parametrize('field,value', [('status','STOPPED_NO_REPLAY'),('requests_consumed',9),
    ('checkpoint_sha256','a'*64),('proposal_sha256','b'*64),('operation_id','OTHER')])
def test_summary_binding_fails_before_export(completed,field,value):
    _,k=completed; doc=json.loads(k['summary'].read_text());doc[field]=value;write(k['summary'],doc)
    with pytest.raises(ValueError):m73.run(**k)
    assert not k['output'].exists()


@pytest.mark.parametrize('key', ['checkpoint','baseline_report_sha256','m67_sha256'])
def test_wrong_reviewed_digests(completed,key):
    _,k=completed;k[key]='f'*64
    with pytest.raises(ValueError):m73.run(**k)
    assert not k['output'].exists()


def test_source_tamper_even_with_new_source_digest_rejected(completed):
    _,k=completed; manifest=json.loads(k['sources'].read_text());path=k['sources'].parent/manifest['sources'][0]['path']
    doc=json.loads(path.read_text());doc['pages'][0]['items'][0]['asin']='B999999999';write(path,doc)
    manifest['sources'][0]['sha256']=file_hash(path);write(k['sources'],manifest)
    with pytest.raises(ValueError):m73.run(**k)


def test_manifest_drift_and_missing_registry(completed):
    _,k=completed;k['proposal'].write_text(k['proposal'].read_text()+' ')
    with pytest.raises(ValueError):m73.run(**k)
    k['private'].joinpath(REGISTRY).unlink()
    with pytest.raises(ValueError):m73.run(**k)


def test_baseline_report_cannot_change_operation_bound_values(completed):
    _,k=completed;path=k['baseline_dir']/'M70_report.json';doc=json.loads(path.read_text())
    doc['catalog'][0]['brand']='Invented';write(path,doc);k['baseline_report_sha256']=file_hash(path)
    with pytest.raises(ValueError):m73.run(**k)


def test_output_symlinks_and_protected_directory_rejected(completed,tmp_path):
    _,k=completed;k['output']=k['private']/'new-output'
    with pytest.raises(ValueError):m73.run(**k)
    alias=tmp_path/'alias';alias.symlink_to(k['baseline_dir'],target_is_directory=True)
    k['output']=alias/'new-output'
    with pytest.raises(ValueError):m73.run(**k)


def test_conflict_preserves_alternatives_and_never_invents(completed):
    _,k=completed;e=load(k);row=e['observations'][0]
    row['fields']['model']=['FIRST','SECOND'];row['field_evidence']['model']['status']='CONFLICT'
    e['completion']['identity_conflicts']=1
    result=analysis.analyze(e);p=next(p for p in result['catalog'] if p['asin']==row['asin'])
    # The shared baseline model is an additional observation, never a tiebreaker.
    assert p['model'] is None and 'model' in p['identity_conflicts']
    review=next(r for r in result['conflicts'] if r['cohort']=='M72')
    assert review['observed_values']==['FIRST','MODEL1000','SECOND'] and review['resolution']=='UNRESOLVED'
    assert not next(r for r in result['ranking'] if r['asin']==p['asin'])['research_reviewable']
    assert result['summary']['combined_conflict_asins']==1


def test_missing_condition_gtin_pack_not_filled(completed):
    _,k=completed;e=load(k)
    for row in e['observations']:
        for field in ('gtin','condition','pack_quantity'):row['fields'][field]=[]
    p=next(p for p in analysis.analyze(e)['catalog'] if p['asin']=='B000001001')
    assert p['gtin'] is p['condition'] is p['pack_quantity'] is None
    assert not p['identity_complete']


def test_synthetic_record_rejected_by_original_importer(tmp_path):
    from app.m70_sources import ingest
    item=raw_item();item['is_synthetic']=True
    path=tmp_path/'pages.json';write(path,dict(pages=[dict(query_reference='q001',page_index=0,page_token=None,
        marketplace_id='ATVPDKIKX0DER',http_status=200,observed_at=product()['observed_at'],items=[item])]))
    source=tmp_path/'sources.json';write(source,dict(schema=1,sources=[dict(path=path.name,sha256=file_hash(path),
        adapter='amazon_catalog_pages',marketplace='ATVPDKIKX0DER',permission_reference='local:test')]))
    observations,coverage=ingest(source)
    assert not observations and coverage['sources'][0]['rejected']==1


def test_coverage_scenarios_arithmetic_and_determinism(completed):
    _,k=completed;e=load(k);a=analysis.analyze(e);b=analysis.analyze(deepcopy(e))
    assert a==b
    scenarios=a['scenarios']
    assert [r['additional_result_slots'] for r in scenarios]==[1330,1994,3988]
    assert a['summary']['remaining_asins']==997
    assert a['summary']['research_reviewable']==2


def test_formula_safe_excel_and_csv(completed):
    _,k=completed;report=analysis.analyze(load(k));report['catalog'][0]['title']='=HYPERLINK("https://invalid")'
    report['input_sha256']={};m73.export(report,k['output'])
    wb=load_workbook(k['output']/'M73_review.xlsx')
    assert wb['catalog'].cell(2,3).data_type=='s' and wb['catalog'].cell(2,3).value.startswith("'=")
    assert "'=HYPERLINK" in (k['output']/'M73_catalog.csv').read_text()


def test_cli_redacted_invalid_inputs(capsys):
    with pytest.raises(SystemExit):m73.main(['--secret','DO_NOT_LOG'])
    assert 'DO_NOT_LOG' not in capsys.readouterr().err


@pytest.mark.parametrize('change', ['stopped','count','checkpoint','uncertain'])
def test_registry_failure_rejected_before_catalog_import(completed,monkeypatch,change):
    _,k=completed;snapshot=inspect(k['private']/REGISTRY)
    if change=='stopped':snapshot['status']='STOPPED_NO_REPLAY'
    elif change=='count':snapshot['requests_consumed']=9
    elif change=='checkpoint':snapshot['checkpoint_sha256']='0'*64
    else:snapshot['uncertain_slots']=[10]
    monkeypatch.setattr(evidence,'inspect',lambda path:snapshot)
    def forbidden(*a,**kw):raise AssertionError('Import before checkpoint validation')
    monkeypatch.setattr(evidence,'ingest',forbidden)
    with pytest.raises(ValueError):m73.run(**k)
    assert not k['output'].exists()


def test_registry_chain_corruption_rejected(completed):
    import sqlite3
    _,k=completed;db=sqlite3.connect(k['private']/REGISTRY)
    db.execute('DROP TRIGGER immutable_m72_events_UPDATE')
    db.execute("UPDATE m72_events SET payload='{}' WHERE kind='RESPONSE' AND slot=2")
    db.commit();db.close()
    with pytest.raises(ValueError):m73.run(**k)


def test_conflict_count_mismatch_fails_closed(completed):
    _,k=completed;doc=json.loads(k['summary'].read_text());doc['identity_conflicts']=10;write(k['summary'],doc)
    with pytest.raises(ValueError):m73.run(**k)
    assert not k['output'].exists()


def test_old_conflicts_retained_and_research_blocked(completed):
    _,k=completed;e=load(k);p=e['baseline'][0]
    p['gtin']=None;p['observed_alternatives']['gtin']=['00075967300715','00330051887061']
    p['identity_conflicts']=['gtin'];p['field_status']['gtin']='CONFLICT'
    result=analysis.analyze(e)
    assert result['summary']['baseline_conflict_asins']==1
    assert next(r for r in result['conflicts'] if r['cohort']=='M70')['field']=='gtin'
    row=next(p for p in result['catalog'] if p['asin']=='B000001000')
    assert row['gtin'] is None and 'gtin' in row['identity_conflicts']


def test_no_execution_registry_or_credentials_during_consolidation(completed,monkeypatch):
    _,k=completed
    def forbidden(*a,**kw):raise AssertionError('Execution/credentials forbidden')
    monkeypatch.setattr(Registry,'__init__',forbidden)
    from app import m72_execution,m67_execution,m67_policy
    monkeypatch.setattr(m72_execution,'execute',forbidden)
    monkeypatch.setattr(m67_execution,'execute',forbidden)
    monkeypatch.setattr(m67_policy,'private_json',forbidden)
    assert m73.run(**k)['actual_requests']==0


def test_final_input_drift_never_publishes_completion_digest(completed,monkeypatch):
    _,k=completed;original=m73.export_csv;changed=False
    def change_input(*a,**kw):
        nonlocal changed
        original(*a,**kw)
        if not changed:
            changed=True;k['summary'].write_text(k['summary'].read_text()+' ')
    monkeypatch.setattr(m73,'export_csv',change_input)
    with pytest.raises(ValueError):m73.run(**k)
    assert not (k['output']/'M73_output_digests.json').exists()


def test_baseline_synthetic_flag_rejected_even_if_csv_unchanged(completed):
    _,k=completed;p=k['baseline_dir']/'M70_report.json';doc=json.loads(p.read_text())
    doc['catalog'][0]['is_synthetic']=True;write(p,doc);k['baseline_report_sha256']=file_hash(p)
    with pytest.raises(ValueError):m73.run(**k)


def test_missing_existing_lock_never_bootstraps_historical_state(completed):
    _,k=completed;lock=k['private']/'candidate-execution.lock';lock.unlink()
    with pytest.raises(FileNotFoundError):m73.run(**k)
    assert not lock.exists() and not k['output'].exists()
