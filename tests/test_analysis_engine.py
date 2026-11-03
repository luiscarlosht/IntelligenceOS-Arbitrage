from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json
import sqlite3

import pytest

from app.amazon_evaluation import EvaluationPolicy, evaluate
from app.analysis import main
from app.analysis_adapters import ManualAmazon, ManualKeepa, SheetsEvidence
from app.analysis_engine import analyze_record, market_summary, remember
from app.analysis_sheets import HEADERS, TAB, cells, plan, preview, publish
from app.decision_history import database
from app.observations import canonical, fingerprint
from test_amazon_evaluation import complete, NOW, observation, fiskars


def verified():
    record=complete();record['is_synthetic']=False
    def visit(item):
        if isinstance(item,dict):
            if 'observed_at' in item:item['confidence']='HIGH'
            for value in item.values():visit(value)
    visit(record)
    record['monthly_sales'].update(condition='New',basis='authorized_sales')
    record['competing_offers'].update(condition='New',basis='new_offer_count')
    return record


def test_reuses_finances_and_default_policy():
    record=verified()
    result=analyze_record(record,NOW)
    assert result['financials']==evaluate(record,NOW)['financials']
    assert result['decision']=='BUY_CANDIDATE'
    assert result['purchase_authorized'] is False
    assert result['evidence_sha256']==fingerprint(record)
    assert analyze_record(record,NOW,EvaluationPolicy(Decimal('20'),Decimal('50')))['decision']=='REJECTED'
    assert analyze_record(record,NOW,EvaluationPolicy(Decimal('5'),Decimal('120')))['decision']=='REJECTED'


@pytest.mark.parametrize('value', [Decimal('-1'),Decimal('NaN'),Decimal('Infinity'),5])
def test_invalid_policy(value):
    with pytest.raises(ValueError):EvaluationPolicy(value,Decimal('50'))


def test_fiskars_observed_report_and_assumptions_are_separate():
    record=fiskars();result=analyze_record(record,NOW)
    assert result['decision']=='BLOCKED'
    assert result['detailed_decision']=='BLOCKED_APPROVAL_REQUIRED'
    assert result['eligibility']['status']=='APPROVAL_REQUIRED'
    assert result['market']['current_price']['value']=='59.84'
    assert result['market']['sales_rank']['value']=='435'
    assert result['market']['category']['value']=='UNKNOWN'
    assert result['market']['monthly_sales']['value']=='UNKNOWN'
    assert not result['financials']['FBA']['base']['complete']
    assert 'financials.FBA.base.purchase' in result['missing_data']
    # Explicitly fictional test assumptions demonstrate mathematical support only.
    record['financials']=complete()['financials']
    for mode in record['financials'].values():
        for scenario in mode.values():
            for item in scenario.values():item['assumed']=True
    result=analyze_record(record,NOW)
    assert result['financials']['FBA']['base']['complete']
    assert result['assumptions']
    assert result['decision']=='BLOCKED' and not result['buy_candidate_modes']


def test_assumed_cost_and_unknown_confidence_prevent_candidate():
    record=verified();record['financials']['FBA']['base']['purchase']['assumed']=True
    assert analyze_record(record,NOW)['decision']=='REVIEW'
    record=verified();del record['identity']['retailer_product']['confidence']
    assert analyze_record(record,NOW)['decision']=='REVIEW'


@pytest.mark.parametrize('status',['APPROVAL_REQUIRED','RESTRICTED','UNKNOWN'])
def test_all_eligibility_blocks(status):
    record=verified();record['eligibility']['status']=status
    assert analyze_record(record,NOW)['decision']=='BLOCKED'


def test_negative_profit_and_missing_cost():
    record=verified()
    for mode in record['financials'].values():
        for scenario in mode.values():scenario['purchase']['value']='100'
    result=analyze_record(record,NOW)
    assert result['decision']=='REJECTED'
    assert Decimal(result['financials']['FBA']['base']['net_profit'])<0
    record=verified()
    for mode in record['financials'].values():del mode['base']['referral_fee']
    assert analyze_record(record,NOW)['decision']=='BLOCKED'


