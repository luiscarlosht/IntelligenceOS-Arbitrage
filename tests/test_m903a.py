"""Isolated /tmp filesystem and subprocess faults only. Never production access."""
from dataclasses import dataclass, replace, asdict
from datetime import timedelta
import errno
import fcntl
import json
import os
from pathlib import Path
import shutil
import socket

import pytest
from app import m903a_authority as a, m903a_contract as c, m903a_fs as storage
from app import m902c_cutover as model
from test_m902c import sample, NOW, evidence, approve


def write(path,raw):
    path.write_bytes(raw);path.chmod(0o600)


@dataclass
class Harness:
    store: a.AuthorityStore
    sample: tuple
    review: a.FreezeReview
    ctx: a.Context

    def step(self,index):
        return self.store.step(c.TRANSITIONS[index],c.sha(str(index).encode()),
            peer_uid=self.ctx.requester_uid,runtime_sha256=self.ctx.runtime_sha256,now=NOW)

    def run(self,count=8):
        for i in range(count):self.step(i)

    def verify(self):
        return self.store.verify(peer_uid=self.ctx.requester_uid,runtime_sha256=self.ctx.runtime_sha256,now=NOW)


@pytest.fixture
def harness(tmp_path,sample):
    tmp_path.chmod(0o700)
    for name in ('source','protected','independent'):(tmp_path/name).mkdir(mode=0o700)
    root=tmp_path/'source'
    for name in ('account','m89'):(root/name).mkdir(mode=0o700)
    write(root/'account'/'candidate-execution.lock',b'')
    write(root/'m89'/'ledger.lock',b'')
    plan,raw,claims=sample
    write(root/'m89'/'ledger.json',raw)
    claim_records=[]
    for claim in claims:
        record=asdict(claim);record['timestamp']=claim.timestamp.isoformat()
        record['attempts']=list(claim.attempts);record['resolution']=claim.resolution.value
        claim_records.append(record)
    claim_bytes=c.canonical(dict(version=1,migration_id=plan.migration_id,generation=1,claims=claim_records))
    write(root/'m89'/'claim-index.json',claim_bytes)
    profiles={storage.identity(p.stat()):(p.stat().st_uid,p.stat().st_mode&0o7777,p.stat().st_ctime_ns)
              for p in (root,*root.rglob('*'))}
    review=a.FreezeReview(plan.migration_id,1,profiles,'f'*64,NOW+timedelta(hours=1),a.Quality.SYNTHETIC_ASSERTION)
    source=a.SourceFixtureFS(root,review,now=NOW)
    destination=storage.FixtureFS(tmp_path/'protected');registry=storage.FixtureFS(tmp_path/'independent')
    a.provision_destination(destination)
    runtime=b'synthetic immutable release, no executable code'
    destination.create('evidence/runtime.bin',runtime)
    destination.create('evidence/release.json',c.canonical(dict(version=1,release_commit=plan.release_commit,runtime_sha256=c.sha(runtime))))
    ctx=a.Context(plan.migration_id,1,plan.source_sha256,plan.prefix_sha256,c.sha(claim_bytes),c.sha(runtime),
        plan.release_commit,plan.requester_uid,a.file_identity(source,'account/candidate-execution.lock'),
        a.file_identity(source,'m89/ledger.lock'),a.file_identity(destination,'m89/ledger.lock'),
        a.file_identity(source,'m89/ledger.json'),'e'*64)
    retained=a.provision_registry(registry,ctx)
    store=a.AuthorityStore(destination,registry,source,ctx,retained)
    plan=replace(plan,runtime_sha256=ctx.runtime_sha256,lock_identities=tuple(a.tuple_id(x) for x in
        (ctx.account_lock_identity,ctx.source_lock_identity,ctx.destination_lock_identity)))
    yield Harness(store,(plan,raw,claims),review,ctx)
    source.close();destination.close();registry.close()


def blocked(call):
    with pytest.raises(storage.Blocked) as error:call()
    assert str(error.value) in ('AUTHORITY_BLOCKED','PRODUCTION_DISABLED')


