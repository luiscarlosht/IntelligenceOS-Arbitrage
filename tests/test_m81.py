from copy import deepcopy
from datetime import timedelta
import hashlib
from pathlib import Path
import socket
import sqlite3
import pytest
from app import m80_contract as c,m80_execution as x
from app.m80_demo import demonstrate
from app.m80_journal import inspect
from app.sales_evidence import load_ledger
from app.evidence_io import offline,publication,pinned,json_write


def test_historical_read_does_not_relax_live_code_gate(tmp_path,monkeypatch):
    demonstrate(tmp_path/'demo')
    path=tmp_path/'demo/synthetic-m80.sqlite3';sha=hashlib.sha256(path.read_bytes()).hexdigest()
    before=path.stat().st_mtime_ns
    monkeypatch.setattr(c,'implementation',lambda:{'changed.py':'f'*64})
    with pytest.raises(ValueError):inspect(path)
    snapshot=inspect(path,historical=True)
    from datetime import datetime,timezone
    report=load_ledger(path,sha,datetime(2026,11,3,1,tzinfo=timezone.utc))
    assert report['source_kind']=='SYNTHETIC' and report['requests_consumed']==42
    assert path.stat().st_mtime_ns==before
    with pytest.raises(ValueError):c.validate(snapshot['binding']['plan'])


def test_pin_mismatch_rejected_before_import(tmp_path):
    path=tmp_path/'not-a-ledger';path.write_text('unchanged')
    from datetime import datetime,timezone
    with pytest.raises(ValueError):load_ledger(path,'0'*64,datetime.now(timezone.utc))


def test_duplicate_http_rate_headers_rejected_without_retries(tmp_path,monkeypatch):
    from email.message import Message
    from io import BytesIO
    from app.m80_demo import plan,SyntheticTransport
    p=plan(tmp_path);t=SyntheticTransport(p);calls=[]
    class Response(BytesIO):
        status=200
        headers=Message()
    Response.headers.add_header('x-amzn-RateLimit-Limit','1')
    Response.headers.add_header('x-amzn-RateLimit-Limit','0.01')
    class Opener:
        def open(self,*a,**kw):calls.append(1);return Response(b'{}')
    monkeypatch.setattr(x,'build_opener',lambda *a:Opener())
    with pytest.raises(ValueError,match='Ambiguous duplicate'):x.Transport.send(t,t.build(p['requests'][0]),p['requests'][0])
    assert calls==[1]


def test_offline_boundary_and_exclusive_publication(tmp_path):
    inputs=tmp_path/'inputs';inputs.mkdir()
    source=inputs/'original.json';source.write_text('{}');out=tmp_path/'report'
    with publication(out,[source]) as stage:
        with offline(reads=[source],writes=[stage]):
            with pytest.raises(PermissionError):socket.socket()
            with pytest.raises(PermissionError):source.write_text('bad')
            json_write(stage/'result.json',{'purchase_authorized':False})
    assert source.read_text()=='{}' and (out/'result.json').exists()
    with pytest.raises(ValueError):
        with publication(out,[source]):pass
