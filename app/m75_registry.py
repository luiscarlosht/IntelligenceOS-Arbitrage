"""New permanent M75 claim and hash-chained, before-dispatch accounting."""
import json
import os
from pathlib import Path
import re
import sqlite3

from app.m67_state import secure, readonly
from app.m74_plan import OPERATION
from app.m75_policy import requests
from app.observations import canonical, fingerprint


def validate_response(slot: int, page: dict | None, source: str, binding: dict):
    if type(slot) is not int or not 1<=slot<=21:raise ValueError('Bounded response slot required')
    if not isinstance(source,str) or not re.fullmatch('[a-f0-9]{64}',source):raise ValueError('Response digest required')
    if slot==1:
        if page is not None:raise ValueError('Authentication data must not be persisted')
        return
    definition=requests()[slot-2]
    fields={'query_reference','page_index','page_token','pagination','marketplace_id','http_status',
            'observed_at','items','operation_id','manifest_sha256','request_definition_sha256',
            'request_slot','response_sha256'}
    from app.m65_intelligence import observed
    if (not isinstance(page,dict) or set(page)!=fields or not observed(page.get('observed_at'))
            or page.get('request_slot')!=slot
            or page.get('query_reference')!=definition['query_id'] or page.get('page_index')!=0
            or page.get('page_token') is not None or page.get('operation_id')!=OPERATION
            or page.get('response_sha256')!=source
            or page.get('manifest_sha256')!=binding['preflight']['manifest_sha256']
            or page.get('request_definition_sha256')!=fingerprint(definition)
            or page.get('marketplace_id')!=binding['preflight']['marketplace_id'] or page.get('http_status')!=200):
        raise ValueError('Exact first-page response provenance required')
    from app.m71_adapter import validate_page
    validate_page(dict(items=page['items'],pagination=page['pagination']),prior_tokens=set())


def intent(slot: int) -> dict:
    if type(slot) is not int or not 1<=slot<=21:raise ValueError('Bounded M75 slot required')
    return dict(slot=slot,phase='authentication' if slot==1 else 'keyword',
        query_reference=None if slot==1 else requests()[slot-2]['query_id'],
        request_sha256=fingerprint(dict(slot=slot,phase='authentication',parameters={}) if slot==1 else requests()[slot-2]))


