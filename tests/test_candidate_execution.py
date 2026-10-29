"""All HTTP and credential inputs below are injected synthetic fixtures."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest

from app import amazon_candidates as candidates
from app import amazon_pilot as pilot
from app.candidate_execution import execute_details, prepare_details
from app.observations import canonical, fingerprint, normalized
from app.sheets_candidate_plan import MARKETPLACE, plan
from app.sheets_intake import FIELDS, IntakeStore, process, product
from app.source_keywords import search_keywords
from test_amazon_candidates import catalog, CREDS, source as csv_source, search as search_response, ASIN


@pytest.fixture(autouse=True)
def forbid_real_io(monkeypatch):
    monkeypatch.setattr(pilot,'load_credentials',lambda *_: pytest.fail('No real credential access'))
    monkeypatch.setattr(pilot,'request_json',lambda *_: pytest.fail('No live HTTP'))


def stored_case(tmp_path, count=5, reused=0, shared_asin=False):
    tmp_path.mkdir(exist_ok=True)
    template=json.loads((Path(__file__).parent/'fixtures/sheets_browser_five_representative.json').read_text())
    original=deepcopy(template['Walmart_Intake'][1:])
    cells=[]
    for i in range(count):
        row=dict(zip(FIELDS,original[i%5]))
        if i>=5:
            row['walmart_item_id']=str(20000000+i)
            row['product_url']='https://www.walmart.com/ip/widget/'+row['walmart_item_id']
        row['record_id']=row['batch_id']+':'+row['walmart_item_id']
        raw=json.loads(row['raw_record_json'])
        raw.update(walmart_item_id=row['walmart_item_id'],product_url=row['product_url'])
        row['raw_record_json']=json.dumps(raw)
        cells.append([row[k] for k in FIELDS])
    template['Walmart_Intake']=[FIELDS,*cells]
    template['Walmart_Batches'][1][1:3]=[str(count),str(count)]
    class Client:
        def read(self, tab, columns): return deepcopy(template[tab])
        def ack(self, row, stamp): pass
    database=tmp_path/'intake.sqlite3'
    assert process(Client(),IntakeStore(database))['accepted']==1
    rows=sorted((dict(zip(FIELDS,c)) for c in cells),key=lambda r:r['record_id'])
    report=dict(is_mock=False,status='succeeded',rows=[],attempts=[],manifest=dict(
        marketplace_id=MARKETPLACE,requests=[]))
    selections={}
    for ordinal,row in enumerate(rows,1):
        p=product(row); asin='B0'+str(1 if shared_asin else ordinal).zfill(8)
        query=search_keywords(p)
        search=dict(selected_asin=asin,keywords=query,observed_at='2026-01-01T00:03:00Z',
                    provenance='Synthetic saved US catalog page',complete=False,more_results=True,
                    candidates=[dict(asin=asin,title='Synthetic candidate',rank=1)])
        detail=normalized(candidates.detail_evidence(catalog(asin),asin,is_mock=False,secrets=())) if ordinal<=reused else None
        report['rows'].append(dict(ordinal=ordinal,source=normalized(p),search=search,detail=detail))
        report['manifest']['requests'].append(dict(ordinal=ordinal,source_fingerprint=fingerprint(p),
            search=dict(params=dict(marketplaceIds=MARKETPLACE,keywords=query)),
            detail=dict(params=dict(marketplaceIds=MARKETPLACE))))
        report['attempts'].append(dict(kind='search',ordinal=ordinal,status='response_received'))
        if detail: report['attempts'].append(dict(kind='detail',ordinal=ordinal,status='response_received'))
        selections[row['walmart_item_id']]=dict(asin=asin,reason='Explicit synthetic review',previous_selection_disposition='retained')
    saved=tmp_path/'saved-searches.json';saved.write_text(json.dumps(report))
    batch=rows[0]['batch_id']
    preview=plan(database,batch,[saved],selections)
    reviewed=tmp_path/'reviewed-plan.json';reviewed.write_text(canonical(preview)+'\n')
    manifest=prepare_details(database,reviewed)
    manifest_path=tmp_path/'execution-manifest.json';manifest_path.write_text(canonical(manifest)+'\n')
    digest=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    return database,reviewed,saved,manifest_path,digest,manifest


def run_case(tmp_path, *, count=5, failure_at=None, interrupt=False, reused=0, shared_asin=False):
    case=stored_case(tmp_path,count,reused,shared_asin)
    calls=[]
    def transport(request):
        calls.append(request)
        if len(calls)==failure_at:
            if interrupt: raise KeyboardInterrupt()
            raise RuntimeError('synthetic-secret')
        if len(calls)==1: return dict(access_token='synthetic-access',token_type='bearer')
        return catalog(urlsplit(request.full_url).path.rsplit('/',1)[-1])
    database,reviewed,saved,path,digest,manifest=case
    before=database.read_bytes()
    report=execute_details(path,digest,manifest['limits']['total'],tmp_path/'private',
        transport=transport,credential_loader=lambda _: CREDS,sleep=lambda _:None)
    assert database.read_bytes()==before
    return case,report,calls


@pytest.mark.parametrize('count',[5,10,20])
def test_variable_stored_batch_all_outcomes_and_request_limits(tmp_path,count):
    case,report,calls=run_case(tmp_path,count=count)
    database,reviewed,saved,path,digest,manifest=case
    assert report['status']=='succeeded' and len(calls)==count+1
    assert manifest['limits']==dict(authentication=1,search=0,detail=count,total=count+1)
    assert len(report['rows'])==count and all(not r['exact'] for r in report['rows'])
    for request in calls[1:]:
        assert request.get_method()=='GET'
        assert urlsplit(request.full_url).path.startswith('/catalog/2022-04-01/items/')
        assert parse_qs(urlsplit(request.full_url).query)==dict(marketplaceIds=[MARKETPLACE],
            includedData=['summaries,identifiers,relationships,attributes'])
    with sqlite3.connect(tmp_path/'private'/'candidate-executions.sqlite3') as db:
        checkpoint=json.loads(db.execute('SELECT checkpoint_json FROM candidate_executions').fetchone()[0])
        assert len(checkpoint['rows'])==count
        assert db.execute('SELECT count(*) FROM candidate_operations').fetchone()[0]==count+1
        assert checkpoint['reviewed_plan_sha256']==hashlib.sha256(reviewed.read_bytes()).hexdigest()
    evidence_db=next(p for p in (tmp_path/'private').glob('candidate-details-*.sqlite3'))
    with sqlite3.connect(evidence_db) as db:
        assert db.execute('SELECT count(*) FROM pilot_run_items').fetchone()[0]==count
        assert db.execute('SELECT candidates FROM runs').fetchone()[0]==count
    assert report['batch_content_hash']==manifest['batch_content_hash']
    for row,original in zip(report['rows'],manifest['rows']):
        assert row['original_intake_row']==original['original_intake_row']
        assert row['original_search']==original['original_search']
        assert row['source']['retrieved_at']==original['source']['retrieved_at']
    assert all(secret not in canonical(report) for secret in (*CREDS.values(),'synthetic-access'))
    checkpoints=next((tmp_path/'private').glob('*.checkpoints.jsonl')).read_text().splitlines()
    assert len(checkpoints)>count and len(json.loads(checkpoints[0])['rows'])==count


@pytest.mark.parametrize('failure_at',[1,2,4,6])
def test_failure_preserves_all_rows_and_replay_consumed(tmp_path,failure_at):
    case,report,calls=run_case(tmp_path,failure_at=failure_at)
    assert report['status']=='failed_no_retry' and len(calls)==failure_at
    assert len(report['rows'])==5
    path,digest,manifest=case[3:]
    with pytest.raises(sqlite3.IntegrityError):
        execute_details(path,digest,6,tmp_path/'private',transport=lambda _:pytest.fail('Replay HTTP'),
                        credential_loader=lambda _:pytest.fail('Replay credentials'))


def test_interruption_claims_all_remaining_details(tmp_path):
    case,report,calls=run_case(tmp_path,failure_at=3,interrupt=True)
    assert report['status']=='failed_no_retry' and len(calls)==3
    assert sum(r['status']=='not_attempted' for r in report['rows'])==3
    # Changed output path and evaluated timestamp cannot bypass stable run/operation claims.
    reviewed=json.loads(case[1].read_text());reviewed['evaluated_at']='2026-10-29T00:00:00+00:00'
    # A new reviewed timestamp alone must also rebind derived search ages explicitly.
    with pytest.raises((ValueError,sqlite3.IntegrityError)):
        copied=tmp_path/'copy.json';copied.write_bytes(case[3].read_bytes())
        execute_details(copied,case[4],6,tmp_path/'private',credential_loader=lambda _:pytest.fail('Replay'))


@pytest.mark.parametrize('change',['hash','source','saved','preview','limit','endpoint'])
def test_tampering_rejected_before_private_access(tmp_path,monkeypatch,change):
    db,reviewed,saved,path,digest,manifest=stored_case(tmp_path)
    if change=='hash': digest='0'*64
    elif change=='source':
        with sqlite3.connect(db) as connection: connection.execute("UPDATE source_observations SET observed_at='2026-01-01T00:01:00Z'")
    elif change=='saved': saved.write_text(saved.read_text()+'\n')
    elif change=='preview': reviewed.write_text(reviewed.read_text()+'\n')
    elif change=='endpoint':
        manifest['requests'][0]['path']='/products/pricing/v0/items/forbidden/offers'
        path.write_text(canonical(manifest));digest=hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(pilot,'private_directory',lambda *_:pytest.fail('Private access before validation'))
    with pytest.raises(ValueError): execute_details(path,digest,5 if change=='limit' else 6,tmp_path/'private')


def test_partial_and_complete_saved_detail_reuse(tmp_path):
    _,report,calls=run_case(tmp_path/'partial',reused=2)
    assert len(calls)==4
    assert sum(r.get('detail_origin')=='reused_saved_catalog' for r in report['rows'])==2
    db,reviewed,saved,path,digest,manifest=stored_case(tmp_path/'all',reused=5)
    report=execute_details(path,digest,0,tmp_path/'all'/'private',
        credential_loader=lambda _:pytest.fail('All details already completed'),
        transport=lambda _:pytest.fail('All details already completed'))
    assert report['status']=='succeeded' and report['attempts']==[]
    assert [r['detail']['observed_at'] for r in report['rows']]==[
        r['catalog_detail_reuse'][0]['evidence']['observed_at'] for r in manifest['rows']]


def test_deduplicated_asin_fetch_links_all_source_rows(tmp_path):
    case,report,calls=run_case(tmp_path,shared_asin=True)
    assert len(calls)==2 and case[-1]['limits']['detail']==1
    assert all(r['detail'] for r in report['rows'])


def test_presentation_failure_does_not_enable_repeat(tmp_path,monkeypatch):
    monkeypatch.setattr(candidates,'persist',lambda *_:(_ for _ in ()).throw(OSError('private-message')))
    with pytest.raises(OSError): run_case(tmp_path)
    with sqlite3.connect(tmp_path/'private'/'candidate-executions.sqlite3') as db:
        result=json.loads(db.execute('SELECT checkpoint_json FROM candidate_executions').fetchone()[0])
        assert len(result['rows'])==5 and all(r['detail'] for r in result['rows'])
        assert result['presentation_status'].startswith('failed')
    path=tmp_path/'execution-manifest.json';digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(sqlite3.IntegrityError): execute_details(path,digest,6,tmp_path/'private')


@pytest.mark.parametrize('count',[5,10,20])
def test_existing_csv_candidate_mode_variable_sizes(tmp_path,count):
    source=csv_source(tmp_path)
    lines=source.read_text().splitlines()
    source.write_text('\n'.join([lines[0]]+[lines[1+i%10] for i in range(count)])+'\n')
    manifest,products=candidates.source_plan(source)
    assert len(products)==count and manifest['limits']['total']==1+2*count
    calls=[]
    def transport(request):
        calls.append(request)
        if len(calls)==1: return dict(access_token='synthetic-access',token_type='bearer')
        return catalog() if urlsplit(request.full_url).path.endswith('/'+ASIN) else search_response()
    report=candidates.execute(source,manifest,tmp_path/'private',transport=transport,
        credential_loader=lambda _:CREDS,is_mock=True,sleep=lambda _:None)
    assert len(report['rows'])==count and len(calls)==1+2*count


def test_reserved_before_credentials_and_http(tmp_path):
    db,reviewed,saved,path,digest,manifest=stored_case(tmp_path)
    private=tmp_path/'private';calls=[]
    def loader(_):
        with sqlite3.connect(private/'candidate-executions.sqlite3') as ledger:
            assert ledger.execute("SELECT count(*) FROM candidate_operations WHERE state='claimed_not_attempted'").fetchone()[0]==5
            assert len(json.loads(ledger.execute('SELECT checkpoint_json FROM candidate_executions').fetchone()[0])['rows'])==5
        return CREDS
    def transport(req):
        calls.append(req)
        with sqlite3.connect(private/'candidate-executions.sqlite3') as ledger:
            assert ledger.execute("SELECT count(*) FROM candidate_operations WHERE state='reserved'").fetchone()[0]==1
        return dict(access_token='synthetic-access',token_type='bearer') if len(calls)==1 else catalog(urlsplit(req.full_url).path.rsplit('/',1)[-1])
    result=execute_details(path,digest,6,private,transport=transport,credential_loader=loader,sleep=lambda _:None)
    assert result['status']=='succeeded' and len(calls)==6
    with pytest.raises(sqlite3.IntegrityError):
        execute_details(path,digest,6,private,credential_loader=lambda _:pytest.fail('Completed replay'))


def test_hard_interruption_leaves_authoritative_sql_checkpoint(tmp_path):
    db,reviewed,saved,path,digest,manifest=stored_case(tmp_path)
    def stop(_): raise SystemExit(99)
    with pytest.raises(SystemExit):
        execute_details(path,digest,6,tmp_path/'private',transport=stop,credential_loader=lambda _:CREDS)
    with sqlite3.connect(tmp_path/'private'/'candidate-executions.sqlite3') as ledger:
        report=json.loads(ledger.execute('SELECT checkpoint_json FROM candidate_executions').fetchone()[0])
        assert len(report['rows'])==5 and report['attempts'][0]['status']=='reserved'
    with pytest.raises(sqlite3.IntegrityError):
        execute_details(path,digest,6,tmp_path/'private',credential_loader=lambda _:pytest.fail('Crash replay'))


def test_changed_run_cannot_repeat_overlapping_operations(tmp_path):
    case,result,calls=run_case(tmp_path)
    db,reviewed,saved,path,digest,manifest=case
    original=json.loads(reviewed.read_text())
    selections={r['walmart_item_id']:dict(asin=r['candidate_asin'],reason=r['selection_reason'],
        previous_selection_disposition=r['previous_selection_disposition']) for r in original['rows']}
    report=json.loads(saved.read_text());target=original['rows'][0]['walmart_item_id']
    report['rows'][0]['search']['candidates'].append(dict(asin='B099999999',title='Another retained lead',rank=2))
    saved.write_text(json.dumps(report));selections[target]['asin']='B099999999'
    reviewed.write_text(canonical(plan(db,manifest['batch_id'],[saved],selections)))
    changed=prepare_details(db,reviewed)
    assert changed['run_key']!=manifest['run_key']
    path.write_text(canonical(changed));digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(sqlite3.IntegrityError):
        execute_details(path,digest,6,tmp_path/'private',credential_loader=lambda _:pytest.fail('Overlapping calls'))


def test_second_authentication_attempt_stops_before_second_http(tmp_path,monkeypatch):
    from urllib.request import Request
    case=stored_case(tmp_path);calls=[]
    def twice(credentials, call):
        call(Request('https://api.amazon.com/auth/o2/token'))
        call(Request('https://api.amazon.com/auth/o2/token'))
        pytest.fail('Second authentication must not be possible')
    monkeypatch.setattr(pilot,'exchange_token',twice)
    result=execute_details(case[3],case[4],6,tmp_path/'private',
        credential_loader=lambda _:CREDS,transport=lambda r:(calls.append(r) or {}),sleep=lambda _:None)
    assert result['status']=='failed_no_retry' and len(calls)==1
    assert len(result['attempts'])==1


def test_checkpoint_failure_prevents_http_and_replay(tmp_path,monkeypatch):
    from app.candidate_execution import ExecutionJournal
    case=stored_case(tmp_path)
    original=ExecutionJournal.checkpoint
    def broken(self):
        if self.report['attempts']: raise OSError('Synthetic checkpoint failure')
        return original(self)
    monkeypatch.setattr(ExecutionJournal,'checkpoint',broken)
    with pytest.raises(OSError):
        execute_details(case[3],case[4],6,tmp_path/'private',credential_loader=lambda _:CREDS,
                        transport=lambda _:pytest.fail('HTTP before checkpoint'))
    with sqlite3.connect(tmp_path/'private'/'candidate-executions.sqlite3') as db:
        saved=json.loads(db.execute('SELECT checkpoint_json FROM candidate_executions').fetchone()[0])
        assert len(saved['rows'])==5 and saved['attempts'][0]['status']=='reserved'
    monkeypatch.setattr(ExecutionJournal,'checkpoint',original)
    with pytest.raises(sqlite3.IntegrityError):
        execute_details(case[3],case[4],6,tmp_path/'private',credential_loader=lambda _:pytest.fail('Checkpoint replay'))


@pytest.mark.parametrize('count',[0,1001])
def test_csv_batch_size_bounds(tmp_path,monkeypatch,count):
    from types import SimpleNamespace
    source=csv_source(tmp_path)
    _,products=candidates.source_plan(source)
    monkeypatch.setattr(candidates,'CsvConnector',lambda *_:SimpleNamespace(products=lambda:iter([products[0]]*count)))
    with pytest.raises(ValueError,match='1 to 1000'): candidates.source_plan(source)


def test_parser_failure_keeps_every_outcome_and_stops(tmp_path):
    case=stored_case(tmp_path);calls=[]
    def transport(request):
        calls.append(request)
        return dict(access_token='synthetic-access',token_type='bearer') if len(calls)==1 else catalog('B099999999')
    report=execute_details(case[3],case[4],6,tmp_path/'private',transport=transport,
        credential_loader=lambda _:CREDS,sleep=lambda _:None)
    assert len(calls)==2 and report['status']=='failed_no_retry' and len(report['rows'])==5
    assert report['rows'][0]['status']=='failed'
    assert all(r['status']=='not_attempted' for r in report['rows'][1:])


def test_cli_preparation_and_live_opt_in(tmp_path,monkeypatch,capsys):
    from app.candidate_execution import main
    case=stored_case(tmp_path)
    output=tmp_path/'prepared.json'
    monkeypatch.setattr('sys.argv',['candidates','prepare-details','--database',str(case[0]),
        '--reviewed-plan',str(case[1]),'--manifest',str(output)])
    assert main()==0
    result=json.loads(capsys.readouterr().out)
    assert result['limits']['total']==6 and result['live_requests']==0
    assert result['manifest_sha256']==hashlib.sha256(output.read_bytes()).hexdigest()
    monkeypatch.setattr('sys.argv',['candidates','run-details','--manifest',str(output)])
    with pytest.raises(SystemExit): main()


def test_other_acknowledged_batches_do_not_invalidate_selected_batch(tmp_path):
    case=stored_case(tmp_path)
    db,reviewed,saved,path,digest,manifest=case
    with sqlite3.connect(db) as connection:
        originals=[json.loads(x[0]) for x in connection.execute('SELECT original_json FROM sheets_records')]
    rows=[]
    for row in originals:
        row['batch_id']='other_batch';row['record_id']='other:'+row['walmart_item_id']
        rows.append(row)
    batch=dict(batch_id='other_batch',expected_record_count='5',actual_record_count='5',status='COMPLETE',
               completed_at_utc='2026-01-01T00:02:00Z',consumer_status='',consumer_acknowledged_at_utc='')
    store=IntakeStore(db)
    assert store.store(batch,rows,[product(r) for r in rows])
    with store.connect() as connection: connection.execute("UPDATE sheets_batches SET acknowledged_at='2026-01-01T00:03:00Z' WHERE batch_id='other_batch'")
    assert prepare_details(db,reviewed)==manifest
