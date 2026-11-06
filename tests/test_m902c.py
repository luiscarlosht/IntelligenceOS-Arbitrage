"""Pure synthetic cutover model: no production fixtures or operations."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import socket
import builtins
import os

import pytest
from app import m902c_cutover as m
from app.m902_history import canonical_hash

NOW = datetime(2026,11,6,tzinfo=timezone.utc)


@pytest.fixture
def sample():
    prior=dict(pilot='m88-real-six-pilot',ceiling=49,purchase_authorized=False,
               includes_authentication_and_retries=True,attempts_used=12,
               attempts=[dict(number=i,status='COMPLETE',phase='detail',candidate_id='SYNTHETIC')
                         for i in range(1,13)])
    value=dict(prior,m89_authentication_only='CLAIMED_NO_REPLAY',attempts_used=13,
        attempts=prior['attempts']+[dict(number=13,status='COMPLETE',phase='authentication',candidate_id=None,
            operation='m89-authentication-only',token_received=True,
            reserved_at=NOW.isoformat(),completed_at=NOW.isoformat())])
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    plan=m.Plan('a'*64,'b'*40,'c'*64,hashlib.sha256(raw).hexdigest(),canonical_hash(prior),999,
                ((1,101),(1,102),(1,103)))
    claim=m.Claim('d'*64,'EMBEDDED','synthetic-ledger-marker','e'*64,'m89-authentication-only',NOW,
                  True,m.Resolution.ACCOUNTED,plan.source_sha256,'f'*64,(13,))
    return plan,raw,(claim,)


def evidence(state,target,sample):
    plan,raw,claims=sample
    count=2 if target in (m.Phase.WRITERS_FROZEN,m.Phase.SOURCE_VERIFIED) else 3
    return m.Evidence(tuple((name,m.digest(name)) for name in m.REQUIRED[target]),
        m.LOCK_ORDER[:count],plan.lock_identities[:count],
        (m.Authority.NEW if target in (m.Phase.AUTHORITY_COMMITTED,m.Phase.POST_CUTOVER_VERIFIED) else m.Authority.OLD,),
        None if target is m.Phase.WRITERS_FROZEN else raw,
        () if target is m.Phase.WRITERS_FROZEN else claims,
        plan.runtime_sha256 if target in tuple(m.Phase)[6:] else None)


def approve(state,target,ev,nonce=None):
    return m.Approval(nonce or m.digest(target),m.digest(state.plan),state.sha256,m.digest(ev),target,
                      m.OPERATION,'synthetic-reviewer',999,NOW-timedelta(seconds=1),NOW+timedelta(minutes=5))


def walk(sample,until=m.Phase.POST_CUTOVER_VERIFIED):
    state=m.State(sample[0])
    for target in tuple(m.Phase)[1:]:
        ev=evidence(state,target,sample)
        state=m.advance(state,target,ev,approve(state,target,ev),NOW)
        assert state.authority is (m.Authority.NEW if target in tuple(m.Phase)[7:] else m.Authority.OLD)
        if target is until:return state
    return state


def test_all_legal_transitions_single_authority_bytes_claims(sample):
    state=walk(sample)
    assert state.source_bytes == state.destination_bytes == sample[1]
    assert state.source_bytes is state.destination_bytes
    assert state.claims == sample[2]
    assert len(state.receipts)==len(set(state.used_nonces))==8
    result=m.verify_destination_model(state,sample[1],sample[2],runtime_sha256=sample[0].runtime_sha256,
                                     peer_uid=999,operation=m.OPERATION)
    assert result['live_enabled'] is False and result['attempts_used']==13
    assert result['purchase_authorized'] is False


@pytest.mark.parametrize('target',tuple(m.Phase)[2:])
def test_illegal_jump(sample,target):
    state=m.State(sample[0]);ev=evidence(state,target,sample)
    with pytest.raises(m.Blocked):m.advance(state,target,ev,approve(state,target,ev),NOW)


@pytest.mark.parametrize('target',tuple(m.Phase)[1:])
def test_duplicate_authorities(sample,target):
    before=tuple(m.Phase)[tuple(m.Phase).index(target)-1]
    state=m.State(sample[0]) if before is m.Phase.PRECHECK else walk(sample,before)
    ev=replace(evidence(state,target,sample),authorities=(m.Authority.OLD,m.Authority.NEW))
    with pytest.raises(m.Blocked):m.advance(state,target,ev,approve(state,target,ev),NOW)


@pytest.mark.parametrize('phase',tuple(m.Phase))
def test_interruption_every_transition_terminal(sample,phase):
    state=m.State(sample[0]) if phase is m.Phase.PRECHECK else walk(sample,phase)
    stopped=m.interrupt(state)
    assert stopped.claims==state.claims and stopped.receipts==state.receipts
    assert stopped.authority is state.authority
    expected='MANUAL_FIX_FORWARD_ONLY' if state.authority is m.Authority.NEW else 'PRESERVE_OLD_KEEP_WRITERS_FROZEN'
    assert m.recovery_action(stopped)==expected
    if phase is not m.Phase.POST_CUTOVER_VERIFIED:
        target=tuple(m.Phase)[tuple(m.Phase).index(phase)+1];ev=evidence(state,target,sample)
        with pytest.raises(m.Blocked):m.advance(stopped,target,ev,approve(stopped,target,ev),NOW)


def test_failed_manifest_commit_is_unknown_no_fallback(sample):
    state=walk(sample,m.Phase.RUNTIME_ATTESTED)
    stopped=m.interrupt(state,commit_uncertain=True)
    assert stopped.authority is m.Authority.UNKNOWN
    assert m.recovery_action(stopped)=='INVESTIGATE_MANIFEST_NO_WRITERS'
    with pytest.raises(m.Blocked):m.interrupt(walk(sample),commit_uncertain=True)


@pytest.mark.parametrize('target',tuple(m.Phase)[1:])
def test_missing_fsync_or_required_evidence(sample,target):
    before=tuple(m.Phase)[tuple(m.Phase).index(target)-1]
    state=m.State(sample[0]) if before is m.Phase.PRECHECK else walk(sample,before)
    ev=replace(evidence(state,target,sample),artifacts=())
    with pytest.raises(m.Blocked):m.advance(state,target,ev,approve(state,target,ev),NOW)
    assert state.authority is (m.Authority.NEW if before is m.Phase.AUTHORITY_COMMITTED else m.Authority.OLD)


@pytest.mark.parametrize('field,value',[('operation','shell'),('requester_uid',1000),('requester_uid',True),
    ('previous_sha256','0'*64),('plan_sha256','0'*64),('evidence_sha256','0'*64),
    ('expires_at',NOW),('approved_at',NOW+timedelta(seconds=1))])
def test_approval_binding(sample,field,value):
    state=m.State(sample[0]);target=m.Phase.WRITERS_FROZEN;ev=evidence(state,target,sample)
    approval=replace(approve(state,target,ev),**{field:value})
    with pytest.raises(m.Blocked) as error:m.advance(state,target,ev,approval,NOW)
    assert str(error.value)=='CUTOVER_BLOCKED'


def test_replay_nonce(sample):
    state=walk(sample,m.Phase.WRITERS_FROZEN);target=m.Phase.SOURCE_VERIFIED;ev=evidence(state,target,sample)
    with pytest.raises(m.Blocked):m.advance(state,target,ev,approve(state,target,ev,state.used_nonces[0]),NOW)


@pytest.mark.parametrize('bad_locks',[m.LOCK_ORDER[::-1],m.LOCK_ORDER[:1],(),m.LOCK_ORDER[:2]+('OTHER',)])
def test_lock_order(sample,bad_locks):
    state=walk(sample,m.Phase.SOURCE_VERIFIED);target=m.Phase.DESTINATION_STAGED
    ev=replace(evidence(state,target,sample),held_locks=bad_locks)
    with pytest.raises(m.Blocked):m.advance(state,target,ev,approve(state,target,ev),NOW)


@pytest.mark.parametrize('target',[m.Phase.SOURCE_VERIFIED,m.Phase.DESTINATION_STAGED,m.Phase.DESTINATION_VERIFIED])
@pytest.mark.parametrize('bad',[b'interrupted-read',b'{}',b' '])
def test_ledger_mismatch_or_copy_failure(sample,target,bad):
    before=tuple(m.Phase)[tuple(m.Phase).index(target)-1]
    state=walk(sample,before);ev=replace(evidence(state,target,sample),ledger_bytes=bad)
    with pytest.raises(m.Blocked):m.advance(state,target,ev,approve(state,target,ev),NOW)
    assert state.authority is m.Authority.OLD


@pytest.mark.parametrize('problem',['missing','conflict','unresolved','missing_evidence','future_consumed','wrong_binding'])
def test_claim_reconciliation(sample,problem):
    plan,raw,claims=sample;claim=claims[0]
    if problem=='missing':changed=()
    elif problem=='conflict':
        variants=((claim,replace(claim,consumed=False)),
                  (claim,replace(claim,claim_id='1'*64)),
                  (claim,replace(claim,claim_id='1'*64,origin_kind='PROTECTED',
                                 origin_ref='distinct-origin',consumed=False)))
        for variant in variants:
            with pytest.raises(m.Blocked):walk((plan,raw,variant))
        return
    elif problem=='unresolved':changed=(replace(claim,resolution=m.Resolution.UNRESOLVED),)
    elif problem=='missing_evidence':changed=(replace(claim,evidence_sha256=None),)
    elif problem=='future_consumed':changed=(claim,replace(claim,claim_id='1'*64,origin_kind='PROTECTED',
        operation='m902',attempts=(14,),resolution=m.Resolution.FUTURE_CONSUMED))
    else:changed=(replace(claim,ledger_sha256='0'*64),)
    altered=(plan,raw,changed)
    with pytest.raises(m.Blocked):walk(altered)


def test_claim_cannot_disappear_after_snapshot(sample):
    state=walk(sample,m.Phase.SOURCE_VERIFIED);target=m.Phase.DESTINATION_STAGED
    ev=replace(evidence(state,target,sample),claims=())
    with pytest.raises(m.Blocked):m.advance(state,target,ev,approve(state,target,ev),NOW)


@pytest.mark.parametrize('field,value',[('runtime_sha256','0'*64),('peer_uid',1),('peer_uid',True),('operation','PURCHASE')])
def test_successor_verifier_binding(sample,field,value):
    state=walk(sample);args=dict(runtime_sha256=sample[0].runtime_sha256,peer_uid=999,operation=m.OPERATION)
    args[field]=value
    with pytest.raises(m.Blocked):m.verify_destination_model(state,sample[1],sample[2],**args)


def test_runtime_attestation_mismatch(sample):
    state=walk(sample,m.Phase.CLAIMS_RECONCILED);target=m.Phase.RUNTIME_ATTESTED
    ev=replace(evidence(state,target,sample),runtime_sha256='0'*64)
    with pytest.raises(m.Blocked):m.advance(state,target,ev,approve(state,target,ev),NOW)


def test_forged_or_rolled_back_state_cannot_verify(sample):
    state=walk(sample)
    for altered in (replace(state,authority=m.Authority.OLD),replace(state,receipts=('0'*64,)*8),
                    replace(state,events=state.events[:-1]),replace(state,claims=())):
        with pytest.raises(m.Blocked):m.verify_destination_model(altered,sample[1],sample[2],
            runtime_sha256=sample[0].runtime_sha256,peer_uid=999,operation=m.OPERATION)


def test_no_filesystem_network_or_credential_operations(sample,monkeypatch):
    def forbidden(*args,**kwargs):pytest.fail('I/O attempted')
    for name in ('open','stat','lstat','rename','replace','unlink','mkdir','chmod','chown'):
        monkeypatch.setattr(os,name,forbidden)
    monkeypatch.setattr(builtins,'open',forbidden)
    monkeypatch.setattr(socket,'getaddrinfo',forbidden)
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    state=walk(sample)
    assert state.authority is m.Authority.NEW
