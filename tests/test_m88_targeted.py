"""Synthetic bounded continuation tests; never uses live vendor data or credentials."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from app import m88_targeted as target
from app.m88_targeted_state import TargetedJournal,CLAIM,prefix_sha
from app.m88_targeted_evidence import catalog_detail,ranking
from app.m88_state import write,read,sha,ledger
from app.m88_evidence import product,US
from app.amazon_diagnostics import AmazonFailure
from test_amazon_details import catalog,pricing,fees,CREDS

IDS=['17011265','13952053139','721324153','37481849','47070933','711088244']
ASINS={item:f'B90000000{i}' for i,item in enumerate(IDS)}


def fixture(tmp_path,monkeypatch,*,exact=False,account=False):
    private=tmp_path/'private';private.mkdir(mode=0o700);write(private/'credentials.json',CREDS)
    evidence=tmp_path/'evidence';evidence.mkdir(mode=0o700)
    path=evidence/'amazon-http-attempt-ledger.json'
    original=[dict(number=i,phase='authentication' if i==1 else 'search',candidate_id=None if i==1 else 'synthetic:'+str(i),
        status='COMPLETE',plan_sha256='a'*64) for i in range(1,8)]
    write(path,dict(pilot='m88-real-six-pilot',ceiling=49,attempts_used=7,attempts=original,
        includes_authentication_and_retries=True,purchase_authorized=False,m88_operation='a'*64))
    doc=catalog();doc['summaries'][1]['brand']='Example'
    batch=dict(schema='walmart_pilot_batch_v1',name='m88-real-six-pilot',batch_kind='NEW_PILOT',purchase_authorized=False,
        other_cost_basis='excludes_retailer_shipping',observations=[])
    records=[]
    for i,item in enumerate(IDS):
        p=product(doc,doc['asin'],());p.pop('asin');p.update(walmart_item_id=item,url='https://www.walmart.com/ip/'+item,
            pack_description='Synthetic two-pack',verified=exact)
        batch['observations'].append(dict(source_candidate_id='synthetic:'+item,walmart_product=p,
            acquisition=dict(purchase=dict(value='1.00'),retailer_shipping=dict(value='UNKNOWN')),identity_exceptions=['Synthetic unresolved evidence']))
        for j in range([9,9,4,2,0,2][i]):
            a=ASINS[item] if j==0 else f'B8{i:02d}{j:06d}'
            records.append(dict(walmart_item_id=item,asin=a,classification='NEEDS_REVIEW',
                comparisons=dict(upc=dict(overlap=j==0 and i in (0,2),amazon_identifiers=dict(distinct_canonical_gtins=['00012345678905'])),
                    brand=dict(status='MATCH'),model=dict(status='MATCH' if exact else 'UNKNOWN')),
                amazon_product=dict(size='8 Count (Pack of 1)' if i==1 and j==0 else 'Synthetic size'),
                source_exceptions=['Synthetic gap'],remaining_gaps=['Synthetic identity gap']))
    write(evidence/'enriched-batch.json',batch)
    reconciliation=evidence/'candidate-reconciliation.json'
    write(reconciliation,dict(cohort='m88-real-six-pilot',records=records,source_inventory=[dict(path=str(path),sha256=sha(path))]))
    context=None
    if account:
        context=private/'account.json';write(context,dict(seller_id='SYNTHETICSELLER',credentials_sha256=sha(private/'credentials.json')))
    monkeypatch.setattr(target,'OperationPacer',lambda **_:type('P',(),{'call':lambda self,request,transport:transport(request)})())
    out=tmp_path/'operation';plan=target.prepare(reconciliation,sha(reconciliation),private,out,context)
    return plan,out,path,doc


class Fake:
    def __init__(self,path,doc,fail=None):self.path=path;self.doc=doc;self.calls=[];self.fail=fail
    def __call__(self,request):
        current=ledger(self.path);assert current['attempts'][-1]['status']=='RESERVED'
        self.calls.append(request)
        if self.fail==len(self.calls):raise AmazonFailure('synthetic-secret',reason='http_error',http_status=429)
        path=urlsplit(request.full_url).path
        if path=='/auth/o2/token':return dict(access_token='synthetic-access',token_type='bearer',expires_in=3600)
        if path.startswith('/catalog/2022-04-01/items/'):
            d=deepcopy(self.doc);d['asin']=path.rsplit('/',1)[-1]
            d['attributes']={'part_number':[dict(value='Synthetic-MPN',marketplace_id=US)],
                'model_number':[dict(value='Example model',marketplace_id=US)],
                'unit_count':[dict(value=2,type=dict(value='count'),marketplace_id=US)],
                'item_form':[dict(value='Synthetic formulation',marketplace_id=US)]}
            d['dimensions']=[dict(marketplaceId=US,item=dict(height=dict(value=2,unit='inches')))]
            return d
        if path.endswith('/offers'):
            asin=path.split('/')[-2];p=pricing()
            p['payload']['ASIN']=asin;p['payload']['Identifier']['ASIN']=asin
            p['payload']['Summary']['BuyBoxPrices']=[dict(condition='New',fulfillmentChannel='Amazon',ListingPrice=dict(CurrencyCode='USD',Amount=25),Shipping=dict(CurrencyCode='USD',Amount=0))]
            return p
        if path.endswith('/feesEstimate'):
            asin=path.split('/')[-2];body=json.loads(request.data)['FeesEstimateRequest']
            f=fees(body['Identifier']);f['payload']['FeesEstimateResult']['FeesEstimateIdentifier'].update(IdValue=asin,IsAmazonFulfilled=body['IsAmazonFulfilled'])
            return f
        raise AssertionError('No search or write endpoint allowed')


def test_rank_plan_and_preparation_do_not_change_original_accounting(tmp_path,monkeypatch):
    plan,out,path,doc=fixture(tmp_path,monkeypatch)
    assert ledger(path)['attempts_used']==7 and CLAIM not in ledger(path)
    assert len(read(out/'ranking.json')['ranked_candidates'])==26
    assert {t['asin'] for t in plan['targets']}=={ASINS[i] for i in IDS[:3]}
    assert len(plan['requests'])==13 and plan['maximum_cumulative_attempts']==20
    assert all('/catalog/2022-04-01/items?' not in r['path'] for r in plan['requests'])


def test_live_seam_charges_four_preserves_first_seven_and_never_replays(tmp_path,monkeypatch):
    plan,out,path,doc=fixture(tmp_path,monkeypatch);before=deepcopy(ledger(path))
    fake=Fake(path,doc);expected=sha(out/'plan.json')
    target.execute(out/'plan.json',expected,transport=fake)
    after=ledger(path)
    assert len(fake.calls)==4 and after['attempts_used']==11
    assert after['attempts'][:7]==before['attempts'] and after['m88_operation']==before['m88_operation']
    assert after[CLAIM]==expected and all(a['status']=='COMPLETE' for a in after['attempts'])
    with pytest.raises(PermissionError):target.execute(out/'plan.json',expected,transport=fake)
    summary=target.recover(out/'plan.json',expected,tmp_path/'reports')
    assert summary['verified_matches']==0 and summary['new_attempts']==4
    assert summary['supported_profitability_products']==0
    assert (tmp_path/'reports'/'comparison.xlsx').is_file()
    receipts=''.join(p.read_text() for p in out.glob('receipt-*.json'))
    assert all(s not in receipts for s in [*CREDS.values(),'synthetic-access'])


def test_retain_mpn_scope_units_and_dimensions_without_model_alias(tmp_path,monkeypatch):
    plan,out,path,doc=fixture(tmp_path,monkeypatch)
    fake=Fake(path,doc);target.execute(out/'plan.json',sha(out/'plan.json'),transport=fake)
    result=read(out/'receipt-9.json')['evidence']['product']
    assert result['manufacturer_part_number']=='Synthetic-MPN'
    assert result['model']=='Example model'
    assert result['retained_attributes']['unit_count'][0]['type']['value']=='count'
    assert result['dimensions'][0]['item']['height']['unit']=='inches'
    assert result['dimensions'][0]['marketplaceId']==US


@pytest.mark.parametrize('failure',[1,2,4])
def test_api_failure_charged_stops_without_retry(tmp_path,monkeypatch,failure):
    plan,out,path,doc=fixture(tmp_path,monkeypatch);fake=Fake(path,doc,fail=failure)
    with pytest.raises(target.Stop):target.execute(out/'plan.json',sha(out/'plan.json'),transport=fake)
    assert len(fake.calls)==failure and ledger(path)['attempts_used']==7+failure
    assert ledger(path)['attempts'][-1]['status']=='FAILED'
    assert 'synthetic-secret' not in path.read_text()
    summary=target.recover(out/'plan.json',sha(out/'plan.json'),tmp_path/'recovered')
    assert len(summary['failed_attempts'])==1


def test_uncertain_reservation_recovery_never_refunds_or_dispatches(tmp_path,monkeypatch):
    plan,out,path,doc=fixture(tmp_path,monkeypatch);expected=sha(out/'plan.json')
    j=TargetedJournal(path,expected,plan);j.start();j.reserve('authentication',None)
    baseline=path.read_bytes()
    monkeypatch.setattr(target.pilot,'load_credentials',lambda *_:pytest.fail('Recovery must not read credentials'))
    summary=target.recover(out/'plan.json',expected,tmp_path/'recovered')
    assert summary['unknown_outcomes']==[8] and path.read_bytes()==baseline
    with pytest.raises(PermissionError):j.start()


def test_scope_phase_and_49_attempt_ceiling(tmp_path,monkeypatch):
    plan,out,path,doc=fixture(tmp_path,monkeypatch);j=TargetedJournal(path,sha(out/'plan.json'),plan)
    with pytest.raises(ValueError):j.reserve('search','unrelated')
    with pytest.raises(PermissionError):j.reserve('detail',plan['targets'][0]['candidate_id'])
    data=ledger(path);data['attempts'].extend(dict(number=i,status='COMPLETE',phase='other') for i in range(8,50));data['attempts_used']=49
    write(path,data,replace=True)
    with pytest.raises((PermissionError,ValueError)):j.reserve('authentication',None)


def test_original_history_drift_refused_before_values_are_read(tmp_path,monkeypatch):
    plan,out,path,doc=fixture(tmp_path,monkeypatch);data=ledger(path);data['attempts'][0]['phase']='tampered';write(path,data,replace=True)
    monkeypatch.setattr(target.pilot,'load_credentials',lambda *_:pytest.fail('No credential read on drift'))
    with pytest.raises(ValueError):target.execute(out/'plan.json',sha(out/'plan.json'),transport=Fake(path,doc))
    assert ledger(path)['attempts_used']==7


def test_exact_synthetic_path_only_then_offers_and_fees(tmp_path,monkeypatch):
    plan,out,path,doc=fixture(tmp_path,monkeypatch,exact=True,account=True)
    fake=Fake(path,doc);target.execute(out/'plan.json',sha(out/'plan.json'),transport=fake)
    assert len(fake.calls)==13 and ledger(path)['attempts_used']==20
    summary=target.recover(out/'plan.json',sha(out/'plan.json'),tmp_path/'reports')
    assert summary['verified_matches']==3 and summary['supported_profitability_products']==0


def test_missing_or_foreign_mpn_never_filled_from_source():
    doc=catalog();doc['summaries'][1]['brand']='Example'
    source=product(doc,doc['asin'],());source['verified']=False
    doc['attributes']={'part_number':[dict(value='Foreign',marketplace_id='OTHER')]}
    result=catalog_detail(doc,doc['asin'],source,())
    assert result['product']['manufacturer_part_number']=='UNKNOWN' and not result['identity']['exact']


def test_parser_failure_stops_counted(tmp_path,monkeypatch):
    plan,out,path,doc=fixture(tmp_path,monkeypatch);fake=Fake(path,doc)
    def malformed(request):
        value=fake(request)
        if len(fake.calls)>1:value['dimensions']='invalid'
        return value
    with pytest.raises(target.Stop):target.execute(out/'plan.json',sha(out/'plan.json'),transport=malformed)
    assert ledger(path)['attempts_used']==9
    assert ledger(path)['attempts'][-1]['failure']['reason']=='response_validation_failed'


def test_source_conflict_never_erased_by_matching_amazon_fields():
    doc=catalog();doc['summaries'][1]['brand']='Example'
    source=product(doc,doc['asin'],());source.update(verified=True,conflicting_observations=['Conflicting 0.5 oz source phrase'])
    result=catalog_detail(doc,doc['asin'],source,())
    assert not result['identity']['exact'] and 'source.conflicting_observations' in result['identity']['missing']


def test_changed_selection_cannot_expand_scope_even_with_recomputed_digest(tmp_path,monkeypatch):
    plan,out,path,doc=fixture(tmp_path,monkeypatch)
    plan['targets'][0]['asin']='B000000099';plan['requests']=target.definitions(plan['targets'])
    write(out/'plan.json',plan,replace=True)
    monkeypatch.setattr(target.pilot,'load_credentials',lambda *_:pytest.fail('No read outside approved target set'))
    with pytest.raises(ValueError):target.execute(out/'plan.json',sha(out/'plan.json'),transport=Fake(path,doc))
    assert ledger(path)['attempts_used']==7


def test_report_only_recovery_detects_receipt_tampering(tmp_path,monkeypatch):
    plan,out,path,doc=fixture(tmp_path,monkeypatch)
    target.execute(out/'plan.json',sha(out/'plan.json'),transport=Fake(path,doc))
    write(out/'receipt-9.json',dict(tampered=True),replace=True)
    before=path.read_bytes()
    with pytest.raises(ValueError):target.recover(out/'plan.json',sha(out/'plan.json'),tmp_path/'reports')
    assert path.read_bytes()==before and not (tmp_path/'reports').exists()


def test_independent_part_number_comparison_never_infers_model_alias():
    doc=catalog();doc['summaries'][1]['brand']='Example'
    source=product(doc,doc['asin'],());source.update(verified=True,mpn='SOURCE-MPN')
    doc['attributes']={'part_number':[dict(value='AMAZON-MPN',marketplace_id=US)]}
    result=catalog_detail(doc,doc['asin'],source,())
    assert result['comparisons']['manufacturer_part_number']['status']=='DIFFERENT_LABELS'
    assert not result['identity']['exact']
    assert result['comparisons']['quantity_packaging']['equivalence']=='UNKNOWN'
