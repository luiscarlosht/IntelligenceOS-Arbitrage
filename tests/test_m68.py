"""Synthetic offline reviews only; no real artifact, account or reservation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import warnings

import pytest

from app import m68, m68_authorization as auth, m67_policy
from app.m65_intelligence import sha256
from app.m67_state import Ledger
from app.observations import canonical, fingerprint
from test_m67 import cohort

NAME = 'm68-authorization-synthetic.json'
NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args,**kwargs):
        pytest.fail('Network, credentials loader, executor or reservation forbidden')
    for name in ('create_connection','getaddrinfo','gethostbyname'):
        monkeypatch.setattr(socket,name,denied)
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket.socket,'connect_ex',denied)
    from app import amazon_pilot, m65_batch, m67_execution, m67_transport
    for name in ('load_credentials','exchange_token','_request_json'):
        monkeypatch.setattr(amazon_pilot,name,denied)
    monkeypatch.setattr(Ledger,'__init__',denied)
    monkeypatch.setattr(m65_batch,'reserve_future',denied)
    monkeypatch.setattr(m65_batch,'consume_attempt',denied)
    monkeypatch.setattr(m67_execution,'execute',denied)
    monkeypatch.setattr(m67_transport.AmazonTransport,'send',denied)
    monkeypatch.setattr(m67_transport.AmazonTransport,'request',denied)


def write(path,value):
    path.write_text(canonical(value)+'\n');path.chmod(0o600)


@pytest.fixture
def review(cohort,monkeypatch):
    c=cohort
    monkeypatch.setattr(auth,'PRIVATE',c['private'])
    monkeypatch.setattr(auth,'MANIFEST_SHA256',c['digest'])
    monkeypatch.setattr(auth,'utcnow',lambda:NOW)
    monkeypatch.setattr(auth,'confirm_account',lambda seller:seller=='SYNTHETICSELLER')
    context=c['private']/m67_policy.CONTEXT
    value=json.loads(context.read_text());value['credentials_sha256']=sha256(c['private']/'credentials.json')
    write(context,value)
    preflight=c['private']/'m68-preflight.json'
    write(preflight,m67_policy.preflight(c['path'],c['digest'],[c['source']],c['store_path'],c['private']))
    c['preflight']=preflight
    return c


def common(c):
    return (c['path'],c['digest'],[c['source']],c['store_path'],c['private'],c['preflight'],NAME)


def prepare(c):
    return auth.prepare(*common(c),'manual:M68-synthetic-review')


def validate(c,result):
    return auth.validate(*common(c),result['authorization_sha256'],result['receipt_sha256'])


def protected(c):
    paths=[c['path'],c['store_path'],c['private']/m67_policy.CONTEXT,c['private']/'credentials.json',
           c['private']/'candidate-executions.sqlite3',c['private']/'m63-eligibility-authorization-01.json']
    return {str(p):sha256(p) for p in paths}


def test_exact_schema_short_lifetime_private_output_and_m67_policy(review):
    c=review;before=protected(c);result=prepare(c)
    path,receipt=auth.paths(c['private'],NAME)
    artifact=json.loads(path.read_text())
    assert set(artifact)=={'schema','approved','execution_permission','manifest_sha256','asins','account_reference',
        'account_binding_sha256','marketplace_id','condition','budget','review_reference','reviewed_at','expires_at',
        'implementation_sha256','preflight_sha256','no_retry'}
    assert artifact['asins']==c['inner']['asins'] and len(artifact['asins'])==20
    assert artifact['budget']==auth.BUDGET
    assert artifact['reviewed_at']==NOW.isoformat()
    assert artifact['expires_at']==(NOW+timedelta(minutes=15)).isoformat()
    assert artifact['implementation_sha256']==m67_policy.implementation()
    assert artifact['preflight_sha256']==fingerprint(json.loads(c['preflight'].read_text()))
    assert path.stat().st_mode&0o777==0o600 and receipt.stat().st_mode&0o777==0o600
    assert path.stat().st_nlink==receipt.stat().st_nlink==1
    assert sha256(path)==result['authorization_sha256']
    assert validate(c,result)['status']=='VALID_M67_POLICY_OFFLINE_ONLY'
    assert protected(c)==before
    assert not (c['private']/m67_policy.LEDGER).exists()
    assert not list(c['private'].glob('.m68-pending-*'))
    for value in (path.read_text(),receipt.read_text(),canonical(result)):
        assert 'SYNTHETICSELLER' not in value and 'seller_id' not in value
        assert 'SYNTHETICSECRET' not in value


def test_preparation_deterministic_given_same_evidence_and_clock(review):
    first=prepare(review)
    second=auth.prepare(*common(review)[:-1],'m68-authorization-second.json','manual:M68-synthetic-review')
    assert first==second


def test_validation_readonly_byte_preservation(review):
    result=prepare(review)
    before={str(p):sha256(p) for p in review['private'].iterdir()}
    revision=review['store'].revision()
    assert validate(review,result)['live_requests']==0
    assert {str(p):sha256(p) for p in review['private'].iterdir()}==before
    assert review['store'].revision()==revision


@pytest.mark.parametrize('choice',[False,None,1,'yes'])
def test_explicit_human_confirmation_required(review,monkeypatch,choice):
    monkeypatch.setattr(auth,'confirm_account',lambda seller:choice)
    with pytest.raises(ValueError):prepare(review)
    assert not auth.paths(review['private'],NAME)[0].exists()
    assert not auth.paths(review['private'],NAME)[1].exists()


@pytest.mark.parametrize('change',['manifest-bytes','manifest-digest','order','source','preflight-implementation',
    'preflight-binding','preflight-asins','preflight-budget','preflight-fingerprint','preflight-not-ready',
    'account-binding','credentials','history','missing-preflight','missing-binding','missing-credentials','missing-store'])
def test_missing_evidence_and_drift_before_preparation(review,change):
    c=review
    if change=='manifest-bytes':c['path'].write_text(c['path'].read_text()+' ')
    elif change=='manifest-digest':c['digest']='0'*64
    elif change=='order':
        value=json.loads(c['path'].read_text());value['restrictions_proposal']['asins'].reverse();write(c['path'],value)
    elif change=='source':write(c['source'],[])
    elif change=='account-binding':
        path=c['private']/m67_policy.CONTEXT;value=json.loads(path.read_text());value['seller_id']='DIFFERENT';write(path,value)
    elif change=='credentials':write(c['private']/'credentials.json',{'client_secret':'SYNTHETICCHANGED'})
    elif change=='history':write(c['private']/'m60-added.json',dict(asin=c['inner']['asins'][0],requests_attempted=1))
    elif change.startswith('missing-'):
        path={'preflight':c['preflight'],'binding':c['private']/m67_policy.CONTEXT,
              'credentials':c['private']/'credentials.json','store':c['store_path']}[change[8:]];path.unlink()
    else:
        value=json.loads(c['preflight'].read_text())
        key={'preflight-implementation':'implementation_sha256','preflight-binding':'account_binding_sha256',
             'preflight-asins':'asins','preflight-budget':'budget','preflight-fingerprint':'audit_sha256',
             'preflight-not-ready':'ready'}[change]
        value[key]=False if key=='ready' else 'CHANGED';write(c['preflight'],value)
    with pytest.raises((ValueError,FileNotFoundError)):prepare(c)
    assert not auth.paths(c['private'],NAME)[0].exists()


@pytest.mark.parametrize('field,value',[
    ('approved',False),('execution_permission',False),('no_retry',False),
    ('account_reference','OTHER'),('marketplace_id','OTHER'),('condition','used'),
    ('asins',[]),('budget',dict(auth.BUDGET,authentication=2)),('preflight_sha256','0'*64),
    ('account_binding_sha256','0'*64),('implementation_sha256',{}),
    ('reviewed_at','2099-01-01T00:00:00+00:00'),('expires_at','2099-01-01T00:00:00+00:00')])
def test_tampered_authorizations_rejected_even_with_new_digest(review,field,value):
    c=review;r=prepare(c);path,_=auth.paths(c['private'],NAME)
    artifact=json.loads(path.read_text());artifact[field]=value;write(path,artifact)
    r['authorization_sha256']=sha256(path)
    with pytest.raises(ValueError):validate(c,r)


def test_expiration_exact_boundary_and_review_window(review,monkeypatch):
    r=prepare(review)
    monkeypatch.setattr(auth,'utcnow',lambda:NOW+timedelta(minutes=15)-timedelta(microseconds=1))
    assert validate(review,r)['status']=='VALID_M67_POLICY_OFFLINE_ONLY'
    monkeypatch.setattr(auth,'utcnow',lambda:NOW+timedelta(minutes=15))
    with pytest.raises(ValueError):validate(review,r)


def test_no_extension_of_short_window_even_if_m67_would_accept(review):
    c=review;r=prepare(c);path,receipt_path=auth.paths(c['private'],NAME)
    artifact=json.loads(path.read_text());artifact['expires_at']=(NOW+timedelta(hours=1)).isoformat();write(path,artifact)
    receipt=json.loads(receipt_path.read_text());receipt['authorization_sha256']=sha256(path)
    receipt['expires_at']=artifact['expires_at'];write(receipt_path,receipt)
    r.update(authorization_sha256=sha256(path),receipt_sha256=sha256(receipt_path))
    with pytest.raises(ValueError):validate(c,r)


@pytest.mark.parametrize('which',['authorization_sha256','receipt_sha256'])
def test_exact_reviewed_file_digests_required(review,which):
    r=prepare(review);r[which]='0'*64
    with pytest.raises(ValueError):validate(review,r)


def test_preparation_code_drift_and_missing_receipt(review,monkeypatch):
    c=review;r=prepare(c)
    monkeypatch.setattr(auth,'implementation',lambda:{'changed':'0'*64})
    with pytest.raises(ValueError):validate(c,r)
    _,receipt=auth.paths(c['private'],NAME);receipt.unlink()
    with pytest.raises(FileNotFoundError):validate(c,r)


def test_m67_code_drift_fails_closed(review,monkeypatch):
    c=review;r=prepare(c)
    monkeypatch.setattr(m67_policy,'implementation',lambda:{'changed':'0'*64})
    with pytest.raises(ValueError):validate(c,r)


def test_historical_claim_after_preparation_blocks_validation(review):
    c=review;r=prepare(c)
    # Synthetic derived claim only. No reservation primitive or live record.
    with c['store'].db:
        c['store'].db.execute('INSERT INTO asin_claims VALUES (?,?)',('ATVPDKIKX0DER:new_new:'+c['inner']['asins'][0],'a'*64))
    with pytest.raises(ValueError):validate(c,r)


def test_global_claim_blocks_without_opening_ledger_for_write(review,monkeypatch):
    monkeypatch.setattr(m67_policy,'ledger_snapshot',lambda path:dict(batches=[],claims=[review['inner']['asins'][0]]))
    with pytest.raises(ValueError):prepare(review)


def test_evidence_rechecked_after_hidden_confirmation(review,monkeypatch):
    c=review
    def confirm(seller):
        write(c['private']/'m60-during-review.json',dict(asin=c['inner']['asins'][0],requests_attempted=1))
        return True
    monkeypatch.setattr(auth,'confirm_account',confirm)
    with pytest.raises(ValueError):prepare(c)
    assert not auth.paths(c['private'],NAME)[0].exists()


@pytest.mark.parametrize('name',['../escape.json','credentials.json','m67-account-context.json',
    '/tmp/m68-authorization-escape.json','m68-authorization-x/y.json','m68-authorization-.json'])
def test_path_escape_and_protected_names_blocked(review,name):
    with pytest.raises(ValueError):auth.prepare(*common(review)[:-1],name,'manual:synthetic')


def test_only_existing_private_directory_allowed(review,tmp_path):
    other=tmp_path/'other';other.mkdir(mode=0o700)
    with pytest.raises(ValueError):auth.paths(other,NAME)
    assert not list(other.iterdir())


@pytest.mark.parametrize('kind',['symlink','permissions','hardlink'])
def test_unsafe_artifact_inputs_rejected(review,kind):
    c=review;r=prepare(c);path,_=auth.paths(c['private'],NAME)
    if kind=='symlink':path.rename(c['private']/'old.json');path.symlink_to('old.json')
    elif kind=='permissions':path.chmod(0o644)
    else:os.link(path,c['private']/'other.json')
    with pytest.raises(ValueError):validate(c,r)


def test_no_overwrite_or_clobber(review):
    c=review;r=prepare(c);path,receipt=auth.paths(c['private'],NAME)
    before=path.read_bytes(),receipt.read_bytes()
    with pytest.raises(ValueError):prepare(c)
    assert before==(path.read_bytes(),receipt.read_bytes())
    assert validate(c,r)['execution_performed'] is False


def test_publish_failure_leaves_no_authorization_or_consumed_state(review,monkeypatch):
    c=review;original=os.link
    def fail_auth(source,destination,**kwargs):
        if Path(destination).name==NAME:raise OSError('SYNTHETICSELLER')
        return original(source,destination,**kwargs)
    monkeypatch.setattr(os,'link',fail_auth)
    before=protected(c)
    with pytest.raises(OSError):prepare(c)
    assert not auth.paths(c['private'],NAME)[0].exists()
    assert auth.paths(c['private'],NAME)[1].exists()
    assert not list(c['private'].glob('.m68-pending-*'))
    assert protected(c)==before


def test_duplicate_keys_and_nonfinite_private_json_rejected(review):
    path=review['private']/'ambiguous.json'
    for text in ('{"approved":false,"approved":true}','{"value":NaN}'):
        path.write_text(text);path.chmod(0o600)
        with pytest.raises(ValueError):auth.load_private(path)


def test_cli_safe_summary_and_redacted_failure(review,monkeypatch,capsys):
    c=review
    argv=['--manifest',str(c['path']),'--manifest-sha256',c['digest'],'--catalog',str(c['source']),
          '--store',str(c['store_path']),'--preflight',str(c['preflight']),'--name',NAME]
    assert m68.main(['prepare',*argv,'--review-reference','manual:M68-synthetic'])==0
    text=capsys.readouterr().out;result=json.loads(text)
    assert 'SYNTHETICSELLER' not in text and 'execution_permission' not in text and 'asins' not in text
    assert m68.main(['validate',*argv,'--authorization-sha256',result['authorization_sha256'],
                     '--receipt-sha256',result['receipt_sha256']])==0
    def fail(*args,**kwargs):raise ValueError('SYNTHETICSELLER SYNTHETICSECRET')
    monkeypatch.setattr(auth,'prepare',fail)
    assert m68.main(['prepare',*argv,'--review-reference','manual:M68-synthetic'])==2
    assert 'SYNTHETIC' not in capsys.readouterr().out


def test_no_execute_or_confirmation_bypass_cli():
    for argv in (['execute'],['prepare','--execute'],['prepare','--yes'],['prepare','--seller-id','PRIVATE']):
        with pytest.raises(SystemExit):m68.main(argv)


def test_import_and_help_do_not_import_execution_or_transport():
    script="import sys,socket; sys.modules['app.m67_execution']=None; sys.modules['app.m67_transport']=None; socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('NETWORK')); from app.m68 import main; main(['--help'])"
    result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True)
    assert result.returncode==0 and 'Offline M67' in result.stdout


PRIVATE_CONFIRM = auth.confirm_account


@pytest.mark.parametrize('seller,phrase,expected',[
    ('SYNTHETICSELLER',auth.CONFIRMATION,True),('OTHER',auth.CONFIRMATION,False),
    ('SYNTHETICSELLER','yes',False),('','',False)])
def test_hidden_terminal_confirmation(seller,phrase,expected,monkeypatch):
    import builtins
    class Terminal:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def isatty(self):return True
    monkeypatch.setattr(builtins,'open',lambda *args,**kwargs:Terminal())
    answers=iter((seller,phrase));prompts=[]
    def hidden(prompt,**kwargs):prompts.append(prompt);return next(answers)
    monkeypatch.setattr(auth.getpass,'getpass',hidden)
    assert PRIVATE_CONFIRM('SYNTHETICSELLER') is expected
    assert all('SYNTHETICSELLER' not in prompt for prompt in prompts)


def test_missing_tty_and_echo_fallback_fail_closed(monkeypatch):
    import builtins
    def unavailable(*args,**kwargs):raise OSError('no tty')
    monkeypatch.setattr(builtins,'open',unavailable)
    with pytest.raises(OSError):PRIVATE_CONFIRM('SYNTHETICSELLER')
    class Terminal:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def isatty(self):return True
    monkeypatch.setattr(builtins,'open',lambda *args,**kwargs:Terminal())
    def echo(*args,**kwargs):warnings.warn('Hidden entry unavailable',auth.getpass.GetPassWarning)
    monkeypatch.setattr(auth.getpass,'getpass',echo)
    with pytest.raises(auth.getpass.GetPassWarning):PRIVATE_CONFIRM('SYNTHETICSELLER')


@pytest.mark.parametrize('mask',[0,0o777])
def test_validation_never_prompts_and_artifact_created_0600_regardless_of_umask(review,monkeypatch,mask):
    old=os.umask(mask)
    try:r=prepare(review)
    finally:os.umask(old)
    def forbidden(*args):pytest.fail('Read-only validation must not prompt')
    monkeypatch.setattr(auth,'confirm_account',forbidden)
    assert validate(review,r)['execution_performed'] is False
    for path in auth.paths(review['private'],NAME):assert path.stat().st_mode&0o777==0o600


@pytest.mark.parametrize('change',['binding','credentials','history'])
def test_drift_after_preparation_blocks_readonly_validation(review,change):
    c=review;r=prepare(c)
    if change=='binding':
        path=c['private']/m67_policy.CONTEXT;value=json.loads(path.read_text());value['seller_id']='OTHER';write(path,value)
    elif change=='credentials':write(c['private']/'credentials.json',{'changed':'SYNTHETIC'})
    else:write(c['private']/'m60-after-preparation.json',dict(asin=c['inner']['asins'][0],requests_attempted=1))
    with pytest.raises(ValueError):validate(c,r)


def test_receipt_confirmation_cannot_be_rewritten(review):
    c=review;r=prepare(c);_,path=auth.paths(c['private'],NAME)
    receipt=json.loads(path.read_text());receipt['human_account_confirmed']=False;write(path,receipt)
    r['receipt_sha256']=sha256(path)
    with pytest.raises(ValueError):validate(c,r)


def test_argument_errors_never_echo_mistakenly_supplied_secrets(capsys):
    with pytest.raises(SystemExit):m68.main(['prepare','--seller-id','SYNTHETICSELLER'])
    captured=capsys.readouterr()
    assert 'SYNTHETICSELLER' not in captured.out+captured.err
    assert 'M68_BLOCKED' in captured.err


def test_m68_rejects_smaller_cohort_even_when_m67_accepts_it(review,monkeypatch):
    from app import m66_discovery
    c=review
    manifest,_,_=m66_discovery.build([c['source']],c['store'],c['private'],
        as_of=datetime.fromisoformat('2026-01-02T12:00:00+00:00'),maximum=19)
    write(c['path'],manifest);c['digest']=sha256(c['path'])
    monkeypatch.setattr(auth,'MANIFEST_SHA256',c['digest'])
    write(c['preflight'],m67_policy.preflight(c['path'],c['digest'],[c['source']],c['store_path'],c['private']))
    with pytest.raises(ValueError):prepare(c)


def test_existing_execution_lock_is_read_only_and_blocks_active_execution(review):
    import fcntl
    c=review;path=c['private']/'candidate-execution.lock';path.touch(mode=0o600)
    before=path.stat().st_size,sha256(path)
    fd=os.open(path,os.O_RDWR)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):prepare(c)
    finally:os.close(fd)
    assert before==(path.stat().st_size,sha256(path))
    assert not auth.paths(c['private'],NAME)[0].exists()


@pytest.mark.parametrize('filename',['candidate-execution.lock','m67-executions.sqlite3'])
def test_dangling_execution_evidence_symlinks_fail_closed(review,filename):
    c=review;(c['private']/filename).symlink_to('missing-protected-state')
    with pytest.raises(ValueError):prepare(c)
    assert not auth.paths(c['private'],NAME)[0].exists()
