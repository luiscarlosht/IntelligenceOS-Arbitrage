"""Isolated M95 execution regression tests; no credentials or network."""
import copy
import json
import os
import fcntl
from urllib.request import Request
from urllib.parse import urlencode

import pytest

from app.amazon_diagnostics import ResponseDocument
from app.m63_history import audit
from ops import m95_restrictions as m95
from ops import m95_manifest as manifest
from ops.m95_eligibility import m95_decision


@pytest.fixture(autouse=True)
def no_pacing_wait(monkeypatch):
    from app.amazon_pacing import OperationPacer
    monkeypatch.setattr(OperationPacer, 'acquire', lambda *args, **kwargs: None)


@pytest.fixture
def reviewed(m95_reviewed_manifest):
    return m95_reviewed_manifest


def request(asin=manifest.ASINS[0], **changes):
    params = dict(asin=asin, sellerId='TESTSELLER', marketplaceIds='ATVPDKIKX0DER',
                  conditionType='new_new', reasonLocale='en_US')
    params.update(changes)
    return Request('https://sellingpartnerapi-na.amazon.com/listings/2021-08-01/restrictions?'+urlencode(params))


def auth():
    return Request('https://api.amazon.com/auth/o2/token', data=b'fixture')


def execute(tmp_path, monkeypatch, reviewed, reply=None, **overrides):
    def network(req):
        if req.full_url.startswith('https://api.amazon.com/'):
            return dict(access_token='fixture', token_type='bearer')
        if isinstance(reply, BaseException):
            raise reply
        return ResponseDocument(reply if reply is not None else dict(restrictions=[]), 200)
    options = dict(execute_reviewed=True, private=tmp_path/'private', transport=network,
                   credential_loader=lambda fd: {}, seller_prompt=lambda: 'TESTSELLER', is_mock=True)
    options.update(overrides)
    return m95.run(**options)


def test_empty_is_ambiguous_no_early_stop(tmp_path, monkeypatch, reviewed):
    result = execute(tmp_path, monkeypatch, reviewed)
    assert len(result['attempts']) == 11
    assert result['stop_reason'] is None
    assert all(m95_decision(r) == 'NO_RESTRICTIONS_REPORTED' for r in result['rows'])
    assert not result['purchase_approved'] and not result['listing_authorized']
    assert all(a['stage'] in ('authentication', 'restrictions') for a in result['attempts'])
    assert 'TESTSELLER' not in json.dumps(result)


def test_qualifying_parser_signal_stops_after_one(tmp_path, monkeypatch, reviewed):
    # Contract test for a future independently validated affirmative parser.
    original = m95.parse_restrictions
    def affirmative(*args, **kwargs):
        data = original(*args, **kwargs)
        data['listing_permission']['value'] = True
        return data
    monkeypatch.setattr(m95, 'parse_restrictions', affirmative)
    result = execute(tmp_path, monkeypatch, reviewed)
    assert len(result['attempts']) == 2
    assert result['status'] == 'stopped_listing_permission_goal'
    assert len(result['no_restrictions_asins']) == 1
    assert result['rows'][1]['restrictions']['status'] == 'not_attempted'


@pytest.mark.parametrize('code,expected', [('APPROVAL_REQUIRED','APPROVAL_REQUIRED'),
    ('NOT_ELIGIBLE','NOT_ELIGIBLE'), ('PRIVATE','OTHER_RESTRICTED')])
def test_restricted(tmp_path, monkeypatch, reviewed, code, expected):
    reply = dict(restrictions=[dict(marketplaceId='ATVPDKIKX0DER', conditionType='new_new',
        reasons=[dict(reasonCode=code, message='SECRET')])])
    result = execute(tmp_path, monkeypatch, reviewed, reply)
    assert m95_decision(result['rows'][0]) == expected
    assert result['stop_reason'] is None
    assert 'SECRET' not in json.dumps(result)


