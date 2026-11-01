"""Offline, allowlisted eligibility evidence and append-only manual intelligence.

No credential, transport or executor imports. Historical facts never authorize
new operations, establish current FBA eligibility, or permit a purchase.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from app.m63_history import ASIN, audit as historical_audit, sha256
from app.normalization import timestamp
from app.observations import canonical, fingerprint

US = 'ATVPDKIKX0DER'
CONDITION = 'new_new'
STATES = ('NO_REPORTED_RESTRICTIONS', 'APPROVAL_REQUIRED', 'NOT_ELIGIBLE',
          'OTHER_RESTRICTED', 'UNKNOWN')
REASONS = {'APPROVAL_REQUIRED', 'NOT_ELIGIBLE', 'ASIN_NOT_FOUND', 'OTHER'}
PRIVATE_KEYS = {'sellerid', 'seller_id', 'seller_reference', 'seller_account_reference',
                'client_id', 'client_secret', 'refresh_token', 'access_token',
                'authorization', 'x-amz-access-token'}


def read_json(path: Path) -> tuple[object, str]:
    if (path.is_symlink() or not path.is_file() or path.stat().st_size > 16*1024*1024
            or re.search(r'credential|token|\.env', path.name, re.I)):
        raise ValueError('Bounded evidence file required; credential files forbidden')
    raw = path.read_bytes()
    return json.loads(raw), __import__('hashlib').sha256(raw).hexdigest()


def private_values(value: object) -> set[str]:
    """Find private context in supplied evidence, never in credential storage."""
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in PRIVATE_KEYS and isinstance(child, str) and child:
                found.add(child)
                if child.casefold().startswith('bearer '):
                    found.add(child[7:].strip())
            found.update(private_values(child))
    elif isinstance(value, list):
        for child in value:
            found.update(private_values(child))
    return found


def safe_text(value: object, secrets: set[str] = frozenset()) -> str:
    if not isinstance(value, str):
        return ''
    for secret in sorted(secrets, key=len, reverse=True):
        value = value.replace(secret, '[REDACTED]')
    return ''.join(c for c in value if c.isprintable()).strip()[:512]


def observed(value: object) -> str | None:
    try:
        dt = timestamp(value) if isinstance(value, str) else None
        return dt.isoformat() if dt else None
    except (TypeError, ValueError):
        return None


def classify(stage: object, marketplace: str, condition: str, observed_at: str | None) -> tuple[str, str, list[str]]:
    """Operation completion, evidence validity and eligibility are independent."""
    operation = 'UNKNOWN'
    codes = []
    try:
        if not isinstance(stage, dict):
            return operation, 'UNKNOWN', codes
        operation = {'succeeded':'SUCCEEDED', 'failed':'FAILED', 'interrupted':'FAILED',
                     'attempted':'UNCERTAIN', 'not_attempted':'NOT_ATTEMPTED'}.get(stage.get('status'), 'UNKNOWN')
        if stage.get('http_status') not in (None, 200):
            operation = 'FAILED'
        if operation != 'SUCCEEDED' or marketplace != US or condition != CONDITION or not observed_at:
            return operation, 'UNKNOWN', codes
        # Future timestamps are not valid observations. Historical observations
        # retain their dates and are never promoted to current unrestrictedness.
        if timestamp(observed_at) > datetime.now(timezone.utc):
            return operation, 'UNKNOWN', codes
        if 'response' in stage:
            raw = stage['response']
            if not isinstance(raw, dict) or raw.get('errors') or not isinstance(raw.get('restrictions'), list):
                raise ValueError('Malformed response')
            rows = raw['restrictions']
            # Amazon's official guide labels exactly [{}] a no-restrictions
            # example, although the model requires marketplaceId on a row.
            # Accept only this exact placeholder after successful US/New scope
            # and observation validation above; mixed/malformed rows stay UNKNOWN.
            if rows == [{}]:
                rows = []
            found = []
            for row in rows:
                if (not isinstance(row, dict) or row.get('marketplaceId') != marketplace
                        or row.get('conditionType') not in (None, condition)
                        or not isinstance(row.get('reasons', []), list)):
                    raise ValueError('Ambiguous response scope')
                for reason in row.get('reasons', []):
                    if not isinstance(reason, dict):
                        raise ValueError('Malformed reason')
                    found.append(reason.get('reasonCode'))
            count, permission, approval = len(rows), not rows, 'APPROVAL_REQUIRED' in found
        else:
            data = stage.get('data')
            if not isinstance(data, dict):
                raise ValueError('Missing normalized evidence')
            count = data.get('restriction_count')
            permission = (data.get('listing_permission') or {}).get('value')
            found = data.get('reason_codes')
            approval = data.get('approval_required')
            if (type(count) is not int or count < 0 or type(permission) is not bool
                    or permission != (count == 0) or not isinstance(found, list)
                    or not isinstance(data.get('reasons',[]),list)
                    or (count == 0 and (found or data.get('reasons') or approval is True))
                    or (approval is True and 'APPROVAL_REQUIRED' not in found)):
                raise ValueError('Contradictory normalized evidence')
        if any(not isinstance(code, str) for code in found):
            raise ValueError('Invalid codes')
        codes = sorted({code if code in REASONS else 'OTHER' for code in found})
        state = ('NO_REPORTED_RESTRICTIONS' if count == 0 else
                 'NOT_ELIGIBLE' if 'NOT_ELIGIBLE' in codes else
                 'APPROVAL_REQUIRED' if 'APPROVAL_REQUIRED' in codes else 'OTHER_RESTRICTED')
        return operation, state, codes
    except (ValueError, TypeError, AttributeError):
        return operation, 'UNKNOWN', []


def import_report(path: Path) -> list[dict]:
    """Read M63 normalized rows or scoped standalone evidence; drop private data."""
    document, digest = read_json(path)
    if not isinstance(document, dict) or document.get('is_mock') is True:
        raise ValueError('Real structured evidence required')
    secrets = private_values(document)
    manifest = document.get('source_bound_manifest') or document.get('manifest') or {}
    specs = {}
    for spec in manifest.get('requests', []):
        asin = (spec.get('params') or {}).get('asin') or spec.get('asin')
        if isinstance(asin, str):
            specs.setdefault(asin, []).append(spec)
    rows = document.get('rows')
    if rows is None and document.get('asin'):
        rows = [document]
    if not isinstance(rows, list):
        raise ValueError('Restriction evidence rows required')
    events = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get('asin'), str) or not ASIN.fullmatch(row['asin']):
            raise ValueError('Explicit ASIN required')
        asin = row['asin']
        spec = specs.get(asin, [])
        details = spec[0] if len(spec) == 1 else {}
        params = details.get('params') or {}
        marketplace = row.get('marketplace_id') or manifest.get('marketplace_id') or ''
        condition = row.get('condition') or manifest.get('condition') or ''
        stage = row.get('restrictions')
        data = stage.get('data') if isinstance(stage, dict) else None
        permission=data.get('listing_permission') if isinstance(data,dict) else None
        date = observed(permission.get('observed_at')) if isinstance(permission,dict) else None
        date = date or observed(row.get('observed_at')) or observed(document.get('finished_at'))
        operation, state, codes = classify(stage, marketplace, condition, date)
        if (len(spec) > 1 or (params and (params.get('asin') != asin
                or params.get('marketplaceIds') != marketplace or params.get('conditionType') != condition))):
            state = 'UNKNOWN'
        # Preserve only public scope constants. Unexpected scope is UNKNOWN.
        events.append(dict(kind='eligibility', asin=asin, marketplace=US if marketplace == US else 'UNKNOWN',
            condition=CONDITION if condition == CONDITION else 'UNKNOWN', observed_at=date,
            operation_status=operation, eligibility=state, reason_codes=codes,
            brand=safe_text(details.get('brand') or row.get('brand'), secrets) or None,
            category=safe_text(details.get('category') or row.get('category'), secrets) or None,
            brand_approval_requirement='UNKNOWN', fba_eligibility=None, purchase_authorized=False,
            source_reference=f'sha256:{digest}:row:{index}', source_sha256=digest))
    return events


MANUAL_FIELDS = {'asin','brand','marketplace','condition','review_date','application_scope',
    'approval_pathway','invoice_required','minimum_invoiced_units','minimum_invoice_count',
    'supplier_documentation_requirements','immediate_approval_offered','additional_requirements',
    'source_reference','review_status'}


def manual_observation(row: dict) -> dict:
    """Manual intake is explicit and scoped to one observed ASIN, not a brand rule."""
    if not isinstance(row, dict) or set(row) != MANUAL_FIELDS:
        raise ValueError('Exact manual observation schema required')
    asin, brand = row['asin'], row['brand']
    if (not isinstance(asin, str) or not ASIN.fullmatch(asin) or not isinstance(brand, str)
            or not brand.strip() or len(brand)>100 or any(ord(c)<32 for c in brand)
            or row['marketplace'] != US or row['condition'] != CONDITION):
        raise ValueError('Explicit US/New ASIN/brand required')
    if row['review_date'] is not None and observed(row['review_date']) is None:
        raise ValueError('Aware review date required')
    if row['review_date'] and timestamp(row['review_date']) > datetime.now(timezone.utc):
        raise ValueError('Future review date')
    if (row['application_scope'] not in ('BRAND','ASIN','CATEGORY','UNKNOWN')
            or row['approval_pathway'] not in ('INVOICE','IMMEDIATE','OTHER','UNKNOWN')
            or row['review_status'] not in ('VERIFIED_USER_OBSERVATION','REVIEWED','NEEDS_REVIEW')):
        raise ValueError('Unsupported manual vocabulary')
    for key in ('invoice_required','immediate_approval_offered'):
        if row[key] is not None and type(row[key]) is not bool:
            raise ValueError('Explicit boolean or null required')
    for key in ('minimum_invoiced_units','minimum_invoice_count'):
        if row[key] is not None and (type(row[key]) is not int or row[key]<1):
            raise ValueError('Positive integer or null required')
    allowed = {'MANUFACTURER_OR_DISTRIBUTOR_PURCHASE_INVOICE','AUTHORIZED_SUPPLIER_INVOICE',
               'PRODUCT_PHOTOS','PACKAGING_PHOTOS','BRAND_AUTHORIZATION','OTHER_REVIEW_REQUIRED'}
    for key in ('supplier_documentation_requirements','additional_requirements'):
        if row[key] is not None and (not isinstance(row[key],list) or any(v not in allowed for v in row[key])):
            raise ValueError('Use documented requirement codes, not private free text')
    if not isinstance(row['source_reference'],str) or not re.fullmatch(r'(?:manual|user|sha256):[A-Za-z0-9:._-]{1,100}',row['source_reference']):
        raise ValueError('Nonsecret source alias required')
    if row['invoice_required'] is False and (row['minimum_invoiced_units'] or row['minimum_invoice_count']):
        raise ValueError('Contradictory invoice requirements')
    return dict(kind='manual_approval',**row)


class IntelligenceStore:
    """Owner-only SQLite, insert-only events and permanent request claims.

    SQL triggers prevent normal UPDATE/DELETE, not privileged filesystem tampering.
    Imported source hashes preserve provenance; originals remain read-only.
    """
    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise ValueError('Private regular store required')
        finally:
            os.close(fd)
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS intelligence_events (
                event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, asin TEXT NOT NULL,
                payload TEXT NOT NULL, recorded_at TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS no_event_update BEFORE UPDATE ON intelligence_events BEGIN SELECT RAISE(ABORT,'append only'); END;
            CREATE TRIGGER IF NOT EXISTS no_event_delete BEFORE DELETE ON intelligence_events BEGIN SELECT RAISE(ABORT,'append only'); END;
            CREATE TABLE IF NOT EXISTS batch_claims (digest TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS asin_claims (scope TEXT PRIMARY KEY, digest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS request_attempts (request_id TEXT PRIMARY KEY, digest TEXT NOT NULL, kind TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS batch_stops (digest TEXT PRIMARY KEY, reason TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS no_claim_delete BEFORE DELETE ON asin_claims BEGIN SELECT RAISE(ABORT,'permanent claim'); END;
            CREATE TRIGGER IF NOT EXISTS no_claim_update BEFORE UPDATE ON asin_claims BEGIN SELECT RAISE(ABORT,'permanent claim'); END;
        ''')
        for table in ('batch_claims','request_attempts','batch_stops'):
            for operation in ('UPDATE','DELETE'):
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'permanent accounting'); END")

    def close(self):
        self.db.close()

    def append(self, events: list[dict]) -> dict:
        added=0
        with self.db:
            for event in events:
                if event.get('kind')=='manual_approval':
                    event=manual_observation({k:v for k,v in event.items() if k!='kind'})
                else:
                    allowed={'kind','asin','marketplace','condition','observed_at','operation_status','eligibility',
                        'reason_codes','brand','category','brand_approval_requirement','fba_eligibility',
                        'purchase_authorized','source_reference','source_sha256'}
                    if (set(event)!=allowed or event.get('kind')!='eligibility' or event.get('eligibility') not in STATES
                            or not ASIN.fullmatch(event.get('asin',''))
                            or event.get('purchase_authorized') is not False or event.get('fba_eligibility') is not None
                            or not re.fullmatch(r'sha256:[a-f0-9]{64}:row:[0-9]+',event.get('source_reference',''))):
                        raise ValueError('Validated intelligence event required')
                added+=self.db.execute('INSERT OR IGNORE INTO intelligence_events VALUES (?,?,?,?,?)',
                    (fingerprint(event),event['kind'],event['asin'],canonical(event),datetime.now(timezone.utc).isoformat())).rowcount
        return dict(added=added,duplicates=len(events)-added)

    def events(self, kind: str | None=None) -> list[dict]:
        rows=self.db.execute('SELECT payload FROM intelligence_events WHERE (? IS NULL OR kind=?) ORDER BY event_id',(kind,kind))
        return [json.loads(row[0]) for row in rows]

    def excluded(self) -> set[str]:
        asins={e['asin'] for e in self.events('eligibility')}
        asins.update(row[0].split(':')[-1] for row in self.db.execute('SELECT scope FROM asin_claims'))
        return asins

    def revision(self) -> str:
        return fingerprint(dict(events=self.events(),claims=list(self.db.execute('SELECT scope,digest FROM asin_claims ORDER BY scope'))))


def coverage(store: IntelligenceStore) -> list[dict]:
    manual=store.events('manual_approval')
    output=[]
    for event in store.events('eligibility'):
        matches=[m for m in manual if (m['asin'],m['marketplace'],m['condition'])==(event['asin'],event['marketplace'],event['condition'])]
        reviewed=any(m['review_status'] in ('REVIEWED','VERIFIED_USER_OBSERVATION') for m in matches)
        output.append(dict(asin=event['asin'],eligibility=event['eligibility'],operation_status=event['operation_status'],
            manual_review_status='REVIEWED' if reviewed else 'NEEDS_REVIEW' if matches else 'NOT_REVIEWED',
            observation_count=len(matches),fba_eligibility=None,purchase_authorized=False))
    return output


def build_audit(private: Path, store: IntelligenceStore) -> dict:
    if private.is_symlink() or not private.is_dir():
        raise ValueError('Existing historical evidence directory required')
    legacy=historical_audit(private)
    return dict(legacy=legacy,store_revision=store.revision(),
                excluded_asins=sorted(set(legacy['excluded_asins'])|store.excluded()))
