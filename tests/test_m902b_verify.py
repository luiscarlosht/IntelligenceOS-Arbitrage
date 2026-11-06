"""Synthetic verification only. The production invocation is never run."""
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest
from app import m902_history as history
from app import m902b_verify as verifier


def save(path, value):
    path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
    path.chmod(0o600)


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    tmp_path.chmod(0o700)
    for name in ('account','ledger','policy'):
        (tmp_path/name).mkdir(mode=0o700)
    account=tmp_path/'account'/'candidate-execution.lock'
    ledger=tmp_path/'ledger'/'ledger.json'
    ledger_lock=ledger.with_suffix('.lock')
    policy=tmp_path/'policy'/'verification-policy.json'
    for path in (account,ledger_lock): save(path,{})
    prior=dict(pilot='m88-real-six-pilot',ceiling=49,purchase_authorized=False,
               includes_authentication_and_retries=True,attempts_used=12,
               attempts=[dict(number=i,status='COMPLETE' if i!=12 else 'FAILED',
                              phase='detail',candidate_id='SYNTHETIC-PRIVATE') for i in range(1,13)])
    value=deepcopy(prior)
    value.update(m89_authentication_only='CLAIMED_NO_REPLAY',attempts_used=13)
    value['attempts'].append(dict(number=13,status='COMPLETE',phase='authentication',candidate_id=None,
        operation='m89-authentication-only',token_received=True,
        reserved_at='2026-11-05T01:00:00+00:00',completed_at='2026-11-05T01:00:01+00:00'))
    save(ledger,value)
    identities={key:dict(device=path.stat().st_dev,inode=path.stat().st_ino)
                for key,path in (('account_lock',account),('ledger_lock',ledger_lock))}
    save(policy,dict(version=1,**identities))
    for key,path in [('ACCOUNT_LOCK',account),('LEDGER',ledger),('LEDGER_LOCK',ledger_lock),
                     ('POLICY',policy),('CLAIM_ROOT',tmp_path/'protected'),('ANCHOR',tmp_path)]:
        monkeypatch.setattr(verifier,key,path)
    monkeypatch.setattr(verifier,'OWNER',os.getuid())
    monkeypatch.setattr(verifier,'BASELINE_13',hashlib.sha256(ledger.read_bytes()).hexdigest())
    # The production default remains pinned. Supply a synthetic prefix only to this test seam.
    original=verifier.validate_snapshot
    monkeypatch.setattr(verifier,'validate_snapshot',lambda raw,pin:original(raw,pin,history.canonical_hash(prior)))
    return tmp_path


def blocked():
    with pytest.raises(verifier.VerificationError) as error: verifier.verify()
    assert str(error.value)=='VERIFICATION_BLOCKED'


def snapshot(root):
    """No-atime snapshot of fixture contents, entries and nanosecond metadata."""
    result={}
    def visit(path):
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NOATIME|os.O_CLOEXEC)
        try:
            info=os.fstat(fd)
            if path.is_dir():
                names=sorted(os.listdir(fd))
                result[str(path)]=(verifier._snapshot(info),tuple(names))
                for name in names:visit(path/name)
            else:
                result[str(path)]=(verifier._snapshot(info),os.read(fd,history.MAX_LEDGER+1))
        finally:os.close(fd)
    visit(root)
    return result


