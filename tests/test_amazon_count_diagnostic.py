"""Targeted count diagnostic: synthetic responses, no credential/network access."""
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from app import amazon_pilot as pilot
from app import amazon_pricing_diagnostic as diagnostic
from app.amazon_diagnostics import AmazonFailure, ResponseDocument
from app.amazon_pricing_shape import pricing_count_shape

SECRET = 'synthetic-never-persist-this'
CREDS = dict(client_id=SECRET, client_secret=SECRET, refresh_token=SECRET)


def response(count=7, returned=2):
    return {'payload': {'status': 'Success', 'ASIN': diagnostic.COUNT_ASIN,
        'marketplaceId': pilot.MARKETPLACE, 'ItemCondition': 'New',
        'Identifier': {'ASIN': diagnostic.COUNT_ASIN, 'MarketplaceId': pilot.MARKETPLACE,
                       'ItemCondition': 'New'},
        'Summary': {'TotalOfferCount': count}, 'Offers': [{'SellerId': SECRET}] * returned,
        SECRET: SECRET}}


class Transport:
    def __init__(self, document=None, fail_at=None):
        self.document = document if document is not None else response()
        self.fail_at = fail_at
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        assert len(self.requests) <= 2
        if len(self.requests) == self.fail_at:
            raise AmazonFailure(SECRET, reason='transport_error')
        if len(self.requests) == 1:
            return ResponseDocument({'access_token': SECRET, 'token_type': 'bearer'}, 200)
        return ResponseDocument(self.document, 200)


def run(path, transport):
    real = diagnostic.pricing_once
    def fake(credentials, **kwargs):
        return real(credentials, transport=transport, is_mock=True, **kwargs)
    with patch.object(diagnostic, 'load_credentials', return_value=CREDS), \
         patch.object(diagnostic, 'pricing_once', side_effect=fake):
        diagnostic.run_pricing_diagnostic(path, count_only=True)


def test_partial_placeholders_rejected_with_exact_counts_context_label_and_fixed_request(tmp_path, capsys):
    transport = Transport()
    with pytest.raises(AmazonFailure):
        run(tmp_path / 'amazon', transport)
    text = (tmp_path / 'amazon' / diagnostic.COUNT_REPORT_NAME).read_text()
    report = json.loads(text)
    assert report['validation_label'] == 'pricing_offer_details_invalid'
    assert report['failure_diagnostics']['validation_label'] == report['validation_label']
    assert report['response_diagnostics']['current_pricing']['http_status'] == 200
    assert report['count_shape']['total_offer_count'] == {'value': 7, 'type': 'integer', 'value_withheld': False}
    assert report['count_shape']['offers_count'] == 2
    assert report['count_shape']['expected_offers_count'] == 7
    assert report['count_shape']['application_status'] == 'Success'
    assert all(v is True for v in report['count_shape']['context'].values())
    assert report['pricing'] is None and 'response_shape' not in report
    assert SECRET not in text and 'SellerId' not in text
    assert report['requests_attempted'] == len(transport.requests) == 2
    offer = transport.requests[1]
    assert urlsplit(offer.full_url).path == '/products/pricing/v0/items/B0G1MJ24B4/offers'
    assert parse_qs(urlsplit(offer.full_url).query) == {'MarketplaceId': [pilot.MARKETPLACE],
        'ItemCondition': ['New'], 'CustomerType': ['Consumer']}
    assert [r.get_method() for r in transport.requests] == ['POST', 'GET']
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('count,kind,value', [(None, 'null', None), (False, 'boolean', False),
    (-1, 'integer', -1), (1.5, 'number', 1.5), (SECRET, 'string', None),
    ({SECRET: SECRET}, 'object', None), ([SECRET], 'array', None)])
def test_count_types_without_arbitrary_values(count, kind, value):
    facts = pricing_count_shape(response(count), expected_asin=diagnostic.COUNT_ASIN)
    assert facts['total_offer_count']['type'] == kind
    assert facts['total_offer_count']['value'] == value
    assert SECRET not in json.dumps(facts)


def test_absent_fields_are_distinct_and_status_is_allowlisted():
    data = response()
    del data['payload']['Summary']['TotalOfferCount']
    del data['payload']['Offers']
    del data['payload']['Identifier']['ASIN']
    data['payload']['ASIN'] = SECRET
    data['payload']['status'] = SECRET
    facts = pricing_count_shape(data, expected_asin=diagnostic.COUNT_ASIN)
    assert facts['total_offer_count']['type'] == 'absent'
    assert facts['offers_type'] == 'absent' and facts['offers_count'] is None
    assert facts['context']['payload_asin_matches'] is False
    assert facts['context']['identifier_asin_matches'] is None
    assert facts['application_status'] == 'OTHER'
    assert SECRET not in json.dumps(facts)


@pytest.mark.parametrize('change,label', [('ASIN', 'pricing_asin_mismatch'),
    ('marketplaceId', 'pricing_marketplace_mismatch'), ('ItemCondition', 'pricing_condition_mismatch'),
    ('currency', 'pricing_currency_not_usd')])