def test_full_durable_success_and_model_adapter(harness):
    h=harness;state=model.State(h.sample[0])
    original=h.store.source.read('m89/ledger.json',8*1024*1024)
    audited=a.audit_source(h.store.source,h.ctx,now=NOW)
    assert audited.report()['production_qualified'] is False
    assert audited._ledger_bytes==original
    for target in tuple(model.Phase)[1:]:
        ev=evidence(state,target,h.sample)
        receipts={name:a.Receipt(digest,a.Quality.SYNTHETIC_ASSERTION) for name,digest in ev.artifacts}
        state,receipt=a.advance_model(h.store,state,target,ev,approve(state,target,ev),NOW,receipts)
        assert receipt.quality is a.Quality.DURABLE_SYNTHETIC
    assert h.verify()['status']=='SYNTHETIC_VERIFIED'
    assert h.store.source.read('m89/ledger.json',8*1024*1024)==original
    records,registry=h.store.consistent()
    assert len(records)==registry['sequence']==16
    assert len(registry['nonces'])==len(registry['operation_claims'])==8
    assert registry['decision']=='NEW' and not registry['pending']
    assert h.store.fs.read('m89/ledger.json',8*1024*1024)==original


FAULTS=('journal_intent.before_write','journal_intent.during_write','journal_intent.after_file_fsync',
 'journal_intent.before_dir_fsync','journal_intent.after_dir_fsync','after_nonce_consumption',
 'before_manifest_creation','manifest.before_write','manifest.during_write','manifest.after_file_fsync',
 'manifest.before_dir_fsync','manifest.after_dir_fsync','manifest.after_rename',
 'manifest.before_publish_dir_fsync','manifest.after_publish_dir_fsync',
 'journal_complete.before_write','journal_complete.during_write','journal_complete.after_file_fsync',
 'journal_complete.before_dir_fsync','journal_complete.after_dir_fsync',
 'registry.during_write','registry.after_file_fsync','registry.before_dir_fsync','registry.after_rename',
 'registry.before_publish_dir_fsync','registry.after_publish_dir_fsync')


@pytest.mark.parametrize('fault',FAULTS)
def test_process_crash_each_barrier(harness,fault):
    h=harness;h.run(6)
    old=h.store.retained
    pid=os.fork()
    if pid==0:
        def crash(point):
            if point==fault:os._exit(77)
        h.store.fs.fault=h.store.registry.fault=crash
        h.step(6);os._exit(78)
    _,status=os.waitpid(pid,0)
    assert os.waitstatus_to_exitcode(status)==77
    assert h.store.retained==old  # parent is the separately retained test anchor
    if fault=='journal_intent.before_write':
        assert h.store.consistent()[1]['sequence']==12
    else:
        blocked(h.verify)
        blocked(lambda:h.step(6))
    assert h.store.source.read('m89/ledger.json',8*1024*1024)==h.sample[1]


@pytest.mark.parametrize('failure',range(1,14))
def test_fsync_errors_fail_closed(harness,monkeypatch,failure):
    h=harness;h.run(6);real=os.fsync;count=0
    def fail(fd):
        nonlocal count
        count+=1
        if count==failure:raise OSError('synthetic-secret')
        return real(fd)
    monkeypatch.setattr(os,'fsync',fail)
    blocked(lambda:h.step(6))
    assert h.store.retained.sequence==12
    blocked(h.verify)


@pytest.mark.parametrize('label',['ledger_copy.during_write','ledger_copy.after_file_fsync',
                                 'ledger_copy.after_rename','claims_copy.before_publish_dir_fsync'])
def test_copy_failure_never_activates_authority(harness,label):
    h=harness;h.run(2)
    def fail(point):
        if point==label:raise OSError('fixture-secret')
    h.store.fs.fault=fail
    blocked(lambda:h.step(2))
    assert not (h.store.fs.root/'authority/manifest.json').exists()
    blocked(h.verify)


