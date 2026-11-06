"""Filesystem-backed synthetic authority infrastructure. NO production entry point.

Only /tmp FixtureFS instances are accepted. Every result is synthetic, never
operational authorization. No transport, credential, shell or executable interface.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import os
import stat

from app import m903a_contract as c
from app.m903a_fs import FixtureFS, Blocked, identity, metadata
from app.m902_history import validate_snapshot, MAX_LEDGER
from app import m902c_cutover as model


def protected(function):
    def boundary(*args, **kwargs):
        try:return function(*args, **kwargs)
        except BaseException:raise Blocked('AUTHORITY_BLOCKED') from None
    return boundary


def file_identity(fs, name):
    with fs.opened(name) as fd:
        device,inode=identity(os.fstat(fd))
        return dict(device=device,inode=inode)


@dataclass(frozen=True)
class Context:
    migration_id: str
    generation: int
    ledger_sha256: str
    prefix_sha256: str
    claims_sha256: str
    runtime_sha256: str
    release_commit: str
    requester_uid: int
    account_lock_identity: dict
    source_lock_identity: dict
    destination_lock_identity: dict
    source_identity: dict
    retirement_sha256: str

    def __post_init__(self):
        for value in (self.migration_id,self.ledger_sha256,self.prefix_sha256,self.claims_sha256,
                      self.runtime_sha256,self.retirement_sha256):c.hashed(value)
        c.hashed(self.release_commit,40);c.number(self.generation,positive=True);c.number(self.requester_uid,positive=True)
        for value in (self.account_lock_identity,self.source_lock_identity,self.destination_lock_identity,self.source_identity):c.identity(value)


class Quality(str,Enum):
    SYNTHETIC_ASSERTION='SYNTHETIC_ASSERTION'
    DURABLE_SYNTHETIC='DURABLE_SYNTHETIC'
    INDEPENDENTLY_VERIFIED='INDEPENDENTLY_VERIFIED'
    MISSING='MISSING'
    UNCERTAIN='UNCERTAIN'
    CONFLICTING='CONFLICTING'


@dataclass(frozen=True)
class RetainedCheckpoint:
    migration_id: str
    generation: int
    sequence: int
    journal_sha256: str
    registry_sha256: str
    decision: str


def checkpoint_receipt(value):
    return RetainedCheckpoint(value['migration_id'],value['generation'],value['sequence'],
                              value['journal_sha256'],c.sha(c.canonical(value)),value['decision'])


@dataclass(frozen=True)
class Receipt:
    digest: str
    quality: Quality
    checkpoint: RetainedCheckpoint | None = None


@dataclass(frozen=True, repr=False)
class AuditedSnapshot:
    # Internal copy payload, not an IPC/diagnostic result. Repr/report omit bytes.
    _ledger_bytes: bytes
    _claim_bytes: bytes
    receipt: Receipt

    def __repr__(self):return 'AuditedSnapshot(SYNTHETIC_ONLY)'

    def report(self):
        return dict(status='SYNTHETIC_SOURCE_VERIFIED',attempts_used=13,ceiling=49,remaining=36,
                    purchase_authorized=False,source_trust='APPLICATION_OWNED_SYNTHETIC_FREEZE',
                    production_qualified=False)


@dataclass(frozen=True)
class FreezeReview:
    migration_id: str
    generation: int
    reviewed_profiles: dict
    evidence_sha256: str
    expires_at: datetime
    quality: Quality


class SourceFixtureFS(FixtureFS):
    """Separate weaker source profile; never changes root-only verifier/storage."""
    def __init__(self,root,review:FreezeReview,*,now:datetime):
        if (type(review) is not FreezeReview or review.quality is not Quality.SYNTHETIC_ASSERTION
                or type(now) is not datetime or now.tzinfo is None or review.expires_at.tzinfo is None
                or now>=review.expires_at or not review.reviewed_profiles):
            raise Blocked('SOURCE_TRUST_UNAVAILABLE')
        c.hashed(review.migration_id);c.hashed(review.evidence_sha256);c.number(review.generation,positive=True)
        self.review=review
        super().__init__(root)

    def validate(self,info,*,directory=False):
        expected=self.review.reviewed_profiles.get(identity(info))
        if (expected is None or expected != (info.st_uid,info.st_mode & 0o7777,info.st_ctime_ns)
                or (info.st_mode & 0o022) or (not directory and (info.st_nlink!=1 or (info.st_mode&0o7777)!=0o600))):
            raise Blocked('SOURCE_TRUST_UNAVAILABLE')
        # Type is checked independently of the permitted owner/profile.
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise Blocked('SOURCE_TRUST_UNAVAILABLE')

    def mkdir(self,*_args,**_kwargs):raise Blocked('READ_ONLY_SOURCE')
    def create(self,*_args,**_kwargs):raise Blocked('READ_ONLY_SOURCE')
    def publish(self,*_args,**_kwargs):raise Blocked('READ_ONLY_SOURCE')


def tuple_id(value):return value['device'],value['inode']


def parse_claims(raw,ctx):
    value=c.load(raw,c.MAX_REGISTRY)
    c.exact(value,('version','migration_id','generation','claims'));c.common(value)
    if value['migration_id']!=ctx.migration_id or value['generation']!=ctx.generation or type(value['claims']) is not list:
        raise ValueError('CLAIMS_BLOCKED')
    parsed=[]
    keys=('claim_id','origin_kind','origin_ref','identity_sha256','operation','timestamp','consumed','resolution',
          'ledger_sha256','evidence_sha256','attempts')
    for record in value['claims']:
        c.exact(record,keys)
        item=dict(record)
        if type(item['timestamp']) is not str or type(item['attempts']) is not list:raise ValueError('CLAIMS_BLOCKED')
        item['timestamp']=datetime.fromisoformat(item['timestamp'])
        item['attempts']=tuple(item['attempts']);item['resolution']=model.Resolution(item['resolution'])
        parsed.append(model.Claim(**item))
    _claim_check(tuple(parsed),ctx)
    if c.sha(raw)!=ctx.claims_sha256:raise ValueError('CLAIMS_BLOCKED')
    return tuple(parsed)


def _claim_check(claims,ctx):
    # Minimal immutable view expected by the existing pure model; no weakening.
    @dataclass(frozen=True)
    class Binding:source_sha256:str
    model._claims(claims,Binding(ctx.ledger_sha256),reconciled=True)


@protected
def audit_source(source:SourceFixtureFS,ctx:Context,*,now:datetime):
    if (type(source) is not SourceFixtureFS or source.review.migration_id!=ctx.migration_id
            or source.review.generation!=ctx.generation or now>=source.review.expires_at):
        raise ValueError('SOURCE_TRUST_UNAVAILABLE')
    with source.lock('account/candidate-execution.lock',tuple_id(ctx.account_lock_identity)), source.lock('m89/ledger.lock',tuple_id(ctx.source_lock_identity)):
        if source.entries('m89')!=['claim-index.json','ledger.json','ledger.lock']:raise ValueError('UNKNOWN_SOURCE_ARTIFACT')
        if file_identity(source,'m89/ledger.json')!=ctx.source_identity:raise ValueError('SOURCE_IDENTITY_BLOCKED')
        raw=source.read('m89/ledger.json',MAX_LEDGER)
        validate_snapshot(raw,ctx.ledger_sha256,ctx.prefix_sha256)
        claims=source.read('m89/claim-index.json',c.MAX_REGISTRY);parse_claims(claims,ctx)
        source.check()
        return AuditedSnapshot(raw,claims,Receipt(c.sha(raw+claims),Quality.DURABLE_SYNTHETIC))


def provision_destination(fs:FixtureFS):
    """Explicit fixture-only provisioning; never called by readers/verifiers."""
    if type(fs) is not FixtureFS or fs.entries():raise Blocked('PROVISIONING_BLOCKED')
    for name in ('authority','m89','claims','journal','evidence'):fs.mkdir(name)
    fs.create('m89/ledger.lock',b'',label='provision_ledger_lock')


def provision_registry(fs:FixtureFS,ctx:Context):
    if type(fs) is not FixtureFS or fs.entries():raise Blocked('PROVISIONING_BLOCKED')
    fs.create('checkpoint.json',c.canonical(initial_registry(ctx)),label='registry_init')
    return checkpoint_receipt(initial_registry(ctx))


def initial_registry(ctx):
    return dict(version=1,migration_id=ctx.migration_id,generation=ctx.generation,sequence=0,journal_sha256=c.ZERO,
                nonces=[],operation_claims=[],decision='OLD',pending=False,claims_sha256=ctx.claims_sha256)


class AuthorityStore:
    def __init__(self,destination:FixtureFS,registry:FixtureFS,source:SourceFixtureFS,ctx:Context,retained:RetainedCheckpoint):
        if (type(destination) is not FixtureFS or type(registry) is not FixtureFS or type(source) is not SourceFixtureFS
                or destination.root.is_relative_to(registry.root) or registry.root.is_relative_to(destination.root)
                or source.root.is_relative_to(destination.root) or destination.root.is_relative_to(source.root)):
            raise Blocked('INDEPENDENT_ROOT_REQUIRED')
        if source.review.migration_id!=ctx.migration_id or source.review.generation!=ctx.generation:
            raise Blocked('SOURCE_TRUST_UNAVAILABLE')
        if type(retained) is not RetainedCheckpoint:raise Blocked('RETAINED_CHECKPOINT_REQUIRED')
        self.fs,self.registry,self.source,self.ctx,self.retained=destination,registry,source,ctx,retained

    @contextmanager
    def locked(self):
        with self.source.lock('account/candidate-execution.lock',tuple_id(self.ctx.account_lock_identity)), self.source.lock('m89/ledger.lock',tuple_id(self.ctx.source_lock_identity)), self.fs.lock('m89/ledger.lock',tuple_id(self.ctx.destination_lock_identity)):
            yield

    def _check_locks(self):
        self.source.check();self.fs.check()
        for fs,path,expected in ((self.source,'account/candidate-execution.lock',self.ctx.account_lock_identity),
                                 (self.source,'m89/ledger.lock',self.ctx.source_lock_identity),
                                 (self.fs,'m89/ledger.lock',self.ctx.destination_lock_identity)):
            if file_identity(fs,path)!=expected:raise ValueError('HELD_LOCK_REPLACED')

    def _journal(self):
        names=self.fs.entries('journal')
        if len(names)>1024 or names!=[f'{i:08d}.json' for i in range(1,len(names)+1)]:raise ValueError('JOURNAL_BLOCKED')
        records=[];previous=c.ZERO;pending=None;nonces=[];claims=[];decision='OLD'
        for sequence,name in enumerate(names,1):
            record=c.load(self.fs.read('journal/'+name));c.record(record)
            if (record['sequence']!=sequence or record['previous']!=previous
                    or record['migration_id']!=self.ctx.migration_id or record['generation']!=self.ctx.generation):
                raise ValueError('JOURNAL_BLOCKED')
            if record['operation_claim']!=c.sha(c.canonical([self.ctx.migration_id,self.ctx.generation,record['transition']])):
                raise ValueError('OPERATION_CLAIM_BLOCKED')
            if sequence%2:
                next_index=len(records)//2
                if (next_index>=len(c.TRANSITIONS) or record['transition']!=c.TRANSITIONS[next_index]
                        or record['kind']!='INTENT' or record['nonce'] in nonces or record['operation_claim'] in claims):
                    raise ValueError('REPLAY_BLOCKED')
                pending=record;nonces.append(record['nonce']);claims.append(record['operation_claim'])
                if record['transition']=='AUTHORITY_COMMITTED':decision='PENDING_NO_WRITERS'
            else:
                if record['kind']!='COMPLETE' or pending is None:raise ValueError('JOURNAL_BLOCKED')
                for key in ('transition','nonce','operation_claim','payload_sha256'):
                    if record[key]!=pending[key]:raise ValueError('JOURNAL_BLOCKED')
                if record['transition']=='AUTHORITY_COMMITTED':decision='NEW'
                pending=None
            if record['decision']!=decision:raise ValueError('DECISION_CONFLICT')
            previous=record['record_sha256'];records.append(record)
        expected=dict(initial_registry(self.ctx),sequence=len(records),journal_sha256=previous,nonces=nonces,
                      operation_claims=claims,decision=decision,pending=pending is not None)
        return records,expected

    def consistent(self,*,allow_pending=False,check_anchor=True):
        if self.fs.entries()!=['authority','claims','evidence','journal','m89']:raise ValueError('UNKNOWN_PROTECTED_STATE')
        if self.registry.entries()!=['checkpoint.json']:raise ValueError('REGISTRY_UNCERTAIN')
        checkpoint=c.load(self.registry.read('checkpoint.json',c.MAX_REGISTRY),c.MAX_REGISTRY);c.registry(checkpoint)
        records,expected=self._journal()
        if checkpoint!=expected or (checkpoint['pending'] and not allow_pending):raise ValueError('CHECKPOINT_DISAGREEMENT')
        if check_anchor and checkpoint_receipt(checkpoint)!=self.retained:raise ValueError('RETAINED_CHECKPOINT_DISAGREEMENT')
        if self.fs.entries('authority') not in ([],['manifest.json']):raise ValueError('MANIFEST_UNCERTAIN')
        return records,checkpoint

    def _append(self,checkpoint,kind,transition,nonce,operation_claim,payload,decision):
        record=dict(version=1,migration_id=self.ctx.migration_id,generation=self.ctx.generation,
            sequence=checkpoint['sequence']+1,previous=checkpoint['journal_sha256'],kind=kind,transition=transition,
            nonce=nonce,operation_claim=operation_claim,payload_sha256=payload,decision=decision)
        record['record_sha256']=c.sha(c.canonical(record));c.record(record)
        self.fs.create('journal/'+f"{record['sequence']:08d}.json",c.canonical(record),label='journal_'+kind.lower())
        return record

    def _checkpoint(self,value):
        c.registry(value)
        self.registry.publish('checkpoint.json',c.canonical(value),replace=True,label='registry',guard=self._check_locks)

    def _check_actor(self,peer_uid,runtime_sha256,now):
        if (type(peer_uid) is not int or peer_uid!=self.ctx.requester_uid or runtime_sha256!=self.ctx.runtime_sha256
                or type(now) is not datetime or now.tzinfo is None or now>=self.source.review.expires_at):
            raise ValueError('ACTOR_BLOCKED')

    @protected
    def step(self,transition,nonce,*,peer_uid,runtime_sha256,now):
        """Synthetic fixed transition; no arbitrary side-effect callback."""
        self._check_actor(peer_uid,runtime_sha256,now)
        with self.locked():
            self._check_locks()
            records,checkpoint=self.consistent()
            if len(records)//2>=8 or transition!=c.TRANSITIONS[len(records)//2]:raise ValueError('TRANSITION_BLOCKED')
            c.hashed(nonce)
            operation_claim=c.sha(c.canonical([self.ctx.migration_id,self.ctx.generation,transition]))
            if nonce in checkpoint['nonces'] or operation_claim in checkpoint['operation_claims']:raise ValueError('REPLAY_BLOCKED')
            manifest=None
            if transition=='DESTINATION_STAGED':
                audited=audit_source_unlocked(self.source,self.ctx)
                payload=c.sha(audited['ledger_bytes']+audited['claim_bytes'])
            elif transition=='AUTHORITY_COMMITTED':
                audit_source_unlocked(self.source,self.ctx)
                self._staged()
                manifest=self.manifest(checkpoint,nonce);payload=c.sha(c.canonical(manifest))
            else:
                if transition=='RUNTIME_ATTESTED':self._runtime()
                payload=c.sha(c.canonical([transition,self.ctx.ledger_sha256,self.ctx.claims_sha256,self.ctx.runtime_sha256]))
            decision='PENDING_NO_WRITERS' if transition=='AUTHORITY_COMMITTED' else checkpoint['decision']
            intent=self._append(checkpoint,'INTENT',transition,nonce,operation_claim,payload,decision)
            pending=dict(checkpoint,sequence=intent['sequence'],journal_sha256=intent['record_sha256'],
                nonces=checkpoint['nonces']+[nonce],operation_claims=checkpoint['operation_claims']+[operation_claim],
                decision=decision,pending=True)
            self._checkpoint(pending)
            self.fs.fault('after_nonce_consumption')
            self._check_locks()
            # Every side effect below occurs AFTER both durable intent and registry.
            if transition=='DESTINATION_STAGED':
                self.fs.publish('m89/ledger.json',audited['ledger_bytes'],label='ledger_copy',guard=self._check_locks)
                self.fs.publish('claims/index.json',audited['claim_bytes'],label='claims_copy',guard=self._check_locks)
            elif transition=='AUTHORITY_COMMITTED':
                self.fs.fault('before_manifest_creation')
                self.fs.publish('authority/manifest.json',c.canonical(manifest),label='manifest',guard=self._check_locks)
            if transition=='POST_CUTOVER_VERIFIED':self._verify_files(records,checkpoint)
            self._check_locks()
            decision='NEW' if transition=='AUTHORITY_COMMITTED' else checkpoint['decision']
            completion=self._append(pending,'COMPLETE',transition,nonce,operation_claim,payload,decision)
            finished=dict(pending,sequence=completion['sequence'],journal_sha256=completion['record_sha256'],decision=decision,pending=False)
            self._checkpoint(finished)
            self.consistent(check_anchor=False)
        # A receipt is acknowledged only after all lock contexts close cleanly.
        self.retained=checkpoint_receipt(finished)
        return Receipt(completion['record_sha256'],Quality.DURABLE_SYNTHETIC,self.retained)

    def manifest(self,checkpoint,nonce):
        value=dict(version=1,migration_id=self.ctx.migration_id,generation=self.ctx.generation,
            source_path=model.SOURCE,destination_path=model.DESTINATION,account_lock_path=model.ACCOUNT_LOCK,
            source_identity=self.ctx.source_identity,destination_identity=file_identity(self.fs,'m89/ledger.json'),
            account_lock_identity=self.ctx.account_lock_identity,source_lock_identity=self.ctx.source_lock_identity,
            destination_lock_identity=self.ctx.destination_lock_identity,ledger_sha256=self.ctx.ledger_sha256,
            prefix_sha256=self.ctx.prefix_sha256,ceiling=49,purchase_authorized=False,claims_sha256=self.ctx.claims_sha256,
            runtime_sha256=self.ctx.runtime_sha256,release_commit=self.ctx.release_commit,
            previous_checkpoint=dict(sequence=checkpoint['sequence'],journal_sha256=checkpoint['journal_sha256']),
            approval_nonce=nonce,authority='NEW',active_authorities=['NEW'],retirement_sha256=self.ctx.retirement_sha256)
        c.manifest(value);return value

    def _runtime(self):
        if c.sha(self.fs.read('evidence/runtime.bin'))!=self.ctx.runtime_sha256:raise ValueError('RUNTIME_BLOCKED')
        release=c.load(self.fs.read('evidence/release.json'))
        c.exact(release,('version','release_commit','runtime_sha256'))
        if release!=dict(version=1,release_commit=self.ctx.release_commit,runtime_sha256=self.ctx.runtime_sha256):
            raise ValueError('RUNTIME_BLOCKED')

    def _staged(self):
        validate_snapshot(self.fs.read('m89/ledger.json',MAX_LEDGER),self.ctx.ledger_sha256,self.ctx.prefix_sha256)
        parse_claims(self.fs.read('claims/index.json',c.MAX_REGISTRY),self.ctx)
        self._runtime()

    def _verify_files(self,records,checkpoint):
        self.fs.fault('during_post_verification')
        self._runtime()
        if checkpoint['decision']!='NEW':raise ValueError('NO_WRITERS')
        manifest=c.load(self.fs.read('authority/manifest.json'));c.manifest(manifest)
        committed=[r for r in records if r['transition']=='AUTHORITY_COMMITTED' and r['kind']=='INTENT']
        if len(committed)!=1:raise ValueError('AUTHORITY_BLOCKED')
        intent=committed[0];previous=records[intent['sequence']-2] if intent['sequence']>1 else None
        prior=dict(sequence=intent['sequence']-1,journal_sha256=c.ZERO if previous is None else previous['record_sha256'])
        expected=self.manifest(dict(prior),intent['nonce'])
        if manifest!=expected or c.sha(c.canonical(manifest))!=intent['payload_sha256']:raise ValueError('STALE_MANIFEST')
        raw=self.fs.read('m89/ledger.json',MAX_LEDGER);validate_snapshot(raw,self.ctx.ledger_sha256,self.ctx.prefix_sha256)
        claim_bytes=self.fs.read('claims/index.json',c.MAX_REGISTRY);parse_claims(claim_bytes,self.ctx)
        if self.fs.entries('m89')!=['ledger.json','ledger.lock'] or self.fs.entries('claims')!=['index.json']:
            raise ValueError('DUPLICATE_AUTHORITY_OR_CLAIM')
        if file_identity(self.source,'account/candidate-execution.lock')!=self.ctx.account_lock_identity:raise ValueError('LOCK_BLOCKED')
        if file_identity(self.source,'m89/ledger.lock')!=self.ctx.source_lock_identity:raise ValueError('LOCK_BLOCKED')
        if file_identity(self.fs,'m89/ledger.lock')!=self.ctx.destination_lock_identity:raise ValueError('LOCK_BLOCKED')

    @protected
    def verify(self,*,peer_uid,runtime_sha256,now):
        self._check_actor(peer_uid,runtime_sha256,now)
        with self.locked():
            records,checkpoint=self.consistent()
            if len(records)!=16:raise ValueError('INCOMPLETE_CUTOVER')
            self._verify_files(records,checkpoint)
            return dict(status='SYNTHETIC_VERIFIED',production_qualified=False,live_enabled=False,
                        authority='NEW',attempts_used=13,remaining=36,ceiling=49,purchase_authorized=False)


def audit_source_unlocked(source,ctx):
    # Caller holds all three reviewed locks; do not re-acquire flock on another FD.
    if source.entries('m89')!=['claim-index.json','ledger.json','ledger.lock']:raise ValueError('UNKNOWN_SOURCE_ARTIFACT')
    if file_identity(source,'m89/ledger.json')!=ctx.source_identity:raise ValueError('SOURCE_IDENTITY_BLOCKED')
    raw=source.read('m89/ledger.json',MAX_LEDGER);validate_snapshot(raw,ctx.ledger_sha256,ctx.prefix_sha256)
    claims=source.read('m89/claim-index.json',c.MAX_REGISTRY);parse_claims(claims,ctx)
    return dict(ledger_bytes=raw,claim_bytes=claims)


@protected
def advance_model(store,state,target,evidence,approval,now,receipts):
    """Offline adapter. Pure model stays unchanged; receipt provenance is explicit."""
    if (type(receipts) is not dict or set(receipts)!=set(model.REQUIRED[target])
            or any(type(r) is not Receipt or r.quality not in (Quality.DURABLE_SYNTHETIC,Quality.SYNTHETIC_ASSERTION)
                   for r in receipts.values())):raise ValueError('RECEIPTS_UNAVAILABLE')
    if tuple((name,receipts[name].digest) for name in model.REQUIRED[target])!=evidence.artifacts:raise ValueError('RECEIPTS_CONFLICT')
    if (state.plan.migration_id!=store.ctx.migration_id or state.plan.release_commit!=store.ctx.release_commit
            or state.plan.source_sha256!=store.ctx.ledger_sha256 or state.plan.prefix_sha256!=store.ctx.prefix_sha256
            or state.plan.runtime_sha256!=store.ctx.runtime_sha256
            or state.plan.lock_identities!=(tuple_id(store.ctx.account_lock_identity),tuple_id(store.ctx.source_lock_identity),tuple_id(store.ctx.destination_lock_identity))):
        raise ValueError('MODEL_BINDING_CONFLICT')
    proposed=model.advance(state,target,evidence,approval,now)
    receipt=store.step(target.value,approval.nonce,peer_uid=approval.requester_uid,runtime_sha256=state.plan.runtime_sha256,now=now)
    return proposed,receipt


def production_transition(*_args,**_kwargs):
    # No attestation trust key/host policy/production path adapter is provisioned.
    # A caller-supplied INDEPENDENTLY_VERIFIED label can never enable operations.
    raise Blocked('PRODUCTION_DISABLED')
