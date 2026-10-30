"""Synthetic transport only: never use stored credentials or remote endpoints."""
import csv
from dataclasses import replace
from datetime import datetime, timezone
import json
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest

from app import amazon_candidates as stage
from app import amazon_pilot as pilot
from app.amazon_catalog import parse_catalog, MARKETPLACE
from app.authorized_imports import HEADERS, validate
from app.connectors import SOURCE_FIELDS
from app.observations import canonical
from app.provider_runtime import ProviderFailure

ASIN = 'B012345678'
OTHER = 'B087654321'
CREDS = dict(client_id='synthetic-client', client_secret='synthetic-secret', refresh_token='synthetic-refresh')


def catalog(asin=ASIN):
    return dict(asin=asin, summaries=[dict(marketplaceId=MARKETPLACE, itemName='Synthetic kitchen set',
        manufacturer='Synthetic maker', modelNumber='Model 1', packageQuantity=1,
        itemClassification='BASE_PRODUCT', color='gray')],
        identifiers=[dict(marketplaceId=MARKETPLACE, identifiers=[dict(identifierType='UPC', identifier='036000291452')])],
        relationships=[dict(marketplaceId=MARKETPLACE, relationships=[])],
        attributes=dict(included_components=[dict(marketplace_id=MARKETPLACE, value='spoon')],
                        number_of_items=[dict(marketplace_id=MARKETPLACE, value=1)]))


def search(asins=(ASIN,), **extra):
    return dict(numberOfResults=len(asins), items=[dict(asin=a, summaries=[dict(marketplaceId=MARKETPLACE,
                itemName='Synthetic kitchen set')]) for a in asins], **extra)


def source(tmp_path, *, exact=False):
    path = tmp_path/'source.csv'
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS+SOURCE_FIELDS)
        writer.writeheader()
        for i in range(10):
            row = dict(retailer='eBay', name='Synthetic kitchen set', url=f'https://www.ebay.com/itm/{100000000000+i}',
                purchase_price='', availability='unknown', provenance='Synthetic source', source_provider='priceapi',
                retailer_item_id=str(100000000000+i), source_seller='Synthetic seller', source_condition='Brand New')
            if exact:
                row.update(gtin='036000291452', package_quantity=1, variation='{"color": "gray"}',
                           source_package_contents=canonical(['spoon']))
            writer.writerow(row)
    return path


def run(tmp_path, responses=None, *, exact=False):
    src = source(tmp_path, exact=exact)
    manifest, _ = stage.source_plan(src)
    calls = []
    def transport(request):
        calls.append(request)
        if len(calls)==1:
            return dict(access_token='synthetic-access', token_type='bearer')
        if responses:
            return responses(request, len(calls))
        return catalog() if urlsplit(request.full_url).path.endswith('/'+ASIN) else search()
    outcome = stage.execute(src, manifest, tmp_path/'private', transport=transport,
        credential_loader=lambda _: CREDS, is_mock=True, sleep=lambda _: None)
    return src, manifest, outcome, calls


def test_21_attempt_cap_requests_and_every_source_row(tmp_path):
    src, manifest, result, calls = run(tmp_path)
    assert len(calls)==21 and result['status']=='succeeded'
    assert [r['ordinal'] for r in result['rows']]==list(range(1,11))
    assert all(r['status']=='candidate_unverified' and not r['exact'] for r in result['rows'])
    for req in calls[1:]:
        assert req.get_method()=='GET'
        assert '/catalog/2022-04-01/items' in req.full_url
        params = parse_qs(urlsplit(req.full_url).query)
        assert params['marketplaceIds']==[MARKETPLACE]
        assert 'pageToken' not in params
    assert all(parse_qs(urlsplit(r.full_url).query)['pageSize']==['10'] for r in calls[1::2])
    with sqlite3.connect(next((tmp_path/'private').glob('*.sqlite3'))) as db:
        assert db.execute('SELECT count(*) FROM pilot_run_items').fetchone()[0]==10
        assert db.execute('SELECT sum(exact) FROM marketplace_matches').fetchone()[0]==0
        payload = json.loads(db.execute('SELECT payload_json FROM source_observations ORDER BY id LIMIT 1').fetchone()[0])
        assert payload['source_context']['source_seller']=='Synthetic seller'
        assert payload['source_context']['source_shipping_cost'] is None
    report = next((tmp_path/'private').glob('*.json')).read_text()
    assert all(secret not in report for secret in (*CREDS.values(), 'synthetic-access'))
    assert src.read_bytes()
    assert result['live_requests']==0  # All transport calls are synthetic.