def test_unknown_market_never_rank_to_sales():
    record=verified();del record['monthly_sales']
    record['market']={'sales_rank':dict(observation(435),confidence='HIGH',condition='New',basis='category_rank')}
    result=analyze_record(record,NOW)
    assert result['market']['monthly_sales']['value']=='UNKNOWN'
    assert result['decision']=='BLOCKED'
    record['monthly_sales']=dict(observation(999),confidence='HIGH',condition='New',basis='rank_estimate')
    assert analyze_record(record,NOW)['decision']=='BLOCKED'


def test_manual_keepa_volatility_and_conflicts():
    stats=dict(observation(dict(min='20',max='30',mean='25')),confidence='HIGH',condition='New',basis='New Amazon price 30d USD',currency='USD')
    patch=[dict(asin='B000YZASYO',market={'historical_30d':stats})]
    record=ManualKeepa(patch).merge([verified()])[0]
    market,missing=market_summary(record,NOW)
    assert market['price_volatility']['value']=='40.0'
    assert market['price_volatility']['source'].startswith('Derived from ')
    assert 'market.price_volatility' not in missing
    with pytest.raises(ValueError):ManualKeepa([dict(patch[0],eligibility={})]).merge([verified()])
    with pytest.raises(ValueError):ManualKeepa(patch+patch).merge([verified()])
    changed=deepcopy(patch);changed[0]['market']['historical_30d']['value']['max']='40'
    with pytest.raises(ValueError):ManualKeepa(changed).merge([record])
    assert 'market' not in verified() # adapters did not mutate original caller


@pytest.mark.parametrize('stats', [dict(min='0',max='30',mean='25'),dict(min='40',max='20',mean='30'),dict(min='NaN',max='30',mean='25')])
def test_invalid_stats_leave_volatility_unknown(stats):
    record=verified();record['market']={'historical_30d':dict(observation(stats),confidence='HIGH',condition='New')}
    assert market_summary(record,NOW)[0]['price_volatility']['value']=='UNKNOWN'


def test_append_only_history_dedup_and_unrelated_db_preserved(tmp_path):
    tmp_path.chmod(0o700);path=tmp_path/'analysis.sqlite3'
    report=analyze_record(fiskars(),NOW)
    remember(path,[report]);remember(path,[report])
    with database(path) as db:
        original=db.execute('SELECT * FROM observations').fetchall()
        assert len(original)==1
        with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE observations SET payload=?',('{}',))
    remember(path,[analyze_record(fiskars(),NOW+timedelta(minutes=1))])
    with database(path) as db:
        assert db.execute('SELECT * FROM observations WHERE sequence=1').fetchall()==original
        assert db.execute('SELECT count(*) FROM observations').fetchone()[0]==2
    other=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(other) as db:db.execute('CREATE TABLE legacy (data TEXT)')
    other.chmod(0o600);before=other.read_bytes()
    with pytest.raises(ValueError):remember(other,[report])
    assert other.read_bytes()==before


class Client:
    def __init__(self):
        self.meta=dict(sheets=[dict(properties=dict(title='Historical',sheetId=0))])
        self.saved=[];self.writes=0
    def select(self,book):assert book=='1FcbY7OLu5Vz50IehxuA23E6obwuxt6_SYtFgRUac0ps'
    def metadata(self):return deepcopy(self.meta)
    def request(self,suffix,payload=None):
        if payload is None:return dict(values=deepcopy(self.saved))
        assert suffix==':batchUpdate';self.writes+=1
        for request in payload['requests']:
            if 'addSheet' in request:self.meta['sheets'].append(dict(properties=request['addSheet']['properties']))
            else:
                w=request['updateCells'];n=w['start']['rowIndex']
                while len(self.saved)<=n:self.saved.append([])
                row=[v['userEnteredValue']['stringValue'] for v in w['rows'][0]['values']]
                self.saved[n][:len(row)]=row


def test_preview_publish_readback_and_sparse_upsert():
    client=Client();proposal=preview(client,[fiskars()],NOW)
    assert client.writes==0
    assert proposal['reports'][0]['decision']=='BLOCKED'
    assert publish(client,proposal,NOW+timedelta(minutes=1))['mode']=='published'
    client.saved[0].append('manual');client.saved[1].append('preserve this')
    proposal=preview(client,[fiskars()],NOW)
    assert len(proposal['requests'])==1
    publish(client,proposal,NOW)
    assert len(client.saved)==2 and client.saved[1][-1]=='preserve this'
    assert all(r['updateCells']['start']['sheetId']!=0 for r in proposal['requests'])


