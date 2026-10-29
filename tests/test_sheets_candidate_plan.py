import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from app.observations import canonical, fingerprint, normalized
from app.sheets_candidate_plan import audit_database, plan, MARKETPLACE
from app.sheets_intake import FIELDS, IntakeStore, process, product
from app.source_keywords import search_keywords


@pytest.fixture
def prepared(tmp_path):
    data = json.loads((Path(__file__).parent/'fixtures/sheets_browser_five_representative.json').read_text())
    class Client:
        def read(self, tab, columns):
            return copy.deepcopy(data[tab])
        def ack(self, row, stamp):
            pass  # Temporary fixture database only, no transport.
    database = tmp_path/'fixture.sqlite3'
    assert process(Client(), IntakeStore(database))['accepted'] == 1
    rows = [dict(zip(FIELDS, row)) for row in data['Walmart_Intake'][1:]]
    batch = rows[0]['batch_id']
    report = dict(is_mock=False, status='succeeded', rows=[], attempts=[],
                  manifest=dict(marketplace_id=MARKETPLACE, requests=[]))
    selections = {}
    for ordinal, row in enumerate(rows, 1):
        p = product(row); asin = 'B0'+row['walmart_item_id']
        search = dict(selected_asin=asin, keywords=search_keywords(p), observed_at='2026-01-01T00:03:00Z',
                      complete=False, more_results=True, candidates=[dict(asin=asin,title='Candidate',rank=1)])
        report['rows'].append(dict(ordinal=ordinal, source=normalized(p), search=search, detail=None))
        report['manifest']['requests'].append(dict(ordinal=ordinal,source_fingerprint=fingerprint(p),
            search=dict(params=dict(marketplaceIds=MARKETPLACE, keywords=search['keywords'])),
            detail=dict(params=dict(marketplaceIds=MARKETPLACE))))
        report['attempts'].append(dict(kind='search',ordinal=ordinal,status='response_received'))
        selections[row['walmart_item_id']] = dict(asin=asin,reason='Reviewed offline lead only',previous_selection_disposition='none')
    saved = tmp_path/'saved-candidates.json'
    saved.write_text(json.dumps(report))
    return database, batch, saved, report, selections


def test_read_only_database_audit_and_five_record_budget(prepared):
    database, batch, saved, report, selections = prepared
    before = hashlib.sha256(database.read_bytes()).hexdigest(), database.stat().st_mtime_ns
    result = plan(database,batch,[saved],selections)
    assert result['audit']['sheets_batches'] == 1
    assert result['audit']['unique_record_ids'] == 5
    assert result['audit']['observation_timestamps_verified']
    assert result['reused_searches'] == 5
    assert result['budget']['maximum_requests'] == 6
    assert result['budget']['search'] == 0
    assert len(result['requests']) == 5
    assert not result['execution_supported'] and result['live_requests'] == 0
    assert all(row['selected_variant'] == '' for row in result['rows'])
    assert before == (hashlib.sha256(database.read_bytes()).hexdigest(), database.stat().st_mtime_ns)


def test_missing_database_never_created(tmp_path):
    path = tmp_path/'missing.sqlite3'
    with pytest.raises(sqlite3.OperationalError):
        audit_database(path,'batch')
    assert not path.exists()


@pytest.mark.parametrize('damage', ['raw','timestamp','record_count','batch_hash'])
def test_database_corruption_fails_closed(prepared, damage):
    database,batch,*_ = prepared
    with sqlite3.connect(database) as db:
        if damage == 'raw':
            rid, original = db.execute('SELECT record_id,original_json FROM sheets_records LIMIT 1').fetchone()
            row = json.loads(original); row['title'] = 'Changed'
            db.execute('UPDATE sheets_records SET original_json=? WHERE record_id=?',(json.dumps(row),rid))
        elif damage == 'timestamp':
            db.execute("UPDATE source_observations SET observed_at='2026-01-01T00:01:00Z'")
        elif damage == 'record_count':
            db.execute('DELETE FROM sheets_records WHERE record_id=(SELECT min(record_id) FROM sheets_records)')
        else:
            db.execute("UPDATE sheets_batches SET content_hash='wrong'")
    with pytest.raises(ValueError): audit_database(database,batch)


