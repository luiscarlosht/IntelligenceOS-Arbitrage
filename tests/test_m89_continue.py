from copy import deepcopy
from pathlib import Path

import pytest

from app.m88_state import ledger, read, sha, write
from app.m88_targeted_state import prefix_sha
from app.m89_continue import ASIN, ResearchJournal, reconcile
from app import m89_continue as continuation
from app.amazon_diagnostics import AmazonFailure
from app.m88 import Stop


def journal(tmp_path):
    data = dict(pilot='m88-real-six-pilot', ceiling=49, purchase_authorized=False,
                includes_authentication_and_retries=True, attempts_used=11,
                attempts=[dict(number=i, status='COMPLETE', phase='detail', candidate_id='old', plan_sha256='old')
                          for i in range(1, 12)])
    path = tmp_path / 'ledger.json'
    write(path, data)
    return ResearchJournal(path, 'new', dict(prefix_sha256=prefix_sha(data['attempts']), baseline_sha256=sha(path)))


def test_reserve_durable_failure_counts_and_prevents_retry(tmp_path):
    j = journal(tmp_path)
    j.start()
    original = deepcopy(ledger(j.path)['attempts'])
    n = j.reserve('authentication', None)
    assert n == 12
    assert ledger(j.path)['attempts'][-1]['status'] == 'RESERVED'
    with pytest.raises(PermissionError):
        j.start()
    j.finish(n, 'FAILED', failure={'reason': 'authentication_failed'})
    assert ledger(j.path)['attempts_used'] == 12
    assert ledger(j.path)['attempts'][:11] == original
    with pytest.raises(PermissionError):
        j.reserve('authentication', None)
    with pytest.raises(PermissionError):
        j.reserve('offers', ASIN)


def test_bounded_scope_and_no_replay(tmp_path):
    j = journal(tmp_path)
    for phase, candidate in [('offers', ASIN), ('authentication', ASIN), ('search', ASIN)]:
        with pytest.raises(PermissionError):
            j.reserve(phase, candidate)
    for phase in ('authentication', 'restrictions', 'offers', 'fees_FBA', 'fees_FBM'):
        n = j.reserve(phase, None if phase == 'authentication' else ASIN)
        j.finish(n, 'COMPLETE')
    assert ledger(j.path)['attempts_used'] == 16
    with pytest.raises(PermissionError):
        j.reserve('fees_FBM', ASIN)
    data = read(j.path)
    data['attempts'][0]['candidate_id'] = 'tampered'
    write(j.path, data, replace=True)
    with pytest.raises(ValueError):
        j.history()


def test_independent_catalog_not_imported_amazon_upc():
    ids = [ASIN, 'B003SI0TD4', 'B0006BAFKI']
    baseline = dict(candidates=[dict(asin=a, amazon_evidence=dict(identifiers=[dict(identifier_type='UPC', value='021200471797')],
        model='600K3', size='3 Rolls', brand='Scotch')) for a in ids])
    research = dict(purchase_authorized=False, candidates=[dict(asin=a, walmart_upc='021200471797' if a == ASIN else 'conflict',
        amazon_upc='untrusted', walmart_model='600K3', walmart_item_id='21014274',
        retail_pack='3 boxes, one roll per box; each 0.75 in x 1000 in') for a in ids])
    rows = reconcile(research, baseline)
    assert rows[0]['classification'] == 'SUPPORTED_MATCH_WITH_SPEC_CAVEAT'
    assert rows[0]['verified_exact_match'] is False
    assert all(r['classification'] == 'NEEDS_REVIEW' for r in rows[1:])
    baseline['candidates'][0]['amazon_evidence']['identifiers'][0]['value'] = 'different'
    with pytest.raises(ValueError):
        reconcile(research, baseline)


def test_authentication_transport_failure_stops_all_endpoints_and_replay(tmp_path, monkeypatch):
    j = journal(tmp_path)
    credentials = tmp_path / 'credentials.json'
    write(credentials, {'test': 'fixture'})
    write(tmp_path / 'm67-account-context.json', dict(seller_id='TESTSELLER', marketplace_id='ATVPDKIKX0DER',
        condition='new_new', credentials_sha256=sha(credentials)))
    plan_path = tmp_path / 'plan.json'
    write(plan_path, dict(j.plan, private_root=str(tmp_path), ledger_path=str(j.path)))
    # Isolate dispatch accounting from separately tested evidence/contract preflight.
    monkeypatch.setattr(continuation, 'check', lambda plan: None)
    monkeypatch.setattr(continuation.pilot, 'load_credentials', lambda fd: dict(client_id='fixture', client_secret='fixture', refresh_token='fixture'))
    calls = []

    def fail(request):
        calls.append(request.full_url)
        assert ledger(j.path)['attempts'][-1]['status'] == 'RESERVED'
        raise AmazonFailure('fixture failure', reason='transport_error')

    with pytest.raises(Stop):
        continuation.execute(plan_path, sha(plan_path), transport=fail)
    assert calls == ['https://api.amazon.com/auth/o2/token']
    assert ledger(j.path)['attempts_used'] == 12
    assert ledger(j.path)['attempts'][-1]['status'] == 'FAILED'
    assert read(tmp_path / 'execution-status.json')['status'] == 'STOPPED_NO_RETRY'
    with pytest.raises(PermissionError):
        continuation.execute(plan_path, sha(plan_path), transport=fail)
    assert len(calls) == 1