def test_valid_history_no_persistent_changes(fixture,monkeypatch,capsys):
    before=snapshot(fixture)
    def forbidden(*args,**kwargs):pytest.fail('Network attempted')
    monkeypatch.setattr(socket,'getaddrinfo',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    assert verifier.main(['verify'])==0
    result=json.loads(capsys.readouterr().out)
    assert result==dict(status='VERIFIED',baseline_match=True,attempts_used=13,ceiling=49,
        remaining=36,purchase_authorized=False,claims='ABSENT_IN_FIXED_SCOPE',persistent_changes=False)
    assert snapshot(fixture)==before


@pytest.mark.parametrize('change',['sha','additional','missing','corrupt','reservation','purchase','ceiling',
    'embedded_claim','history','auth_failure','chronology','duplicate','nonfinite'])
def test_drift(fixture,monkeypatch,change):
    value=json.loads(verifier.LEDGER.read_bytes())
    if change=='sha':verifier.LEDGER.write_bytes(verifier.LEDGER.read_bytes()+b' ')
    elif change=='additional':value['attempts'].append(dict(number=14,status='RESERVED'));value['attempts_used']=14
    elif change=='missing':value['attempts'].pop();value['attempts_used']=12
    elif change=='corrupt':verifier.LEDGER.write_bytes(b'fixture-secret broken')
    elif change=='reservation':value['attempts'][0]['status']='RESERVED'
    elif change=='purchase':value['purchase_authorized']=True
    elif change=='ceiling':value['ceiling']=50
    elif change=='embedded_claim':value['m90_one_request']={'claimed':True}
    elif change=='history':value['attempts'][0]['candidate_id']='tampered'
    elif change=='auth_failure':value['attempts'][-1]['token_received']=False
    elif change=='chronology':value['attempts'][-1]['completed_at']='2026-11-04T00:00:00+00:00'
    elif change=='duplicate':verifier.LEDGER.write_bytes(b'{"attempts":[],"attempts":[]}')
    elif change=='nonfinite':verifier.LEDGER.write_bytes(b'{"attempts":NaN}')
    if change not in ('sha','corrupt','duplicate','nonfinite'):save(verifier.LEDGER,value)
    # Also exercise structural/history rejection even with a matching synthetic full digest.
    if change!='sha':monkeypatch.setattr(verifier,'BASELINE_13',hashlib.sha256(verifier.LEDGER.read_bytes()).hexdigest())
    before=snapshot(fixture)
    blocked()
    assert snapshot(fixture)==before


@pytest.mark.parametrize('location',['m901','unknown','protected','protected_empty_claim'])
def test_unexpected_claim(fixture,location):
    if location in ('m901','unknown'):
        save(verifier.LEDGER.parent/('m901-no-replay.json' if location=='m901' else 'unexpected'),{})
    else:
        verifier.CLAIM_ROOT.mkdir(mode=0o700)
        (verifier.CLAIM_ROOT/('m902-no-replay.json' if location=='protected' else 'empty-claim')).touch(mode=0o600)
    before=snapshot(fixture);blocked();assert snapshot(fixture)==before


def test_empty_protected_scope(fixture):
    verifier.CLAIM_ROOT.mkdir(mode=0o700)
    assert verifier.verify()['claims']=='ABSENT_IN_FIXED_SCOPE'


@pytest.mark.parametrize('lock',['ACCOUNT_LOCK','LEDGER_LOCK'])
@pytest.mark.parametrize('problem',['contention','missing','replaced','symlink','hardlink','mode','owner'])
def test_locks(fixture,monkeypatch,lock,problem):
    path=getattr(verifier,lock)
    if problem=='contention':
        fd=os.open(path,os.O_RDONLY|os.O_NOATIME)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            blocked()
        finally:os.close(fd)
        assert verifier.verify()['attempts_used']==13
        return
    if problem=='missing':path.unlink()
    elif problem in ('replaced','symlink'):
        old=path.with_name('old');path.rename(old)
        if problem=='symlink':path.symlink_to(old)
        else:save(path,{})
    elif problem=='hardlink':os.link(path,path.with_name('hardlink'))
    elif problem=='mode':path.chmod(0o640)
    else:
        real=verifier._metadata;identity=verifier._identity(path.stat())
        def owner(info,**kwargs):
            if verifier._identity(info)==identity:raise ValueError('Wrong synthetic owner')
            return real(info,**kwargs)
        monkeypatch.setattr(verifier,'_metadata',owner)
    blocked()
    if problem=='missing':assert not path.exists()


@pytest.mark.parametrize('target',['LEDGER','POLICY'])
@pytest.mark.parametrize('problem',['symlink','hardlink','mode','missing','oversized'])
def test_inputs(fixture,target,problem):
    path=getattr(verifier,target)
    if problem=='symlink':
        old=path.with_name('original');path.rename(old);path.symlink_to(old)
    elif problem=='hardlink':os.link(path,path.with_name('alias'))
    elif problem=='mode':path.chmod(0o644)
    elif problem=='missing':path.unlink()
    else:path.write_bytes(b'x'*(history.MAX_LEDGER+1 if target=='LEDGER' else 4097))
    blocked()


@pytest.mark.parametrize('problem',['owner','writable','inaccessible','symlink'])
def test_ancestry(fixture,monkeypatch,problem):
    path=verifier.LEDGER.parent
    if problem=='writable':path.chmod(0o770)
    elif problem=='symlink':
        old=path.with_name('old-ledger');path.rename(old);path.symlink_to(old,target_is_directory=True)
    elif problem=='owner':
        real=verifier._metadata;inode=path.stat().st_ino
        def owner(info,**kwargs):
            if info.st_ino==inode:raise ValueError('Untrusted owner')
            return real(info,**kwargs)
        monkeypatch.setattr(verifier,'_metadata',owner)
    else:
        real=os.open
        def denied(name,flags,*args,**kwargs):
            if name==path.name and flags & os.O_DIRECTORY:raise PermissionError('fixture-secret')
            return real(name,flags,*args,**kwargs)
        monkeypatch.setattr(os,'open',denied)
    blocked()


@pytest.mark.parametrize('error',[OSError,PermissionError,InterruptedError,KeyboardInterrupt])
def test_read_failure(fixture,monkeypatch,error):
    def fail(*args):raise error('fixture-secret')
    monkeypatch.setattr(os,'read',fail)
    blocked()


def test_metadata_safe_access_required(fixture,monkeypatch):
    monkeypatch.setattr(os,'O_NOATIME',0)
    blocked()


def test_no_fallback_if_noatime_denied(fixture,monkeypatch):
    real=os.open;calls=[]
    def denied(name,flags,*args,**kwargs):
        calls.append(flags)
        assert flags & os.O_NOATIME
        raise PermissionError('No O_NOATIME permission')
    monkeypatch.setattr(os,'open',denied)
    blocked();assert len(calls)==1


def test_open_flags_and_lock_order(fixture,monkeypatch):
    real_open=os.open;real_flock=fcntl.flock;opened={};locked=[]
    def checked(name,flags,*args,**kwargs):
        assert flags & os.O_NOFOLLOW and flags & os.O_CLOEXEC and flags & os.O_NOATIME
        assert not flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)
        fd=real_open(name,flags,*args,**kwargs);opened[fd]=name;return fd
    def locking(fd,operation):
        assert operation==fcntl.LOCK_EX|fcntl.LOCK_NB
        locked.append(opened[fd]);return real_flock(fd,operation)
    monkeypatch.setattr(os,'open',checked);monkeypatch.setattr(fcntl,'flock',locking)
    assert verifier.verify()['baseline_match'] is True
    assert locked==[verifier.ACCOUNT_LOCK.name,verifier.LEDGER_LOCK.name]


