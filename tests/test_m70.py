"""Temporary synthetic scale fixtures only; real data never manufactured/enriched."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import csv
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app import m70,m70_discovery as discovery,m70_identity as model,m70_sources as sources,m70_plan as api_plan
from app.m65_intelligence import US,sha256
from app.observations import canonical,fingerprint
from test_m67 import cohort
from test_m69 import fixture as history_fixture,offline

NOW=datetime.now(timezone.utc).replace(microsecond=0)


def write(path,value):
    path.write_text(canonical(value)+'\n');path.chmod(0o600)


def upc(i):
    prefix=f'{i:011d}'
    digit=(10-sum(int(c)*(3 if n%2==0 else 1) for n,c in enumerate(reversed(prefix)))%10)%10
    return prefix+str(digit)


def product(i=1000):
    return dict(asin=f'B{i:09d}',marketplace=US,brand=f'ScaleBrand{i%60}',title=f'Synthetic fixture item {i}',
        category=f'Category{i%12}',product_type=f'TYPE{i%20}',upc=upc(i),model=f'MODEL{i}',size='small',
        variation=dict(color='blue',size='small'),pack_quantity=1,condition='new_new',observed_at=NOW.isoformat())


def spec(path,adapter='local_json',**kwargs):
    return dict(path=str(path),sha256=sources.file_hash(path),adapter=adapter,
                marketplace=US,permission_reference='local:synthetic-test-export',**kwargs)


def manifest(tmp_path,files):
    path=tmp_path/'sources.json';write(path,dict(schema=1,sources=files));return path


def observe(value,source='a',role='amazon',index=0):
    return model.observation(sources.local_record(value),role=role,
        reference='sha256:'+source*64+f':row:{index}',source_hash=source*64,source_class='local_json',
        observed_at=value.get('observed_at'))


def build(c,source_manifest,**kwargs):
    return discovery.build(source_manifest,c['store_path'],c['private'],c['path'],c['digest'],as_of=NOW,**kwargs)


def raw_item(i=1000):
    p=product(i)
    return dict(asin=p['asin'],summaries=[dict(marketplaceId=US,brand=p['brand'],itemName=p['title'],modelNumber=p['model'],
        packageQuantity=1,size='small',color='blue',browseClassification=dict(displayName=p['category']))],
        identifiers=[dict(marketplaceId=US,identifiers=[dict(identifierType='UPC',identifier=p['upc'])])],
        productTypes=[dict(marketplaceId=US,productType=p['product_type'])],
        relationships=[dict(marketplaceId=US,relationships=[])],attributes={})


def test_1200_scale_diversity_and_history_exclusions(history_fixture,tmp_path):
    c=history_fixture;rows=[product(i) for i in range(1000,2200)]
    legacy=json.loads(c['source'].read_text());old=set(c['inner']['asins'])|{f'B{i:09d}' for i in range(20)}
    rows += [r for r in legacy if r['asin'] in old]
    source=tmp_path/'large.json';write(source,rows)
    sm=manifest(tmp_path,[spec(source)])
    before={str(p):sha256(p) for p in (c['ledger'],c['store_path'],c['path'])}
    result=build(c,sm,shortlist=200)
    summary=result['summary']
    assert summary['discovered_asins']==1240
    assert summary['identity_complete']==1200 and summary['identity_complete_percent']>=80
    assert summary['brand_count']>=50 and summary['category_count']>=10
    assert summary['shortlist_count']==200
    assert len(summary['shortlist_brand_distribution'])>=50
    assert len(summary['shortlist_category_distribution'])>=10
    assert not set(result['selected_asins'])&set(result['history']['excluded_asins'])
    assert before=={str(p):sha256(p) for p in (c['ledger'],c['store_path'],c['path'])}
    assert all(not p['identity_verified'] and p['eligibility']=='UNKNOWN' for p in result['catalog'])
    assert summary['actual_amazon_requests']==summary['new_permanent_reservations']==0


def test_observed_identity_does_not_assert_verification_or_permission():
    merged=model.merge([observe(product())])
    assert merged['identity_complete'] and merged['identity_confidence_percent']==100
    assert not merged['identity_verified'] and merged['eligibility']=='UNKNOWN'
    assert merged['gtin']==upc(1000).zfill(14) and merged['upc_values']==[upc(1000)]
    assert all(e[0]['status']=='SOURCE_OBSERVED' for e in merged['field_provenance'].values())


def test_duplicate_asins_complementary_fields_preserve_provenance(tmp_path):
    a=product();b=product();a['model']=None;b['upc']=None
    source_a=tmp_path/'a.json';source_b=tmp_path/'b.json';write(source_a,[a]);write(source_b,[b])
    sm=manifest(tmp_path,[spec(source_b),spec(source_a),spec(source_a)])
    observations,coverage=sources.ingest(sm,page_size=1)
    assert len(observations)==2 and coverage['duplicate_source_files']==1
    merged=model.merge(observations)
    assert merged['identity_complete'] and not merged['identity_conflicts']
    assert merged['model']==product()['model'] and merged['gtin']==product()['upc'].zfill(14)
    assert len(merged['source_references'])==2
    assert model.merge(list(reversed(observations)))==merged


@pytest.mark.parametrize('field,other',[('upc',upc(9999)),('model','OTHER'),('size','large'),('pack_quantity',2),('brand','OTHER'),('product_type','OTHER')])
def test_cross_source_identity_conflicts_never_last_write_win(field,other):
    a=product();b=product();b[field]=other
    result=model.merge([observe(a,'a'),observe(b,'b')])
    target='gtin' if field=='upc' else field
    assert target in result['identity_conflicts'] and result[target] is None
    assert not result['identity_complete']
    assert model.merge([observe(b,'b'),observe(a,'a')])==result


@pytest.mark.parametrize('missing',['upc','model','pack_quantity','variation','condition','product_type'])
def test_missing_fields_never_generated(missing):
    p=product();p[missing]=None
    result=model.merge([observe(p)])
    target='gtin' if missing=='upc' else missing
    assert result[target] is None and target in result['missing_fields']
    assert not result['identity_complete']
    if missing=='pack_quantity':assert result['pack_quantity'] is None


@pytest.mark.parametrize('flag',['inferred_fields','generated_fields'])
def test_inferred_or_generated_identifiers_not_observed_or_verified(flag):
    p=product();p[flag]=['upc','model']
    result=model.merge([observe(p)])
    assert result['gtin'] is None and result['model'] is None and not result['upc_values']
    assert not result['identity_complete'] and not result['identity_verified']
    assert result['field_status']['gtin'] in ('INFERRED_UNVERIFIED','GENERATED_UNVERIFIED')


@pytest.mark.parametrize('change',[dict(generated_fields=['asin']),dict(inferred_fields=['asin']),dict(is_generated=True),dict(is_mock=True),dict(is_synthetic=True)])
def test_generated_asins_or_mock_rows_rejected(change):
    with pytest.raises(ValueError):observe(dict(product(),**change))


@pytest.mark.parametrize('field,value',[('upc','123'),('upc',123456789012),('pack_quantity',True),('pack_quantity',0),('pack_quantity','1.0')])
def test_invalid_identity_values_are_missing(field,value):
    p=product();p[field]=value;result=model.merge([observe(p)])
    target='gtin' if field=='upc' else field
    assert result[target] is None and result['field_status'][target]=='INVALID'


def test_gtin_does_not_invent_a_new_upc():
    p=product();p['gtin']=p.pop('upc').zfill(14)
    result=model.merge([observe(p)])
    assert result['gtin'] and not result['upc_values']


def test_raw_amazon_catalog_fields_scoped_and_no_condition_inference(tmp_path):
    path=tmp_path/'raw.json';write(path,dict(items=[raw_item()],observed_at=NOW.isoformat()))
    observations,_=sources.ingest(manifest(tmp_path,[spec(path,'amazon_catalog_items')]))
    result=model.merge(observations)
    assert result['product_type']=='TYPE0' and result['category']=='Category4'
    assert result['model']=='MODEL1000' and result['pack_quantity']==1
    assert result['catalog_identity_complete'] and result['condition'] is None
    assert not result['identity_complete']


def test_raw_unit_count_does_not_become_pack_quantity(tmp_path):
    item=raw_item();item['summaries'][0].pop('packageQuantity')
    item['summaries'][0]['numberOfItems']=24
    item['attributes']['unit_count']=[dict(value=24,marketplace_id=US)]
    path=tmp_path/'raw.json';write(path,dict(items=[item],observed_at=NOW.isoformat()))
    o,_=sources.ingest(manifest(tmp_path,[spec(path,'amazon_catalog_items')]))
    assert model.merge(o)['pack_quantity'] is None


def test_legacy_csv_adapter_keeps_gaps_and_preserves_real_fields(tmp_path):
    row=dict(asin='B000001000',title='Synthetic item',brand='Brand',category='kitchen',
        observed_at=NOW.isoformat(),model='MODEL',identifiers_json=canonical([dict(identifier_type='UPC',value=upc(1000))]),
        pack_information_json=canonical(dict(package_quantity=2)),variation_json=canonical(dict(summary='')))
    path=tmp_path/'legacy.csv'
    with path.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(row));w.writeheader();w.writerow(row)
    o,_=sources.ingest(manifest(tmp_path,[spec(path,'m63_csv')]))
    result=model.merge(o)
    assert result['pack_quantity']==2 and result['variation'] is None and result['size'] is None
    assert result['product_type'] is None and result['condition'] is None


def test_local_csv_paging_and_json_equivalence(tmp_path):
    rows=[dict(product(i),variation='blue') for i in range(1000,1025)]
    csv_path=tmp_path/'local.csv'
    with csv_path.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    a,c=sources.ingest(manifest(tmp_path,[spec(csv_path,'local_csv')]),page_size=7)
    assert len(a)==25 and c['sources'][0]['local_pages']==4
    assert all(o['fields']['pack_quantity']==[1] for o in a)
    assert len({o['source_reference'] for o in a})==25


def pages(partial=False):
    return dict(pages=[dict(query_reference='local:query-1',page_index=0,page_token=None,
        pagination=dict(nextToken='PRIVATE_CURSOR'),items=[raw_item(1000)],marketplace_id=US,http_status=200,observed_at=NOW.isoformat()),
        *([] if partial else [dict(query_reference='local:query-1',page_index=1,page_token='PRIVATE_CURSOR',pagination={},
        items=[raw_item(1001)],marketplace_id=US,http_status=200,observed_at=NOW.isoformat())])])


def test_saved_pagination_partial_export_does_not_fetch_next_page(tmp_path):
    path=tmp_path/'pages.json';write(path,pages(partial=True))
    o,c=sources.ingest(manifest(tmp_path,[spec(path,'amazon_catalog_pages')]))
    assert len(o)==1 and c['sources'][0]['partial_query_windows']==1
    assert 'PRIVATE_CURSOR' not in canonical(c)
    write(path,pages());o,c=sources.ingest(manifest(tmp_path,[spec(path,'amazon_catalog_pages')]))
    assert len(o)==2 and c['sources'][0]['partial_query_windows']==0


@pytest.mark.parametrize('bad',['token','index','repeat','http','scope','oversize'])
def test_broken_or_unauthorized_saved_pages_fail_closed(tmp_path,bad):
    data=pages();page=data['pages'][1]
    if bad=='token':page['page_token']='OTHER'
    elif bad=='index':page['page_index']=2
    elif bad=='repeat':page['pagination']['nextToken']='PRIVATE_CURSOR'
    elif bad=='http':page['http_status']=403
    elif bad=='scope':page['marketplace_id']='OTHER'
    else:page['items']=[raw_item()]*21
    path=tmp_path/'pages.json';write(path,data)
    with pytest.raises(ValueError):sources.ingest(manifest(tmp_path,[spec(path,'amazon_catalog_pages')]))


def test_retailer_without_asin_is_not_a_discovered_amazon_product(tmp_path):
    p=product();p.pop('asin')
    path=tmp_path/'retailer.json';write(path,[p])
    o,c=sources.ingest(manifest(tmp_path,[spec(path,'retailer_json')]))
    assert len(o)==1 and o[0]['role']=='retailer' and o[0]['asin'] is None


def test_exact_retailer_matching_never_grants_eligibility():
    a=model.merge([observe(product(),'a')]);b=model.merge([observe(product(),'b','retailer')])
    match=model.exact_match(a,b)
    assert match['status']=='EXACT_IDENTITY_OBSERVED' and not match['selling_permission_confirmed']
    b['pack_quantity']=2
    assert model.exact_match(a,b)['status']=='MISMATCH'
    b['pack_quantity']=None
    assert model.exact_match(a,b)['status']=='UNKNOWN'
    b=model.merge([observe(product(),'a','retailer')])
    assert model.exact_match(a,b)['status']=='UNKNOWN'  # same-file comparison isn't independent evidence


def test_retailer_cannot_fill_missing_amazon_identity(history_fixture,tmp_path):
    a=product();a['model']=None;b=product()
    pa=tmp_path/'a.json';pb=tmp_path/'b.json';write(pa,[a]);write(pb,[b])
    result=build(history_fixture,manifest(tmp_path,[spec(pa),spec(pb,'retailer_json')]))
    assert result['summary']['discovered_asins']==1 and result['catalog'][0]['model'] is None
    assert result['catalog'][0]['retailer_match_status']=='UNKNOWN'


def test_deterministic_ranking_and_duplicate_rates(history_fixture,tmp_path):
    data=[product(i) for i in range(1000,1200)]
    path=tmp_path/'data.json';write(path,data+[data[0]])
    sm=manifest(tmp_path,[spec(path)])
    a=build(history_fixture,sm,shortlist=100);b=build(history_fixture,sm,shortlist=100)
    assert a==b and a['source_coverage']['duplicate_asin_observations']==1
    assert a['source_coverage']['duplicate_asin_rate']==1/201
    assert len(a['selected_asins'])==100 and len(set(a['selected_asins']))==100


def test_conflicting_sources_are_not_shortlisted(history_fixture,tmp_path):
    a=product();b=product();b['model']='OTHER'
    pa=tmp_path/'a.json';pb=tmp_path/'b.json';write(pa,[a]);write(pb,[b])
    result=build(history_fixture,manifest(tmp_path,[spec(pa),spec(pb)]))
    assert result['summary']['conflict_asins']==1 and not result['selected_asins']
    assert result['catalog'][0]['model'] is None


def test_empty_or_rejected_sources_never_pad_catalog(history_fixture,tmp_path):
    path=tmp_path/'empty.json';write(path,[dict(product(),asin='INVALID')])
    result=build(history_fixture,manifest(tmp_path,[spec(path)]))
    assert result['summary']['discovered_asins']==0 and result['summary']['shortlist_count']==0
    assert result['source_coverage']['sources'][0]['rejected']==1


def test_source_permission_scope_hash_and_unknown_adapters_fail_closed(tmp_path):
    path=tmp_path/'data.json';write(path,[product()])
    for change in (dict(permission_reference=''),dict(marketplace='OTHER'),dict(sha256='0'*64),dict(adapter='browser_scraper')):
        sm=manifest(tmp_path,[dict(spec(path),**change)])
        with pytest.raises(ValueError):sources.ingest(sm)
    private=tmp_path/'credentials.json';write(private,dict(client_secret='PRIVATESECRET'))
    with pytest.raises(ValueError):sources.file_hash(private)


def test_source_privacy_redacts_private_context_and_nested_variation(tmp_path):
    p=product();p['model']='PRIVATESELLER';p['variation']=dict(color='PRIVATESELLER')
    path=tmp_path/'data.json';write(path,dict(records=[p],seller_id='PRIVATESELLER',client_secret='PRIVATESECRET'))
    o,c=sources.ingest(manifest(tmp_path,[spec(path)]))
    result=model.merge(o);text=canonical(dict(identity=result,coverage=c))
    assert 'PRIVATESELLER' not in text and 'PRIVATESECRET' not in text
    assert result['model'] is None and result['variation'] is None


@pytest.mark.parametrize('limit,value',[('maximum_observations',1),('maximum_asins',1)])
def test_local_memory_budget_fail_closed(tmp_path,limit,value):
    path=tmp_path/'data.json';write(path,[product(1000),product(1001)])
    with pytest.raises(ValueError):sources.ingest(manifest(tmp_path,[spec(path)]),**{limit:value})


def test_future_api_plan_scenarios_and_configured_usage_limits(monkeypatch):
    monkeypatch.setenv('AMAZON_RATE_SEARCHCATALOGITEMS','.5')
    p=api_plan.plan()
    assert not p['executable'] and not p['execution_authorized'] and p['actual_requests']==0
    assert p['budget']['total']==251 and p['budget']['restrictions']==0 and p['budget']['retries']==0
    assert [s['estimated_keyword_pages'] for s in p['scenarios']]==[50,100,200]
    assert p['configured_limits']['search_rps_cap']==.5 and p['configured_limits']['effective_search_rps']==.25
    assert p['configured_limits']['account_usage_plan']=='UNKNOWN_NO_LIVE_PROBE'


@pytest.mark.parametrize('kwargs',[dict(page_size=21),dict(maximum_requests=250),dict(keyword_budget=201,maximum_requests=252),
    dict(identifier_budget=-1),dict(query_slots=0),dict(pages_per_query=51),dict(page_size=True),dict(maximum_requests=20000)])
def test_plan_budget_and_service_limits(kwargs):
    with pytest.raises(ValueError):api_plan.plan(**kwargs)


def test_page_count_depends_on_page_size_not_fixed_50():
    p=api_plan.plan(query_slots=1,pages_per_query=100,page_size=10,keyword_budget=100,identifier_budget=0,maximum_requests=101)
    assert p['maximum_pages_per_query']==100 and p['theoretical_record_capacity_before_overlap']==1000


def test_offline_pagination_projection_enforces_budget_cursors_and_no_retries():
    budget=api_plan.plan(query_slots=1,pages_per_query=2,keyword_budget=2,identifier_budget=0,maximum_requests=3)['budget']
    pp=[dict(kind='keyword',query_id='q',page_token=None,next_token='a'),dict(kind='keyword',query_id='q',page_token='a',next_token=None)]
    p=api_plan.project_pages(pp,budget,per_query_limit=2)
    assert p['projected_total_slots']==3 and p['actual_requests']==0 and p['incomplete_queries']==0
    with pytest.raises(ValueError):api_plan.project_pages(pp+[dict(kind='keyword',query_id='other',page_token=None)],budget)
    with pytest.raises(ValueError):api_plan.project_pages([pp[0],dict(pp[1],page_token='WRONG')],budget)
    with pytest.raises(ValueError):api_plan.project_pages([pp[0],dict(pp[1],next_token='a')],budget)


def test_export_all_requested_files_no_overwrite(history_fixture,tmp_path):
    path=tmp_path/'data.json';write(path,[product(1000),product(1001)])
    report=build(history_fixture,manifest(tmp_path,[spec(path)]));out=tmp_path/'out'
    m70.export(report,out)
    required={'M70_catalog_1000.csv','M70_identity_quality.csv','M70_candidate_ranking.csv','M70_exclusions.csv','M70_source_coverage.json','M70_summary.json'}
    assert required<={p.name for p in out.iterdir()}
    with (out/'M70_catalog_1000.csv').open(encoding='utf-8-sig') as f:assert len(list(csv.DictReader(f)))==2
    with pytest.raises(FileExistsError):m70.export(report,out)
    assert all(p.stat().st_mode&0o777==0o600 for p in out.iterdir())


def test_m69_backward_compatible_outputs_and_original_records_unchanged(history_fixture,tmp_path):
    from test_m69 import analyze,protected
    c=history_fixture;before=protected(c);legacy,h=analyze(c)
    path=tmp_path/'data.json';write(path,[product()])
    build(c,manifest(tmp_path,[spec(path)]))
    after,h2=analyze(c)
    assert legacy==after and h==h2 and protected(c)==before


def test_cli_no_execute_args_and_redacted_errors(tmp_path,capsys):
    for action in ('execute','run','authenticate','purchase','listing','restrictions'):
        with pytest.raises(SystemExit):m70.main([action,'--output',str(tmp_path/'out')])
    with pytest.raises(SystemExit):m70.main(['plan','--seller-id','PRIVATESELLER','--output',str(tmp_path/'out')])
    assert 'PRIVATESELLER' not in capsys.readouterr().err
    assert m70.main(['plan','--maximum-requests','1','--output',str(tmp_path/'out')])==2
    assert not (tmp_path/'out').exists()


def test_help_and_planning_without_live_modules(tmp_path):
    script="import sys,socket; sys.modules['app.amazon_pilot']=None; sys.modules['app.m67_execution']=None; sys.modules['app.m67_transport']=None; socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('NETWORK')); from app.m70 import main; main(['plan','--output',sys.argv[1]])"
    r=subprocess.run([sys.executable,'-c',script,str(tmp_path/'plan.json')],capture_output=True,text=True)
    assert r.returncode==0 and json.loads((tmp_path/'plan.json').read_text())['executable'] is False


def test_nested_generated_identifiers_are_never_observed():
    row=product();row['catalog']=dict(asin=row['asin'],upc=row.pop('upc'),model=row.pop('model'),
        generated_fields=['gtin','model'])
    p=model.merge([observe(row)])
    assert p['gtin'] is None and p['model'] is None


def test_csv_adapter_preserves_text_identifiers(tmp_path):
    import csv
    row=product();row['variation']='blue';path=tmp_path/'products.csv'
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(row));writer.writeheader();writer.writerow(row)
    m=tmp_path/'csv-manifest.json'
    write(m,dict(schema=1,sources=[dict(path=path.name,sha256=sources.file_hash(path),adapter='local_csv',
        permission_reference='manual:test-only',marketplace=US)]))
    rows,_=sources.ingest(m)
    assert model.merge(rows)['gtin']==upc(1000).zfill(14)


def test_cli_has_no_execution_and_fails_closed(tmp_path,capsys):
    assert m70.main(['plan','--output',str(tmp_path/'plan.json')])==0
    assert m70.main(['plan','--maximum-requests','2','--output',str(tmp_path/'bad.json')])==2
    assert not (tmp_path/'bad.json').exists()
    for action in ('execute','authenticate','reserve','eligibility'):
        with pytest.raises(SystemExit):m70.main([action,'--output',str(tmp_path/'bad.json')])
    assert m70.main(['analyze','--output',str(tmp_path/'bad')])==2
