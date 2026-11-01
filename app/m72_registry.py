"""Fixed-operation, permanent one-shot request registry. Never stores ASIN claims."""
import json
import os
from pathlib import Path
import sqlite3
from app.m67_state import secure, readonly
from app.m72_policy import OPERATION
from app.observations import canonical, fingerprint


class Registry:
    def __init__(self,path: Path,binding: dict):
        secure(path.parent,directory=True)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:os.fsync(fd)
        finally:os.close(fd)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(directory)
        finally:os.close(directory)
        self.db=sqlite3.connect(path);self.db.execute('PRAGMA synchronous=FULL');self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.executescript('''
            CREATE TABLE m72_operation(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE m72_events(slot INTEGER,kind TEXT NOT NULL,payload TEXT NOT NULL,
                previous_sha256 TEXT NOT NULL,event_sha256 TEXT NOT NULL UNIQUE);
            CREATE UNIQUE INDEX m72_unique_attempt ON m72_events(slot) WHERE kind='ATTEMPT';
            CREATE UNIQUE INDEX m72_unique_response ON m72_events(slot) WHERE kind='RESPONSE';
            CREATE UNIQUE INDEX m72_unique_terminal ON m72_events(kind) WHERE kind='TERMINAL';
        ''')
        for table in ('m72_operation','m72_events'):
            for op in ('UPDATE','DELETE'):
                self.db.execute(f"CREATE TRIGGER immutable_{table}_{op} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
        with self.db:
            self.db.execute('INSERT INTO m72_operation VALUES (?,?)',(OPERATION,canonical(binding)))
            self._append('CLAIM',None,dict(operation_id=OPERATION,binding_sha256=fingerprint(binding)))

    def _append(self,kind,slot,payload):
        last=self.db.execute('SELECT event_sha256 FROM m72_events ORDER BY rowid DESC LIMIT 1').fetchone()
        prior=last[0] if last else '0'*64
        digest=fingerprint(dict(kind=kind,slot=slot,payload=payload,previous_sha256=prior))
        self.db.execute('INSERT INTO m72_events VALUES (?,?,?,?,?)',(slot,kind,canonical(payload),prior,digest))

    def consume(self,slot: int,request_sha256: str):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            count=self.count()
            if (type(slot) is not int or slot!=count+1 or not 1<=slot<=10
                    or self.db.execute("SELECT 1 FROM m72_events WHERE kind='TERMINAL'").fetchone()
                    or (slot>1 and not self.db.execute("SELECT 1 FROM m72_events WHERE kind='RESPONSE' AND slot=?",(slot-1,)).fetchone())):
                raise ValueError('Fixed one-shot ten-slot sequence required')
            self._append('ATTEMPT',slot,dict(phase='authentication' if slot==1 else 'keyword',
                query_reference=None if slot==1 else f'q{slot-1:03}',request_sha256=request_sha256))
            self.db.commit()
        except BaseException:self.db.rollback();raise

    def response(self,slot: int,page: dict | None,source: str):
        if not self.db.execute("SELECT 1 FROM m72_events WHERE kind='ATTEMPT' AND slot=?",(slot,)).fetchone():
            raise ValueError('Response without consumed request')
        with self.db:self._append('RESPONSE',slot,dict(page=page,response_sha256=source))

    def finish(self,completed: bool):
        if completed and self.count()!=10:raise ValueError('Ten successful slots required for completion')
        with self.db:self._append('TERMINAL',None,dict(status='COMPLETED_NO_REPLAY' if completed else 'STOPPED_NO_REPLAY'))

    def count(self):return self.db.execute("SELECT count(*) FROM m72_events WHERE kind='ATTEMPT'").fetchone()[0]
    def close(self):self.db.close()


def inspect(path: Path) -> dict:
    db=readonly(path)
    try:
        for table in ('m72_operation','m72_events'):
            triggers=[r[0].upper() for r in db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))]
            if not all(any('BEFORE '+op in sql and 'RAISE(ABORT' in sql for sql in triggers) for op in ('UPDATE','DELETE')):
                raise ValueError('Immutable registry protections required')
        operations=db.execute('SELECT id,payload FROM m72_operation').fetchall()
        if len(operations)!=1 or operations[0][0]!=OPERATION:raise ValueError('Permanent operation identity required')
        binding=json.loads(operations[0][1]);prior='0'*64;attempts=[];responses={};status='UNCERTAIN_NO_REPLAY';claimed=False;ended=False
        for slot,kind,text,previous,digest in db.execute('SELECT * FROM m72_events ORDER BY rowid'):
            payload=json.loads(text)
            if ended or previous!=prior or digest!=fingerprint(dict(kind=kind,slot=slot,payload=payload,previous_sha256=prior)):
                raise ValueError('Registry chain corruption')
            prior=digest
            if kind=='CLAIM':
                if claimed or payload!=dict(operation_id=OPERATION,binding_sha256=fingerprint(binding)):raise ValueError('Claim binding drift')
                claimed=True
            elif kind=='ATTEMPT':
                if not claimed or type(slot) is not int or slot!=len(attempts)+1 or slot>10 or (slot>1 and slot-1 not in responses):
                    raise ValueError('Invalid request sequence')
                if payload['phase']!=('authentication' if slot==1 else 'keyword') or payload['query_reference']!=(None if slot==1 else f'q{slot-1:03}'):
                    raise ValueError('Operation outside pilot scope')
                attempts.append(slot)
            elif kind=='RESPONSE':
                if slot not in attempts or slot in responses:raise ValueError('Unbound response')
                responses[slot]=payload
            elif kind=='TERMINAL':
                ended=True;status=payload['status']
                if status not in ('COMPLETED_NO_REPLAY','STOPPED_NO_REPLAY'):raise ValueError('Invalid terminal state')
                if status=='COMPLETED_NO_REPLAY' and (len(attempts)!=10 or len(responses)!=10):raise ValueError('Incomplete completion')
            else:raise ValueError('Unknown registry event')
        if not claimed:raise ValueError('Incomplete registry initialization; no replay')
        return dict(binding=binding,status=status,requests_consumed=len(attempts),
            uncertain_slots=sorted(set(attempts)-set(responses)),
            pages=[responses[s]['page'] for s in sorted(responses) if responses[s]['page'] is not None],
            checkpoint_sha256=prior)
    finally:db.close()