@pytest.mark.parametrize('reply', [{}, {'restrictions':None}, {'restrictions':[None]},
    {'restrictions':[{'marketplaceId':'wrong'}]}, {'errors':[{}]},
    {'restrictions':[{'marketplaceId':'ATVPDKIKX0DER','reasons':[None]}]}])
def test_malformed(tmp_path, monkeypatch, reviewed, reply):
    result = execute(tmp_path, monkeypatch, reviewed, reply)
    assert m95_decision(result['rows'][0]) == 'UNKNOWN'
    assert result['stop_reason'] is None


def test_interruption_and_replay(tmp_path, monkeypatch, reviewed):
    result = execute(tmp_path, monkeypatch, reviewed, KeyboardInterrupt())
    assert result['status'] == 'stopped_no_retry'
    assert len(result['attempts']) == 2
    assert result['rows'][0]['restrictions']['status'] == 'interrupted'
    saved = json.loads((tmp_path/'private'/(m95.REPORT_STEM+'.json')).read_text())
    assert saved['attempts'][1]['status'] == 'reserved'
    with pytest.raises(FileExistsError):
        execute(tmp_path, monkeypatch, reviewed)


def test_lock_contention(tmp_path, monkeypatch, reviewed):
    private = tmp_path/'private'
    private.mkdir(mode=0o700)
    fd = os.open(private/'candidate-execution.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            execute(tmp_path, monkeypatch, reviewed)
        assert not (private/m95.AUTHORIZATION).exists()
    finally:
        os.close(fd)


def test_fresh_validation_under_lock(tmp_path, monkeypatch, reviewed):
    real = m95.validate
    calls = []
    def validate(*args):
        calls.append(1)
        if len(calls) == 2:
            raise ValueError('Historical evidence changed')
        return real(*args)
    monkeypatch.setattr(m95, 'validate', validate)
    with pytest.raises(ValueError, match='Historical'):
        execute(tmp_path, monkeypatch, reviewed)
    assert not (tmp_path/'private'/m95.AUTHORIZATION).exists()


@pytest.mark.parametrize('req', [Request('https://example.com'),
    Request('https://sellingpartnerapi-na.amazon.com/products/pricing/v0/items/X/offers'),
    Request(request().full_url, method='POST'), request(marketplaceIds='wrong'),
    request(conditionType='used'), request(asin='B000000000')])
def test_unexpected_operation_never_calls_network(req):
    calls = []
    send = m95.bounded_transport(lambda r: calls.append(r) or {})
    send(auth())
    with pytest.raises(ValueError):
        send(req)
    assert len(calls) == 1


def test_budget_and_duplicates():
    calls = []
    send = m95.bounded_transport(lambda r: calls.append(r) or ResponseDocument(dict(restrictions=[]),200))
    send(auth())
    for asin in manifest.ASINS:
        send(request(asin))
    with pytest.raises(ValueError, match='budget'):
        send(request())
    with pytest.raises(ValueError, match='budget'):
        send(auth())
    assert len(calls) == 11


@pytest.mark.parametrize('field,value', [('asins',list(manifest.ASINS[:-1])+[manifest.ASINS[0]]),
    ('marketplace_id','wrong'), ('condition','used'), ('budget',{}), ('requests',[])])
def test_changed_manifest_scope(tmp_path, reviewed, field, value):
    changed = copy.deepcopy(reviewed)
    changed[field] = value
    path = tmp_path/'changed.json'
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError):
        m95.validate(path)


def test_real_m95_reservation_excluded(tmp_path):
    (tmp_path/m95.AUTHORIZATION).write_text(json.dumps(dict(asins=list(manifest.ASINS))))
    assert set(manifest.ASINS) <= set(audit(tmp_path)['excluded_asins'])


def test_missing_permission_not_verified():
    row = dict(restrictions=dict(status='succeeded',data=dict(reason_codes=[],restriction_count=0,
        listing_permission=dict(value=True,is_mock=False))))
    assert m95_decision(row) == 'NO_RESTRICTIONS_REPORTED'