def test_validation_remains_strict_and_facts_survive(tmp_path, change, label):
    data = response(1, 1)
    if change == 'currency':
        data['payload']['Summary']['LowestPrices'] = [{'condition': 'new',
            'ListingPrice': {'CurrencyCode': 'EUR', 'Amount': 123.45}}]
    else:
        data['payload'][change] = SECRET
    with pytest.raises(AmazonFailure):
        run(tmp_path / 'amazon', Transport(data))
    text = (tmp_path / 'amazon' / diagnostic.COUNT_REPORT_NAME).read_text()
    report = json.loads(text)
    assert report['validation_label'] == label and report['count_shape']['offers_count'] == 1
    assert SECRET not in text and '123.45' not in text and 'EUR' not in text


def test_success_is_also_detail_free(tmp_path):
    data = response(21, 20)
    data['payload']['Summary']['LowestPrices'] = [{'condition': 'new',
        'ListingPrice': {'CurrencyCode': 'USD', 'Amount': 123.45}}]
    run(tmp_path / 'amazon', Transport(data))
    text = (tmp_path / 'amazon' / diagnostic.COUNT_REPORT_NAME).read_text()
    report = json.loads(text)
    assert report['status'] == 'success' and report['validation_label'] == 'pricing_validated'
    assert report['count_shape']['expected_offers_count'] == 20
    assert report['pricing'] is None
    assert SECRET not in text and '123.45' not in text


@pytest.mark.parametrize('fail_at', [1, 2])
def test_failure_has_no_retry_and_deadline_is_restored(tmp_path, fail_at):
    transport = Transport(fail_at=fail_at)
    with patch.object(diagnostic.signal, 'signal', return_value=diagnostic.signal.SIG_DFL) as handler, \
         patch.object(diagnostic.signal, 'alarm') as alarm:
        with pytest.raises(AmazonFailure):
            run(tmp_path / 'amazon', transport)
    assert len(transport.requests) == fail_at
    assert [c.args for c in alarm.call_args_list] == [(30,), (0,)]
    assert handler.call_args_list[-1].args == (diagnostic.signal.SIGALRM, diagnostic.signal.SIG_DFL)
    report = json.loads((tmp_path / 'amazon' / diagnostic.COUNT_REPORT_NAME).read_text())
    assert report['validation_label'] is None  # No parser validation happened.
    assert 'count_shape' not in report


def test_exclusive_private_report_preserves_all_prior_files_and_blocks_rerun(tmp_path):
    path = tmp_path / 'amazon'
    path.mkdir(mode=0o700)
    prior = ['credentials.json', diagnostic.REPORT_NAME, diagnostic.SHAPE_REPORT_NAME,
             'pricing-selected-pilot-B0G1MJ24B4-01.json']
    for name in prior:
        (path / name).write_text(SECRET)
    before = {name: (path / name).stat() for name in prior}
    run(path, Transport(response(0, 0)))
    target = path / diagnostic.COUNT_REPORT_NAME
    assert target.stat().st_mode & 0o777 == 0o600
    for name in prior:
        assert (path / name).read_text() == SECRET
        assert (path / name).stat().st_mtime_ns == before[name].st_mtime_ns
        assert (path / name).stat().st_ino == before[name].st_ino
    saved = target.read_bytes()
    with patch.object(diagnostic, 'load_credentials') as load, patch.object(diagnostic, 'pricing_once') as call:
        with pytest.raises(FileExistsError):
            diagnostic.run_pricing_diagnostic(path, count_only=True)
    load.assert_not_called()
    call.assert_not_called()
    assert target.read_bytes() == saved


def test_symlink_report_cannot_be_overwritten(tmp_path):
    path = tmp_path / 'amazon'
    path.mkdir(mode=0o700)
    sentinel = tmp_path / 'sentinel'
    sentinel.write_text(SECRET)
    (path / diagnostic.COUNT_REPORT_NAME).symlink_to(sentinel)
    with patch.object(diagnostic, 'load_credentials') as load:
        with pytest.raises(FileExistsError):
            diagnostic.run_pricing_diagnostic(path, count_only=True)
    load.assert_not_called()
    assert sentinel.read_text() == SECRET


def test_cli_fixed_scope_and_safe_failure_output(capsys):
    with patch('sys.argv', ['amazon_pilot', 'pricing-count-diagnostic']), \
         patch.object(diagnostic, 'run_pricing_diagnostic', side_effect=AmazonFailure(SECRET,
             reason='response_validation_failed', validation_label='pricing_offer_count_inconsistent')) as run_mock:
        assert pilot.main() == 1
    run_mock.assert_called_once_with(count_only=True)
    output = capsys.readouterr().out
    assert SECRET not in output and 'pricing_offer_count_inconsistent' in output


@pytest.mark.parametrize('extra', [['--asin', diagnostic.COUNT_ASIN], ['--fee-price', '25']])
def test_cli_rejects_other_scope_before_io(extra):
    with patch('sys.argv', ['amazon_pilot', 'pricing-count-diagnostic', *extra]), \
         patch.object(diagnostic, 'run_pricing_diagnostic') as run_mock:
        with pytest.raises(SystemExit):
            pilot.main()
    run_mock.assert_not_called()