def test_interrupted_postverification(harness):
    h=harness;h.run(7)
    def fail(point):
        if point=='during_post_verification':raise OSError('secret')
    h.store.fs.fault=fail
    blocked(lambda:h.step(7));blocked(h.verify)
    assert h.store.retained.decision=='NEW'


@pytest.mark.parametrize('mode',['journal_only','valid_prefix_and_manifest','registry_and_journal'])
def test_rollback_against_retained_checkpoint(harness,mode):
    h=harness;h.run(6)
    older_registry=h.store.registry.read('checkpoint.json',c.MAX_REGISTRY)
    h.step(6);h.step(7)
    for p in (h.store.fs.root/'journal').iterdir():
        if int(p.stem)>12:p.unlink()
    if mode!='journal_only':(h.store.fs.root/'authority/manifest.json').unlink()
    if mode=='registry_and_journal':write(h.store.registry.root/'checkpoint.json',older_registry)
    blocked(h.verify);blocked(lambda:h.step(6))


def test_duplicate_nonce_and_operation_claim(harness):
    h=harness;h.step(0)
    blocked(lambda:h.store.step(c.TRANSITIONS[1],c.sha(b'0'),peer_uid=h.ctx.requester_uid,runtime_sha256=h.ctx.runtime_sha256,now=NOW))
    blocked(lambda:h.step(0))
    assert h.store.retained.sequence==2


@pytest.mark.parametrize('target',['journal','registry','manifest'])
@pytest.mark.parametrize('attack',['duplicate_key','extra','nonfinite','wrong_generation','bad_hash'])
def test_strict_storage_schemas(harness,target,attack):
    h=harness;h.run()
    path=(h.store.fs.root/'journal/00000001.json' if target=='journal' else
          h.store.registry.root/'checkpoint.json' if target=='registry' else h.store.fs.root/'authority/manifest.json')
    value=json.loads(path.read_bytes())
    if attack=='duplicate_key':raw=b'{"version":1,"version":1}\n'
    elif attack=='nonfinite':raw=b'{"version":NaN}\n'
    else:
        if attack=='extra':value['unexpected']=True
        elif attack=='wrong_generation':value['generation']=True
        else:value['migration_id']='not-a-hash'
        raw=c.canonical(value)
    write(path,raw);blocked(h.verify)


@pytest.mark.parametrize('target',['ledger','claims','runtime','duplicate_authority','stale_manifest','missing_claim'])
def test_independent_successor_checks(harness,target):
    h=harness;h.run()
    if target=='ledger':write(h.store.fs.root/'m89/ledger.json',b'corrupt')
    elif target=='runtime':write(h.store.fs.root/'evidence/runtime.bin',b'wrong runtime')
    elif target in ('claims','missing_claim'):
        path=h.store.fs.root/'claims/index.json';value=json.loads(path.read_bytes());value['claims']=[];write(path,c.canonical(value))
    else:
        path=h.store.fs.root/'authority/manifest.json';value=json.loads(path.read_bytes())
        if target=='duplicate_authority':value['active_authorities']=['OLD','NEW']
        else:value['previous_checkpoint']['sequence']=0
        write(path,c.canonical(value))
    blocked(h.verify)


@pytest.mark.parametrize('problem',['symlink','hardlink','mode','owner','inode','directory'])
def test_filesystem_attacks(harness,monkeypatch,problem):
    h=harness;h.run();path=h.store.fs.root/'m89/ledger.json'
    if problem=='symlink':path.rename(path.with_name('old'));path.symlink_to(path.with_name('old'))
    elif problem=='hardlink':os.link(path,path.with_name('alias'))
    elif problem=='mode':path.chmod(0o644)
    elif problem=='inode':
        raw=path.read_bytes();path.rename(path.with_name('old'));write(path,raw)
    elif problem=='directory':
        directory=path.parent;directory.rename(directory.with_name('old'));directory.mkdir(mode=0o700)
    else:
        real=storage.metadata;ino=path.stat().st_ino
        def mismatch(info,*args,**kwargs):
            if info.st_ino==ino:raise storage.Blocked('OWNER_BLOCKED')
            return real(info,*args,**kwargs)
        monkeypatch.setattr(storage,'metadata',mismatch)
    blocked(h.verify)


