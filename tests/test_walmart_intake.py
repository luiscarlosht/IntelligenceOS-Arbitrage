"""Synthetic validation fixtures only, never current product evidence."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from app.evidence_io import digest
from app.walmart_intake import validate, main
from app.walmart_evidence import normalize
from app.product_analysis import comparison

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def completed(tmp_path):
    batch = json.loads(Path('templates/m88-real-six-pilot.json').read_text())
    evidence = tmp_path / 'browser.txt'
    evidence.write_text('Synthetic test evidence only')
    for i, row in enumerate(batch['observations']):
        row.update(human_reviewed=True, reviewer='Test reviewer')
        row['walmart_product'].update(walmart_item_id=str(900001+i),
            url=f'https://www.walmart.com/ip/{900001+i}', title='Synthetic fixture',
            pack_quantity=1, variation='Test variant', seller='Test seller',
            shipping_availability='Unknown at test location', observed_at=NOW.isoformat(),
            source_reference='Test browser capture')
        row['acquisition']['purchase']['value']='1.25'
        row['source_evidence']=dict(path='browser.txt',sha256=digest(evidence),description='Test capture')
    return batch


def test_template_is_incomplete_and_leads_are_not_observations(tmp_path):
    batch=json.loads(Path('templates/m88-real-six-pilot.json').read_text())
    assert len(batch['observations']) == 6
    assert batch['observations'][-1]['research_lead']['walmart_item_id'] is None
    assert all(r['walmart_product']['walmart_item_id'] is None for r in batch['observations'])
    with pytest.raises(ValueError): validate(batch,NOW,tmp_path)


def test_conversion_preserves_unknowns_and_m87_m86_gates(tmp_path):
    batch=completed(tmp_path); original=deepcopy(batch)
    result=validate(batch,NOW,tmp_path)
    assert batch==original
    assert result['observations'][0]['acquisition']['retailer_shipping']['value']=='UNKNOWN'
    report=comparison(normalize(result),NOW)
    assert len(report['records'])==6
    assert not report['purchase_authorized']
    assert all(r['financial_assessment']=='INSUFFICIENT_DATA' for r in report['records'])


@pytest.mark.parametrize('field,value', [('url','https://evil.test/ip/900001'),
    ('url','https://www.walmart.com/ip/999999'), ('url','https://www.walmart.com/ip/900001?x=y'),
    ('title',None), ('seller','UNKNOWN'), ('variation',''), ('pack_quantity',True),
    ('pack_quantity',0), ('observed_at','2026-11-05T12:00:00'),
    ('observed_at','2020-01-01T00:00:00+00:00'), ('observed_at','2099-01-01T00:00:00+00:00')])
def test_invalid_identity(tmp_path,field,value):
    batch=completed(tmp_path); batch['observations'][0]['walmart_product'][field]=value
    with pytest.raises(ValueError): validate(batch,NOW,tmp_path)


@pytest.mark.parametrize('value', ['0','-1','NaN','Infinity','1.234',1,True,None])
def test_invalid_price(tmp_path,value):
    batch=completed(tmp_path); batch['observations'][0]['acquisition']['purchase']['value']=value
    with pytest.raises(ValueError): validate(batch,NOW,tmp_path)


@pytest.mark.parametrize('case',['count','duplicate','review','hash','shipping','amazon','purchase'])
def test_invalid_intake(tmp_path,case):
    batch=completed(tmp_path); row=batch['observations'][0]
    if case=='count': batch['observations'].pop()
    if case=='duplicate': batch['observations'][1]=deepcopy(row)
    if case=='review': row['human_reviewed']=False
    if case=='hash': row['source_evidence']['sha256']='0'*64
    if case=='shipping': row['acquisition']['retailer_shipping']['value']='free'
    if case=='amazon': row['amazon']={}
    if case=='purchase': batch['purchase_authorized']=True
    with pytest.raises(ValueError): validate(batch,NOW,tmp_path)


def test_cli_private_exclusive_and_offline(tmp_path,monkeypatch):
    batch=completed(tmp_path)
    for row in batch['observations']:
        row['walmart_product']['observed_at']=datetime.now(timezone.utc).isoformat()
    source=tmp_path/'inputs'/'intake.json'; source.parent.mkdir()
    for row in batch['observations']: row['source_evidence']['path']='../browser.txt'
    source.write_text(json.dumps(batch)); before=source.read_bytes()
    output=tmp_path/'imported'
    monkeypatch.setattr('sys.argv',['intake','--input',str(source),'--sha256',digest(source),'--output',str(output)])
    main()
    assert source.read_bytes()==before
    assert (output/'m87-batch.json').stat().st_mode & 0o777 == 0o600
    assert output.stat().st_mode & 0o777 == 0o700
    assert json.loads((output/'validation.json').read_text())['network_requests']==0
    with pytest.raises(ValueError): main()
    from app.walmart_evidence import main as m87_main
    imported=output/'m87-batch.json'; report=tmp_path/'analysis'
    monkeypatch.setattr('sys.argv',['m87','--input',str(imported),'--sha256',digest(imported),
                                  '--output',str(report)])
    m87_main()
    assert (report/'comparison.xlsx').is_file()
    assert not json.loads((report/'comparison.json').read_text())['purchase_authorized']


@pytest.mark.parametrize('field,value',[('brand',None),('size',12),('model',''),('gtin','123456789013')])
def test_optional_identity_must_be_explicit_unknown_or_valid(tmp_path,field,value):
    batch=completed(tmp_path); batch['observations'][0]['walmart_product'][field]=value
    with pytest.raises(ValueError): validate(batch,NOW,tmp_path)
