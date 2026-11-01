"""Dedicated append-only request accounting for injected adapter tests; no ASIN claims."""
import os
from pathlib import Path
import sqlite3
from copy import deepcopy
from app.observations import canonical, fingerprint
from app.m71_manifest import validate


class Journal:
    """New paths only; never open, migrate, reset or resume historical ledgers."""
    def __init__(self,path: Path,manifest: dict):
        validate(manifest)
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):raise ValueError('No symlink accounting paths')
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
        self.db=sqlite3.connect(path);self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE m71_events(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,
                previous_sha256 TEXT NOT NULL,event_sha256 TEXT NOT NULL UNIQUE);
            CREATE UNIQUE INDEX m71_single_start ON m71_events(kind) WHERE kind='START';
            CREATE TRIGGER immutable_m71_update BEFORE UPDATE ON m71_events BEGIN SELECT RAISE(ABORT,'immutable'); END;
            CREATE TRIGGER immutable_m71_delete BEFORE DELETE ON m71_events BEGIN SELECT RAISE(ABORT,'immutable'); END;
        ''')
        self.manifest=deepcopy(manifest);self.digest=manifest['proposal_sha256'];self._append('BIND',dict(proposal_sha256=self.digest))

    def _append(self,kind: str,payload: dict):
        last=self.db.execute('SELECT event_sha256 FROM m71_events ORDER BY id DESC LIMIT 1').fetchone()
        previous=last[0] if last else '0'*64
        digest=fingerprint(dict(kind=kind,payload=payload,previous_sha256=previous))
        self.db.execute('INSERT INTO m71_events(kind,payload,previous_sha256,event_sha256) VALUES (?,?,?,?)',
            (kind,canonical(payload),previous,digest))

    def start(self):
        with self.db:self._append('START',dict(proposal_sha256=self.digest))

    def consume(self,phase: str,request_sha256: str) -> int:
        if phase not in ('authentication','keyword','identifier'):raise ValueError('Catalog-only phases')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if not self.db.execute("SELECT 1 FROM m71_events WHERE kind='START'").fetchone():raise ValueError('One-shot start required')
            if self.db.execute("SELECT 1 FROM m71_events WHERE kind IN ('STOP','COMPLETE')").fetchone():raise ValueError('Terminal journal cannot resume')
            rows=self.db.execute("SELECT payload FROM m71_events WHERE kind='ATTEMPT'").fetchall()
            import json
            attempts=[json.loads(r[0]) for r in rows]
            if len(attempts)>=251 or sum(a['phase']==phase for a in attempts)>=self.manifest['budget'][phase]:
                raise ValueError('Absolute or phase request budget exhausted')
            if (not attempts and phase!='authentication') or (attempts and phase=='authentication'):
                raise ValueError('Exactly one first authentication slot required')
            slot=len(attempts)+1
            self._append('ATTEMPT',dict(slot=slot,phase=phase,request_sha256=request_sha256))
            self.db.commit();return slot
        except BaseException:self.db.rollback();raise

    def response(self,slot: int,page: dict | None,response_sha256: str):
        with self.db:self._append('RESPONSE',dict(slot=slot,page=page,response_sha256=response_sha256))

    def finish(self,status: str):
        if status not in ('STOP','COMPLETE'):raise ValueError('Fixed terminal states required')
        with self.db:self._append(status,dict(reason='TERMINAL_NO_REPLAY'))

    def count(self) -> int:
        return self.db.execute("SELECT count(*) FROM m71_events WHERE kind='ATTEMPT'").fetchone()[0]

    def close(self):self.db.close()


def checkpoint(path: Path,manifest: dict) -> dict:
    """Read-only recovery/audit after stop or hard kill; never continue dispatch."""
    import json
    from app.m67_state import readonly
    validate(manifest)
    db=readonly(path)
    try:
        previous='0'*64;attempts=[];responses={};bound=False;started=False;terminal=None
        for kind,text,prior,digest in db.execute('SELECT kind,payload,previous_sha256,event_sha256 FROM m71_events ORDER BY id'):
            payload=json.loads(text)
            if prior!=previous or digest!=fingerprint(dict(kind=kind,payload=payload,previous_sha256=previous)):
                raise ValueError('Checkpoint chain integrity failure')
            previous=digest
            if terminal is not None:raise ValueError('Events after terminal boundary')
            if kind=='BIND':
                if bound or started or payload!=dict(proposal_sha256=manifest['proposal_sha256']):raise ValueError('Frozen checkpoint binding required')
                bound=True
            elif kind=='START':
                if not bound or started or payload!=dict(proposal_sha256=manifest['proposal_sha256']):raise ValueError('Single bound start required')
                started=True
            elif kind=='ATTEMPT':
                if not started or payload['slot']!=len(attempts)+1:raise ValueError('Sequential accounted request slots required')
                phase=payload['phase']
                if phase not in ('authentication','keyword','identifier') or len(attempts)>=251:
                    raise ValueError('Invalid checkpoint operation/budget')
                if sum(a['phase']==phase for a in attempts)>=manifest['budget'][phase]:raise ValueError('Checkpoint phase budget exceeded')
                if (not attempts and phase!='authentication') or (attempts and phase=='authentication'):raise ValueError('Authentication order drift')
                attempts.append(payload)
            elif kind=='RESPONSE':
                slot=payload['slot']
                if type(slot) is not int or not 1<=slot<=len(attempts) or slot in responses:raise ValueError('Unbound/duplicate response')
                responses[slot]=payload
            elif kind in ('STOP','COMPLETE'):terminal=kind
            else:raise ValueError('Unknown checkpoint event')
        if not bound:raise ValueError('Missing frozen binding')
        pages=[responses[s]['page'] for s in sorted(responses) if responses[s]['page'] is not None]
        return dict(status='COMPLETED_NO_REPLAY' if terminal=='COMPLETE' else 'STOPPED_NO_REPLAY' if terminal=='STOP' else 'UNCERTAIN_NO_REPLAY',
            requests_consumed=len(attempts),uncertain_slots=[a['slot'] for a in attempts if a['slot'] not in responses],
            pages=pages,checkpoint_sha256=previous,proposal_sha256=manifest['proposal_sha256'],
            execution_authorized=False,new_asin_reservations=0,eligibility='UNKNOWN')
    finally:db.close()