def test_empty_results_skip_all_details(tmp_path):
    _, _, result, calls = run(tmp_path, lambda *_: search(()))
    assert len(calls)==11 and all(r['status']=='unmatched' for r in result['rows'])


def test_ambiguous_and_paginated_preserved_no_pagination(tmp_path):
    def respond(req, _):
        if urlsplit(req.full_url).path.endswith('/'+ASIN): return catalog()
        doc = search((ASIN,OTHER), pagination=dict(nextToken='never-persist-this-token'))
        doc['numberOfResults']=30
        return doc
    _, _, result, calls = run(tmp_path, respond, exact=True)
    assert len(calls)==21
    assert all(r['status']=='ambiguous' and not r['exact'] for r in result['rows'])
    assert all([c['asin'] for c in r['search']['candidates']]==[ASIN,OTHER] for r in result['rows'])
    assert 'never-persist-this-token' not in canonical(result)


def test_exact_needs_identifier_package_contents_and_variation(tmp_path):
    _, _, result, _ = run(tmp_path, exact=True)
    assert all(r['exact'] for r in result['rows'])
    with sqlite3.connect(next((tmp_path/'private').glob('*.sqlite3'))) as db:
        assert db.execute('SELECT sum(exact) FROM marketplace_matches').fetchone()[0]==10
        assert all(json.loads(r[0])['status']=='REJECT' for r in db.execute('SELECT result_json FROM pilot_run_items'))


@pytest.mark.parametrize('field,value', [('gtin',''),('package_quantity',2),('variation',''),
                                       ('source_package_contents','["fork"]')])
def test_missing_or_mismatched_evidence_blocks_exact(tmp_path, field, value):
    src = source(tmp_path, exact=True)
    _, products = stage.source_plan(src)
    product = products[0]
    if field=='source_package_contents':
        product=replace(product, source_context={**product.source_context, field:value})
    else: product=replace(product, **{field:value})
    detail=stage.detail_evidence(catalog(),ASIN,is_mock=True,secrets=())
    assert not stage.decide(product,stage.parse_search(search()),detail)[1].exact


def test_asin_hint_and_title_alone_never_exact(tmp_path):
    _, products = stage.source_plan(source(tmp_path))
    product=replace(products[0],asin_hint=ASIN,package_quantity=1,variation='{"color": "gray"}',
        source_context={**products[0].source_context,'source_package_contents':canonical(['spoon'])})
    assert not stage.decide(product,stage.parse_search(search()),
                           stage.detail_evidence(catalog(),ASIN,is_mock=True,secrets=()))[1].exact


@pytest.mark.parametrize('failure_at', [1,2,3,20,21])
def test_failure_stops_no_retry_and_preserves_all_rows(tmp_path,failure_at):
    src=source(tmp_path); manifest,_=stage.source_plan(src); calls=[]
    def transport(req):
        calls.append(req)
        if len(calls)==failure_at: raise RuntimeError('synthetic-secret')
        if len(calls)==1: return dict(access_token='synthetic-access',token_type='bearer')
        return catalog() if urlsplit(req.full_url).path.endswith('/'+ASIN) else search()
    result=stage.execute(src,manifest,tmp_path/'private',transport=transport,
        credential_loader=lambda _:CREDS,is_mock=True,sleep=lambda _:None)
    assert len(calls)==failure_at and result['status']=='failed_no_retry'
    assert len(result['rows'])==10
    assert 'synthetic-secret' not in canonical(result)
    with sqlite3.connect(next((tmp_path/'private').glob('*.sqlite3'))) as db:
        assert db.execute('SELECT count(*) FROM pilot_run_items').fetchone()[0]==10
    with pytest.raises(FileExistsError):
        stage.execute(src,manifest,tmp_path/'private',transport=lambda _:pytest.fail('Replay'),
                      credential_loader=lambda _:pytest.fail('Credential replay'))


