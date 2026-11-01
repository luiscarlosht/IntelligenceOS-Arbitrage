"""Synthetic local replay only; these fixtures are not real sourced candidates."""
from datetime import datetime, timezone
import json
import socket
import subprocess
import sys

from openpyxl import load_workbook
import pytest

from app.account_eligibility import classify, evaluate, export, plan

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def candidate():
    source = dict(brand='Fictional', model='EXAMPLE', gtin='012345678905', pack_count=1,
                  variation='one red unit', observed_at=NOW.isoformat(), provenance='synthetic fixture')
    return dict(retailer=dict(source, retailer='Example', title='Fictional example',
                url='https://example.com/item', cost='10', availability='in_stock'),
        amazon=dict(source, asin='B000000001', url='https://www.amazon.com/dp/B000000001'),
        eligibility=dict(asin='B000000001', seller_reference='fixture-account', marketplace_id='ATVPDKIKX0DER',
            condition='new_new', reference='synthetic', observed_at=NOW.isoformat(),
            restrictions=dict(status='succeeded', response={'restrictions': []})))


def document():
    return dict(account_reference='fixture-account', is_synthetic=True, candidates=[candidate() for _ in range(20)])


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Network forbidden')
    monkeypatch.setattr(socket, 'create_connection', blocked)


@pytest.mark.parametrize('response,status', [
    ({'restrictions': []}, 'NO_REPORTED_RESTRICTIONS'),
    ({'restrictions': [{'marketplaceId': 'ATVPDKIKX0DER', 'conditionType': 'new_new',
       'reasons': [{'reasonCode': 'APPROVAL_REQUIRED', 'message': 'Brand approval required merchant SECRET',
                    'links': [{'resource': 'https://sellercentral.amazon.com/approval?merchant=SECRET'}]}]}]}, 'APPROVAL_REQUIRED'),
    ({'restrictions': [{'marketplaceId': 'ATVPDKIKX0DER', 'reasons': [{'reasonCode': 'NOT_ELIGIBLE'}]}]}, 'OTHER_RESTRICTED'),
    ({}, 'ERROR'), ({'restrictions': [{'marketplaceId': 'OTHER'}]}, 'ERROR')])
def test_shapes(response, status):
    entry = candidate()
    entry['eligibility']['restrictions']['response'] = response
    result = classify(entry['eligibility'], 'B000000001', 'fixture-account', NOW)
    assert result['status'] == status
    assert 'SECRET' not in json.dumps(result)
    if status == 'APPROVAL_REQUIRED':
        assert result['reason_codes'] == ['APPROVAL_REQUIRED']
        assert result['instructions'] and result['links']


@pytest.mark.parametrize('failure', ['http_429', 'http_500', 'http_503', 'timeout', 'failed', 'uncertain'])
def test_failure_cannot_infer_permission(failure):
    entry = candidate()
    entry['eligibility']['restrictions']['status'] = failure
    assert classify(entry['eligibility'], 'B000000001', 'fixture-account', NOW)['status'] == 'ERROR'


@pytest.mark.parametrize('update', [dict(seller_reference=''), dict(seller_reference='other'),
    dict(asin='B000000002'), dict(condition='used'), dict(marketplace_id='other'),
    dict(observed_at='2026-10-28T00:00:00Z'), dict(observed_at='2026-11-02T00:00:00Z')])
def test_missing_stale_and_wrong_scope(update):
    entry = candidate()['eligibility']
    entry.update(update)
    assert classify(entry, 'B000000001', 'fixture-account', NOW)['status'] == 'UNKNOWN'


@pytest.mark.parametrize('field,value', [('pack_count', 2), ('gtin', '000123456784'),
                                         ('asin', 'B000000002'), ('variation', 'blue')])
def test_bad_match_never_enters_eligible(field, value):
    data = document()
    data['candidates'][0]['amazon'][field] = value
    row = evaluate(data, NOW)['rows'][0]
    assert not row['exact_match'] and not row['eligible_for_downstream_checks']
    assert not row['purchase_ready']


def test_normalized_m60_shape_and_transport_success_only():
    entry = candidate()['eligibility']
    entry['restrictions'] = dict(status='succeeded', data=dict(restriction_count=1,
        listing_permission=dict(value=False), approval_required=True, reason_codes=['APPROVAL_REQUIRED'], reasons=[]))
    assert classify(entry, 'B000000001', 'fixture-account', NOW)['status'] == 'APPROVAL_REQUIRED'
    entry['restrictions']['data'] = {}
    assert classify(entry, 'B000000001', 'fixture-account', NOW)['status'] == 'ERROR'
    entry['restrictions']['data'] = dict(restriction_count=0, listing_permission=dict(value=False))
    assert classify(entry, 'B000000001', 'fixture-account', NOW)['status'] == 'ERROR'


def test_workbook_and_independent_unknowns(tmp_path):
    data = document()
    data['candidates'][0]['retailer']['model'] = '=HYPERLINK("bad")'
    result = evaluate(data, NOW)
    path = tmp_path/'review.xlsx'
    export(result, path)
    book = load_workbook(path)
    assert book.sheetnames == ['review', 'eligible', 'restricted', 'unknown']
    assert all(c.data_type != 'f' for s in book for row in s for c in row)
    for row in result['rows']:
        assert row['fba_eligible'] is None and row['fees_verified'] is None
        assert row['roi_ge_50'] is None and row['net_ge_5'] is None
        assert row['review_required'] and not row['manual_purchase_authorized'] and not row['purchase_ready']


def test_plan_is_opt_in_nonexecutable_and_excludes_failed_targets():
    data = document()
    data['is_synthetic'] = False  # Test the proposal validation, never real evidence.
    for i, entry in enumerate(data['candidates']):
        entry['amazon']['asin'] = f'B{i:09}'
        entry['amazon']['url'] = 'https://www.amazon.com/dp/' + entry['amazon']['asin']
        entry['eligibility'] = {}
    result = evaluate(data, NOW)
    target = data['candidates'][0]['amazon']['asin']
    with pytest.raises(ValueError): plan(data, result, 'hash', [target], False)
    proposal = plan(data, result, 'hash', [target], True)
    assert proposal['budget']['maximum_requests'] == 2
    assert not proposal['execution_authorized'] and proposal['authorized_requests'] == 0
    result['rows'][0]['eligibility']['status'] = 'ERROR'
    with pytest.raises(ValueError): plan(data, result, 'hash', [target], True)


def test_cli_template_validate_export_and_no_overwrite(tmp_path):
    template, report, workbook = [tmp_path/name for name in ('intake.json', 'report.json', 'report.xlsx')]
    def cli(*args):
        return subprocess.run([sys.executable, '-m', 'app.account_eligibility', *map(str, args)], capture_output=True)
    assert cli('template', '--output', template).returncode == 0
    assert cli('validate', '--input', template, '--output', report, '--now', NOW.isoformat()).returncode == 0
    assert json.loads(report.read_text())['exact_matches'] == 0
    assert cli('export', '--input', template, '--output', workbook).returncode == 0
    assert cli('template', '--output', template).returncode != 0


@pytest.mark.parametrize('count', [0, 19, 51])
def test_input_bounds(count):
    data = document()
    data['candidates'] = [candidate() for _ in range(count)]
    with pytest.raises(ValueError): evaluate(data, NOW)


@pytest.mark.parametrize('http_status', [429, 500, 503])
def test_http_failure_overrides_success_label(http_status):
    entry = candidate()['eligibility']
    entry['restrictions']['http_status'] = http_status
    assert classify(entry, 'B000000001', 'fixture-account', NOW)['status'] == 'ERROR'