class Registry:
    def __init__(self,path: Path,binding: dict):
        secure(path.parent,directory=True)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:os.fsync(fd)
        finally:os.close(fd)
        parent=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(parent)
        finally:os.close(parent)
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA synchronous=FULL');self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.executescript('''
            CREATE TABLE m75_operation(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE m75_events(slot INTEGER,kind TEXT NOT NULL,payload TEXT NOT NULL,
                previous_sha256 TEXT NOT NULL,event_sha256 TEXT NOT NULL UNIQUE);
            CREATE UNIQUE INDEX m75_unique_attempt ON m75_events(slot) WHERE kind='ATTEMPT';
            CREATE UNIQUE INDEX m75_unique_response ON m75_events(slot) WHERE kind='RESPONSE';
            CREATE UNIQUE INDEX m75_unique_boundary ON m75_events(kind) WHERE kind IN ('CLAIM','START','TERMINAL');
        ''')
        for table in ('m75_operation','m75_events'):
            for operation in ('UPDATE','DELETE'):
                self.db.execute(f"CREATE TRIGGER immutable_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
        with self.db:
            self.db.execute('INSERT INTO m75_operation VALUES (?,?)',(OPERATION,canonical(binding)))
            self._append('CLAIM',None,dict(operation_id=OPERATION,binding_sha256=fingerprint(binding)))

    def _append(self,kind,slot,payload):
        row=self.db.execute('SELECT event_sha256 FROM m75_events ORDER BY rowid DESC LIMIT 1').fetchone()
        prior=row[0] if row else '0'*64
        digest=fingerprint(dict(kind=kind,slot=slot,payload=payload,previous_sha256=prior))
        self.db.execute('INSERT INTO m75_events VALUES (?,?,?,?,?)',(slot,kind,canonical(payload),prior,digest))

    def start(self):
        with self.db:
            if self.db.execute("SELECT 1 FROM m75_events WHERE kind='TERMINAL'").fetchone():raise ValueError('Terminal operation')
            self._append('START',None,dict(operation_id=OPERATION))

    def consume(self,slot: int):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            payload=intent(slot)
            if (slot!=self.count()+1 or self.db.execute("SELECT 1 FROM m75_events WHERE kind='TERMINAL'").fetchone()
                    or not self.db.execute("SELECT 1 FROM m75_events WHERE kind='START'").fetchone()
                    or (slot>1 and not self.db.execute("SELECT 1 FROM m75_events WHERE kind='RESPONSE' AND slot=?",(slot-1,)).fetchone())):
                raise ValueError('Fresh strictly sequential M75 attempt required')
            self._append('ATTEMPT',slot,payload);self.db.commit()
        except BaseException:self.db.rollback();raise

    def response(self,slot: int,page: dict | None,source: str):
        if (slot!=self.count() or not self.db.execute("SELECT 1 FROM m75_events WHERE kind='ATTEMPT' AND slot=?",(slot,)).fetchone()
                or self.db.execute("SELECT 1 FROM m75_events WHERE kind='TERMINAL'").fetchone()):
            raise ValueError('Latest accounted response required')
        binding=json.loads(self.db.execute('SELECT payload FROM m75_operation').fetchone()[0])
        validate_response(slot,page,source,binding)
        with self.db:self._append('RESPONSE',slot,dict(page=page,response_sha256=source))

    def finish(self,completed: bool):
        count=self.db.execute("SELECT count(*) FROM m75_events WHERE kind='RESPONSE'").fetchone()[0]
        if completed and (self.count()!=21 or count!=21):raise ValueError('All 21 successes required for completion')
        with self.db:self._append('TERMINAL',None,dict(status='COMPLETED_NO_REPLAY' if completed else 'STOPPED_NO_REPLAY'))

    def count(self):return self.db.execute("SELECT count(*) FROM m75_events WHERE kind='ATTEMPT'").fetchone()[0]
    def close(self):self.db.close()


def inspect(path: Path) -> dict:
    db=readonly(path)
    try:
        for table in ('m75_operation','m75_events'):
            triggers=[r[0].upper() for r in db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))]
            if not all(any('BEFORE '+op in sql and 'RAISE(ABORT' in sql for sql in triggers) for op in ('UPDATE','DELETE')):
                raise ValueError('Immutable registry protections required')
        operations=db.execute('SELECT id,payload FROM m75_operation').fetchall()
        if len(operations)!=1 or operations[0][0]!=OPERATION:raise ValueError('M75 permanent identity required')
        binding=json.loads(operations[0][1]);previous='0'*64;claimed=started=ended=False
        attempts=[];responses={};status='UNCERTAIN_NO_REPLAY'
        for slot,kind,text,prior,digest in db.execute('SELECT * FROM m75_events ORDER BY rowid'):
            payload=json.loads(text)
            if ended or prior!=previous or digest!=fingerprint(dict(kind=kind,slot=slot,payload=payload,previous_sha256=prior)):
                raise ValueError('M75 chain corruption')
            previous=digest
            if kind=='CLAIM':
                if claimed or slot is not None or payload!=dict(operation_id=OPERATION,binding_sha256=fingerprint(binding)):
                    raise ValueError('Single first claim required')
                claimed=True
            elif kind=='START':
                if not claimed or started or slot is not None or payload!=dict(operation_id=OPERATION):raise ValueError('Single fresh start required')
                started=True
            elif kind=='ATTEMPT':
                if not started or slot!=len(attempts)+1 or payload!=intent(slot) or (slot>1 and slot-1 not in responses):
                    raise ValueError('Out-of-contract request sequence')
                attempts.append(slot)
            elif kind=='RESPONSE':
                if (not attempts or slot!=attempts[-1] or slot in responses or set(payload)!={'page','response_sha256'}
                        or not re.fullmatch('[a-f0-9]{64}',payload['response_sha256'])):
                    raise ValueError('Unbound response')
                validate_response(slot,payload['page'],payload['response_sha256'],binding)
                responses[slot]=payload
            elif kind=='TERMINAL':
                if not claimed or slot is not None or set(payload)!={'status'}:raise ValueError('Invalid terminal boundary')
                status=payload['status'];ended=True
                if status not in ('COMPLETED_NO_REPLAY','STOPPED_NO_REPLAY'):raise ValueError('Invalid terminal state')
                if status=='COMPLETED_NO_REPLAY' and (len(attempts)!=21 or len(responses)!=21):raise ValueError('Incomplete completion')
            else:raise ValueError('Unknown registry event')
        if not claimed:raise ValueError('Incomplete registry initialization permanently blocks replay')
        return dict(binding=binding,status=status,requests_consumed=len(attempts),
            uncertain_slots=sorted(set(attempts)-set(responses)),checkpoint_sha256=previous,
            pages=[responses[s]['page'] for s in sorted(responses) if responses[s]['page'] is not None])
    finally:db.close()