def test_manifest_tampering_fails_before_private_directory_or_credentials(tmp_path,monkeypatch):
    src=source(tmp_path); manifest,_=stage.source_plan(src)
    manifest['limits']['total']=22
    monkeypatch.setattr(pilot,'private_directory',lambda _:pytest.fail('Private access'))
    with pytest.raises(ValueError): stage.execute(src,manifest)


def test_source_change_invalidates_manifest(tmp_path,monkeypatch):
    src=source(tmp_path); manifest,_=stage.source_plan(src);src.write_text(src.read_text()+'\n')
    monkeypatch.setattr(pilot,'private_directory',lambda _:pytest.fail('Private access'))
    with pytest.raises(ValueError):stage.execute(src,manifest)


def test_arbitrary_asin_detail_and_mismatch():
    assert parse_catalog(catalog(OTHER),expected_asin=OTHER,is_mock=True).value.asin==OTHER
    with pytest.raises(ProviderFailure):parse_catalog(catalog(OTHER),expected_asin=ASIN,is_mock=True)
    with pytest.raises(ProviderFailure):parse_catalog(catalog(),expected_asin='../invalid',is_mock=True)


@pytest.mark.parametrize('change', ['bad_asin','wrong_marketplace','oversize','bad_count','bad_token'])
def test_search_validation(change):
    doc=search()
    if change=='bad_asin':doc['items'][0]['asin']='../invalid'
    if change=='wrong_marketplace':doc['items'][0]['summaries'][0]['marketplaceId']='wrong'
    if change=='oversize':doc['items']*=11;doc['numberOfResults']=11
    if change=='bad_count':doc['numberOfResults']=True
    if change=='bad_token':doc['pagination']=dict(nextToken=42)
    with pytest.raises(ProviderFailure):stage.parse_search(doc)


def test_duplicate_asins_do_not_create_false_ambiguity():
    result=stage.parse_search(search((ASIN,ASIN)))
    assert len(result['candidates'])==1 and result['complete']


def test_plan_cli_no_credentials_or_network(tmp_path,monkeypatch):
    src=source(tmp_path); manifest=tmp_path/'manifest.json'
    monkeypatch.setattr('sys.argv',['amazon_candidates','plan','--source',str(src),'--manifest',str(manifest)])
    monkeypatch.setattr(pilot,'private_directory',lambda _:pytest.fail('Private access'))
    monkeypatch.setattr(pilot,'load_credentials',lambda _:pytest.fail('Credentials'))
    monkeypatch.setattr(pilot,'request_json',lambda _:pytest.fail('Network'))
    assert stage.main()==0
    assert json.loads(manifest.read_text())['limits']['total']==21


def test_legacy_generic_headers_remain_valid(tmp_path):
    for size in (13,16):
        path=tmp_path/f'legacy-{size}.csv'
        with path.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=HEADERS+SOURCE_FIELDS[:size]);writer.writeheader()
            writer.writerow(dict(retailer='eBay',name='Synthetic',purchase_price=''))
        assert not any(x.startswith('Header') for x in validate(path,datetime.now(timezone.utc)))


@pytest.mark.parametrize('attribute,value', [('number_of_items',2),('color','blue'),
                                           ('material','wood'),('unit_count',dict(value=10))])
def test_conflicting_or_unverified_detail_attributes_block_exact(tmp_path,attribute,value):
    _, products=stage.source_plan(source(tmp_path,exact=True))
    doc=catalog();doc['attributes'][attribute]=[dict(marketplace_id=MARKETPLACE,value=value)]
    detail=stage.detail_evidence(doc,ASIN,is_mock=True,secrets=())
    assert not stage.decide(products[0],stage.parse_search(search()),detail)[1].exact


def test_wrong_detail_asin_preserves_failed_row_and_remaining_rows(tmp_path):
    def respond(req,_):
        return catalog(OTHER) if urlsplit(req.full_url).path.endswith('/'+ASIN) else search()
    _,_,result,calls=run(tmp_path,respond)
    assert len(calls)==3 and result['status']=='failed_no_retry'
    assert result['rows'][0]['status']=='failed'
    assert len(result['rows'][0]['search']['candidates'])==1
    assert all(r['status']=='not_attempted' for r in result['rows'][1:])