@pytest.mark.parametrize('lock',['account/candidate-execution.lock','m89/ledger.lock'])
def test_existing_source_lock_contention(harness,lock):
    h=harness
    with h.store.source.opened(lock) as fd:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        blocked(lambda:a.audit_source(h.store.source,h.ctx,now=NOW))
    assert a.audit_source(h.store.source,h.ctx,now=NOW).report()['production_qualified'] is False


def test_lock_order(harness,monkeypatch):
    h=harness;real=fcntl.flock;seen=[]
    def check(fd,flags):
        seen.append(storage.identity(os.fstat(fd)));return real(fd,flags)
    monkeypatch.setattr(fcntl,'flock',check)
    h.step(0)
    assert seen==[a.tuple_id(h.ctx.account_lock_identity),a.tuple_id(h.ctx.source_lock_identity),a.tuple_id(h.ctx.destination_lock_identity)]


def test_cross_device_rename_has_no_fallback(harness,monkeypatch):
    h=harness;h.run(6)
    def fail(*args,**kwargs):raise OSError(errno.EXDEV,'synthetic cross device')
    monkeypatch.setattr(os,'rename',fail)
    blocked(lambda:h.step(6));blocked(h.verify)


@pytest.mark.parametrize('peer,runtime',[(1,None),(True,None),(999,'0'*64)])
def test_wrong_requester_runtime(harness,peer,runtime):
    h=harness
    blocked(lambda:h.store.step(c.TRANSITIONS[0],'1'*64,peer_uid=peer,runtime_sha256=runtime or h.ctx.runtime_sha256,now=NOW))
    assert h.store.retained.sequence==0


@pytest.mark.parametrize('quality',[a.Quality.MISSING,a.Quality.UNCERTAIN,a.Quality.CONFLICTING,a.Quality.INDEPENDENTLY_VERIFIED])
def test_receipt_provenance_cannot_enable_production(harness,quality):
    h=harness;state=model.State(h.sample[0]);target=model.Phase.WRITERS_FROZEN;ev=evidence(state,target,h.sample)
    receipts={name:a.Receipt(digest,quality) for name,digest in ev.artifacts}
    blocked(lambda:a.advance_model(h.store,state,target,ev,approve(state,target,ev),NOW,receipts))
    blocked(lambda:a.production_transition(receipts=receipts))


def test_source_trust_required_and_not_weakened(harness):
    h=harness
    with pytest.raises(storage.Blocked):a.SourceFixtureFS(h.store.source.root,replace(h.review,reviewed_profiles={}),now=NOW)
    blocked(lambda:a.audit_source(h.store.source,h.ctx,now=NOW+timedelta(days=1)))
    with pytest.raises(storage.Blocked):h.store.source.create('m89/not-allowed',b'')


def test_source_corruption_extra_attempt_and_claim(harness):
    h=harness;path=h.store.source.root/'m89/ledger.json';value=json.loads(path.read_bytes())
    value['attempts_used']=14;value['attempts'].append(dict(number=14,status='RESERVED'))
    write(path,c.canonical(value))
    blocked(lambda:a.audit_source(h.store.source,h.ctx,now=NOW))


def test_readonly_audit_preserves_content_and_metadata(harness):
    h=harness;paths=[h.store.source.root/'account/candidate-execution.lock',h.store.source.root/'m89/ledger.lock',h.store.source.root/'m89/ledger.json',h.store.source.root/'m89/claim-index.json']
    before={p:storage.snapshot(p.stat()) for p in paths}
    a.audit_source(h.store.source,h.ctx,now=NOW)
    assert {p:storage.snapshot(p.stat()) for p in paths}==before


