"""Offline identity triage, synthetic test data only."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import pytest
from app import m88
from app.m88_state import read,write,sha,ledger
from app.m88_identity import analyze,barcode_evidence,compare,content_counts,build
from test_m88 import setup,Fake


def pair():
    source=dict(source_candidate_id='test:1',walmart_product=dict(title='Test transparent tape',
        pack_description='3/4 x 1000 in; 4 rolls; single pack',gtin='UNKNOWN',brand='UNKNOWN',
        model='UNKNOWN',size='UNKNOWN',variation='UNKNOWN',pack_quantity=4,verified=False,
        pack_quantity_basis='Content count, retail pack unverified',walmart_item_id='900001',url='https://www.walmart.com/ip/900001'))
    candidate=dict(product=dict(asin='B000000001',title='Test Transparent Tape, 4 Rolls',brand='Test',
        model='T4',size='3/4 x 1000 in; 4 rolls',variation='Clear',gtin='00026000003049',
        identifiers=[dict(identifier_type='UPC',value='026000003049',normalized_gtin='00026000003049')],
        pack_quantity=1,mapping_issues=[]),identity=dict(exact=False,missing=['retailer.valid_gtin'],mismatches=[]))
    return source,candidate


def test_retains_package_bases_without_false_equivalence():
    source,candidate=pair();before=deepcopy((source,candidate))
    result=compare(source,candidate,1)
    assert result['plausible_textual_lead']
    assert result['evidence_availability']['amazon_package_quantity']==1
    assert result['textual_clues']['source_contents_counts']==[4]
    assert 'gtin' in result['identity_gaps']['walmart_missing_fields']
    assert not result['verified_exact_match'] and not result['purchase_authorized']
    assert (source,candidate)==before


def test_ambiguous_barcodes_never_select_first():
    source,candidate=pair()
    candidate['product']['identifiers'].append(dict(identifier_type='UPC',value='012345678905',normalized_gtin='00012345678905'))
    result=barcode_evidence(candidate['product'])
    assert result['status']=='MULTIPLE_ALTERNATIVES'
    assert len(result['distinct_canonical_gtins'])==2
    assert not result['source_equivalence_verified']


def test_invalid_barcode_visible_not_usable():
    source,candidate=pair();candidate['product']['identifiers'][0]['value']='026000003040'
    result=barcode_evidence(candidate['product'])
    assert result['status']=='MISSING' and len(result['invalid_identifiers'])==1


def test_retention_gaps_distinct_from_actual_absence():
    source,candidate=pair();result=compare(source,candidate,1)
    assert result['evidence_availability']['model']
    assert result['evidence_availability']['manufacturer_part_number']=='NOT_RETAINED_IN_SAVED_RECEIPTS'
    assert result['evidence_availability']['structured_dimensions']=='NOT_RETAINED_IN_SAVED_RECEIPTS'


@pytest.mark.parametrize('change',['count','brand','family','bundle','size'])
def test_conflicting_text_downgrades_lead_without_changing_facts(change):
    source,candidate=pair()
    if change=='count':candidate['product'].update(title='Test Transparent Tape, 12 Rolls',size='12 rolls')
    if change=='brand':candidate['product']['brand']='OtherBrand'
    if change=='family':candidate['product']['title']='Test Magic Invisible Tape, 4 Rolls'
    if change=='bundle':candidate['product']['title']+=' Pack of 2'
    if change=='size':candidate['product']['size']='2 in; 36 in'
    result=compare(source,candidate,1)
    assert result['warnings'] and not result['plausible_textual_lead']
    assert not result['verified_exact_match']


def test_sheets_per_pad_conflict():
    source,candidate=pair()
    source['walmart_product'].update(title='Test Super Sticky Notes',pack_description='3 x 3 in; 4 pads; 90 sheets per pad')
    candidate['product'].update(title='Test Super Sticky Notes 4 pads, 50 sheets per pad',size='3 x 3 in')
    assert 'Textual sheets-per-pad conflict' in compare(source,candidate,1)['warnings']


def test_same_title_never_promotes_identity():
    source,candidate=pair();candidate['product']['title']=source['walmart_product']['title']
    result=compare(source,candidate,1)
    assert not result['verified_exact_match'] and result['identity_gaps']['walmart_review_missing']


def test_counts_are_contents_not_outer_bundle():
    assert content_counts('AA; 8/PK')=={8}
    assert content_counts('8 Count (Pack of 2)')=={8}
    assert content_counts('3 x 3 in; 4 pads; 90 sheets per pad')=={4}


def operation(tmp_path,monkeypatch):
    plan,path,accounting,doc=setup(tmp_path,monkeypatch)
    m88.execute(path/'plan.json',sha(path/'plan.json'),transport=Fake(accounting,doc))
    return plan,path,accounting


def test_exclusive_offline_report_and_original_preservation(tmp_path,monkeypatch):
    plan,path,accounting=operation(tmp_path,monkeypatch)
    original={f:f.read_bytes() for f in path.iterdir() if f.is_file()}
    baseline=accounting.read_bytes();source=Path(plan['source_path']).read_bytes()
    import socket
    monkeypatch.setattr(socket,'socket',lambda *_a,**_k:pytest.fail('Offline phase must not connect'))
    out=tmp_path/'identity-report'
    result=analyze(path/'plan.json',sha(path/'plan.json'),out)
    assert len(result['products'])==6 and result['verified_exact_matches']==0
    assert result['additional_http_attempts']==0
    assert all(f.read_bytes()==v for f,v in original.items())
    assert accounting.read_bytes()==baseline and Path(plan['source_path']).read_bytes()==source
    assert (out/'identity-gap-report.json').stat().st_mode & 0o777==0o600
    assert out.stat().st_mode & 0o777==0o700
    assert 'UNKNOWN' in (out/'browser-use-checklist.md').read_text()
    with pytest.raises(ValueError):analyze(path/'plan.json',sha(path/'plan.json'),out)


@pytest.mark.parametrize('change',['receipt','source','ledger','plan'])
def test_pinned_evidence_drift_stops_publication(tmp_path,monkeypatch,change):
    plan,path,accounting=operation(tmp_path,monkeypatch)
    expected=sha(path/'plan.json')
    target={'receipt':path/'receipt-2.json','source':Path(plan['source_path']),
            'ledger':accounting,'plan':path/'plan.json'}[change]
    write(target,{'corrupted':True},replace=True)
    with pytest.raises((ValueError,KeyError)):analyze(path/'plan.json',expected,tmp_path/'out')
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('description',['Test Transparent Tape, 4 Rolls, 2-Pack','Test Transparent Tape, 4 Rolls (Pack of 2)'])
def test_outer_bundle_forms_do_not_become_compatible(description):
    source,candidate=pair();candidate['product']['title']=description
    result=compare(source,candidate,1)
    assert not result['plausible_textual_lead']
    assert any('outer multipack' in w for w in result['warnings'])


@pytest.mark.parametrize('size',['1 Gallon','20g'])
def test_different_measure_units_are_review_gaps(size):
    source,candidate=pair();source['walmart_product']['pack_description']='4 oz; 1 bottle'
    candidate['product'].update(title='Test Transparent Tape',size=size)
    assert 'Textual size conflict' in compare(source,candidate,1)['warnings']


def test_barcode_type_length_matters():
    source,candidate=pair();candidate['product']['identifiers']=[dict(identifier_type='UPC',value='0026000003049',normalized_gtin='00026000003049')]
    assert barcode_evidence(candidate['product'])['status']=='MISSING'