def test_deadline_stops_before_first_transport_preserves_rows(tmp_path):
    src=source(tmp_path);manifest,_=stage.source_plan(src);ticks=iter([0,301,301])
    result=stage.execute(src,manifest,tmp_path/'private',transport=lambda _:pytest.fail('Deadline'),
        credential_loader=lambda _:CREDS,is_mock=True,monotonic=lambda:next(ticks),sleep=lambda _:None)
    assert result['status']=='failed_no_retry' and not result['attempts'] and len(result['rows'])==10


def test_credentials_failure_preserves_rows_and_no_http(tmp_path):
    src=source(tmp_path);manifest,_=stage.source_plan(src)
    def denied(_):raise PermissionError('synthetic-secret')
    result=stage.execute(src,manifest,tmp_path/'private',transport=lambda _:pytest.fail('HTTP'),
                         credential_loader=denied,is_mock=True)
    assert len(result['rows'])==10 and not result['attempts']
    assert 'synthetic-secret' not in canonical(result)


@pytest.mark.parametrize('mode,status,code,attempt_status', [
    ('http', 429, None, 'request_failed'),
    ('parser', 200, 'CATALOG_ASIN_MISMATCH', 'parser_rejected'),
    ('transport', None, None, 'request_failed'),
    ('matching', None, None, 'response_received'),
])
def test_candidate_failure_diagnostics_distinguish_response_parser_and_transport(
        tmp_path, monkeypatch, mode, status, code, attempt_status):
    from app.amazon_diagnostics import AmazonFailure, ResponseDocument
    src = source(tmp_path); manifest, _ = stage.source_plan(src); calls = []
    def transport(request):
        calls.append(request)
        if len(calls) == 1:
            return dict(access_token='synthetic-access', token_type='bearer')
        if len(calls) == 2:
            return ResponseDocument(search(), 200)
        if mode == 'http':
            raise AmazonFailure('synthetic-secret', reason='http_error', http_status=429,
                                codes=('QuotaExceeded', 'synthetic-secret'))
        if mode == 'transport':
            raise TimeoutError('synthetic-secret')
        return ResponseDocument(catalog(OTHER if mode == 'parser' else ASIN), 200)
    if mode == 'matching':
        monkeypatch.setattr(stage, 'decide', lambda *_: (_ for _ in ()).throw(ValueError('synthetic-secret')))
    result = stage.execute(src, manifest, tmp_path/'private', transport=transport,
        credential_loader=lambda _:CREDS, is_mock=True, sleep=lambda _:None)
    assert len(calls) == 3 and result['status'] == 'failed_no_retry'
    assert result['attempts'][1]['status'] == 'response_received'
    attempt = result['attempts'][-1]
    assert attempt['status'] == attempt_status
    assert result['failure']['http_status'] == status
    assert result['failure'].get('validation_code') == code
    if mode == 'http':
        assert attempt['outcome'] == 'http_error_response'
        assert attempt['failure']['amazon_error_codes'] == ['OTHER', 'QuotaExceeded']
    elif mode == 'transport':
        assert attempt['outcome'] == 'uncertain'
    elif mode == 'parser':
        assert attempt['outcome'] == 'response_received' and attempt['http_status'] == 200
    assert 'synthetic-secret' not in canonical(result)
    assert all(r['status'] == 'not_attempted' for r in result['rows'][1:])
    with pytest.raises(FileExistsError):
        stage.execute(src, manifest, tmp_path/'private', credential_loader=lambda _:pytest.fail('Replay'))


@pytest.mark.parametrize('fault_at,expected_stage', [(5,'search_response_checkpoint'),(6,'search_checkpoint')])
def test_checkpoint_failure_does_not_relabel_completed_response_as_parser_failure(
        tmp_path,monkeypatch,fault_at,expected_stage):
    calls=0
    original=stage.os.fsync
    def fail_once(fd):
        nonlocal calls
        calls+=1
        if calls==fault_at:raise OSError('synthetic-secret')
        return original(fd)
    monkeypatch.setattr(stage.os,'fsync',fail_once)
    _,_,result,requests=run(tmp_path)
    assert result['status']=='failed_no_retry' and len(requests)==2
    assert result['attempts'][-1]['status']=='response_received'
    assert result['failure']['stage']==expected_stage
    assert 'validation_code' not in result['failure']
    assert 'synthetic-secret' not in canonical(result)
