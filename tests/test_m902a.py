"""Synthetic security regressions; no production fixtures, network or privilege changes."""
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket

import pytest
from app import m902, m902_contract as contract
from app.m902_storage import Store
from app.m88_state import read, sha, write
from test_m90 import state
from test_m902 import broker, run


def change(broker, target, mutate):
    path = getattr(broker, target)
    value = read(path)
    mutate(value)
    write(path, value, replace=True)
    if target == 'evidence':
        broker = replace(broker, evidence_sha256=sha(path))
        approval = read(broker.approval)
        approval['binding'] = broker.binding()
        write(broker.approval, approval, replace=True)
    return broker


def blocked(broker):
    before = broker.ledger.read_bytes()
    with pytest.raises(m902.BrokerError) as error: run(broker)
    assert str(error.value) == 'STOPPED_NO_RETRY_OPERATOR_REVIEW_REQUIRED'
    assert broker.ledger.read_bytes() == before
    assert not broker.claim.exists()


@pytest.mark.parametrize('field', ['binding','approved_by','approved_at','expires_at','nonce'])
@pytest.mark.parametrize('bad', [None, True, 1, [], {}])
def test_approval_field_types(broker, field, bad):
    blocked(change(broker, 'approval', lambda value: value.update({field: bad})))


@pytest.mark.parametrize('field', ['requester_uid','account_device','account_inode','ledger_device','ledger_inode'])
@pytest.mark.parametrize('bad', [True, -1, 1.0, '1', [], None])
def test_nested_integer_types(broker, field, bad):
    blocked(change(broker, 'approval', lambda value: value['binding'].update({field: bad})))


@pytest.mark.parametrize('field', ['release_commit','baseline_sha256','seller_id','marketplace_id',
    'application_id','credential_sha256','evidence_sha256','account_lock','ledger','ledger_lock','credential_path'])
@pytest.mark.parametrize('bad', [None, True, [], {}, '', ' invalid\n'])
def test_nested_scalar_types(broker, field, bad):
    blocked(change(broker, 'approval', lambda value: value['binding'].update({field: bad})))


@pytest.mark.parametrize('field', ['seller_id','application_id','marketplace_id','credential_sha256',
    'reviewer','reviewed_at', *contract.EVIDENCE])
@pytest.mark.parametrize('bad', [None, True, 1, [], {}, ''])
def test_evidence_field_types(broker, field, bad):
    blocked(change(broker, 'evidence', lambda value: value.update({field: bad})))


@pytest.mark.parametrize('section', contract.EVIDENCE)
@pytest.mark.parametrize('item', [dict(confirmed=1,reference='fixture'),dict(confirmed=True,reference=' '),
    dict(confirmed=True,reference=[]),dict(confirmed=True,reference='x',extra='forbidden'),
    dict(confirmed=True),dict(reference='x'),dict(confirmed=True,reference='x'*2049)])
def test_nested_evidence_exact_schema(broker, section, item):
    blocked(change(broker, 'evidence', lambda value: value.update({section:item})))


@pytest.mark.parametrize('target', ['approval','evidence'])
@pytest.mark.parametrize('problem', ['extra','missing','duplicate','oversized','hardlink','symlink'])
def test_document_integrity(broker, target, problem):
    path = getattr(broker,target)
    if problem in ('extra','missing'):
        def mutate(value):
            if problem == 'extra': value['unexpected'] = True
            else: value.pop(next(iter(value)))
        broker = change(broker,target,mutate)
    elif problem == 'duplicate': path.write_bytes(b'{"binding":{},"binding":{}}')
    elif problem == 'oversized': path.write_bytes(b' '*65537)
    elif problem == 'hardlink': os.link(path, path.with_name(target+'-link'))
    else:
        path.rename(path.with_name(target+'-original'))
        path.symlink_to(path.with_name(target+'-original'))
    blocked(broker)


@pytest.mark.parametrize('timestamp', [0,True,[],{},'2026-11-06','2026-11-06T12:00:00',
    '2026-99-99T12:00:00+00:00','2026-11-06 12:00:00+00:00','2026-11-06T12:00:00+99:00'])
def test_timestamp_grammar(timestamp):
    with pytest.raises((ValueError,TypeError)): contract.aware(timestamp)


