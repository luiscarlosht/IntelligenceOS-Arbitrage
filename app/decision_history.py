"""Private append-only observation history, separate from protected acquisition ledgers."""
from contextlib import contextmanager
from datetime import datetime,timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import stat
from app.evidence_io import safe
from app.observations import canonical,fingerprint

DDL=("CREATE TABLE observations (sequence INTEGER PRIMARY KEY, identity TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, previous TEXT NOT NULL, digest TEXT NOT NULL)",
     "CREATE TRIGGER no_update BEFORE UPDATE ON observations BEGIN SELECT RAISE(ABORT,'immutable history'); END",
     "CREATE TRIGGER no_delete BEFORE DELETE ON observations BEGIN SELECT RAISE(ABORT,'immutable history'); END")


@contextmanager
def database(path:Path):
    path=safe(path);parent=path.parent
    info=parent.stat()
    if not parent.is_dir() or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('Owned private history directory required')
    for p in (parent,path):
        if p.exists() and {'system.posix_acl_access','system.posix_acl_default'}&set(os.listxattr(p,follow_symlinks=False)):
            raise ValueError('History ACL forbidden')
    created=False
    if not path.exists():
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600);os.close(fd);created=True
    info=path.stat()
    if not path.is_file() or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:raise ValueError('Private single-link history required')
    if info.st_size>64*1024*1024:raise ValueError('History size bound exceeded')
    if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal')):raise ValueError('Unexpected history sidecar')
    if not created:
        # Validate a preexisting file without changing its journal mode or schema.
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0) as readonly:
            schema=tuple(row[0] for row in readonly.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY rowid"))
            if schema!=DDL:raise ValueError('Exact history schema required')
    db=sqlite3.connect(path,timeout=0)
    try:
        db.execute('PRAGMA journal_mode=DELETE');db.execute('PRAGMA synchronous=FULL')
        if created:
            with db:
                for sql in DDL:db.execute(sql)
        schema=tuple(row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY rowid"))
        if schema!=DDL:raise ValueError('Exact history schema required')
        db.execute('BEGIN IMMEDIATE')
        previous='0'*64;expected_sequence=1
        for sequence,marker,payload,prior,digest in db.execute('SELECT * FROM observations ORDER BY sequence'):
            obj=json.loads(payload)
            if (sequence!=expected_sequence or prior!=previous or payload!=canonical(obj) or marker!=fingerprint(obj)
                    or digest!=fingerprint([sequence,marker,payload,prior])):raise ValueError('History chain mismatch')
            previous=digest;expected_sequence+=1
        yield db
        db.commit()
    except BaseException:
        db.rollback();raise
    finally:db.close()


def record(db,report:dict) -> list[dict]:
    last=db.execute('SELECT sequence,digest FROM observations ORDER BY sequence DESC LIMIT 1').fetchone()
    sequence,previous=last if last else (0,'0'*64)
    for row in report.get('historical_rows',report['rows']):
        payload=dict(evidence_sha256=report['evidence_sha256'],source_kind=report['source_kind'],asin=row['asin'],
            marketplace=row['marketplace'],condition=row['condition'],account_binding_sha256=row['account_binding_sha256'],
            # Raw reported observations are preserved, even when they later become stale.
            provenance=row['provenance'],prices=row['prices'],ranks=row['ranks'],new_offer_count=row['new_offer_count'],
            listing_permission=row['listing_permission'])
        marker=fingerprint(payload)
        if db.execute('SELECT 1 FROM observations WHERE identity=?',(marker,)).fetchone():continue
        sequence+=1;text=canonical(payload);digest=fingerprint([sequence,marker,text,previous])
        db.execute('INSERT INTO observations VALUES (?,?,?,?,?)',(sequence,marker,text,previous,digest));previous=digest
    return [json.loads(row[0]) for row in db.execute('SELECT payload FROM observations ORDER BY sequence')]


def trend(history:list[dict],row:dict,kind:str,now:datetime) -> dict:
    samples={}
    for item in history:
        if item['source_kind']!=kind or any(item[k]!=row[k] for k in ('asin','marketplace','condition','account_binding_sha256')):continue
        # M80 slot22 is the sole New-offers observation timestamp, never report generation time.
        stamp=item['provenance'].get('22',{}).get('observed_at')
        if not stamp:continue
        observed=datetime.fromisoformat(stamp)
        if observed.tzinfo is None or not now-timedelta(days=30)<=observed<=now:continue
        for price in item['prices']:
            if price['basis']=='lowest_observed' and price.get('fulfillment')=='Amazon' and price['landed_usd'] is not None:
                key=stamp
                value=Decimal(price['landed_usd'])
                # Conflicting same-time records do not become independent samples.
                if key in samples and samples[key]!=value:return dict(price_stability='UNKNOWN',reason='CONFLICTING_SAME_TIME_PRICES')
                samples[key]=value
    ordered=sorted(samples)
    if len(ordered)<7 or datetime.fromisoformat(ordered[-1])-datetime.fromisoformat(ordered[0])<timedelta(days=7):
        return dict(price_stability='UNKNOWN',comparable_samples=len(ordered),basis='US_NEW_LOWEST_AMAZON_FULFILLMENT_30D')
    low=min(samples.values());high=max(samples.values())
    if low<=0:return dict(price_stability='UNKNOWN',reason='NONPOSITIVE_PRICE')
    spread=(high-low)/low*100
    return dict(price_stability='OBSERVED_RANGE_ONLY',comparable_samples=len(ordered),observed_spread_percent=str(spread),
        first_observed_at=ordered[0],last_observed_at=ordered[-1],basis='US_NEW_LOWEST_AMAZON_FULFILLMENT_30D',
        limitation='Selected observation range, not continuous stability, future price or sales velocity')
