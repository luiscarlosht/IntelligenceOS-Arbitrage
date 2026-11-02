"""Synthetic saved pages and curated decisions; never production evidence."""
from copy import deepcopy
import csv
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

import pytest
from openpyxl import load_workbook

from app import m78
from app.m70_identity import FIELDS, merge, observation
from app.m70_sources import file_hash
from app.m78_analysis import analyze
from test_m70 import raw_item


def obs(n=1, **values):
    return observation(dict(asin=f'B{n:09d}', **values), role='amazon', reference=f'local:fixture:{n}',
        source_hash='a'*64, source_class='local_json', observed_at='2026-11-01T00:00:00Z')


@pytest.fixture
def fixture(tmp_path):
    directory = tmp_path/'inputs'
    directory.mkdir()
    p = merge([obs(title='=HYPERLINK("evil")', brand='Curated')])
    p.update(permanently_excluded=True, previously_checked_seller_specific=True, cohorts=['M73'])
    catalog = directory/'M76_catalog.csv'
    fields = sorted(p)
    with catalog.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        from app.m78_reporting import cell
        writer.writerow({k: cell(v) for k, v in p.items()})
    annotations = directory/'M76_historical_annotations.json'
    annotations.write_text(json.dumps([dict(asin=p['asin'], permanently_excluded=True,
        previously_checked_seller_specific=True), dict(asin='B000000099', permanently_excluded=True)]))
    pages = directory/'pages.json'
    pages.write_text(json.dumps(dict(status='COMPLETED_NO_REPLAY', pages=[dict(query_reference='q001',
        page_index=0, page_token=None, marketplace_id='ATVPDKIKX0DER', http_status=200,
        observed_at='2026-11-01T00:00:00Z', items=[raw_item(1000), raw_item(1000)])])))
    sources = directory/'sources.json'
    sources.write_text(json.dumps(dict(schema=1, sources=[dict(path=pages.name, sha256=file_hash(pages),
        adapter='amazon_catalog_pages', permission_reference='local:synthetic', marketplace='ATVPDKIKX0DER')])))
    return dict(catalog=catalog, annotations=annotations, sources=sources, output=tmp_path/'out', verify_expected=False)


def test_reconciliation_preserves_curated_and_annotations():
    curated = merge([obs(model='A'), obs(model='B')])
    curated['permanently_excluded'] = True
    original = deepcopy(curated)
    report = analyze([curated], [obs(2, brand='Fixture'), obs(2, brand='Other'), obs(1, model='C')],
        [dict(asin='B000000099', permanently_excluded=True, previously_checked_seller_specific=True)])
    assert report['summary']['distinct_catalog_asins'] == 2
    assert report['summary']['overlap_asins'] == 1
    assert report['summary']['duplicate_m77_observations'] == 1
    assert report['summary']['conflict_asins'] == 2
    assert not report['annotations'][0]['in_catalog']
    assert report['catalog'][0]['field_provenance'] == original['field_provenance']
    assert report['catalog'][0]['observed_alternatives'] == original['observed_alternatives']
    assert all(p['classification'] == 'Blocked' for p in report['catalog'])
    assert curated == original
    with pytest.raises(ValueError):
        analyze([curated, curated], [], [])


def test_precedence():
    full = dict(zip(FIELDS, ['x']*len(FIELDS)))
    for changes, classification in [({}, 'Identity ready'), ({'condition':None}, 'Needs review'),
            ({'permanently_excluded':True}, 'Blocked'), ({'review_blocks':['REVIEW']}, 'Blocked')]:
        report = analyze([dict(full, asin='B000000001', **changes)], [], [])
        assert report['catalog'][0]['classification'] == classification
        assert report['catalog'][0]['eligibility'] == 'UNKNOWN'
        assert not report['catalog'][0]['purchase_ready']


def test_determinism_safe_exports_private_modes(fixture):
    summary = m78.run(**fixture)
    assert summary['distinct_catalog_asins'] == 2
    first = fixture['output']
    second = first.with_name('second')
    m78.run(**dict(fixture, output=second))
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {p.name:p.read_bytes() for p in second.iterdir()}
    manifest = json.loads((first/'M78_manifest.json').read_text())
    assert all(file_hash(first/name) == digest for name,digest in manifest['output_sha256'].items())
    assert first.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in first.iterdir())
    wb = load_workbook(first/'M78_review.xlsx')
    assert all(c.data_type != 'f' for sheet in wb for row in sheet for c in row)
    assert "'=HYPERLINK" in (first/'M78_catalog.csv').read_text(encoding='utf-8-sig')
    with sqlite3.connect(first/'M78_catalog.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM catalog').fetchone()[0] == 2
    before = (first/'M78_manifest.json').read_bytes()
    with pytest.raises(ValueError):
        m78.run(**fixture)
    assert (first/'M78_manifest.json').read_bytes() == before