@pytest.mark.parametrize('seller', ['seller with space','a'*33,'lowercase','SELLER\n','',[],True])
def test_invalid_seller_even_if_policy_and_documents_agree(broker,seller):
    policy = replace(broker,seller_id=seller)
    approval = read(policy.approval); approval['binding'] = policy.binding()
    write(policy.approval,approval,replace=True)
    blocked(policy)


def test_boolean_authenticated_uid(broker):
    with pytest.raises(m902.BrokerError): run(replace(broker,requester_uid=1),peer_uid=True)
    assert not broker.claim.exists()


def test_parent_replacement_after_pin(broker):
    directory = broker.root/'private'; directory.mkdir(mode=0o700)
    path = directory/'data'; write(path,dict(original=True))
    with Store(broker) as storage:
        assert storage.read(path) == path.read_bytes()
        directory.rename(broker.root/'original')
        directory.mkdir(mode=0o700)
        write(path,dict(attacker=True))
        with pytest.raises(ValueError): storage.read(path)
        with pytest.raises(ValueError): storage.write(path,dict(changed=True),replace=True)
    assert read(path) == dict(attacker=True)
    assert read(broker.root/'original'/'data') == dict(original=True)


def test_parent_substitution_during_write_cannot_redirect(broker,monkeypatch):
    directory = broker.root/'private'; directory.mkdir(mode=0o700)
    path = directory/'data'; write(path,dict(original=True))
    real_replace = os.replace
    def attack(src,dst,**kwargs):
        directory.rename(broker.root/'old')
        directory.mkdir(mode=0o700)
        write(path,dict(attacker=True))
        return real_replace(src,dst,**kwargs)
    with Store(broker) as storage:
        storage.read(path)
        monkeypatch.setattr(os,'replace',attack)
        with pytest.raises(ValueError): storage.write(path,dict(updated=True),replace=True)
    assert read(path) == dict(attacker=True)
    assert read(broker.root/'old'/'data') == dict(updated=True)


def test_open_replacement_never_reads_attacker_bytes(broker,monkeypatch):
    real_open = os.open
    path = broker.evidence
    def attack(name,flags,*args,**kwargs):
        if name == path.name and kwargs.get('dir_fd') is not None:
            path.rename(path.with_name('saved'))
            write(path,dict(attacker=True))
        return real_open(name,flags,*args,**kwargs)
    monkeypatch.setattr(os,'open',attack)
    blocked(broker)


def test_directory_substitution_while_opening(broker,monkeypatch):
    directory = broker.root/'private'; directory.mkdir(mode=0o700)
    path = directory/'data'; write(path,dict(original=True))
    real_open = os.open
    def attack(name,flags,*args,**kwargs):
        if name == 'private' and flags & os.O_DIRECTORY:
            directory.rename(broker.root/'saved')
            directory.mkdir(mode=0o700)
            write(path,dict(attacker=True))
        return real_open(name,flags,*args,**kwargs)
    monkeypatch.setattr(os,'open',attack)
    with Store(broker) as storage:
        with pytest.raises(ValueError): storage.read(path)


def test_credential_bytes_hashed_are_the_bytes_parsed(broker,monkeypatch):
    original = m902.parse_configuration
    def parse(raw):
        # Replace pathname after descriptor snapshot. Parsing must use reviewed bytes.
        broker.credentials.write_bytes(b'attacker-malformed-content')
        assert b'fixture-secret' in raw
        return original(raw)
    monkeypatch.setattr(m902,'parse_configuration',parse)
    assert run(broker)['purchase_authorized'] is False


def test_ledger_snapshot_is_not_reopened_by_history(broker,monkeypatch):
    monkeypatch.setattr(m902.m90,'history',lambda *_: pytest.fail('Pathname reopen'))
    assert run(broker)['purchase_authorized'] is False


def test_no_live_network_and_no_mutation_on_invalid_document(broker,monkeypatch):
    def forbidden(*args,**kwargs): pytest.fail('Network attempted')
    monkeypatch.setattr(socket,'getaddrinfo',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    broker = change(broker,'evidence',lambda value:value.update(reviewer=[]))
    paths = list(broker.root.iterdir())
    before = {p:(p.read_bytes(),p.stat().st_mode,p.stat().st_ino,p.stat().st_mtime_ns) for p in paths}
    blocked(broker)
    assert set(broker.root.iterdir()) == set(paths)
    for path in paths:
        assert (path.read_bytes(),path.stat().st_mode,path.stat().st_ino,path.stat().st_mtime_ns) == before[path]
