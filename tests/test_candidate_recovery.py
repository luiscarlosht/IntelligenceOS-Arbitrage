"""Offline claim and cooldown regression tests."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import pytest
from app import stored_candidate_search as stored
from app.amazon_pacing import OperationPacer
from test_stored_candidate_search import executable


def test_atomic_delegation_retains_owner_and_blocks_replay(tmp_path):
    _, private, _, path = executable(tmp_path)
    manifest = json.loads(path.read_text())
    directory = os.open(private, os.O_RDONLY | os.O_DIRECTORY)
    report = dict(status='failed_no_retry', attempts=[])
    original = stored.Reservations(directory, manifest, report)
    original.close()
    parent = manifest['source_sha256']
    manifest['source_sha256'] = 'recovery'
    manifest['recovery'] = dict(parent_run_key=parent)
    guard = stored.Reservations(directory, manifest, report)
    key = guard.search_key(manifest['requests'][0])
    assert guard.db.execute('SELECT run_key FROM candidate_operations WHERE request_key=?', (key,)).fetchone() == (parent,)
    assert guard.db.execute('SELECT delegate_run_key FROM candidate_delegations WHERE request_key=?', (key,)).fetchone() == ('recovery',)
    other = dict(manifest, source_sha256='concurrent')
    with pytest.raises(BlockingIOError):
        stored.Reservations(directory, other, report)
    guard.close()  # interruption before any request still consumes delegation
    with pytest.raises(ValueError):
        stored.Reservations(directory, other, report)
    with sqlite3.connect(private/'candidate-executions.sqlite3') as db:
        assert db.execute("SELECT 1 FROM candidate_executions WHERE run_key='concurrent'").fetchone() is None
    # A separately reviewed execution can recover only still unattempted work.
    other['recovery'] = dict(parent_run_key='recovery')
    recovered = stored.Reservations(directory, other, report)
    assert recovered.db.execute('SELECT count(*) FROM candidate_delegation_history WHERE request_key=?', (key,)).fetchone()[0] == 2
    recovered.close()
    with pytest.raises(sqlite3.IntegrityError): stored.Reservations(directory, other, report)
    os.close(directory)


def test_attempted_claim_rolls_back_whole_delegation(tmp_path):
    _, private, _, path = executable(tmp_path)
    manifest = json.loads(path.read_text())
    directory = os.open(private, os.O_RDONLY | os.O_DIRECTORY)
    report = dict(status='failed_no_retry', attempts=[])
    guard = stored.Reservations(directory, manifest, report)
    with guard.db:
        guard.db.execute("UPDATE candidate_operations SET state='reserved' WHERE request_key=?", (guard.search_key(manifest['requests'][-1]),))
    guard.close()
    manifest['recovery'] = dict(parent_run_key=manifest['source_sha256'])
    manifest['source_sha256'] = 'invalid-recovery'
    with pytest.raises(ValueError): stored.Reservations(directory, manifest, report)
    with sqlite3.connect(private/'candidate-executions.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM candidate_delegations').fetchone()[0] == 0
    os.close(directory)


def test_cooldown_and_429_diagnostics_survive_new_pacer(tmp_path):
    now = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    path = tmp_path/'state.sqlite3'
    first = OperationPacer(state_path=path, utcnow=now, monotonic=lambda: 0)
    first.observe('searchCatalogItems', 429, {'Retry-After': '120', 'x-amzn-ratelimit-limit': '100'})
    second = OperationPacer(state_path=path, utcnow=now, monotonic=lambda: 1000)
    assert second.not_before['searchCatalogItems'] == 1120
    second.observe('searchCatalogItems', 200, {})
    with sqlite3.connect(path) as db:
        diagnostic = json.loads(db.execute('SELECT diagnostics FROM amazon_cooldowns').fetchone()[0])
    assert diagnostic['http_status'] == 429
    assert first.rates['searchCatalogItems'] == 2


@pytest.mark.parametrize('interrupted', [False, True])
def test_recovery_stops_on_429_and_retains_remaining_claims(tmp_path, interrupted):
    from app import candidate_recovery as recovery
    from app.amazon_diagnostics import AmazonFailure
    from test_stored_candidate_search import CREDS
    _, private, _, path = executable(tmp_path)
    manifest = json.loads(path.read_text())
    calls = []
    def failed(request):
        calls.append(request)
        if len(calls) == 1: return dict(access_token='synthetic-access', token_type='bearer')
        raise AmazonFailure('quota', reason='http_error', http_status=429)
    parent = stored.run(path, stored.sha(path), transport=failed, credential_loader=lambda _: CREDS, is_mock=True, sleep=lambda _: None)
    report_path = private/('candidates-'+manifest['source_sha256']+'.json')
    if interrupted:
        snapshot = json.loads(report_path.read_text())
        snapshot['status'] = 'reserved'
        report_path.write_text('{')  # killed during report rewrite
        with sqlite3.connect(private/'candidate-executions.sqlite3') as db:
            db.execute("UPDATE candidate_executions SET status='reserved',checkpoint_json=?", (json.dumps(snapshot),))
    proposal = dict(parent_manifest=str(path), parent_manifest_sha256=stored.sha(path),
        original_report=str(report_path), original_report_sha256=stored.sha(report_path),
        source_database=manifest['source'], source_database_sha256=stored.sha(Path(manifest['source'])),
        parent_run_key=manifest['source_sha256'], evidence=[], shared_ledger=str(private/'candidate-executions.sqlite3'),
        prior_not_before_utc='2026-01-01T00:00:00+00:00', requests=[])
    for spec in manifest['requests'][1:]:
        proposal['requests'].append(dict(record_id=spec['record_id'], search=spec['search'], detail=spec['detail'], existing_reservation=dict(request_key=stored.Reservations.search_key(spec))))
    proposal_path = tmp_path/'proposal.json'; proposal_path.write_text(json.dumps(proposal))
    prepared, _ = recovery.prepare(proposal_path)
    recovery_path = tmp_path/'recovery.json'; recovery_path.write_text(json.dumps(prepared))
    calls.clear()
    result = recovery.run(recovery_path, stored.sha(recovery_path), 5, transport=failed,
        credential_loader=lambda _: CREDS, is_mock=True, sleep=lambda _: None)
    assert len(calls) == 2 and result['status'] == 'failed_no_retry'
    assert result['failure']['http_status'] == 429
    with sqlite3.connect(private/'candidate-executions.sqlite3') as db:
        states = dict(db.execute("SELECT request_key,state FROM candidate_operations WHERE kind='search'"))
        assert states[stored.Reservations.search_key(manifest['requests'][2])] == 'claimed_not_attempted'
    with pytest.raises(ValueError): recovery.verify(recovery_path, stored.sha(recovery_path), 5)