@pytest.mark.parametrize('failure', ['serialize', 'source', 'code', 'publish', 'race', 'interrupt'])
def test_failure_cleanup(fixture, monkeypatch, failure):
    def injected(*args):
        if failure == 'source':
            fixture['catalog'].write_text('changed')
        elif failure == 'code':
            monkeypatch.setattr(m78, 'implementation', lambda: {})
        elif failure == 'race':
            fixture['output'].mkdir()
            (fixture['output']/'sentinel').write_text('preserve')
        elif failure == 'interrupt':
            raise KeyboardInterrupt()
        else:
            raise OSError('injected')
    if failure == 'serialize':
        monkeypatch.setattr(m78, 'serialize', injected)
    elif failure == 'publish':
        monkeypatch.setattr(m78, 'atomic_publish', injected)
    with pytest.raises((ValueError, OSError, KeyboardInterrupt)):
        m78.run(**fixture, before_completion=injected if failure not in ('serialize','publish') else lambda:None)
    assert not (fixture['output']/'M78_manifest.json').exists()
    assert not list(fixture['output'].parent.glob('.m78-stage-*'))
    if failure == 'race':
        assert (fixture['output']/'sentinel').read_text() == 'preserve'


def test_paths_and_invariants(fixture):
    with pytest.raises(ValueError):
        m78.run(**dict(fixture, verify_expected=True))
    with pytest.raises(ValueError):
        m78.run(**dict(fixture, output=fixture['catalog'].parent/'out'))
    link = fixture['output'].with_name('link')
    link.symlink_to(fixture['catalog'])
    with pytest.raises(ValueError):
        m78.run(**dict(fixture, catalog=link))


def test_guard_during_run(fixture):
    def check():
        with pytest.raises(PermissionError):
            socket.socket()
        with pytest.raises(PermissionError):
            socket.getaddrinfo('example.com',443)
        with pytest.raises(PermissionError):
            open('/tmp/credentials.json')
        with pytest.raises(PermissionError):
            open('/tmp/authorization.json')
        with pytest.raises(PermissionError):
            open('/tmp/undeclared-input.json')
        with pytest.raises(PermissionError):
            subprocess.run([sys.executable, '-c', 'pass'])
    m78.run(**fixture, before_completion=check)


