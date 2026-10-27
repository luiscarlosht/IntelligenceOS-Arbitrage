"""Synthetic schema-profile tests; these do not certify Price API field paths."""
import csv
from dataclasses import replace
import json
import sqlite3

import pytest

from app import ebay_source_details as details
from app.authorized_imports import HEADERS
from app.connectors import SOURCE_FIELDS
from app.observations import canonical
from app import amazon_candidates as candidates
from tests.test_amazon_candidates import catalog, search


def inputs(tmp_path):
    source=tmp_path/'source.csv'
    with source.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=HEADERS+SOURCE_FIELDS);writer.writeheader()
        for i in range(10):
            writer.writerow(dict(retailer='eBay',name='Synthetic ten-piece title is not evidence',purchase_price='',
                source_provider='priceapi',retailer_item_id=str(100000000000+i),
                url=f'https://www.ebay.com/itm/{100000000000+i}',source_seller='Synthetic seller'))
    profile=dict(schema_verified=True,package_quantity_means_retail_packages=True,evidence_reference='SYNTHETIC schema only',
                 paths={key:['synthetic',key] for key in details.FIELDS})
    path=tmp_path/'profile.json';path.write_text(json.dumps(profile))
    return source,path,profile


def export(tmp_path,fields=None,*,item_id='100000000000',success=True,topic='product'):
    path=tmp_path/'saved.json'
    path.write_text(json.dumps(dict(job_id='synthetic-job',status='finished',results=[dict(
        query=dict(source='ebay',country='us',topic=topic,key='id',value=item_id),success=success,
        content=dict(synthetic=fields or {}))])))
    return path


def test_source_bound_plan_offline_ids_only_and_no_paid_budget(tmp_path,monkeypatch):
    source,_,_=inputs(tmp_path)
    monkeypatch.setattr('urllib.request.OpenerDirector.open',lambda *_:pytest.fail('Network'))
    plan,products,_=details.prepare_plan(source)
    assert len(products)==10 and len(plan['pending_listing_ids'])==10
    assert plan['proposed_job']['topic']=='product' and plan['proposed_job']['key']=='id'
    assert 'max_age' not in plan['proposed_job'] and 'timeout' not in plan['proposed_job']
    assert plan['budget']['general_tariff_default_credits']==10
    assert plan['budget']['provisional_credit_reserve']==20
    assert plan['budget']['executable_http_attempts']==0
    assert plan['budget']['paid_credits_authorized']==0
    assert not plan['execution_enabled'] and plan['live_requests']==0


def test_existing_usable_detail_excludes_id_before_new_request(tmp_path):
    source,path,_=inputs(tmp_path);saved=export(tmp_path,dict(brand='Synthetic'))
    plan,_,records=details.prepare_plan(source,(saved,),path)
    assert len(plan['pending_listing_ids'])==9
    assert '100000000000' not in plan['pending_listing_ids']
    assert records['100000000000']['fields']['brand']=='Synthetic'
    assert records['100000000000']['fields']['manufacturer'] is None


@pytest.mark.parametrize('mode',['search','failed','empty','no_profile'])
def test_unusable_saved_evidence_does_not_satisfy_detail_requirement(tmp_path,mode):
    source,path,_=inputs(tmp_path)
    saved=export(tmp_path,dict(brand='Synthetic') if mode!='empty' else {},
                 success=mode!='failed',topic='search_results' if mode=='search' else 'product')
    plan,_,_=details.prepare_plan(source,(saved,),None if mode=='no_profile' else path)
    assert len(plan['pending_listing_ids'])==10


def test_unknown_fields_stay_unknown_and_titles_are_ignored(tmp_path):
    _,_,profile=inputs(tmp_path)
    result=details.normalize_detail(dict(name='Brand UPC 036000291452 10 pieces red',synthetic={}),profile)
    assert all(v is None for v in result['fields'].values())
    assert not result['normalized_gtins'] and not result['identifier_contradiction']


def test_valid_identifiers_normalize_without_brand_model_or_count_inference(tmp_path):
    _,_,profile=inputs(tmp_path)
    result=details.normalize_detail(dict(synthetic=dict(brand='Maker',mpn='MPN-1',upc='036000291452',
        component_count=10,item_specifics={'Model':'not automatically mapped'},
        package_contents=['spoon','fork'],variation={'color':'red'},condition='Brand New',
        shipping_cost='0',shipping_currency='USD',destination_zip='76063')),profile)
    assert result['normalized_gtins']==['00036000291452']
    assert result['fields']['manufacturer'] is None and result['fields']['model'] is None
    assert result['fields']['package_quantity'] is None
    assert result['fields']['component_count']==10
    assert result['fields']['shipping_cost']=='0'
    assert result['fields']['shipping_conditions'] is None