@pytest.mark.parametrize('when',['open','read','validate'])
def test_file_replacement(fixture,monkeypatch,when):
    if when=='open':
        real=os.open
        def attack(name,flags,*args,**kwargs):
            if name==verifier.LEDGER.name:
                verifier.LEDGER.rename(verifier.LEDGER.with_name('old'))
                save(verifier.LEDGER,dict(attacker=True))
            return real(name,flags,*args,**kwargs)
        monkeypatch.setattr(os,'open',attack)
    elif when=='read':
        real=os.read;done=False
        def attack(fd,size):
            nonlocal done
            block=real(fd,size)
            if os.fstat(fd).st_ino==verifier.LEDGER.stat().st_ino and not done:
                done=True;verifier.LEDGER.write_bytes(b'tampered')
            return block
        monkeypatch.setattr(os,'read',attack)
    else:
        real=verifier.validate_snapshot
        def attack(raw,pin):
            value=real(raw,pin);verifier.LEDGER.write_bytes(b'tampered');return value
        monkeypatch.setattr(verifier,'validate_snapshot',attack)
    blocked()


def test_directory_replacement(fixture,monkeypatch):
    real=os.open;directory=verifier.LEDGER.parent
    def attack(name,flags,*args,**kwargs):
        if name==directory.name and flags & os.O_DIRECTORY:
            directory.rename(fixture/'saved');directory.mkdir(mode=0o700)
        return real(name,flags,*args,**kwargs)
    monkeypatch.setattr(os,'open',attack)
    blocked()


@pytest.mark.parametrize('args',[[],['--help'],['verify','--ledger','fixture-secret'],['repair'],['verify','verify']])
def test_unexpected_arguments_never_access_files(monkeypatch,capsys,args):
    monkeypatch.setattr(verifier,'verify',lambda:pytest.fail('Filesystem access'))
    assert verifier.main(args)==2
    assert capsys.readouterr().out=='{"code":"INVALID_INVOCATION","status":"BLOCKED"}\n'


def test_sanitized_failure(fixture,monkeypatch,capsys):
    def fail():raise OSError('fixture-secret SYNTHETIC-PRIVATE')
    monkeypatch.setattr(verifier,'_verify',fail)
    assert verifier.main(['verify'])==1
    result=capsys.readouterr()
    assert result.err==''
    assert result.out=='{"code":"VERIFICATION_BLOCKED","status":"BLOCKED"}\n'


@pytest.mark.parametrize('policy',[{},dict(version=True,account_lock={},ledger_lock={}),
    dict(version=1,account_lock=dict(device=True,inode=1),ledger_lock=dict(device=1,inode=2)),
    dict(version=1,account_lock=dict(device=1,inode=0),ledger_lock=dict(device=1,inode=2)),
    dict(version=1,account_lock=[],ledger_lock={}),
    dict(version=1,account_lock={},ledger_lock={},path='/tmp/forbidden')])
def test_bad_policy(fixture,policy):
    save(verifier.POLICY,policy);blocked()


def test_import_has_no_legacy_network_runner():
    root=Path(__file__).resolve().parents[1]
    code="import sys; sys.path.insert(0, sys.argv[1]); import app.m902b_verify; print(','.join(sorted(x for x in sys.modules if x.startswith('app.')))); assert not any(x in sys.modules for x in ('socket','ssl','http.client','urllib.request','app.m90','app.m901','app.m89_deployment','app.amazon_pilot'))"
    result=subprocess.run([sys.executable,'-I','-B','-c',code,str(root)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='app.m902_history,app.m902b_verify'
