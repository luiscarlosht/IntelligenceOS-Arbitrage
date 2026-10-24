import pytest

from app.keepa_pilot import prepare, read_pilot_key


def test_plan_bounds_and_does_not_load_credentials(monkeypatch):
    monkeypatch.setattr('app.keepa_pilot.getpass.getpass', lambda *_: pytest.fail('credential access'))
    plan = prepare(['B00000000' + str(i) for i in range(5)])
    assert plan['maximum_tokens'] == 5
    assert plan['actual_requests'] == plan['tokens_consumed'] == 0
    assert not plan['live_execution_available']
    for request, evidence in zip(plan['requests'], plan['evidence']):
        assert request['parameters']['update'] == -1
        assert request['maximum_attempts'] == 1
        assert 'key' not in request['parameters']
        assert evidence['seller_eligibility'] is evidence['fees'] is None


@pytest.mark.parametrize('asins', [['bad'], ['B000000001'] * 2,
                                 ['B00000000' + str(i) for i in range(6)]])
def test_invalid_selection(asins):
    with pytest.raises(ValueError):
        prepare(asins)


def test_empty_plan_does_not_invent_user_selection():
    assert prepare([])['requests'] == []


def test_secure_entry_rejects_noninteractive_input(monkeypatch):
    monkeypatch.setattr('app.keepa_pilot.sys.stdin.isatty', lambda: False)
    monkeypatch.setattr('app.keepa_pilot.getpass.getpass', lambda *_: pytest.fail('echo fallback'))
    with pytest.raises(ValueError):
        read_pilot_key()


def test_hidden_prompt_fails_closed_on_getpass_warning(monkeypatch):
    import warnings
    import getpass
    monkeypatch.setattr('app.keepa_pilot.sys.stdin.isatty', lambda: True)
    def fallback(*args):
        warnings.warn('cannot disable echo', getpass.GetPassWarning)
        pytest.fail('must not read echoed input')
    monkeypatch.setattr('app.keepa_pilot.getpass.getpass', fallback)
    with pytest.raises(getpass.GetPassWarning):
        read_pilot_key()


def test_runner_once_and_unknown_fields(tmp_path, monkeypatch):
    import json
    from app import keepa_pilot as pilot
    from app.keepa_adapter import KeepaResponse
    monkeypatch.setattr(pilot.keepa_adapter, 'LIVE_CALLS_ENABLED', True)
    marker = tmp_path / 'attempt'
    monkeypatch.setattr(pilot, 'ATTEMPT_MARKER', marker)
    monkeypatch.setattr(pilot, 'read_pilot_key', lambda: 'private-secret')
    calls = []
    def product(self):
        calls.append(self._key_loader())
        return KeepaResponse(200, json.dumps(dict(tokensConsumed=1, products=[dict(
            asin=pilot.PILOT_ASIN, domainId=1, title='Product title',
            lastUpdate=8000000, csv=[[8000000, 1299]])])).encode())
    monkeypatch.setattr(pilot.KeepaHttpTransport, 'pilot_product_once', product)
    result = pilot.run_once()
    assert result['title'] == 'Product title'
    assert result['price_usd'] == '12.99'
    assert result['price_observed_at'] is not None
    assert result['tokens_consumed'] == 1
    assert result['fees'] is result['seller_eligibility'] is None
    assert 'private-secret' not in json.dumps(result) + marker.read_text()
    with pytest.raises(ValueError):
        pilot.run_once()
    assert len(calls) == 1


def test_failed_attempt_cannot_be_retried(tmp_path, monkeypatch):
    from app import keepa_pilot as pilot
    monkeypatch.setattr(pilot.keepa_adapter, 'LIVE_CALLS_ENABLED', True)
    monkeypatch.setattr(pilot, 'ATTEMPT_MARKER', tmp_path / 'attempt')
    monkeypatch.setattr(pilot, 'read_pilot_key', lambda: 'secret')
    calls = []
    def fail(self):
        calls.append(1)
        raise TimeoutError('secret URL')
    monkeypatch.setattr(pilot.KeepaHttpTransport, 'pilot_product_once', fail)
    with pytest.raises(TimeoutError):
        pilot.run_once()
    with pytest.raises(ValueError):
        pilot.run_once()
    assert len(calls) == 1


@pytest.mark.parametrize('usage', [None, 2, -1, True])
def test_bad_usage_stops_without_raw_response(usage):
    import json
    from datetime import datetime, timezone
    from app.keepa_adapter import KeepaResponse
    from app.keepa_pilot import summarize
    reply = KeepaResponse(200, json.dumps(dict(tokensConsumed=usage,
        error={'message': 'secret URL'}, products=[])).encode())
    result = summarize(reply, datetime.now(timezone.utc))
    assert result['status'].startswith('stopped')
    assert 'secret' not in json.dumps(result)


def test_pilot_transport_fixed_basic_request_and_no_retry(monkeypatch):
    from urllib.parse import parse_qs, urlparse
    from app import keepa_http, keepa_adapter
    from app.provider_runtime import ProviderFailure
    calls = []
    class Opener:
        def open(self, req, timeout):
            calls.append((parse_qs(urlparse(req.full_url).query), timeout))
            raise RuntimeError('secret-in-url')
    monkeypatch.setattr(keepa_http, 'build_opener', lambda *args: Opener())
    assert keepa_adapter.LIVE_CALLS_ENABLED is False
    with pytest.raises(ProviderFailure, match='disabled'):
        keepa_http.KeepaHttpTransport(lambda: pytest.fail('key loaded')).pilot_product_once()
    assert calls == []
    monkeypatch.setattr(keepa_adapter, 'LIVE_CALLS_ENABLED', True)
    with pytest.raises(ProviderFailure, match='Keepa transport failed'):
        keepa_http.KeepaHttpTransport(lambda: 'test-secret').pilot_product_once()
    assert calls == [({'key': ['test-secret'], 'domain': ['1'], 'asin': ['B002XQ1R06'],
                       'update': ['-1'], 'history': ['1'], 'days': ['1']}, 10)]


def test_disabled_runner_never_reads_key_or_reserves_marker(tmp_path, monkeypatch):
    from app import keepa_pilot as pilot
    marker = tmp_path / 'attempt'
    monkeypatch.setattr(pilot, 'ATTEMPT_MARKER', marker)
    monkeypatch.setattr(pilot, 'read_pilot_key', lambda: pytest.fail('key loaded'))
    with pytest.raises(ValueError, match='disabled'):
        pilot.run_once()
    assert not marker.exists()
