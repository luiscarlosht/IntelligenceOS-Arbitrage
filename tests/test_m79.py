"""Synthetic-only tests; no production evidence, API client or M77 execution."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import subprocess
from openpyxl import load_workbook
import pytest
from app import m79
from app.m79_analysis import analyze, state, date

NOW = datetime(2026, 11, 3, 3, tzinfo=timezone.utc)


def product(asin='B000000001', **extra):
    values = dict(asin=asin, brand='Observed', title='=unsafe', gtin='00012345678905', model='X',
        category='Kitchen', product_type='TOOLS', pack_quantity=1, size='small', variation='blue',
        condition=None, identity_conflicts=[], review_blocks=[], permanently_excluded=False,
        field_provenance={}, source_references=['sha256:' + 'a'*64], source_sha256=['a'*64])
    for f in ('brand','title','gtin','model','category','pack_quantity'):
        values['field_provenance'][f] = [dict(status='SOURCE_OBSERVED', observed_at='2026-11-02T00:00:00Z')]
    values.update(extra)
    return values


def report(rows=None, history=None, pages=None):
    return analyze(rows or [product()], history or {}, pages or [], 'a'*64, NOW)


def test_no_metrics_no_invented_ranks_or_shortlist():
    d = report()
    assert d['summary']['asins'] == 1 and d['top100'] == d['top20'] == []
    row = d['catalog'][0]
    for f in ('bsr','amazon_price','offer_count','buy_box','price_stability','eligibility',
              'estimated_monthly_sales','sales_estimate_confidence','demand_rank'):
        assert row[f] == 'UNKNOWN'
    assert not row['sourcing_allowed'] and not row['identity_verified']
    assert not d['summary']['walmart_handoff_ready']


def test_history_is_stale_annotation_never_permission():
    h = {'events':[dict(asin='B000000001', marketplace='ATVPDKIKX0DER', condition='new_new',
                        eligibility='ELIGIBLE', observed_at='2026-11-01T00:00:00Z')]}
    d = report(history=h)
    assert d['catalog'][0]['eligibility'] == 'UNKNOWN'
    assert d['catalog'][0]['historical_eligibility_status'] == [{'value':'ELIGIBLE','status':'STALE'}]
    assert next(r for r in d['coverage'] if r['metric']=='historical_eligibility_only')['stale'] == 1
    assert d['top100'] == []


def test_list_price_never_offer_price_and_invalid_values_retained():
    pages = [dict(request_slot=2, observed_at='2026-11-02T00:00:00Z', items=[dict(
        asin='B000000001', attributes={'list_price':[
            dict(value=19.99, currency='USD', marketplace_id='ATVPDKIKX0DER'),
            dict(value=0, currency='USD', marketplace_id='ATVPDKIKX0DER'),
            dict(value=10, currency='CAD', marketplace_id='ATVPDKIKX0DER')]})])]
    d = report(pages=pages)
    row = d['catalog'][0]
    assert row['amazon_price'] == 'UNKNOWN' and row['price_stability'] == 'UNKNOWN'
    assert row['catalog_list_prices'][0]['value'] == '19.99'
    assert len(row['catalog_list_price_rejections']) == 2
    assert row['catalog_list_prices'][0]['source_sha256'] == 'a'*64


@pytest.mark.parametrize('timestamp,expected', [('2026-11-03T00:00:00Z','AVAILABLE'),
    ('2026-11-01T00:00:00Z','STALE'), ('2026-11-04T00:00:00Z','UNVERIFIED'),
    ('2026-11-03T00:00:00','UNVERIFIED'), ('bad','UNVERIFIED')])
def test_freshness(timestamp, expected):
    assert state('value', timestamp, NOW, 24) == expected
    assert state(None, timestamp, NOW, 24) == 'MISSING'


def test_order_is_research_only_with_exclusions_and_ties():
    rows = [product('B000000003'), product('B000000002', gtin=None), product('B000000001'),
            product('B000000004', permanently_excluded=True), product('B000000005', identity_conflicts=['gtin'])]
    d = report(rows=rows)
    assert [r['asin'] for r in d['research100']] == ['B000000001','B000000003','B000000002']
    assert d['research20'][0]['demand_rank'] == 'UNKNOWN'
    assert len(d['catalog']) == 5 and not d['top100']
    assert report(rows=list(reversed(rows)))['research100'] == d['research100']


@pytest.mark.parametrize('rows', [[product(),product()], [product('bad')]])
def test_invalid_or_duplicate_asin_refused(rows):
    with pytest.raises(ValueError): report(rows=rows)


def test_naive_analysis_time_refused():
    with pytest.raises(ValueError): analyze([product()], {}, [], 'a'*64, datetime(2026,11,3))


def test_workbook_and_handoff_safe_and_deterministic(tmp_path):
    d = report()
    d['input_sha256'] = {'original.json':'a'*64}
    for name in ('one','two'):
        path=tmp_path/name;path.mkdir()
        m79.export(d,path)
    assert (tmp_path/'one/M79_amazon_intelligence.xlsx').read_bytes() == (tmp_path/'two/M79_amazon_intelligence.xlsx').read_bytes()
    wb = load_workbook(tmp_path/'one/M79_amazon_intelligence.xlsx')
    sheet = wb['All_ASINs']; headers=[c.value for c in sheet[1]]
    assert sheet.cell(2,headers.index('title')+1).value == "'=unsafe"
    assert wb['Demand_Top100'].max_row == 2
    assert 'NO QUALIFIED' in wb['Demand_Top100']['A2'].value
    handoff=json.loads((tmp_path/'one/M79_walmart_handoff.json').read_text())
    assert not handoff['ready_for_walmart_sourcing'] and handoff['approved_shortlist']==[]
    assert handoff['research_queue'][0]['quantity']==1
    assert handoff['research_queue'][0]['amazon_price']=='UNKNOWN'
    with pytest.raises(FileExistsError): m79.export(d,tmp_path/'one')


def test_offline_guard_denies_network_process_and_credentials(tmp_path):
    secret=tmp_path/'credentials.json';secret.write_text('do not read')
    with m79.offline():
        with pytest.raises(PermissionError): socket.socket()
        with pytest.raises(PermissionError): subprocess.run(['true'])
        with pytest.raises(PermissionError): secret.read_text()
    assert secret.read_text()=='do not read'


@pytest.mark.parametrize('kind', ['existing','symlink','protected','mnt','traversal'])
def test_output_boundary_before_inputs(tmp_path,kind):
    inputs=tmp_path/'inputs';inputs.mkdir()
    out=tmp_path/'out'
    if kind=='existing':out.mkdir()
    elif kind=='symlink':out.symlink_to(inputs, target_is_directory=True)
    elif kind=='protected':out=inputs/'new'
    elif kind=='mnt':out=Path('/mnt/m79-must-not-exist')
    else:out=tmp_path/'dummy'/'..'/'inputs'/'new'
    with pytest.raises((ValueError,FileNotFoundError)):
        m79.run(m76_dir=inputs,m77_dir=inputs,baseline_report=inputs/'baseline.json',output=out,as_of=NOW)
    assert not (inputs/'new').exists()


def test_pinned_manifest_fails_before_any_output(tmp_path):
    source=tmp_path/'source';source.mkdir()
    (source/'M76_evidence_manifest.json').write_text('{}')
    baseline=source/'baseline.json';baseline.write_text('{}')
    out=tmp_path/'new'
    with pytest.raises(ValueError,match='pinned M76'):
        m79.run(m76_dir=source,m77_dir=source,baseline_report=baseline,output=out,as_of=NOW)
    assert not out.exists()


def test_guard_forbids_historical_writes(tmp_path):
    source=tmp_path/'original.json';source.write_text('original')
    target=tmp_path/'new';target.mkdir()
    with m79.offline(target):
        with pytest.raises(PermissionError,match='outside new report'):
            source.write_text('change')
        (target/'allowed.json').write_text('new private output')
    assert source.read_text()=='original'


def test_input_drift_prevents_completion(tmp_path,monkeypatch):
    source=tmp_path/'original.json';source.write_text('original')
    root=tmp_path/'inputs';root.mkdir()
    original=m79.file_hash
    calls=0
    def fake_load(*args):
        return [product()],{},[],'a'*64,{str(source):original(source)}
    monkeypatch.setattr(m79,'load',fake_load)
    def changing(path):
        nonlocal calls
        if Path(path)==source:
            calls+=1
            if calls>0:return 'b'*64
        return original(path)
    monkeypatch.setattr(m79,'file_hash',changing)
    out=tmp_path/'report'
    with pytest.raises(ValueError,match='drift'):
        m79.run(m76_dir=root,m77_dir=root,baseline_report=root/'baseline.json',output=out,as_of=NOW)
    assert not (out/'M79_completion.json').exists()
    assert source.read_text()=='original'
