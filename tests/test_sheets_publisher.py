"""Publication failure and researcher-ownership regressions; no real credentials."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import pytest
from app.research_contract import SCHEMAS, STATUSES, browser_contract, validate_observation, validate_candidates
from app.sheets_publisher import GoogleSheets, index, plan

STAMP = '2026-11-03T13:00:00+00:00'


def candidate(asin='B00004OCNJ'):
    return {**dict.fromkeys(SCHEMAS['Amazon_Candidates'],'UNKNOWN'), 'asin':asin,
            'amazon_title':'=not a formula', 'research_status':'PENDING'}


def apply(requests, meta=None, values=None):
    meta = deepcopy(meta or {'sheets':[]}); values = deepcopy(values or {})
    for request in requests:
        if 'addSheet' in request:
            p=request['addSheet']['properties'];meta['sheets'].append({'properties':p});values[p['title']]=[]
        if 'updateCells' in request:
            u=request['updateCells'];s=u['start'];title=next(p['properties']['title'] for p in meta['sheets'] if p['properties']['sheetId']==s['sheetId'])
            rows=values[title]
            while len(rows)<=s['rowIndex']:rows.append([])
            row=rows[s['rowIndex']]
            while len(row)<s['columnIndex']+len(u['rows'][0]['values']):row.append('')
            row[s['columnIndex']:s['columnIndex']+len(u['rows'][0]['values'])]=[v['userEnteredValue']['stringValue'] for v in u['rows'][0]['values']]
    return meta,values


def planned(rows,meta=None,values=None,run='run1'):
    return plan(rows,meta or {'sheets':[]},values or {},run,STAMP,'20','a'*64)


def test_idempotent_asin_upsert_preserves_research_custom_columns_and_status():
    row=candidate();meta,values=apply(planned([row]))
    values['Walmart_Research'][1][1]='https://www.walmart.com/ip/123'
    values['Amazon_Candidates'][1][13]='IN_PROGRESS'
    values['Amazon_Candidates'][0].append('browser_notes');values['Amazon_Candidates'][1].append('keep me')
    changed={**row,'brand':'Updated brand'}
    meta,again=apply(planned([changed],meta,values),meta,values)
    assert again['Walmart_Research']==values['Walmart_Research']
    assert again['Amazon_Candidates'][1][13]=='IN_PROGRESS'
    assert again['Amazon_Candidates'][1][-1]=='keep me'
    assert again['Amazon_Candidates'][1][3]=='Updated brand'
    assert len(again['Run_Log'])==2
    assert len(again['Amazon_Candidates'])==2


def test_partial_recovery_and_existing_asin_positions():
    first=candidate();second=candidate('B00004Z4CY')
    requests=planned([first,second]);meta,values=apply(requests[:34])
    meta,values=apply(planned([first,second],meta,values),meta,values)
    assert len(values['Amazon_Candidates'])==3
    assert len(values['Walmart_Research'])==3
    assert values['Top_Opportunities']==[SCHEMAS['Top_Opportunities']]


def test_duplicate_and_drift_are_rejected_before_write():
    with pytest.raises(ValueError):validate_candidates([candidate(),candidate()])
    with pytest.raises(ValueError):index([['asin'],['B00004OCNJ'],['B00004OCNJ']],['asin'])
    with pytest.raises(ValueError):planned([candidate()],values={'Walmart_Research':[['wrong']]})


def test_strings_never_become_formulas():
    requests=planned([candidate()])
    cells=[v for r in requests if 'updateCells' in r for row in r['updateCells']['rows'] for v in row['values']]
    assert all(set(v['userEnteredValue'])=={'stringValue'} for v in cells)
    assert any(v['userEnteredValue']['stringValue']=='=not a formula' for v in cells)


class Response:
    def __init__(self,status):self.status_code=status
    def json(self):return {'ok':True}


class Session:
    def __init__(self,statuses):self.statuses=iter(statuses);self.calls=[]
    def request(self,*args,**kwargs):self.calls.append((args,kwargs));return Response(next(self.statuses))


def test_retry_bounded_and_no_secrets_in_error(caplog):
    session=Session([429,503,200]);delays=[]
    assert GoogleSheets('sheet-id',session,delays.append).request('GET')=={'ok':True}
    assert len(delays)==2 and 1<=delays[0]<=2 and 2<=delays[1]<=3
    assert all(call[1]['timeout']==30 and call[1]['allow_redirects'] is False for call in session.calls)
    session=Session([503]*5)
    with pytest.raises(RuntimeError,match='status=503'):GoogleSheets('id',session,delays.append).request('GET')
    assert len(session.calls)==5
    session=Session([403])
    with pytest.raises(RuntimeError,match='status=403'):GoogleSheets('id',session).request('GET')
    assert len(session.calls)==1


def test_contract_rejects_unverified_exact_matches_and_nonfinite_prices():
    row=candidate();contract=browser_contract([row]);observation=contract['sample_output']
    assert validate_observation(observation,row)==observation
    for changes in ({'match_status':'YES'},{'match_status':'EXACT_MATCH'}, {'walmart_price':'NaN'},
                    {'walmart_url':'https://evil.example/ip/1'}, {'research_timestamp':'2026-11-03T13:00:00'}):
        with pytest.raises(ValueError):validate_observation({**observation,**changes},row)
    assert set(contract['allowed_match_statuses'])==set(STATUSES)


def test_live_configuration_is_explicit(monkeypatch):
    monkeypatch.delenv('ARBITRAGE_SHEETS_ID',raising=False)
    monkeypatch.delenv('ARBITRAGE_SHEETS_CREDENTIALS',raising=False)
    with pytest.raises(ValueError,match='required'):GoogleSheets.from_env()


def test_run_identifier_cannot_be_reused_for_other_input_scope():
    meta,values=apply(planned([candidate()]))
    with pytest.raises(ValueError,match='different publication inputs'):
        plan([candidate()],meta,values,'run1',STAMP,'100','a'*64)


def test_large_catalog_partitions_and_only_completes_after_all_parts():
    class Publisher(GoogleSheets):
        def __init__(self): self.parts=[];self.saved=[]
        def snapshot(self):return {'sheets':[{'properties':{'sheetId':105,'title':'Run_Log'}}]}, {'Run_Log':[SCHEMAS['Run_Log']]}
        def request(self,*args,**kwargs):self.saved.append(kwargs);return {}
        def publish(self,rows,*args):
            if len(rows)<=25:self.parts.append(len(rows));return None
            return super().publish(rows,*args)
    publisher=Publisher();rows=[candidate('B'+str(i).zfill(9)) for i in range(100)]
    publisher.publish(rows,'run',STAMP,'100','a'*64)
    assert publisher.parts==[25]*4 and len(publisher.saved)==1
