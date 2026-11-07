import csv
from copy import deepcopy

import pytest

from app.m96 import MARKETPLACE, build, import_observations, validate_record
from app.m96_fba import parse_preview, request_spec


def item(n=1, **updates):
    return dict(asin=f'B{n:09d}', brand=f'Brand {n}', marketplace=MARKETPLACE,
                category=('Pencil Holders', 'Tool Bags', 'Plant Labels', 'Rulers', 'Laundry Bags', 'Shelf Dividers', 'Tool Trays')[n % 7], identity_field_count=8, **updates)


def registry():
    return dict(brand='OXO', asin='', marketplace=MARKETPLACE, condition='new_new',
                approval_status='APPROVAL_REQUIRED', restriction_scope='BRAND',
                invoice_requirements=None, evidence_source='manual', observed_at='2026-11-07T00:00:00Z')


def test_history_union_and_registry_are_immutable():
    catalog = [item(i) for i in range(1, 40)]
    catalog[0]['brand'] = ' oxo '
    m69 = dict(excluded_asins=['B000000002'], events=[dict(asin='B000000003')])
    histories = [dict(rows=[dict(asin='B000000004')]), dict(asins=['B000000005']),
                 dict(rows=[dict(asin='B000000006')])]
    audit = dict(excluded_asins=['B000000007'])
    before = deepcopy((catalog, m69, histories, audit))
    queue = build(catalog, m69, histories, audit, [registry()])
    assert len(queue) == 30
    assert min(r['asin'] for r in queue) == 'B000000008'
    assert (catalog, m69, histories, audit) == before
    assert all(r['eligibility_status'] == r['fba_inbound_status'] == 'UNKNOWN' for r in queue)


def test_identity_complexity_and_brand_diversification():
    catalog = [item(i) for i in range(1, 10)]
    for row in catalog[:3]:
        row['brand'] = 'Same'
    catalog[3]['identity_conflicts'] = ['gtin']
    catalog[4]['identity_verified'] = True
    queue = build(catalog, dict(excluded_asins=[], events=[]), [], dict(excluded_asins=[]), [], 4)
    assert queue[0]['asin'] == catalog[4]['asin']
    assert catalog[3]['asin'] not in {r['asin'] for r in queue}
    assert sum(r['brand'] == 'Same' for r in queue) <= 2


def test_insufficient_and_duplicate_fail_closed():
    assert len(build([item()], dict(excluded_asins=[], events=[]), [], dict(excluded_asins=[]), [])) == 1
    with pytest.raises(ValueError):
        build([item(), item()], dict(excluded_asins=[], events=[]), [], dict(excluded_asins=[]), [])


@pytest.mark.parametrize('observation,status', [('SELL_THIS_PRODUCT','SELL_THIS_PRODUCT'),
    ('APPROVAL_REQUIRED','APPROVAL_REQUIRED'), ('NOT_AVAILABLE','NOT_AVAILABLE'), ('UNKNOWN','UNKNOWN')])
def test_import(tmp_path, observation, status):
    row = dict(asin='B000000001', brand='Example', marketplace=MARKETPLACE,
               condition='new_new', seller_central_outcome=observation,
               approval_scope='ASIN', approval_reason='Screen reason',
               evidence_date='2026-11-07T00:00:00Z', reviewer_notes='Manual review', evidence_source='manual')
    path = tmp_path / 'observations.csv'
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    assert import_observations(path)[0]['approval_status'] == status


@pytest.mark.parametrize('updates', [dict(observed_at='2026-11-07'),dict(condition='used'),
    dict(approval_status='SELL_THIS_PRODUCT'),dict(restriction_scope='ASIN'),dict(evidence_source='')])
def test_invalid_registry(updates):
    with pytest.raises(ValueError):
        validate_record(registry() | updates)


def test_fba_spec_and_conservative_parser():
    asin = 'B000000001'
    assert request_spec(asin)['params']['program'] == 'INBOUND'
    payload = dict(asin=asin, marketplaceId=MARKETPLACE, program='INBOUND', isEligibleForProgram=True)
    assert parse_preview(dict(payload=payload), asin) == 'ELIGIBLE_PREVIEW'
    for change in [dict(asin='B000000002'),dict(program='COMMINGLING'),
                   dict(isEligibleForProgram='true'),dict(ineligibilityReasonList=['NEW_CODE'])]:
        assert parse_preview(dict(payload=payload | change), asin) == 'UNKNOWN'
    assert parse_preview(dict(payload=payload, errors=[{'code':'error'}]), asin) == 'UNKNOWN'
    assert parse_preview(dict(payload=payload | dict(isEligibleForProgram=False)), asin) == 'INELIGIBLE_PREVIEW'


