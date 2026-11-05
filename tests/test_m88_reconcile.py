"""Synthetic offline reconciliation tests; no real credentials or vendor HTTP."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import pytest
from app import m88
from app.m88_state import read,write,sha
from app.m88_reconcile import classify,run,source_issues
from test_m88 import setup,Fake

REVIEW=dict(agent_review_completed=True,independent_human_signoff=False,screenshot_files_not_embedded=True)


def source():
    return dict(walmart_item_id='900001',upc='026000003049',brand='Example',model='M1',mpn='MPN1',
        selected_variant='Single',sellable_pack='Four transparent tape rolls',screenshot_reference='outputs/test.png',
        unresolved=[],conflicts=[])


def candidate():
    return dict(product=dict(asin='B000000001',brand='Example',model='M1',size='4 rolls',
        variation='Single',pack_quantity=1,gtin='00026000003049',identifiers=[
            dict(identifier_type='UPC',value='026000003049',normalized_gtin='00026000003049')],mapping_issues=[]))


def test_barcode_title_and_model_not_sufficient_without_scoped_pack_mpn_evidence():
    row=source();c=candidate();row_before=deepcopy(row);c_before=deepcopy(c)
    result=classify(row,c,REVIEW)
    assert result['classification']=='NEEDS_REVIEW' and not result['verified_exact_match']
    assert result['comparisons']['upc']['overlap']
    assert result['comparisons']['mpn']['amazon']=='UNKNOWN_NOT_RETAINED'
    assert result['agent_review_completed'] and not result['independent_human_signoff']
    assert row==row_before and c==c_before


def test_barcode_overlap_with_model_conflict_not_rejected_or_promoted():
    row=source();c=candidate();c['product']['model']='OTHER'
    result=classify(row,c,REVIEW)
    assert result['classification']=='NEEDS_REVIEW'
    assert any('model labels differ' in s for s in result['remaining_gaps'])


def test_ambiguous_barcodes_no_first_identifier_guess():
    c=candidate();c['product']['identifiers'].append(dict(identifier_type='UPC',value='012345678905',normalized_gtin='00012345678905'))
    result=classify(source(),c,REVIEW)
    assert result['classification']=='NEEDS_REVIEW'
    assert result['comparisons']['upc']['amazon_identifiers']['status']=='MULTIPLE_ALTERNATIVES'


def test_contradictory_barcode_and_model_can_reject():
    c=candidate();c['product'].update(model='OTHER',identifiers=[dict(identifier_type='UPC',value='012345678905',normalized_gtin='00012345678905')])
    assert classify(source(),c,REVIEW)['classification']=='REJECTED'


def test_uncertain_outer_barcode_basis_blocks_barcode_only_exclusion():
    row=source();row['unresolved']=['Separate outer-pack barcode']
    c=candidate();c['product'].update(model='OTHER',identifiers=[dict(identifier_type='UPC',value='012345678905',normalized_gtin='00012345678905')])
    assert classify(row,c,REVIEW)['classification']=='NEEDS_REVIEW'


def test_source_brand_conflict_not_arbitrarily_resolved():
    row=source();row.update(brand='Example or Other — CONFLICT',conflicts=['Brand conflict'])
    result=classify(row,candidate(),REVIEW)
    assert result['comparisons']['brand']['status']=='SOURCE_CONFLICT'
    assert result['classification']=='NEEDS_REVIEW'


def test_same_unit_contents_conflict_rejects_but_package_count_does_not():
    c=candidate();c['product']['size']='12 rolls'
    assert classify(source(),c,REVIEW)['classification']=='REJECTED'
    c['product']['size']='4 rolls';c['product']['pack_quantity']=1
    assert classify(source(),c,REVIEW)['classification']=='NEEDS_REVIEW'


@pytest.mark.parametrize('item,expected',[('13952053139','outer'),('721324153','0.5'),('37481849','Lined'),('47070933','Dispenser'),('711088244','dimensions')])
def test_required_exceptions_survive_even_if_not_repeated_in_new_lists(item,expected):
    row=source();row['walmart_item_id']=item
    assert any(expected in s for s in source_issues(row))


def operation(tmp_path,monkeypatch):
    plan,path,ledger,doc=setup(tmp_path,monkeypatch)
    m88.execute(path/'plan.json',sha(path/'plan.json'),transport=Fake(ledger,doc))
    batch=read(Path(plan['source_path']));rows=[]
    for r in batch['observations']:
        p=r['walmart_product'];row=source()
        row.update(walmart_item_id=p['walmart_item_id'],url=p['url'],observed_utc=datetime.now(timezone.utc).isoformat())
        rows.append(row)
    home=tmp_path/'enrichment';home.mkdir(mode=0o700)
    file=home/'new.json';write(file,dict(cohort='M88-Real-Six-Pilot',purchase_authorized=False,
        review=REVIEW,observations=rows,delivery_context='Sacramento, CA 95829'))
    return path,ledger,file,batch


def test_reports_preserve_prices_references_and_ledger_without_network(tmp_path,monkeypatch):
    path,ledger,file,batch=operation(tmp_path,monkeypatch)
    originals={p:p.read_bytes() for p in [file,ledger,path/'plan.json',*path.glob('receipt-*.json')]}
    import socket
    monkeypatch.setattr(socket,'socket',lambda *_a,**_k:pytest.fail('No network allowed'))
    out=tmp_path/'reports'
    summary=run(path/'plan.json',sha(path/'plan.json'),file,sha(file),out)
    assert summary['counts']['EXACT_MATCH']==0 and summary['cumulative_attempts']==7
    assert summary['additional_amazon_http_attempts']==0 and summary['products_with_supported_profitability']==0
    assert not summary['independent_human_signoff']
    updated=read(out/'enriched-batch.json')
    for before,after in zip(batch['observations'],updated['observations']):
        assert before['acquisition']==after['acquisition']
        assert after['walmart_product']['screenshot_reference']=='outputs/test.png'
        assert not after['walmart_product']['verified']
    assert all(p.read_bytes()==raw for p,raw in originals.items())
    assert (out/'comparison.xlsx').stat().st_mode & 0o777==0o600
    assert (out/'executive-summary.md').is_file()
    with pytest.raises(ValueError):run(path/'plan.json',sha(path/'plan.json'),file,sha(file),out)


@pytest.mark.parametrize('field,value',[('upc','026000003040'),('upc',26000003049),('url','https://example.test'),('model',None)])
def test_invalid_enrichment_fails_without_publication(tmp_path,monkeypatch,field,value):
    path,ledger,file,batch=operation(tmp_path,monkeypatch)
    value_json=read(file);value_json['observations'][0][field]=value;write(file,value_json,replace=True)
    baseline=ledger.read_bytes()
    with pytest.raises(ValueError):run(path/'plan.json',sha(path/'plan.json'),file,sha(file),tmp_path/'out')
    assert not (tmp_path/'out').exists() and ledger.read_bytes()==baseline


def test_receipt_and_enrichment_digest_drift_refused(tmp_path,monkeypatch):
    path,ledger,file,batch=operation(tmp_path,monkeypatch)
    with pytest.raises(ValueError):run(path/'plan.json',sha(path/'plan.json'),file,'0'*64,tmp_path/'out')
    write(path/'receipt-2.json',dict(corrupt=True),replace=True)
    with pytest.raises(ValueError):run(path/'plan.json',sha(path/'plan.json'),file,sha(file),tmp_path/'out')