def test_invalid_identifier_and_disagreeing_valid_identifiers_are_distinct(tmp_path):
    _,_,profile=inputs(tmp_path)
    invalid=details.normalize_detail(dict(synthetic=dict(upc='does not apply')),profile)
    assert invalid['invalid_fields']==['upc'] and not invalid['identifier_contradiction']
    result=details.normalize_detail(dict(synthetic=dict(upc='036000291452',ean='4006381333931')),profile)
    assert result['identifier_contradiction'] and len(result['normalized_gtins'])==2


@pytest.mark.parametrize('left,right,expected',[(None,2,'missing_evidence'),(1,None,'missing_evidence'),
    (1,2,'contradiction'),(1,1,'consistent'),('Maker',' maker ','consistent')])
def test_missing_vs_contradiction(left,right,expected):
    assert details.compare_field(left,right)==expected


def test_import_reuses_pipeline_keeps_ten_rows_and_originals(tmp_path):
    source,profile,_=inputs(tmp_path)
    saved=export(tmp_path,dict(manufacturer='Synthetic maker',model='M1',upc='036000291452',
                             package_contents=['spoon'],package_quantity=1))
    before={p:p.read_bytes() for p in (source,saved,profile)}
    outcome=details.import_saved(source,(saved,),profile,tmp_path/'output')
    assert len(outcome['rows'])==10 and outcome['live_requests']==0
    assert outcome['rows'][0]['status']=='saved_detail_imported'
    assert all(r['status']=='detail_missing' for r in outcome['rows'][1:])
    assert all(v=='missing_evidence' for v in outcome['rows'][0]['comparisons'].values())
    assert outcome['rows'][0]['enriched_source']['gtin']=='00036000291452'
    assert all(p.read_bytes()==b for p,b in before.items())
    with sqlite3.connect(tmp_path/'output/source-details.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM pilot_run_items').fetchone()[0]==10
        assert db.execute('SELECT sum(exact) FROM marketplace_matches').fetchone()[0]==0
        assert all(json.loads(r[0])['status']=='REJECT' for r in db.execute('SELECT result_json FROM pilot_run_items'))
    with pytest.raises(FileExistsError):details.import_saved(source,(saved,),profile,tmp_path/'output')


def test_unverified_profile_rejected_and_no_output(tmp_path):
    source,path,profile=inputs(tmp_path);profile['schema_verified']=False;path.write_text(json.dumps(profile))
    with pytest.raises(ValueError):details.import_saved(source,(),path,tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_explicit_profile_missing_path_stays_unknown(tmp_path):
    _,_,profile=inputs(tmp_path);profile['paths']['brand']=['absent']
    assert details.normalize_detail(dict(synthetic=dict(brand='Maker')),profile)['fields']['brand'] is None


def test_returned_url_mismatch_rejected(tmp_path):
    source,profile,_=inputs(tmp_path);saved=export(tmp_path,dict(brand='Maker'))
    document=json.loads(saved.read_text());document['results'][0]['content']['url']='https://www.ebay.com/itm/999999999999'
    saved.write_text(json.dumps(document))
    with pytest.raises(ValueError):details.prepare_plan(source,(saved,),profile)


def test_conflicting_saved_exports_require_selection(tmp_path):
    source,profile,_=inputs(tmp_path);first=export(tmp_path,dict(brand='Maker'))
    second=tmp_path/'second.json';second.write_bytes(first.read_bytes())
    document=json.loads(second.read_text());document['results'][0]['content']['synthetic']['brand']='Other'
    second.write_text(json.dumps(document))
    with pytest.raises(ValueError):details.prepare_plan(source,(first,second),profile)


def test_candidate_missing_count_and_contents_are_not_reported_as_contradictions(tmp_path):
    source,_,_=inputs(tmp_path)
    _,products,_=details.prepare_plan(source)
    evidence=candidates.detail_evidence(catalog(), 'B012345678',is_mock=True,secrets=())
    _,match=candidates.decide(products[0],candidates.parse_search(search()),evidence)
    assert 'Source package count unknown' in match.reasons
    assert 'Package contents evidence missing' in match.reasons
    assert not any('conflict' in reason or 'differ;' in reason for reason in match.reasons)
