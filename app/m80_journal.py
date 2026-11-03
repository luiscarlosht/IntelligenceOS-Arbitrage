"""M80 permanent claim, immutable hash-chain and durable before-send intents."""
import json
import os
from pathlib import Path
import sqlite3
from app.m67_state import secure, readonly
from app.m80_contract import OPERATION
from app.observations import canonical, fingerprint


def accepted(plan:dict,slot:int,frame:dict) -> bool:
    if frame.get('http_status')!=200 or any(k.casefold()=='retry-after' for k in frame.get('headers',{})):
        return False
    body=frame.get('body',{})
    if slot==1:
        return (set(body)=={'authenticated','expires_in'} and body['authenticated'] is True
                and type(body['expires_in']) is int and body['expires_in']>5)
    from app.m80_evidence import validate_response
    try: validate_response(plan['requests'][slot-1],body)
    except (ValueError,TypeError,KeyError,AttributeError): return False
    return True


class Journal:
    def __init__(self, path: Path, binding: dict):
        secure(path.parent,directory=True)
        if any(Path(str(path)+suffix).exists() or Path(str(path)+suffix).is_symlink() for suffix in ('-journal','-wal','-shm')):
            raise ValueError('Existing journal sidecar; no reset/recovery by execution')
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        os.fsync(fd); os.close(fd)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try: os.fsync(directory)
        finally: os.close(directory)
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA synchronous=FULL'); self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.executescript('''
            CREATE TABLE operation(payload TEXT NOT NULL);
            CREATE TABLE events(kind TEXT NOT NULL,slot INTEGER,payload TEXT NOT NULL,prior TEXT NOT NULL,digest TEXT NOT NULL UNIQUE);
            CREATE UNIQUE INDEX once_attempt ON events(slot) WHERE kind='ATTEMPT';
            CREATE UNIQUE INDEX once_response ON events(slot) WHERE kind='RESPONSE';
            CREATE UNIQUE INDEX once_boundary ON events(kind) WHERE kind IN ('CLAIM','START','TERMINAL');
        ''')
        for table in ('operation','events'):
            for verb in ('UPDATE','DELETE'):
                self.db.execute(f"CREATE TRIGGER immutable_{table}_{verb} BEFORE {verb} ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
        with self.db:
            self.db.execute('INSERT INTO operation VALUES (?)',(canonical(binding),))
            self.append('CLAIM',None,dict(operation_id=OPERATION,binding_sha256=fingerprint(binding)))

    def append(self,kind:str,slot:int|None,payload:dict) -> None:
        last=self.db.execute('SELECT digest FROM events ORDER BY rowid DESC LIMIT 1').fetchone()
        prior=last[0] if last else '0'*64
        sha=fingerprint(dict(kind=kind,slot=slot,payload=payload,prior=prior))
        self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)',(kind,slot,canonical(payload),prior,sha))

    def start(self) -> None:
        if self.db.execute("SELECT 1 FROM events WHERE kind IN ('START','TERMINAL')").fetchone(): raise ValueError('No restart')
        with self.db: self.append('START',None,{'operation_id':OPERATION})

    def consume(self,definition:dict) -> None:
        slot=definition['slot']
        if type(slot) is not int or not 1<=slot<=42: raise ValueError('42-slot budget')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            binding=json.loads(self.db.execute('SELECT payload FROM operation').fetchone()[0])
            count=self.db.execute("SELECT count(*) FROM events WHERE kind='ATTEMPT'").fetchone()[0]
            if (definition!=binding['plan']['requests'][slot-1] or slot!=count+1
                    or not self.db.execute("SELECT 1 FROM events WHERE kind='START'").fetchone()
                    or self.db.execute("SELECT 1 FROM events WHERE kind='TERMINAL'").fetchone()
                    or slot>1 and not self.db.execute("SELECT 1 FROM events WHERE kind='RESPONSE' AND slot=?",(slot-1,)).fetchone()):
                raise ValueError('Exact sequential intent required')
            if slot>1:
                previous=json.loads(self.db.execute("SELECT payload FROM events WHERE kind='RESPONSE' AND slot=?",(slot-1,)).fetchone()[0])
                if not accepted(binding['plan'],slot-1,previous): raise ValueError('No dispatch after rejected response')
            self.append('ATTEMPT',slot,{'definition_sha256':fingerprint(definition)})
            self.db.commit()
        except BaseException: self.db.rollback(); raise

    def response(self,slot:int,frame:dict) -> None:
        last=self.db.execute("SELECT max(slot) FROM events WHERE kind='ATTEMPT'").fetchone()[0]
        if last!=slot or self.db.execute("SELECT 1 FROM events WHERE kind='TERMINAL'").fetchone(): raise ValueError('Unbound response')
        if slot==1 and set(frame.get('body',{}))-{'authenticated','expires_in'}:
            raise ValueError('Authentication secrets must never be persisted')
        with self.db: self.append('RESPONSE',slot,frame)

    def finish(self,success:bool) -> None:
        if success and self.db.execute("SELECT count(*) FROM events WHERE kind='RESPONSE'").fetchone()[0]!=42:
            raise ValueError('All successes required')
        if success:
            plan=json.loads(self.db.execute('SELECT payload FROM operation').fetchone()[0])['plan']
            if any(not accepted(plan,s,json.loads(raw)) for s,raw in self.db.execute("SELECT slot,payload FROM events WHERE kind='RESPONSE'")):
                raise ValueError('Rejected response cannot complete')
        with self.db: self.append('TERMINAL',None,{'status':'COMPLETED_NO_REPLAY' if success else 'STOPPED_NO_REPLAY'})

    def close(self) -> None: self.db.close()


def inspect(path:Path) -> dict:
    db=readonly(path)
    try:
        for table in ('operation','events'):
            triggers=[r[0].upper() for r in db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))]
            if not all(any('BEFORE '+verb in sql and 'RAISE(ABORT' in sql for sql in triggers) for verb in ('UPDATE','DELETE')):
                raise ValueError('Immutable protections required')
        operations=db.execute('SELECT payload FROM operation').fetchall()
        if len(operations)!=1: raise ValueError('Single operation binding required')
        binding=json.loads(operations[0][0]); plan=binding['plan']
        from app.m80_contract import validate
        validate(plan)
        prior='0'*64; claimed=started=ended=False; attempts=[]; responses={}; status='UNCERTAIN_NO_REPLAY'
        for kind,slot,raw,previous,digest in db.execute('SELECT * FROM events ORDER BY rowid'):
            value=json.loads(raw)
            if ended or previous!=prior or digest!=fingerprint(dict(kind=kind,slot=slot,payload=value,prior=previous)):
                raise ValueError('Journal chain drift')
            prior=digest
            if kind=='CLAIM':
                if claimed or slot is not None or value!={'operation_id':OPERATION,'binding_sha256':fingerprint(binding)}: raise ValueError('Claim required')
                claimed=True
            elif kind=='START':
                if not claimed or started or slot is not None or value!={'operation_id':OPERATION}: raise ValueError('Single start required')
                started=True
            elif kind=='ATTEMPT':
                if (not started or type(slot) is not int or slot!=len(attempts)+1 or not 1<=slot<=42
                        or slot>1 and slot-1 not in responses
                        or value!={'definition_sha256':fingerprint(plan['requests'][slot-1])}): raise ValueError('Intent drift')
                if slot>1 and not accepted(plan,slot-1,responses[slot-1]): raise ValueError('Requests after failed response')
                attempts.append(slot)
            elif kind=='RESPONSE':
                if not attempts or slot!=attempts[-1] or slot in responses: raise ValueError('Response without intent')
                if (set(value)!={'http_status','headers','body','observed_at','source_sha256'}
                        or type(value['http_status']) is not int or not isinstance(value['headers'],dict)
                        or not isinstance(value['body'],dict) or value['source_sha256']!=fingerprint(value['body'])):
                    raise ValueError('Invalid response provenance')
                from datetime import datetime
                if datetime.fromisoformat(value['observed_at']).tzinfo is None: raise ValueError('Aware evidence time required')
                responses[slot]=value
            elif kind=='TERMINAL':
                if not claimed or slot is not None or value not in ({'status':'COMPLETED_NO_REPLAY'},{'status':'STOPPED_NO_REPLAY'}): raise ValueError('Invalid terminal')
                status=value['status']; ended=True
                if status=='COMPLETED_NO_REPLAY' and (len(responses)!=42 or len(attempts)!=42): raise ValueError('Incomplete completion')
                if status=='COMPLETED_NO_REPLAY' and any(not accepted(plan,s,f) for s,f in responses.items()): raise ValueError('False completion')
            else: raise ValueError('Unknown event')
        if not claimed: raise ValueError('Incomplete claim; permanently blocked')
        return dict(binding=binding,status=status,requests_consumed=len(attempts),
            uncertain_slots=sorted(set(attempts)-set(responses)),responses=responses,checkpoint_sha256=prior)
    finally: db.close()
