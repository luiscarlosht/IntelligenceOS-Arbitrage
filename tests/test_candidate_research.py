"""Synthetic transport and hidden-input substitutes only; never real credentials/HTTP."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest

from app import amazon_pilot as pilot
from app import amazon_details
from app.candidate_execution import prepare_research, execute_research
from app.observations import canonical
from test_candidate_execution import run_case
from app.amazon_catalog import MARKETPLACE

CREDS = dict(client_id='mock-client', client_secret='mock-secret', refresh_token='mock-refresh')
SELLER = 'MOCKSELLER'


def pricing(asin):
    price = lambda value: dict(CurrencyCode='USD', Amount=value)
    return dict(payload=dict(status='Success', ASIN=asin, marketplaceId=MARKETPLACE, ItemCondition='New',
        Identifier=dict(ASIN=asin, MarketplaceId=MARKETPLACE, ItemCondition='New'), Offers=[{}],
        Summary=dict(TotalOfferCount=1, LowestPrices=[dict(condition='New', fulfillmentChannel='Amazon',
            ListingPrice=price(20), Shipping=price(1), LandedPrice=price(21))])))


@pytest.fixture(autouse=True)
def no_live_access(monkeypatch):
    monkeypatch.setattr(pilot,'load_credentials',lambda *_:pytest.fail('Real credentials'))
    monkeypatch.setattr(pilot,'request_json',lambda *_:pytest.fail('Real HTTP'))
    monkeypatch.setattr(amazon_details,'prompt_seller_id',lambda *_:pytest.fail('Real seller input'))
    monkeypatch.setattr(amazon_details,'parse_fees',lambda *_a,**_k:pytest.fail('Fees disabled'))


@pytest.fixture
def prepared(tmp_path):
    case,report,calls=run_case(tmp_path/'catalog')
    saved=tmp_path/'saved-detail-report.json';saved.write_text(canonical(report)+'\n')
    asins=[r['candidate_asin'] for r in report['rows'][:2]]
    manifest=prepare_research(case[0],saved,asins)
    path=tmp_path/'research-manifest.json';path.write_text(canonical(manifest)+'\n')
    return case[0],saved,path,hashlib.sha256(path.read_bytes()).hexdigest(),manifest


class Transport:
    def __init__(self,failure=None,no_offers=False):self.calls=[];self.failure=failure;self.no_offers=no_offers
    def __call__(self,request):
        self.calls.append(request)
        url=urlsplit(request.full_url);query=parse_qs(url.query)
        if url.hostname=='api.amazon.com':
            if self.failure=='authentication':raise RuntimeError('mock-secret')
            return dict(access_token='mock-access',token_type='bearer')
        if url.path.endswith('/offers'):
            if self.failure=='pricing':raise RuntimeError('mock-secret')
            asin=url.path.split('/')[-2]
            if self.no_offers:
                from app.amazon_catalog import MARKETPLACE
                return dict(payload=dict(status='NoBuyableOffers',ASIN=asin,marketplaceId=MARKETPLACE,ItemCondition='New',
                    Identifier=dict(ASIN=asin,MarketplaceId=MARKETPLACE,ItemCondition='New'),Offers=[],Summary=dict(TotalOfferCount=0)))
            return pricing(asin)
        if url.path=='/listings/2021-08-01/restrictions':
            assert query['sellerId']==[SELLER]
            if self.failure=='restrictions':raise RuntimeError('mock-secret')
            return dict(restrictions=[])
        pytest.fail('Out-of-scope endpoint: '+url.path)


def run(prepared,tmp_path,transport):
    clock = [0.]
    def advance(seconds): clock[0] += seconds
    return execute_research(prepared[2],prepared[3],5,tmp_path/'research-private',
        transport=transport,credential_loader=lambda _:CREDS,seller_prompt=lambda:SELLER,sleep=advance,monotonic=lambda:clock[0])


def test_five_attempt_budget_no_fees_and_original_lineage(prepared,tmp_path):
    before=prepared[0].read_bytes(),prepared[1].read_bytes()
    transport=Transport();report=run(prepared,tmp_path,transport)
    assert report['status']=='succeeded' and len(transport.calls)==5
    assert prepared[-1]['limits']==dict(authentication=1,pricing=2,restrictions=2,detail=0,search=0,total=5)
    assert report['purchase_approved'] is False and report['verified_net_profit'] is None
    assert report['seller_eligible'] is None
    assert report['label'].startswith('CANDIDATE-ASIN RESEARCH')
    for row,original in zip(report['rows'],prepared[-1]['rows']):
        assert row['lineage']==original['lineage']
        assert row['source_identity']=='unverified' and row['packaging']=='unverified'
        assert row['fees']==dict(status='not_requested',data=None)
        assert row['pricing']['status']==row['restrictions']['status']=='succeeded'
        assert row['restrictions']['data']['listing_permission']['value'] is True
        assert row['purchase_approved'] is False and row['exact'] is False
    assert before==(prepared[0].read_bytes(),prepared[1].read_bytes())
    text=canonical(report)
    assert all(secret not in text for secret in (*CREDS.values(),'mock-access',SELLER))
    for req in transport.calls[1:]:
        assert req.get_method()=='GET'
        assert '/fees' not in req.full_url and '/catalog/' not in req.full_url
    with sqlite3.connect(tmp_path/'research-private'/'candidate-executions.sqlite3') as db:
        saved=json.loads(db.execute('SELECT checkpoint_json FROM candidate_executions').fetchone()[0])
        assert canonical(saved)==canonical(report)
    assert len(list((tmp_path/'research-private').glob('candidate-research-*.json')))==1
    assert len(list((tmp_path/'research-private').glob('candidate-research-*.checkpoints.jsonl')))==1


@pytest.mark.parametrize('failure',['pricing','restrictions','authentication'])
def test_independent_outcomes_no_retry(prepared,tmp_path,failure):
    transport=Transport(failure);report=run(prepared,tmp_path,transport)
    if failure=='authentication':
        assert len(transport.calls)==1 and report['status']=='stopped_no_retry'
        assert all(row[k]['status']=='not_attempted' for row in report['rows'] for k in ('pricing','restrictions'))
    else:
        assert len(transport.calls)==5 and report['status']=='partial'
        other='restrictions' if failure=='pricing' else 'pricing'
        assert all(row[failure]['status']=='failed' and row[other]['status']=='succeeded' for row in report['rows'])
    with pytest.raises(sqlite3.IntegrityError):
        execute_research(prepared[2],prepared[3],5,tmp_path/'research-private',
                         seller_prompt=lambda:pytest.fail('Replay prompt'),credential_loader=lambda _:pytest.fail('Replay credentials'))


def test_no_buyable_offers_preserves_independent_restriction_outcomes(prepared,tmp_path):
    report=run(prepared,tmp_path,Transport(no_offers=True))
    assert report['status']=='succeeded'
    for row in report['rows']:
        assert row['pricing']['data']['value']['lookup_status']=='NoBuyableOffers'
        assert row['pricing']['data']['value']['price_unknown'] is True
        assert row['restrictions']['status']=='succeeded'
        assert row['fees']['status']=='not_requested'


@pytest.mark.parametrize('damage',['manifest_sha','limit','fees','saved_report','source'])
def test_validation_before_prompt_credentials_or_private_records(prepared,tmp_path,monkeypatch,damage):
    db,saved,path,digest,manifest=prepared
    if damage=='manifest_sha':digest='0'*64
    elif damage=='fees':
        manifest['fees']=True;path.write_text(canonical(manifest));digest=hashlib.sha256(path.read_bytes()).hexdigest()
    elif damage=='saved_report':saved.write_text(saved.read_text()+'\n')
    elif damage=='source':
        with sqlite3.connect(db) as connection:connection.execute("UPDATE source_observations SET observed_at='2026-01-01T00:01:00Z'")
    monkeypatch.setattr(pilot,'private_directory',lambda *_:pytest.fail('Private access before validation'))
    with pytest.raises(ValueError):execute_research(path,digest,4 if damage=='limit' else 5,tmp_path/'research-private')


def test_interruption_keeps_both_candidates_and_prior_stage_outcomes(prepared,tmp_path):
    base=Transport()
    def transport(request):
        if len(base.calls)==2:raise KeyboardInterrupt()
        return base(request)
    report=execute_research(prepared[2],prepared[3],5,tmp_path/'research-private',transport=transport,
        credential_loader=lambda _:CREDS,seller_prompt=lambda:SELLER,sleep=lambda _:None)
    assert report['status']=='stopped_no_retry' and len(report['rows'])==2
    assert report['rows'][0]['pricing']['status']=='succeeded'
    assert report['rows'][0]['restrictions']['status']=='interrupted'
    assert report['rows'][1]['pricing']['status']=='not_attempted'
    assert len(report['attempts'])==3
    with pytest.raises(sqlite3.IntegrityError):
        execute_research(prepared[2],prepared[3],5,tmp_path/'research-private')


def test_asin_subset_validation(prepared):
    with pytest.raises(ValueError):prepare_research(prepared[0],prepared[1],['B099999999'])
    asin=prepared[-1]['asins'][0]
    with pytest.raises(ValueError):prepare_research(prepared[0],prepared[1],[asin,asin])


def test_cli_scope_and_explicit_live_opt_in(prepared,tmp_path,monkeypatch,capsys):
    from app.candidate_execution import main
    output=tmp_path/'offline-prepared.json'
    args=['candidate','prepare-research','--database',str(prepared[0]),'--detail-report',str(prepared[1]),
          '--manifest',str(output)]
    for asin in prepared[-1]['asins']:args+=['--asin',asin]
    monkeypatch.setattr('sys.argv',args)
    assert main()==0
    result=json.loads(capsys.readouterr().out)
    assert result['limits']['total']==5 and result['live_requests']==0
    assert result['manifest_sha256']==hashlib.sha256(output.read_bytes()).hexdigest()
    monkeypatch.setattr('sys.argv',['candidate','run-research','--manifest',str(output)])
    with pytest.raises(SystemExit):main()


def test_shortlist_research_uses_only_named_evidence(prepared, tmp_path, monkeypatch):
    from app.sheets_candidate_plan import audit_database
    from app.observations import fingerprint
    db, saved_path, _, _, old = prepared
    saved = json.loads(saved_path.read_text())
    original = saved['manifest']
    audit, _, _ = audit_database(db, saved['batch_id'])
    bindings = [dict(batch_id=saved['batch_id'], content_hash=audit['batch_content_hash'])]
    search_path = tmp_path/'named-search.json'
    search_path.write_text(canonical(dict(manifest=dict(batch_bindings=bindings))))
    entries = []
    for parent, bound in zip(saved['rows'], original['rows']):
        asin = parent['candidate_asin']
        candidate = dict(candidate_asin=asin, candidate_audit={'exact': False}, alternatives=[], selection_reason='provisional')
        bound['candidate_outcomes'] = [candidate]
        parent['candidate_outcomes'] = [dict(candidate, detail=parent['detail'])]
        entries.append(dict(asin=asin, lineage=dict(record_id=parent['record_id']),
                            source_fingerprint=parent['source_fingerprint'], candidate_audit={'exact': False}, alternatives=[]))
    reviewed_path = tmp_path/'named-shortlist.json'
    reviewed_path.write_text(canonical(dict(saved_report=dict(path=str(search_path),
        sha256=hashlib.sha256(search_path.read_bytes()).hexdigest()), requests=entries, reused_details=[])))
    original.update(mode='reviewed_shortlist_details', database=str(db), reviewed_plan=str(reviewed_path),
                    reviewed_plan_sha256=hashlib.sha256(reviewed_path.read_bytes()).hexdigest())
    saved_path.write_text(canonical(saved))
    monkeypatch.setattr(Path, 'glob', lambda *_: pytest.fail('Evidence discovery forbidden'))
    manifest = prepare_research(db, saved_path, old['asins'])
    assert manifest['batch_content_hash'] == fingerprint(bindings)
    assert all(r['lineage'][0]['candidate_audit'] == {'exact': False} for r in manifest['rows'])
    assert manifest['limits']['total'] == 5
    reviewed_path.write_text(reviewed_path.read_text()+'\n')
    with pytest.raises(ValueError, match='binding mismatch'):
        prepare_research(db, saved_path, old['asins'])


@pytest.mark.parametrize('throttled', [False, True])
def test_real_run_research_transport_path_is_operation_paced(prepared, tmp_path, monkeypatch, throttled):
    from app.amazon_pacing import OperationPacer
    from app.amazon_diagnostics import AmazonFailure, ResponseDocument
    clock = [0.]
    def advance(seconds): clock[0] += seconds
    pacer = OperationPacer(monotonic=lambda: clock[0], sleep=advance)
    monkeypatch.setattr(pilot, 'default_pacer', lambda: pacer)
    base = Transport()
    observed = []
    def raw(request):
        path = urlsplit(request.full_url).path
        observed.append((path, clock[0]))
        if path.endswith('/offers'):
            if throttled:
                error = AmazonFailure('unretained private response', reason='http_error',
                                      http_status=429, codes=('QuotaExceeded',))
                error.rate_headers = {'Retry-After': '1000'}
                raise error
            document = ResponseDocument(base(request), 200)
            document.rate_headers = {'x-amzn-RateLimit-Limit': '.25'}
            return document
        if path.endswith('/restrictions'):
            return {'restrictions': [{'marketplaceId': MARKETPLACE, 'reasons': [
                {'reasonCode': 'APPROVAL_REQUIRED', 'message': '=Follow Amazon instructions',
                 'links': [{'resource': 'https://sellercentral.amazon.com/approval', 'verb': 'GET'}]}]}]}
        return base(request)
    monkeypatch.setattr(pilot, '_request_json', raw)
    # transport=None selects the production path; all actual I/O is replaced above.
    result = execute_research(prepared[2], prepared[3], 5, tmp_path/'research-private',
        credential_loader=lambda _: CREDS, seller_prompt=lambda: SELLER,
        sleep=advance, monotonic=lambda: clock[0])
    prices = [t for path,t in observed if path.endswith('/offers')]
    restrictions = [t for path,t in observed if path.endswith('/restrictions')]
    assert restrictions[0] == 0
    assert prices == ([0.] if throttled else [0.,4.])
    assert len(restrictions) == 2
    assert len(result['attempts']) == 5
    if throttled:
        assert result['rows'][0]['pricing']['failure']['http_status'] == 429
        assert result['rows'][1]['pricing']['failure']['reason'] == 'pacing_deferred'
        assert result['attempts'][1]['failure']['pacing']['not_before_monotonic'] == 1000
        assert result['attempts'][1]['status'] == 'failed_or_parser_rejected'
        assert 'unretained private' not in canonical(result)
    else:
        assert result['status'] == 'succeeded'
    for row in result['rows']:
        assert row['restrictions']['status'] == 'succeeded'
        data = row['restrictions']['data']
        assert data['reasons'][0]['message'] == '=Follow Amazon instructions'
        assert data['reasons'][0]['links'][0]['resource'].startswith('https://sellercentral.amazon.com/')
        assert data['approval_required'] is True
        assert data['listing_permission']['value'] is False
        assert data['fulfillment_eligibility'] is None
    # Neither changing the output nor another invocation releases consumed claims.
    with pytest.raises(sqlite3.IntegrityError):
        execute_research(prepared[2], prepared[3], 5, tmp_path/'research-private',
            credential_loader=lambda _: pytest.fail('Replay credential access'))