def test_no_network_or_production_access(harness,monkeypatch):
    h=harness;real=os.open;seen=[]
    def guarded(path,flags,*args,**kwargs):
        path=str(path);seen.append(path)
        if path.startswith(('/var/lib/intelligenceos','/etc/intelligenceos','/root/.intelligenceos','/opt/intelligenceos')):
            pytest.fail('production access')
        return real(path,flags,*args,**kwargs)
    def forbidden(*args,**kwargs):pytest.fail('network operation')
    monkeypatch.setattr(os,'open',guarded);monkeypatch.setattr(socket,'getaddrinfo',forbidden)
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    h.run();assert h.verify()['live_enabled'] is False
    assert seen
    for root in ('/var/lib/intelligenceos-arbitrage-protected','/root/.intelligenceos-arbitrage-amazon'):
        with pytest.raises(storage.Blocked):storage.FixtureFS(Path(root))


def test_verifier_has_no_writes_or_provisioning(harness,monkeypatch):
    h=harness;h.run();real=os.open;tracked=[]
    def checked(path,flags,*args,**kwargs):
        assert not flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)
        assert flags&os.O_NOFOLLOW and flags&os.O_CLOEXEC
        assert flags&os.O_NOATIME or flags&os.O_PATH
        fd=real(path,flags,*args,**kwargs)
        if path=='runtime.bin':tracked.append(fd)
        return fd
    monkeypatch.setattr(os,'open',checked)
    assert h.verify()['production_qualified'] is False
    tracked.clear()
    real_snapshot=storage.snapshot;inode=(h.store.fs.root/'evidence/runtime.bin').stat().st_ino
    def fail_snapshot(info):
        if info.st_ino==inode:raise OSError('synthetic metadata I/O failure')
        return real_snapshot(info)
    monkeypatch.setattr(storage,'snapshot',fail_snapshot)
    with pytest.raises(OSError):
        with h.store.fs.opened('evidence/runtime.bin'):pass
    assert len(tracked)==1
    with pytest.raises(OSError):os.fstat(tracked[0])


@pytest.mark.parametrize('problem',['missing_lock','replaced_lock','symlink','hardlink','interrupted_read','duplicate_claim','unresolved_claim'])
def test_source_audit_failures(harness,monkeypatch,problem):
    h=harness;ctx=h.ctx
    if problem in ('missing_lock','replaced_lock'):
        path=h.store.source.root/'m89/ledger.lock';path.unlink()
        if problem=='replaced_lock':write(path,b'')
    elif problem in ('symlink','hardlink'):
        path=h.store.source.root/'m89/ledger.json'
        if problem=='symlink':path.rename(path.with_name('saved'));path.symlink_to(path.with_name('saved'))
        else:os.link(path,path.with_name('alias'))
    elif problem=='interrupted_read':
        def fail(*args):raise InterruptedError('sensitive synthetic diagnostic')
        monkeypatch.setattr(os,'read',fail)
    else:
        path=h.store.source.root/'m89/claim-index.json';value=json.loads(path.read_bytes())
        if problem=='duplicate_claim':value['claims'].append(value['claims'][0])
        else:value['claims'][0]['resolution']='UNRESOLVED'
        raw=c.canonical(value);write(path,raw);ctx=replace(ctx,claims_sha256=c.sha(raw))
    blocked(lambda:a.audit_source(h.store.source,ctx,now=NOW))
    if problem=='missing_lock':assert not (h.store.source.root/'m89/ledger.lock').exists()


def test_source_replacement_while_opening(harness,monkeypatch):
    h=harness;real=os.open;path=h.store.source.root/'m89/ledger.json'
    def attack(name,flags,*args,**kwargs):
        if name=='ledger.json':
            raw=path.read_bytes();path.rename(path.with_name('saved'));write(path,raw)
        return real(name,flags,*args,**kwargs)
    monkeypatch.setattr(os,'open',attack)
    blocked(lambda:a.audit_source(h.store.source,h.ctx,now=NOW))