def test_cli_guard():
    program = '''from app.m78 import guard, _active
import socket
_active.set(True)
guard()
for action in (lambda: socket.socket(), lambda: open('/tmp/token.json')):
    try: action()
    except PermissionError: pass
    else: raise AssertionError('guard bypass')
print('OFFLINE_DENIED')
'''
    result = subprocess.run([sys.executable, '-c', program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'OFFLINE_DENIED'


def test_expected_scale_is_computed_from_synthetic_inputs(tmp_path):
    directory = tmp_path/'inputs'
    directory.mkdir()
    curated = []
    for n in range(777):
        values = {f:'observed' for f in FIELDS if f not in ('gtin','pack_quantity','condition')}
        values.update(gtin='00000000000000', pack_quantity=1)
        if n >= 111:
            values.pop('model')
        p = merge([obs(n, **values)])
        if 111 <= n < 160:
            p['identity_conflicts'] = ['model']
        p.update(permanently_excluded=n < 41, previously_checked_seller_specific=n < 40)
        curated.append(p)
    from app.m78_reporting import cell
    catalog = directory/'M76_catalog.csv'
    fields = sorted({k for p in curated for k in p})
    with catalog.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        for p in curated:
            writer.writerow({k:cell(p.get(k)) for k in fields})
    annotations = directory/'annotations.json'
    annotations.write_text(json.dumps([dict(asin=f'B{n if n<41 else n+2000:09d}',
        permanently_excluded=True, previously_checked_seller_specific=n<40) for n in range(97)]))
    items = []
    for n in range(620):
        item = raw_item(n+1000)
        if n >= 125:
            item['summaries'][0].pop('modelNumber')
        if 125 <= n < 156:
            item['attributes']['model_number'] = [dict(marketplace_id='ATVPDKIKX0DER',value=v) for v in ('A','B')]
        items.append(item)
    pages = directory/'pages.json'
    pages.write_text(json.dumps(dict(status='COMPLETED_NO_REPLAY',pages=[dict(query_reference=f'q{n:03}',
        page_index=0,page_token=None,marketplace_id='ATVPDKIKX0DER',http_status=200,
        observed_at='2026-11-01T00:00:00Z',items=items[n*20:n*20+20]) for n in range(31)])))
    sources = directory/'sources.json'
    sources.write_text(json.dumps(dict(schema=1,sources=[dict(path=pages.name,sha256=file_hash(pages),
        adapter='amazon_catalog_pages',permission_reference='local:synthetic',marketplace='ATVPDKIKX0DER') ])))
    summary = m78.run(catalog=catalog,annotations=annotations,sources=sources,output=tmp_path/'out')
    assert {k:summary[k] for k in m78.EXPECTED} == m78.EXPECTED
    # Reconcile the 56 historical exclusions outside the catalog without adding rows.
    report = json.loads((tmp_path/'out/M78_report.json').read_text())
    assert sum(not a['in_catalog'] for a in report['annotations']) == 56
    assert summary['distinct_catalog_asins'] == 1397
    result = subprocess.run([sys.executable, '-m', 'ops.m78_offline', '--catalog', str(catalog),
        '--annotations', str(annotations), '--sources', str(sources), '--output', str(tmp_path/'cli-out')],
        capture_output=True, text=True, env={'PATH':'/usr/bin:/bin'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == summary
    assert {p.name:p.read_bytes() for p in (tmp_path/'out').iterdir()} == {
        p.name:p.read_bytes() for p in (tmp_path/'cli-out').iterdir()}


@pytest.mark.parametrize('change',['partial','later_page','duplicate_query','rejected_record','digest','adapter'])
def test_saved_page_boundaries(fixture,change):
    source = fixture['sources']
    manifest = json.loads(source.read_text())
    path = source.parent/'pages.json'
    doc = json.loads(path.read_text())
    if change == 'partial':
        doc['status'] = 'STOPPED_NO_REPLAY'
    elif change == 'later_page':
        doc['pages'][0]['page_index'] = 1
    elif change == 'duplicate_query':
        doc['pages'].append(deepcopy(doc['pages'][0]))
    elif change == 'rejected_record':
        doc['pages'][0]['items'][0]['asin'] = 'INVALID'
    path.write_text(json.dumps(doc))
    manifest['sources'][0]['sha256'] = file_hash(path) if change != 'digest' else '0'*64
    if change == 'adapter':
        manifest['sources'][0]['adapter'] = 'local_json'
    source.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        m78.run(**fixture)
    assert not fixture['output'].exists()


def test_curated_missing_provenance_remains_unknown():
    p = dict(asin='B000000001', brand='Decision', identity_conflicts=['model'])
    report = analyze([p], [], [])
    assert report['catalog'][0]['field_provenance'] == {}
    assert report['catalog'][0].get('model') is None
    assert report['catalog'][0]['classification'] == 'Blocked'


def test_parent_symlink_and_dotdot_protection(fixture):
    alias = fixture['output'].with_name('alias')
    alias.symlink_to(fixture['catalog'].parent, target_is_directory=True)
    with pytest.raises(ValueError):
        m78.run(**dict(fixture, output=alias/'out'))
    sibling = fixture['output'].with_name('sibling')
    sibling.mkdir()
    with pytest.raises(ValueError):
        m78.run(**dict(fixture, output=sibling/'..'/'inputs'/'out'))


def test_historical_explicit_blocks_remain_blocks_with_missing_fields():
    report = analyze([dict(asin='B000000001',brand='Curated',
        historical_m73_record={'review_blocks':['VARIATION_PARENT']})], [], [])
    assert report['catalog'][0]['classification'] == 'Blocked'
    assert report['catalog'][0]['review_blocks'] == ['VARIATION_PARENT']


def test_drift_during_manifest_write_is_not_published(fixture,monkeypatch):
    original = m78.write
    def mutate(path,content):
        original(path,content)
        fixture['catalog'].write_text('changed after earlier drift check')
    monkeypatch.setattr(m78,'write',mutate)
    with pytest.raises(ValueError,match='drift'):
        m78.run(**fixture)
    assert not fixture['output'].exists()
    assert not list(fixture['output'].parent.glob('.m78-stage-*'))