def test_seed_invoice_requirements_and_unknown_dates():
    import json
    from app.m96 import REGISTRY
    records = json.loads(REGISTRY.read_text())['records']
    assert {r['brand'] for r in records} == {'OXO', '3M', 'Wera'}
    for row in records:
        validate_record(row)
        assert not row['asin']
        assert row['restriction_scope'] == 'BRAND'
    oxo = next(r for r in records if r['brand'] == 'OXO')
    assert oxo['invoice_requirements'] == dict(supplier='manufacturer/distributor', minimum_units=200, purchase_window_days=180)
    assert 'not supplied' in oxo['observation_date_basis']


def test_simple_category_ranks_without_granting_permission():
    plain = item(1)
    unknown = item(2)
    unknown['category'] = 'UNKNOWN'
    rows = build([unknown, plain], dict(excluded_asins=[], events=[]), [], dict(excluded_asins=[]), [], 2)
    assert rows[0]['asin'] == plain['asin']
    assert all(r['eligibility_status'] == 'UNKNOWN' and not r['purchase_authorized'] for r in rows)


def test_csv_formula_safety_and_exclusive_creation(tmp_path):
    from app.m96 import write_csv
    path = tmp_path / 'queue.csv'
    write_csv(path, [dict(brand='=FORMULA()')], ['brand'])
    with path.open() as stream:
        assert list(csv.DictReader(stream))[0]['brand'] == "'=FORMULA()"
    with pytest.raises(FileExistsError):
        write_csv(path, [], ['brand'])


def test_offline_cli_template_roundtrip(tmp_path, monkeypatch):
    import json
    import sys
    from app import m96
    source = tmp_path / 'sources'
    source.mkdir()
    documents = dict(M79=dict(catalog=[item(i) for i in range(1, 36)]),
                     M69=dict(events=[], excluded_asins=[]), M94=dict(rows=[]),
                     REGISTRY=dict(records=[]))
    for key, value in documents.items():
        path = source / (key + '.json')
        path.write_text(json.dumps(value))
        monkeypatch.setattr(m96, key, path)
    (source / 'm95-eligibility-result.json').write_text(json.dumps(dict(rows=[dict(asin='B000000001')])))
    monkeypatch.setattr(m96, 'DIRECTORY', source)
    monkeypatch.setattr(m96, 'audit', lambda directory: dict(excluded_asins=[]))
    output = tmp_path / 'output'
    monkeypatch.setattr(sys, 'argv', ['m96', '--output', str(output)])
    m96.main()
    summary = json.loads((output / 'M96_summary.json').read_text())
    assert summary['candidate_count'] == 30 and summary['live_requests'] == 0
    assert import_observations(output / 'M96_screening_template.csv') == []
    assert 'M95_0' in summary['source_sha256']
    with (output / 'M96_candidate_queue.csv').open() as stream:
        assert 'B000000001' not in {r['asin'] for r in csv.DictReader(stream)}
    with pytest.raises(FileExistsError):
        m96.main()


def test_observed_brand_deprioritized_not_universally_banned():
    catalog = [item(1), item(2)]
    catalog[0]['brand'] = 'OXO'
    rows = build(catalog, dict(events=[], excluded_asins=[]), [], dict(excluded_asins=[]), [registry()])
    assert rows[-1]['brand'] == 'OXO' and rows[-1]['observed_brand_approval']
    assert rows[-1]['eligibility_status'] == 'UNKNOWN'


@pytest.mark.parametrize('title', ['Battery storage box', 'Medical tool bag', 'Magnetic ruler',
    'Infant laundry bags', 'Cleaner storage box', 'Edible plant labels'])
def test_risky_product_is_excluded(title):
    row = item()
    row['title'] = title
    assert build([row], dict(events=[], excluded_asins=[]), [], dict(excluded_asins=[]), []) == []


def test_m95_classifications_remain_independent():
    from app.m96 import historical_m95
    row = dict(asin='B000000001', restrictions=dict(status='succeeded', data=dict(
        reason_codes=['APPROVAL_REQUIRED'], restriction_count=1)))
    original = deepcopy(row)
    result = historical_m95([dict(rows=[row])])[0]
    assert result['listing_eligibility'] == 'APPROVAL_REQUIRED'
    assert result['fba_eligibility'] == result['profitability'] == 'UNKNOWN'
    assert row == original


@pytest.mark.parametrize('eligible,expected', [(True, 'ELIGIBLE_PREVIEW'), (False, 'INELIGIBLE_PREVIEW')])
def test_explicit_mock_adapter(eligible, expected):
    from app.m96_fba import mock_preview
    result = mock_preview('B000000001', eligible=eligible)
    assert result['is_mock'] is True and result['status'] == expected