def test_changed_historical_evidence(reviewed, monkeypatch):
    original = manifest.evidence
    def changed():
        value = copy.deepcopy(original())
        value['historical_audit_sha256'] = '0'*64
        return value
    monkeypatch.setattr(manifest, 'evidence', changed)
    with pytest.raises(ValueError, match='historical'):
        m95.validate()


@pytest.mark.parametrize('source', ['checked', 'excluded'])
def test_previously_checked_or_excluded(tmp_path, monkeypatch, source):
    import csv
    proposal = tmp_path/'proposal.csv'
    asins = list(manifest.ASINS)+[f'B9{i:08d}' for i in range(90)]
    with proposal.open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=['asin','eligibility_status','purchase_approved'])
        writer.writeheader()
        writer.writerows(dict(asin=a,eligibility_status='UNKNOWN',purchase_approved='false') for a in asins)
    monkeypatch.setattr(manifest, 'PROPOSAL', proposal)
    monkeypatch.setattr(manifest, 'EXPECTED_PROPOSAL_SHA256', manifest.sha256(proposal))
    documents = {manifest.M69: dict(excluded_asins=[asins[0]] if source=='excluded' else [],
                    events=[dict(asin=asins[0])] if source=='checked' else []),
                 manifest.M79: {}, manifest.M94: dict(rows=[])}
    monkeypatch.setattr(manifest, 'load', lambda path: documents[path])
    monkeypatch.setattr(manifest, 'audit', lambda path: dict(excluded_asins=[]))
    with pytest.raises(ValueError, match='Previously'):
        manifest.evidence()


def test_atomic_reservation_race(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from app import amazon_pilot as pilot
    private = tmp_path/'private'
    directory = pilot.private_directory(private)
    def reserve():
        try:
            fd = pilot.create_file(directory, m95.AUTHORIZATION)
            os.close(fd)
            return True
        except FileExistsError:
            return False
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: reserve(), range(2)))
        assert sorted(results) == [False, True]
    finally:
        os.close(directory)


def test_m95_deadline_reserves_claim_without_network(tmp_path, monkeypatch, reviewed):
    original = m95.m94.engine._execute
    clock = iter([0, 121])
    def expired(*args, **kwargs):
        return original(*args, **kwargs, monotonic=lambda: next(clock))
    monkeypatch.setattr(m95.m94.engine, '_execute', expired)
    result = execute(tmp_path, monkeypatch, reviewed)
    assert result['status'] == 'stopped_no_retry'
    assert result['attempts'] == []
    assert (tmp_path/'private'/m95.AUTHORIZATION).exists()


def test_failed_transport_is_not_retried(tmp_path, monkeypatch, reviewed):
    result = execute(tmp_path, monkeypatch, reviewed, ValueError('PRIVATE ERROR'))
    assert len(result['attempts']) == 11
    assert len({a['asin'] for a in result['attempts'][1:]}) == 10
    assert all(a['status'] == 'failed' for a in result['attempts'][1:])
    assert 'PRIVATE ERROR' not in json.dumps(result)


@pytest.mark.parametrize('row', [None, [], {}, {'restrictions': []},
    {'restrictions': {'status':'succeeded','data':{}}},
    {'restrictions': {'status':'succeeded','data':{'restriction_count':False,'reason_codes':[]}}},
    {'restrictions': {'status':'succeeded','data':{'restriction_count':0,'reason_codes':[None]}}}])
def test_malformed_classification_is_unknown(row):
    assert m95_decision(row) == 'UNKNOWN'


def test_restriction_without_reason_is_other_restricted():
    row = dict(restrictions=dict(status='succeeded',data=dict(restriction_count=1,reason_codes=[])))
    assert m95_decision(row) == 'OTHER_RESTRICTED'
