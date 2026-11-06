"""Pure Strategy B review model. No filesystem, network, credentials or CLI.

Receipts/approvals supplied here are synthetic assertions, NOT authenticated host
proof. A future privileged adapter must independently establish each receipt.
There is deliberately no production source-reader, migration or cutover command.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
import hashlib
import json
import re

from app.m902_history import validate_snapshot

SOURCE = '/var/lib/intelligenceos-arbitrage/m89/ledger.json'
DESTINATION = '/var/lib/intelligenceos-arbitrage-protected/m89/ledger.json'
MANIFEST = '/var/lib/intelligenceos-arbitrage-protected/authority/manifest.json'
ACCOUNT_LOCK = '/root/.intelligenceos-arbitrage-amazon/candidate-execution.lock'
LOCK_ORDER = (ACCOUNT_LOCK, '/var/lib/intelligenceos-arbitrage/m89/ledger.lock',
              '/var/lib/intelligenceos-arbitrage-protected/m89/ledger.lock')
OPERATION = 'M902C_OFFLINE_TRANSITION'


class Blocked(Exception):
    """Fixed sanitized diagnostic only."""


class Phase(str, Enum):
    PRECHECK = 'PRECHECK'
    WRITERS_FROZEN = 'WRITERS_FROZEN'
    SOURCE_VERIFIED = 'SOURCE_VERIFIED'
    DESTINATION_STAGED = 'DESTINATION_STAGED'
    DESTINATION_VERIFIED = 'DESTINATION_VERIFIED'
    CLAIMS_RECONCILED = 'CLAIMS_RECONCILED'
    RUNTIME_ATTESTED = 'RUNTIME_ATTESTED'
    AUTHORITY_COMMITTED = 'AUTHORITY_COMMITTED'
    POST_CUTOVER_VERIFIED = 'POST_CUTOVER_VERIFIED'


class Authority(str, Enum):
    OLD = 'OLD'
    NEW = 'NEW'
    UNKNOWN = 'UNKNOWN_NO_WRITERS'


class Resolution(str, Enum):
    ACCOUNTED = 'HISTORICAL_ACCOUNTED'
    UNRESOLVED = 'UNRESOLVED'
    FUTURE_CONSUMED = 'FUTURE_CONSUMED'


REQUIRED = {
    Phase.WRITERS_FROZEN: ('maintenance_freeze', 'writer_inventory', 'claim_scope_inventory'),
    Phase.SOURCE_VERIFIED: ('source_descriptor_audit', 'source_metadata_review'),
    Phase.DESTINATION_STAGED: ('copy_file_fsync', 'copy_directory_fsync', 'new_ledger_lock_review'),
    Phase.DESTINATION_VERIFIED: ('destination_descriptor_audit', 'source_recheck'),
    Phase.CLAIMS_RECONCILED: ('claim_reconciliation', 'claim_inventory_completeness'),
    Phase.RUNTIME_ATTESTED: ('runtime_attestation', 'requester_isolation', 'network_policy_review'),
    Phase.AUTHORITY_COMMITTED: ('manifest_file_fsync', 'manifest_directory_fsync', 'old_writer_retirement'),
    Phase.POST_CUTOVER_VERIFIED: ('post_cutover_descriptor_audit',),
}


def digest(value) -> str:
    """Canonical digest for model documents, never ledger reserialization."""
    def encode(item):
        if isinstance(item, datetime): return item.isoformat()
        if type(item) is bytes: return dict(bytes_sha256=hashlib.sha256(item).hexdigest(), length=len(item))
        if hasattr(item, '__dataclass_fields__'):
            return {key: getattr(item, key) for key in item.__dataclass_fields__}
        raise TypeError()
    return hashlib.sha256(json.dumps(value, default=encode, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _hash(value, length=64):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{'+str(length)+'}', value):
        raise Blocked('CUTOVER_BLOCKED')


def _text(value):
    if type(value) is not str or not 1 <= len(value) <= 2048 or value.strip() != value or not value.isprintable():
        raise Blocked('CUTOVER_BLOCKED')


def _aware(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise Blocked('CUTOVER_BLOCKED')


@dataclass(frozen=True)
class Plan:
    migration_id: str
    release_commit: str
    runtime_sha256: str
    source_sha256: str
    prefix_sha256: str
    requester_uid: int
    # Three separately reviewed existing/provisioned ledger/account identities.
    lock_identities: tuple[tuple[int, int], ...]
    source_path: str = field(default=SOURCE, init=False)
    destination_path: str = field(default=DESTINATION, init=False)
    manifest_path: str = field(default=MANIFEST, init=False)
    lock_paths: tuple[str, ...] = field(default=LOCK_ORDER, init=False)

    def __post_init__(self):
        for value in (self.migration_id, self.runtime_sha256, self.source_sha256, self.prefix_sha256): _hash(value)
        _hash(self.release_commit, 40)
        if type(self.requester_uid) is not int or not 0 < self.requester_uid < 2**32-1:
            raise Blocked('CUTOVER_BLOCKED')
        if type(self.lock_identities) is not tuple or len(self.lock_identities) != 3:
            raise Blocked('CUTOVER_BLOCKED')
        for pair in self.lock_identities:
            if (type(pair) is not tuple or len(pair) != 2
                    or any(type(x) is not int or not 0 <= x < 2**64 for x in pair) or pair[1] == 0):
                raise Blocked('CUTOVER_BLOCKED')
        if len(set(self.lock_identities)) != 3:
            raise Blocked('CUTOVER_BLOCKED')


@dataclass(frozen=True)
class Claim:
    claim_id: str
    origin_kind: str
    origin_ref: str
    identity_sha256: str
    operation: str
    timestamp: datetime
    consumed: bool | None
    resolution: Resolution
    ledger_sha256: str | None
    evidence_sha256: str | None
    attempts: tuple[int, ...]

    def __post_init__(self):
        _hash(self.claim_id); _hash(self.identity_sha256)
        for value in (self.origin_ref, self.operation): _text(value)
        _aware(self.timestamp)
        if self.origin_kind not in ('EMBEDDED', 'SOURCE', 'RELEASE', 'PROTECTED', 'EXTERNAL'):
            raise Blocked('CUTOVER_BLOCKED')
        if self.consumed is not None and type(self.consumed) is not bool: raise Blocked('CUTOVER_BLOCKED')
        if type(self.resolution) is not Resolution: raise Blocked('CUTOVER_BLOCKED')
        for value in (self.ledger_sha256, self.evidence_sha256):
            if value is not None: _hash(value)
        if (type(self.attempts) is not tuple or len(set(self.attempts)) != len(self.attempts)
                or any(type(x) is not int or not 1 <= x <= 49 for x in self.attempts)):
            raise Blocked('CUTOVER_BLOCKED')


@dataclass(frozen=True)
class Evidence:
    # Exact required receipt names with digests; no boolean "confirmed" shortcuts.
    artifacts: tuple[tuple[str, str], ...]
    held_locks: tuple[str, ...]
    lock_identities: tuple[tuple[int, int], ...]
    authorities: tuple[Authority, ...]
    ledger_bytes: bytes | None = None
    claims: tuple[Claim, ...] = ()
    runtime_sha256: str | None = None


@dataclass(frozen=True)
class Approval:
    nonce: str
    plan_sha256: str
    previous_sha256: str
    evidence_sha256: str
    target: Phase
    operation: str
    reviewer: str
    requester_uid: int
    approved_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class Event:
    target: Phase
    evidence: Evidence
    approval: Approval
    observed_at: datetime


@dataclass(frozen=True)
class State:
    plan: Plan
    phase: Phase = Phase.PRECHECK
    authority: Authority = Authority.OLD
    source_bytes: bytes | None = None
    destination_bytes: bytes | None = None
    claims: tuple[Claim, ...] = ()
    receipts: tuple[str, ...] = ()
    used_nonces: tuple[str, ...] = ()
    blocked: bool = False
    events: tuple[Event, ...] = ()

    @property
    def sha256(self) -> str:
        # Bind byte digests, not decoded/reformatted historical contents.
        return digest(dict(plan=self.plan, phase=self.phase, authority=self.authority,
            source=None if self.source_bytes is None else hashlib.sha256(self.source_bytes).hexdigest(),
            destination=None if self.destination_bytes is None else hashlib.sha256(self.destination_bytes).hexdigest(),
            claims=self.claims, receipts=self.receipts, used_nonces=self.used_nonces, blocked=self.blocked))


def _claims(claims, plan, *, reconciled=False):
    if type(claims) is not tuple or any(type(c) is not Claim for c in claims): raise Blocked('CUTOVER_BLOCKED')
    if len({c.claim_id for c in claims}) != len(claims): raise Blocked('CUTOVER_BLOCKED')
    if len({(c.origin_kind, c.origin_ref, c.operation) for c in claims}) != len(claims):
        raise Blocked('CUTOVER_BLOCKED')
    if not any(c.origin_kind == 'EMBEDDED' and c.operation == 'm89-authentication-only'
               and c.attempts == (13,) and c.consumed is True for c in claims):
        raise Blocked('CUTOVER_BLOCKED')
    if reconciled:
        for claim in claims:
            if (claim.resolution is not Resolution.ACCOUNTED or claim.consumed is not True
                    or claim.evidence_sha256 is None or claim.ledger_sha256 != plan.source_sha256
                    or not claim.attempts or any(x > 13 for x in claim.attempts)):
                raise Blocked('CUTOVER_BLOCKED')


def _advance(state: State, target: Phase, evidence: Evidence, approval: Approval, now: datetime) -> State:
    _aware(now)
    if type(state) is not State or type(target) is not Phase or state.blocked:
        raise Blocked('CUTOVER_BLOCKED')
    sequence = tuple(Phase)
    if sequence.index(target) != sequence.index(state.phase)+1: raise Blocked('CUTOVER_BLOCKED')
    if state.authority is not (Authority.NEW if state.phase in sequence[7:] else Authority.OLD):
        raise Blocked('CUTOVER_BLOCKED')
    if type(evidence) is not Evidence or type(approval) is not Approval: raise Blocked('CUTOVER_BLOCKED')
    _hash(approval.nonce); _text(approval.reviewer); _aware(approval.approved_at); _aware(approval.expires_at)
    if (approval.operation != OPERATION or approval.target is not target
            or approval.plan_sha256 != digest(state.plan) or approval.previous_sha256 != state.sha256
            or approval.evidence_sha256 != digest(evidence)
            or type(approval.requester_uid) is not int or approval.requester_uid != state.plan.requester_uid
            or not approval.approved_at <= now < approval.expires_at
            or not 0 < (approval.expires_at-approval.approved_at).total_seconds() <= 3600
            or approval.nonce in state.used_nonces):
        raise Blocked('CUTOVER_BLOCKED')
    count = 2 if target in sequence[1:3] else 3
    expected_authority = Authority.NEW if target in sequence[7:] else Authority.OLD
    if (evidence.held_locks != LOCK_ORDER[:count] or evidence.lock_identities != state.plan.lock_identities[:count]
            or evidence.authorities != (expected_authority,)
            or type(evidence.artifacts) is not tuple
            or tuple(name for name, _ in evidence.artifacts) != REQUIRED[target]):
        raise Blocked('CUTOVER_BLOCKED')
    for _, receipt in evidence.artifacts: _hash(receipt)
    source, destination, claims = state.source_bytes, state.destination_bytes, state.claims
    if target is Phase.WRITERS_FROZEN:
        if evidence.ledger_bytes is not None or evidence.claims: raise Blocked('CUTOVER_BLOCKED')
    elif target is Phase.SOURCE_VERIFIED:
        validate_snapshot(evidence.ledger_bytes, state.plan.source_sha256, state.plan.prefix_sha256)
        _claims(evidence.claims, state.plan)
        source, claims = evidence.ledger_bytes, evidence.claims
    else:
        if evidence.claims != claims or evidence.ledger_bytes != source: raise Blocked('CUTOVER_BLOCKED')
        if target is Phase.DESTINATION_STAGED: destination = evidence.ledger_bytes
        if destination != source or source is None: raise Blocked('CUTOVER_BLOCKED')
        if target in sequence[5:]: _claims(claims, state.plan, reconciled=True)
    if target in sequence[6:] and evidence.runtime_sha256 != state.plan.runtime_sha256:
        raise Blocked('CUTOVER_BLOCKED')
    receipt = digest(dict(previous=state.sha256, target=target, evidence=digest(evidence), approval=approval))
    return replace(state, phase=target, authority=expected_authority, source_bytes=source,
        destination_bytes=destination, claims=claims, receipts=state.receipts+(receipt,),
        used_nonces=state.used_nonces+(approval.nonce,),
        events=state.events+(Event(target, evidence, approval, now),))


def _validate_state(state: State):
    if type(state) is not State or type(state.plan) is not Plan or type(state.events) is not tuple:
        raise Blocked('CUTOVER_BLOCKED')
    rebuilt = State(state.plan)
    for event in state.events:
        if type(event) is not Event: raise Blocked('CUTOVER_BLOCKED')
        rebuilt = _advance(rebuilt, event.target, event.evidence, event.approval, event.observed_at)
    if state.blocked:
        if (type(state.blocked) is not bool
                or state.authority not in (rebuilt.authority, Authority.UNKNOWN)
                or (state.authority is Authority.UNKNOWN and state.phase is not Phase.RUNTIME_ATTESTED)):
            raise Blocked('CUTOVER_BLOCKED')
        rebuilt = replace(rebuilt, blocked=True, authority=state.authority)
    if rebuilt != state: raise Blocked('CUTOVER_BLOCKED')


def advance(state: State, target: Phase, evidence: Evidence, approval: Approval, now: datetime) -> State:
    try:
        _validate_state(state)
        return _advance(state, target, evidence, approval, now)
    except Exception:
        raise Blocked('CUTOVER_BLOCKED') from None


def interrupt(state: State, *, commit_uncertain=False) -> State:
    """Terminal model outcome; no recovery/automatic restart transition exists."""
    _validate_state(state)
    if type(commit_uncertain) is not bool or state.blocked: raise Blocked('CUTOVER_BLOCKED')
    if commit_uncertain and state.phase is not Phase.RUNTIME_ATTESTED: raise Blocked('CUTOVER_BLOCKED')
    return replace(state, blocked=True,
                   authority=Authority.UNKNOWN if commit_uncertain else state.authority)


def recovery_action(state: State) -> str:
    _validate_state(state)
    if not state.blocked: raise Blocked('CUTOVER_BLOCKED')
    return {Authority.OLD: 'PRESERVE_OLD_KEEP_WRITERS_FROZEN',
            Authority.NEW: 'MANUAL_FIX_FORWARD_ONLY',
            Authority.UNKNOWN: 'INVESTIGATE_MANIFEST_NO_WRITERS'}[state.authority]


def verify_destination_model(state: State, ledger: bytes, claims: tuple[Claim, ...], *,
                             runtime_sha256: str, peer_uid: int, operation: str) -> dict:
    """Pure successor-verifier predicate, not a filesystem verifier or authorization."""
    try:
        _validate_state(state)
        if (state.blocked or state.phase is not Phase.POST_CUTOVER_VERIFIED or state.authority is not Authority.NEW
                or type(peer_uid) is not int or peer_uid != state.plan.requester_uid or operation != OPERATION
                or runtime_sha256 != state.plan.runtime_sha256 or ledger != state.destination_bytes
                or claims != state.claims or len(state.receipts) != 8 or len(set(state.used_nonces)) != 8):
            raise ValueError()
        validate_snapshot(ledger, state.plan.source_sha256, state.plan.prefix_sha256)
        _claims(claims, state.plan, reconciled=True)
        return dict(status='MODEL_VERIFIED_NOT_AUTHORIZATION', authority='NEW', attempts_used=13,
                    ceiling=49, remaining=36, purchase_authorized=False, live_enabled=False)
    except Exception:
        raise Blocked('CUTOVER_BLOCKED') from None