def test_changed_snapshot_expired_preview_and_tampering_never_write():
    client=Client();proposal=preview(client,[fiskars()],NOW)
    with pytest.raises(ValueError):publish(client,proposal,NOW+timedelta(minutes=16))
    proposal['reports'][0]['decision']='BUY_CANDIDATE'
    with pytest.raises(ValueError):publish(client,proposal,NOW)
    proposal=preview(client,[fiskars()],NOW)
    client.meta['sheets'][0]['properties']['title']='changed'
    with pytest.raises(ValueError):publish(client,proposal,NOW)
    assert client.writes==0


def test_duplicate_input_and_output_keys_fail():
    with pytest.raises(ValueError):ManualAmazon([fiskars(),fiskars()]).records()
    report=analyze_record(fiskars(),NOW)
    with pytest.raises(ValueError):plan([report],Client().meta,[HEADERS,cells(report),cells(report)])


def test_cli_offline_preview_no_history_and_no_overwrite(tmp_path,monkeypatch):
    monkeypatch.setattr('app.analysis.client',lambda *a:pytest.fail('Offline CLI attempted network'))
    target=tmp_path/'preview.json'
    main(['--input','sample_data/amazon_evaluation_fiskars.json','--output',str(target)])
    assert json.loads(target.read_text())['records'][0]['decision']=='BLOCKED'
    assert not list(tmp_path.glob('*.sqlite3'))
    with pytest.raises(FileExistsError):main(['--input','sample_data/amazon_evaluation_fiskars.json','--output',str(target)])
    with pytest.raises(SystemExit):main(['--publish-preview',str(target)])


def test_sheets_adapter_preserves_conflicts_and_fails_closed():
    from app.amazon_evaluation_sheets import HEADERS as INPUT_HEADERS, seed
    client=Client()
    client.meta['sheets'].append(dict(properties=dict(title='Amazon_Evaluation',sheetId=106,
        gridProperties=dict(rowCount=2002,columnCount=24))))
    client.saved=[INPUT_HEADERS,seed(fiskars())]
    assert SheetsEvidence(client).records()[0]['asin']=='B000YZASYO'
    client.saved[1][INPUT_HEADERS.index('eligibility_status')]='ELIGIBLE'
    report=analyze_record(SheetsEvidence(client).records()[0],NOW)
    assert report['decision']=='BLOCKED'
    assert report['input_evidence']['input_conflicts']==['eligibility_status']


def test_publication_rechecks_input_freshness_at_current_time():
    record=verified()
    # Fresh at preview, but eligibility expires within the preview lifetime.
    record['eligibility']['observed_at']=(NOW-timedelta(hours=24)+timedelta(minutes=1)).isoformat()
    client=Client();proposal=preview(client,[record],NOW)
    assert proposal['reports'][0]['decision']=='BUY_CANDIDATE'
    with pytest.raises(ValueError,match='expired'):publish(client,proposal,NOW+timedelta(minutes=2))
    assert client.writes==0


def test_future_stale_unknown_confidence_market_is_visible_but_unusable():
    for stamp in (NOW+timedelta(minutes=1),NOW-timedelta(days=2)):
        record=verified()
        record['monthly_sales']['observed_at']=stamp.isoformat()
        report=analyze_record(record,NOW)
        assert report['market']['monthly_sales']['value']==50
        assert not report['market']['monthly_sales']['usable']
        assert report['decision']=='BLOCKED'


def test_validation_reference_required_for_estimated_sales():
    record=verified();record['monthly_sales']['basis']='validated_estimate'
    assert analyze_record(record,NOW)['decision']=='BLOCKED'
    record['monthly_sales']['model_validation_reference']='SYNTHETIC TEST VALIDATION REFERENCE'
    assert analyze_record(record,NOW)['decision']=='BUY_CANDIDATE'


def test_conflicting_manual_market_and_existing_evidence_blocks():
    record=verified()
    record['market']={'monthly_sales':dict(record['monthly_sales'],value=999)}
    result=analyze_record(record,NOW)
    assert result['decision']=='BLOCKED'
    assert result['input_evidence']['monthly_sales']['value']==50
    assert result['input_evidence']['market']['monthly_sales']['value']==999
    assert not result['buy_candidate_modes']
