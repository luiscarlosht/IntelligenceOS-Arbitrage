from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import socket
import pytest
from openpyxl import load_workbook
from app.decision_demo import demonstrate_decisions
from app.decision_pipeline import run
from app.decision_history import database,trend
from app.evidence_io import digest,json_write,offline
from app.opportunity_fixtures import NOW,case
from app.decision_workbook import workbook


@pytest.fixture
def completed(tmp_path):
    root=tmp_path/'demo';report=demonstrate_decisions(root)
    return root,report


def test_integrated_demo_and_idempotent_history(completed):
    root,report=completed;manifest=root/'inputs/manifest.json';state=root/'own-state/observations.sqlite3'
    before=state.read_bytes()
    second=run(manifest,digest(manifest),root/'second-report',state,NOW)
    assert len(report['history'])==len(second['history'])==20
    assert state.read_bytes()==before
    assert sum(r['net_profit']=='UNKNOWN' for r in report['opportunities'])==19
    assert report['executive']['economic_review_proposals']==1
    assert report['executive']['universe_asins']==1397 and len(report['historical_unobserved'])==1377
    assert all(r['current_price']=='UNKNOWN' for r in report['historical_unobserved'])
    assert report['weekly'][0]['realized_sales']=='UNKNOWN'
    assert report['synthetic'] and not report['purchase_authorized']
    wb=load_workbook(root/'report/decision-report.xlsx')
    assert {'Executive','Research_Top20','Demand_Competition','Comparable_Categories','Profitability','Weekly','Data_Quality','Observation_History','Provenance','Inventory_Proposals'}<=set(wb.sheetnames)
    assert (root/'report/decision-report.xlsx').read_bytes()==(root/'second-report/decision-report.xlsx').read_bytes()


def test_history_immutable_and_schema_tamper(completed):
    root,report=completed;path=root/'own-state/observations.sqlite3'
    with database(path) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE observations SET digest=?',('f'*64,))
    with sqlite3.connect(path) as db:db.execute('DROP TRIGGER no_update')
    with pytest.raises(ValueError,match='schema'):
        with database(path):pass


def test_source_pins_publication_and_credential_paths(completed):
    root,report=completed;manifest=root/'inputs/manifest.json';state=root/'own-state/observations.sqlite3'
    with pytest.raises(ValueError):run(manifest,'0'*64,root/'bad',state,NOW)
    assert not (root/'bad').exists()
    with pytest.raises(ValueError):run(manifest,digest(manifest),root/'inputs/overwrite',state,NOW)
    assert not (root/'inputs/overwrite').exists()
    with pytest.raises(ValueError):run(root/'credentials.json','0'*64,root/'bad',state,NOW)


def test_stale_amazon_is_not_current(completed):
    root,report=completed;manifest=root/'inputs/manifest.json'
    stale=run(manifest,digest(manifest),root/'stale',root/'own-state/observations.sqlite3',NOW+timedelta(days=7))
    assert stale['executive']['current_amazon_review_ready']==0
    assert len(stale['history'])==20
    assert all(not r['prices'] and not r['ranks'] for r in stale['amazon']['rows'])
    assert all(r['estimated_monthly_unit_sales']=='UNKNOWN' for r in stale['amazon']['rows'])


def test_trend_requires_comparable_multi_day_samples():
    a,_,_,_=case();history=[]
    for i in range(8):
        history.append(dict(source_kind='SYNTHETIC',**{k:a[k] for k in ('asin','marketplace','condition','account_binding_sha256')},
            provenance={'22':{'observed_at':(NOW-timedelta(days=i)).isoformat()}},
            prices=[dict(basis='lowest_observed',fulfillment='Amazon',landed_usd=str(30+i))]))
    assert trend(history[:1],a,'SYNTHETIC',NOW)['price_stability']=='UNKNOWN'
    assert trend(history,a,'AUTHORIZED_LIVE',NOW)['price_stability']=='UNKNOWN'
    assert trend(history,a,'SYNTHETIC',NOW)['price_stability']=='OBSERVED_RANGE_ONLY'
    history[-1]['prices'][0]['fulfillment']='Merchant'
    assert trend(history,a,'SYNTHETIC',NOW)['price_stability']=='UNKNOWN'


def test_workbook_formulas_are_only_generated_from_validated_values(completed,tmp_path):
    root,report=completed
    from app.opportunity_engine import evaluate
    row=evaluate(*case(),NOW,synthetic=True);row['asin']='=HYPERLINK("https://example.invalid")'
    report['opportunities']=[row];path=tmp_path/'formula.xlsx';workbook(report,path)
    ws=load_workbook(path,data_only=False)['Profitability'];headers=[c.value for c in ws[1]]
    assert ws.cell(2,1).data_type=='s' and ws.cell(2,1).value.startswith("'")
    assert ws.cell(2,headers.index('net_profit')+1).data_type=='f'
    assert ws.cell(2,headers.index('referral_fee')+1).value==4.5


def test_supplemental_identity_cannot_override_known_values():
    from app.opportunity_engine import evaluate
    a,q,f,r=case();a['identity']['size']='UNKNOWN';a['identity']['variation']='UNKNOWN'
    assert evaluate(a,q,f,r,NOW,synthetic=True)['status']=='REVIEW_PROPOSAL_ONLY'
    r['verified_amazon_identity']['model']='different'
    assert evaluate(a,q,f,r,NOW,synthetic=True)['status']=='EXCLUDED'


def test_guard_rejects_rename_escape_and_links(tmp_path):
    import os
    stage=tmp_path/'stage';stage.mkdir();source=stage/'a';source.write_text('safe')
    outside=tmp_path/'original';outside.write_text('preserve')
    with offline(writes=[stage]):
        with pytest.raises(PermissionError):os.rename(source,outside)
        with pytest.raises(PermissionError):os.symlink(outside,stage/'link')
        with pytest.raises(PermissionError):os.link(outside,stage/'hardlink')
    assert outside.read_text()=='preserve'


def test_original_artifact_mutation_fails_closed(completed):
    root,report=completed;manifest=root/'inputs/manifest.json'
    (root/'inputs/synthetic-original-0.txt').write_text('tampered')
    with pytest.raises(ValueError,match='artifact digest'):
        run(manifest,digest(manifest),root/'tampered-report',root/'own-state/observations.sqlite3',NOW)
    assert not (root/'tampered-report').exists()
