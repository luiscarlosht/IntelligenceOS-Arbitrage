"""Synthetic local evidence only. Real reports never include these test products."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import socket
import subprocess
import sys
import zipfile

import pytest
from openpyxl import load_workbook

from test_m67 import cohort
from test_m69 import fixture as history_fixture, offline
from test_m72 import pilot
from test_m73 import completed, no_network
from app import m73, m74, m74_evidence as evidence, m74_plan as planning
from app.m70_sources import file_hash
from app.observations import canonical, fingerprint


def write(path,value):
    path.write_text(canonical(value)+'\n');path.chmod(0o600)


@pytest.fixture
def ready(completed,tmp_path,monkeypatch):
    c,k=completed
    # Generate only temporary fixture history, before invoking the M74 reader.
    summary=m73.run(**k)
    monkeypatch.setattr(evidence,'BASELINE',{name:summary[name] for name in evidence.BASELINE})
    args=dict(k);args['m73_dir']=args.pop('output')
    args['m73_digests_sha256']=file_hash(args['m73_dir']/'M73_output_digests.json')
    args['output']=tmp_path/'planning'
    return c,args


def build(k):
    args={key:value for key,value in k.items() if key!='output'}
    report,source,frozen,binding,hashes,_=evidence.verify(**args)
    return planning.build(report,source,frozen,binding,hashes,m74.implementation())


def test_verified_plan_deterministic_private_no_replay(ready,monkeypatch):
    c,k=ready
    protected=list(k['m73_dir'].iterdir())+list(k['baseline_dir'].iterdir())+list(k['private'].rglob('*'))
    def inventory():
        return {str(p):(p.stat().st_size,p.stat().st_mode,p.stat().st_mtime_ns,
            file_hash(p) if p.is_file() and not any(s in p.name for s in ('credential','authorization','account-context')) else None) for p in protected}
    before=inventory()
    def forbidden(*a,**kw):raise AssertionError('Historical execution/report generation forbidden')
    monkeypatch.setattr(m73,'export',forbidden);monkeypatch.setattr(m73,'run',forbidden)
    from app import m72_execution,m67_execution,m67_policy
    monkeypatch.setattr(m72_execution,'execute',forbidden);monkeypatch.setattr(m67_execution,'execute',forbidden)
    monkeypatch.setattr(m67_policy,'private_json',forbidden)
    result=m74.run(**k)
    assert result['actual_amazon_requests']==result['actual_authentication']==0
    assert not result['execution_authorized'] and result['candidate_queries']==51
    assert result['untested_m71_intents']==['personal_care_accessories']
    assert before==inventory()
    files={p.name:file_hash(p) for p in k['output'].iterdir()}
    second=dict(k,output=k['output'].parent/'planning-second');m74.run(**second)
    assert files=={p.name:file_hash(p) for p in second['output'].iterdir()}
    assert all(p.stat().st_mode&0o777==0o600 for p in k['output'].iterdir())
    assert k['output'].stat().st_mode&0o777==0o700
    report=json.loads((k['output']/'M74_planning_report.json').read_text())
    manifest=report['manifest'];queries=manifest['queries']
    assert len(queries)==51 and queries[0]['query_id']=='q010'
    assert [q['query_id'] for q in queries[1:11]]==[f'm74-n{n:03}' for n in range(1,11)]
    assert [q['query_id'] for q in queries[11:20]]==[f'q{n:03}' for n in range(11,20)]
    assert manifest['executed_query_ids']==[f'q{n:03}' for n in range(1,10)]
    assert not set(manifest['executed_query_ids'])&{q['query_id'] for q in queries}
    assert all(q['future_asin_overlap'] is None and q['marketplace_demand'] is None and q['uniqueness_probability'] is None for q in queries)
    assert len(manifest['permanently_excluded_asins'])==97 and len(manifest['previously_checked_asins'])==40
    assert all(q['frozen_definition'] is None for q in queries if q['origin']=='M74_NEW_HYPOTHESIS')
    wb=load_workbook(k['output']/'M74_discovery_plan.xlsx')
    assert wb['queries'].max_row==52 and wb['coverage'].max_row==10 and wb['exclusions'].max_row==98
    text=canonical(report)
    assert all(secret not in text for secret in ('SYNTHETICSECRET','SYNTHETICSELLER','SYNTHETICACCESS','PRIVATECURSOR',str(k['private'])))
    assert not list(k['private'].glob('m75*'))
    with pytest.raises(FileExistsError):m74.run(**k)


def test_observed_overlap_is_measured_not_assumed(ready):
    _,k=ready;r=build(k)
    # Fixture pages intentionally repeat three ASINs. Real pages do not.
    assert len(r['overlaps'])==36 and all(x['shared_asins']==3 for x in r['overlaps'])
    assert all(x['jaccard']==1 for x in r['overlaps'])
    assert all(x['within_page_duplicates']==0 for x in r['coverage'])
    assert all(x['baseline_overlap']==1 for x in r['coverage'])
    assert all(x['has_unfollowed_cursor'] for x in r['coverage'])


def test_budget_scenarios_exact_target_and_request_overhead():
    rows=planning.budgets(623,51)
    assert [r['result_slots'] for r in rows]==[831,1246,2492]
    assert [r['keyword_pages'] for r in rows]==[42,63,125]
    assert [r['single_operation_request_ceiling'] for r in rows]==[43,64,126]
    assert [r['twenty_page_authentication'] for r in rows]==[3,4,7]
    assert [r['twenty_page_total_request_ceiling'] for r in rows]==[45,67,132]
    assert [r['extra_query_definitions_required'] for r in rows]==[0,12,74]
    assert not any(r['m75_can_reach_remaining_target_at_zero_duplicates'] for r in rows)
    assert all(not r['execution_authorized'] and r['monetary_cost']=='UNKNOWN_NOT_ESTIMATED' for r in rows)
    assert all(r['keyword_pages']==r['single_operation_authentication']==0 for r in planning.budgets(0,51))
    with pytest.raises(ValueError):planning.budgets(-1,51)


@pytest.mark.parametrize('name',['M73_catalog.csv','M73_review.xlsx','M73_report.json'])
def test_m73_output_corruption_rejected_before_new_output(ready,name):
    _,k=ready;p=k['m73_dir']/name;p.write_bytes(p.read_bytes()+b' ')
    with pytest.raises(ValueError):m74.run(**k)
    assert not k['output'].exists()


@pytest.mark.parametrize('change',['missing','omitted','path_traversal','wrong_digest','symlink'])
def test_completion_manifest_strict_allowlist(ready,change,tmp_path):
    _,k=ready;p=k['m73_dir']/'M73_output_digests.json';doc=json.loads(p.read_text())
    if change=='missing':p.unlink()
    elif change=='omitted':doc.pop('M73_catalog.csv');write(p,doc)
    elif change=='path_traversal':doc['../outside.json']='a'*64;write(p,doc)
    elif change=='wrong_digest':doc['M73_catalog.csv']='a'*64;write(p,doc)
    else:
        target=tmp_path/'copy.csv';target.write_bytes((k['m73_dir']/'M73_catalog.csv').read_bytes())
        (k['m73_dir']/'M73_catalog.csv').unlink();(k['m73_dir']/'M73_catalog.csv').symlink_to(target)
    if change!='missing':k['m73_digests_sha256']=file_hash(p)
    with pytest.raises((ValueError,FileNotFoundError)):m74.run(**k)
    assert not k['output'].exists()


def test_resealed_report_cannot_forge_observations(ready):
    _,k=ready;p=k['m73_dir']/'M73_report.json';report=json.loads(p.read_text());report['catalog'][0]['brand']='FAKE'
    write(p,report);manifest=k['m73_dir']/'M73_output_digests.json';doc=json.loads(manifest.read_text())
    doc[p.name]=file_hash(p);write(manifest,doc);k['m73_digests_sha256']=file_hash(manifest)
    with pytest.raises(ValueError):m74.run(**k)


@pytest.mark.parametrize('key',['m73_digests_sha256','baseline_report_sha256','checkpoint','m67_sha256'])
def test_reviewed_digest_mismatch(ready,key):
    _,k=ready;k[key]='f'*64
    with pytest.raises(ValueError):m74.run(**k)


def test_actual_baseline_contract_not_inferred_from_fixture(ready,monkeypatch):
    _,k=ready;monkeypatch.setattr(evidence,'BASELINE',dict(real_asins=377))
    with pytest.raises(ValueError):m74.run(**k)


def test_new_vocabulary_cannot_reuse_executed_phrase(ready,monkeypatch):
    _,k=ready;monkeypatch.setattr(planning,'NEW_QUERIES',(('unexplored','plant support clips'),))
    with pytest.raises(ValueError):build(k)


@pytest.mark.parametrize('change',['scope','budget','execute','replay','identifier'])
def test_contract_and_manifest_fail_closed(ready,change):
    _,k=ready;r=build(k)
    if change=='scope':r['contract']['keyword_requests'][0]['host']='evil.example'
    elif change=='budget':r['contract']['budget']['total']=22
    elif change=='execute':r['manifest']['execution_authorized']=True
    elif change=='replay':r['manifest']['queries'][0]['query_id']='q001'
    else:r['contract']['keyword_requests'][0]['parameters']['identifiers']='B000001000'
    with pytest.raises(ValueError):m74.validate(r)


def test_new_m75_contract_is_proposal_only(ready):
    _,k=ready;r=build(k);contract=r['contract']
    assert contract['operation_id']=='M75-US-CATALOG-EXPLORE20-ONCE'
    assert contract['budget']==planning.BUDGET and contract['budget']['total']==21
    assert len(contract['keyword_requests'])==20
    assert contract['authentication']['maximum_requests']==1
    assert all(set(q['parameters'])=={'marketplaceIds','includedData','pageSize','keywords'} for q in contract['keyword_requests'])
    assert contract['authorization']['maximum_lifetime_seconds']==600 and contract['authorization']['required']
    assert contract['authorization']['separate_from_all_historical_operations']
    assert contract['account_binding_sha256'] and contract['hard_operation_timeout_seconds']==120
    assert not contract['execution_authorized'] and not contract['live_enabled']
    assert not (k['private']/contract['permanent_registry']).exists()
    m74.validate(r)


def test_protected_paths_and_symlink_outputs(ready,tmp_path):
    _,k=ready;k['output']=k['m73_dir']/'nested'
    with pytest.raises(ValueError):m74.run(**k)
    alias=tmp_path/'alias';alias.symlink_to(k['baseline_dir'],target_is_directory=True);k['output']=alias/'nested'
    with pytest.raises(ValueError):m74.run(**k)


def test_formula_safe_and_time_normalized_workbook():
    tables={'review':(['text'],[dict(text='=HYPERLINK("invalid")')])}
    a=m74.workbook_bytes(tables);b=m74.workbook_bytes(tables)
    assert a==b
    wb=load_workbook(BytesIO(a));assert wb['review']['A2'].data_type=='s'
    assert wb['review']['A2'].value.startswith("'=")
    with zipfile.ZipFile(BytesIO(a)) as archive:
        assert all(i.date_time==(2000,1,1,0,0,0) for i in archive.infolist())
        assert b'2000-01-01T00:00:00Z' in archive.read('docProps/core.xml')


def test_final_drift_never_publishes_completion(ready,monkeypatch):
    _,k=ready;original=m74.export_csv;changed=False
    def drift(*a,**kw):
        nonlocal changed
        original(*a,**kw)
        if not changed:
            changed=True;p=k['m73_dir']/'M73_catalog.csv';p.write_bytes(p.read_bytes()+b' ')
    monkeypatch.setattr(m74,'export_csv',drift)
    with pytest.raises(ValueError):m74.run(**k)
    assert not (k['output']/'M74_evidence_digests.json').exists()


def test_import_and_cli_offer_no_live_execution(capsys):
    script="import sys;sys.modules['app.amazon_pilot']=None;sys.modules['app.m72_execution']=None;sys.modules['app.m67_execution']=None;from app.m74 import main;main(['--help'])"
    result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True)
    assert result.returncode==0 and '--execute-live' not in result.stdout
    for action in ('execute','authorize','resume'):
        with pytest.raises(SystemExit):m74.main([action,'SECRET_DO_NOT_LOG'])
    assert 'SECRET_DO_NOT_LOG' not in capsys.readouterr().err