def test_manifest_directory_replacement_during_rename(harness,monkeypatch):
    h=harness;h.run(6);real=os.rename;directory=h.store.fs.root/'authority'
    def attack(src,dst,*args,**kwargs):
        if src=='manifest.json.pending':
            directory.rename(directory.with_name('old-authority'));directory.mkdir(mode=0o700)
        return real(src,dst,*args,**kwargs)
    monkeypatch.setattr(os,'rename',attack)
    blocked(lambda:h.step(6));blocked(h.verify)
    assert list(directory.iterdir())==[]


def test_registry_roots_must_be_independently_retained(harness):
    h=harness
    with pytest.raises(storage.Blocked):a.AuthorityStore(h.store.fs,h.store.fs,h.store.source,h.ctx,h.store.retained)
    with pytest.raises(storage.Blocked):a.AuthorityStore(h.store.fs,h.store.registry,h.store.source,h.ctx,None)


def test_expired_freeze_blocks_before_side_effect(harness):
    h=harness
    blocked(lambda:h.store.step(c.TRANSITIONS[0],'1'*64,peer_uid=h.ctx.requester_uid,
                               runtime_sha256=h.ctx.runtime_sha256,now=NOW+timedelta(days=1)))
    assert h.store.retained.sequence==0 and h.store.fs.entries('journal')==[]


def test_sanitized_fault_output(harness,capsys):
    h=harness
    def fail(_):raise OSError('SYNTHETIC_SECRET_NOT_FOR_OUTPUT')
    h.store.fs.fault=fail
    blocked(lambda:h.step(0))
    captured=capsys.readouterr()
    assert captured.out==captured.err==''


def test_source_lock_replacement_before_publication_blocks_ack(harness):
    h=harness;h.run(6);old=h.store.retained;path=h.store.source.root/'m89/ledger.lock'
    def attack(point):
        if point=='manifest.after_file_fsync':
            path.rename(path.with_name('old-lock'));write(path,b'')
    h.store.fs.fault=attack
    blocked(lambda:h.step(6))
    assert h.store.retained==old
    assert not (h.store.fs.root/'authority/manifest.json').exists()


def test_weaker_source_profile_does_not_relax_protected_storage(harness):
    from types import SimpleNamespace
    h=harness;path=h.store.source.root/'m89/ledger.json';info=path.stat()
    fake=SimpleNamespace(st_uid=12345,st_mode=info.st_mode,st_nlink=1,st_dev=info.st_dev,
                         st_ino=info.st_ino,st_ctime_ns=info.st_ctime_ns)
    h.review.reviewed_profiles[storage.identity(info)]=(12345,0o600,info.st_ctime_ns)
    h.store.source.validate(fake)
    with pytest.raises(storage.Blocked):h.store.fs.validate(fake)


def test_ancestor_traversal_and_strict_fixture_access(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    real = os.open
    calls = []
    def checked(name, flags, *args, **kwargs):
        calls.append((name, flags))
        if name != tmp_path.name:
            # Same restriction as a nonroot caller on root-owned ancestors.
            if flags & os.O_NOATIME:
                raise PermissionError('foreign-owned ancestor')
            assert flags & os.O_PATH and flags & os.O_DIRECTORY
        else:
            assert flags & os.O_NOATIME and not flags & os.O_PATH
        return real(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', checked)
    with storage.FixtureFS(tmp_path) as fs:
        for key, fd in fs.dirs.items():
            if key != str(tmp_path):
                with pytest.raises(OSError): os.listdir(fd)
    assert calls


def test_fixture_noatime_denied_has_no_fallback(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    real = os.open
    denied = []
    def checked(name, flags, *args, **kwargs):
        if name == tmp_path.name:
            denied.append(flags)
            assert flags & os.O_NOATIME and not flags & os.O_PATH
            raise PermissionError('strict fixture access')
        return real(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', checked)
    with pytest.raises(PermissionError): storage.FixtureFS(tmp_path)
    assert len(denied) == 1