@pytest.mark.parametrize('damage',['mock','marketplace','url','brand','fingerprint','attempt','unreturned_asin'])
def test_incompatible_saved_evidence_never_triggers_search(prepared, damage):
    database,batch,saved,report,selections = prepared
    first = report['rows'][0]
    if damage == 'mock': report['is_mock'] = True
    elif damage == 'marketplace': report['manifest']['marketplace_id'] = 'different'
    elif damage == 'url': first['source']['url'] += '?different'
    elif damage == 'brand': first['source']['source_context']['brand'] = 'Different'
    elif damage == 'fingerprint': report['manifest']['requests'][0]['source_fingerprint'] = 'wrong'
    elif damage == 'attempt': report['attempts'][0]['status'] = 'reserved'
    else: selections[next(iter(selections))]['asin'] = 'B000000000'
    saved.write_text(json.dumps(report))
    with pytest.raises(ValueError): plan(database,batch,[saved],selections)


def test_complete_detail_reused_and_uncertain_attempt_not_repeated(prepared):
    database,batch,saved,report,selections = prepared
    first = report['rows'][0]; asin = first['search']['selected_asin']
    report['attempts'].append(dict(kind='detail',ordinal=1,status='response_received'))
    first['detail'] = dict(is_mock=False,observed_at='2026-01-01T00:04:00Z',
        value=dict(catalog=dict(asin=asin,is_mock=False)),provenance='Saved US detail')
    saved.write_text(json.dumps(report))
    result = plan(database,batch,[saved],selections)
    assert result['budget']['catalog_detail'] == 4
    assert all(r['asin'] != asin for r in result['requests'])
    report['attempts'][-1]['status'] = 'reserved'; first['detail'] = None
    saved.write_text(json.dumps(report))
    with pytest.raises(ValueError,match='already attempted'):
        plan(database,batch,[saved],selections)


def test_historical_query_reuse_not_claimed_as_current_coverage(prepared):
    database,batch,saved,report,selections = prepared
    report['rows'][0]['search']['keywords'] = 'Old differently worded query'
    report['manifest']['requests'][0]['search']['params']['keywords'] = 'Old differently worded query'
    saved.write_text(json.dumps(report))
    result = plan(database,batch,[saved],selections,evaluated_at=datetime(2026,2,1,tzinfo=timezone.utc))
    changed = [r for r in result['rows'] if not r['search_reuse']['current_keywords_equal']]
    assert len(changed) == 1 and changed[0]['search_reuse']['older_than_24_hours']
    assert result['budget']['automatic_refresh'] == 0
    assert result['budget']['search'] == 0


def test_cli_inputs_manifest_no_overwrite_and_no_database_write(prepared, tmp_path, monkeypatch, capsys):
    from app.sheets_candidate_plan import main
    database,batch,saved,report,selections = prepared
    selection_path = tmp_path/'selections.json'; selection_path.write_text(json.dumps(selections))
    inputs = tmp_path/'inputs.json'; inputs.write_text(json.dumps(dict(
        database=str(database),batch_id=batch,saved_reports=[str(saved)],selections=str(selection_path))))
    output = tmp_path/'preview.json'
    before = database.read_bytes()
    monkeypatch.setattr('sys.argv',['plan','--inputs',str(inputs),'--output',str(output)])
    assert main() == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary['live_requests'] == 0
    assert summary['budget']['maximum_requests'] == 6
    content = output.read_bytes()
    assert output.stat().st_mode & 0o077 == 0
    assert main() == 1
    assert output.read_bytes() == content
    assert database.read_bytes() == before
