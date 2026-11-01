"""Offline Seller Central/FBA evidence layered on M65's immutable intelligence."""
from datetime import datetime, timezone, timedelta
import json
import re

from app.m65_intelligence import (ASIN, US, CONDITION, STATES, IntelligenceStore,
    observed, manual_observation, safe_text)
from app.observations import canonical, fingerprint

SC_STATES=('OFFER_CREATION_AVAILABLE','APPROVAL_APPLICATION_REQUIRED','LISTING_CREATION_ACCESSIBLE',
           'BRAND_VALIDATION_BLOCKED','NEW_LISTINGS_NOT_ACCEPTED','UNVERIFIED')
FBA_STATES=('FBA_ELIGIBLE','FBA_INELIGIBLE','FBA_UNKNOWN')
METHODS=('MANUAL_EXISTING_ASIN_OFFER','MANUAL_COPY_LISTING','MANUAL_APPROVAL_SCREEN',
         'MANUAL_FBA_ELIGIBILITY','USER_REPORTED_OBSERVATION')
ACCOUNT='existing-authorized-us-account'


def normalize(row: dict) -> dict:
    fields={'asin','brand','marketplace','condition','account_reference','observed_at','verification_method',
            'seller_central_states','fba_state','invoice_required','minimum_invoiced_units',
            'restriction_scope','source_reference'}
    if not isinstance(row,dict) or not fields<=set(row) or set(row)-fields-{'restriction_codes','fba_program'}:
        raise ValueError('Exact nonsecret verification schema required')
    if (row['asin'] is not None and (not isinstance(row['asin'],str) or not ASIN.fullmatch(row['asin']))
            or row['marketplace']!=US or row['condition']!=CONDITION or row['account_reference']!=ACCOUNT
            or not isinstance(row['brand'],str) or not row['brand'].strip() or len(row['brand'])>100
            or row['verification_method'] not in METHODS):
        raise ValueError('Explicit existing-account US/New scope required')
    states=row['seller_central_states']
    if not isinstance(states,list) or not states or len(states)!=len(set(states)) or any(s not in SC_STATES for s in states):
        raise ValueError('Explicit Seller Central observations required')
    if row['fba_state'] not in FBA_STATES or row['restriction_scope'] not in ('ASIN','BRAND','PRODUCT','CATEGORY','UNKNOWN'):
        raise ValueError('Explicit FBA/scope vocabulary required')
    if row['observed_at'] is not None and (not observed(row['observed_at']) or datetime.fromisoformat(observed(row['observed_at']))>datetime.now(timezone.utc)):
        raise ValueError('Aware, non-future observation date required')
    if row['verification_method']=='MANUAL_COPY_LISTING' and ('OFFER_CREATION_AVAILABLE' in states or row['fba_state']!='FBA_UNKNOWN'):
        raise ValueError('Copy listing cannot verify offer creation or FBA')
    if row['fba_state']!='FBA_UNKNOWN' and row['verification_method']!='MANUAL_FBA_ELIGIBILITY':
        raise ValueError('Independent FBA verification required')
    if row.get('fba_program') not in (None,'INBOUND','COMMINGLING'):
        raise ValueError('Explicit FBA program required')
    if row['fba_state']!='FBA_UNKNOWN' and row.get('fba_program')!='INBOUND':
        raise ValueError('Commingling or unspecified preview does not verify FBA inbound eligibility')
    if 'OFFER_CREATION_AVAILABLE' in states and row['verification_method']!='MANUAL_EXISTING_ASIN_OFFER':
        raise ValueError('Existing-ASIN offer verification required')
    if row['asin'] is None and (row['fba_state']!='FBA_UNKNOWN' or any(s not in ('APPROVAL_APPLICATION_REQUIRED','UNVERIFIED') for s in states)):
        raise ValueError('Brand-only signals cannot establish ASIN permission')
    if row['invoice_required'] is not None and type(row['invoice_required']) is not bool:
        raise ValueError('Explicit invoice boolean or null required')
    units=row['minimum_invoiced_units']
    if units is not None and (type(units) is not int or units<1 or row['invoice_required'] is not True):
        raise ValueError('Explicit supported invoice minimum required')
    if not isinstance(row['source_reference'],str) or not re.fullmatch(r'(?:manual|user|sha256):[A-Za-z0-9:._-]{1,100}',row['source_reference']):
        raise ValueError('Nonsecret evidence alias required; no URLs or private messages')
    codes=row.get('restriction_codes',[])
    allowed={'PRODUCT_RESTRICTED','CATEGORY_RESTRICTED','HAZMAT_REVIEW_REQUIRED','BRAND_CLARIFICATION_REQUIRED','OTHER_REVIEW_REQUIRED'}
    if not isinstance(codes,list) or any(c not in allowed for c in codes):raise ValueError('Typed restriction codes required')
    if row['asin'] is None and codes:raise ValueError('No ASIN-level restriction from a brand-only signal')
    return dict(row,seller_central_states=sorted(states),brand=safe_text(row['brand']),restriction_codes=sorted(set(codes)))


class VerificationStore(IntelligenceStore):
    """New derived store only; never opens an original authorization for writing."""
    def __init__(self,path):
        super().__init__(path)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS m66_verifications (event_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS m66_results (digest TEXT NOT NULL,asin TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(digest,asin));
        ''')
        for table in ('m66_verifications','m66_results'):
            for operation in ('UPDATE','DELETE'):
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable evidence'); END")

    def append_verifications(self,rows: list[dict]) -> dict:
        validated=[normalize(row) for row in rows]
        known={fingerprint(row) for row in verification_rows(self)}
        added=0
        with self.db:
            for row in validated:
                if fingerprint(row) in known:continue
                added+=self.db.execute('INSERT OR IGNORE INTO m66_verifications VALUES (?,?)',(fingerprint(row),canonical(row))).rowcount
                known.add(fingerprint(row))
        return dict(added=added,duplicates=len(rows)-added)

    def verifications(self) -> list[dict]:
        return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM m66_verifications ORDER BY event_id')]

    def revision(self) -> str:
        return fingerprint(dict(m65=super().revision(),verifications=self.verifications(),
            results=list(self.db.execute('SELECT digest,asin,payload FROM m66_results ORDER BY digest,asin'))))


def fresh(date: str | None, as_of: datetime, hours: int=24) -> bool:
    stamp=observed(date)
    return bool(stamp and 0<=(as_of-datetime.fromisoformat(stamp)).total_seconds()<=hours*3600)


def verification_rows(store: VerificationStore) -> list[dict]:
    """Project existing exact-ASIN M64 facts without duplicating their storage."""
    rows=store.verifications()
    for e in store.events('manual_approval'):
        if e['review_status'] not in ('REVIEWED','VERIFIED_USER_OBSERVATION'):continue
        rows.append(dict(asin=e['asin'],brand=e['brand'],marketplace=e['marketplace'],condition=e['condition'],
            account_reference=ACCOUNT,observed_at=e['review_date'],verification_method='USER_REPORTED_OBSERVATION',
            seller_central_states=['APPROVAL_APPLICATION_REQUIRED'] if e['approval_pathway']=='INVOICE' else ['UNVERIFIED'],
            fba_state='FBA_UNKNOWN',invoice_required=e['invoice_required'],minimum_invoiced_units=e['minimum_invoiced_units'],
            restriction_scope=e['application_scope'] if e['application_scope'] in ('ASIN','BRAND','CATEGORY') else 'UNKNOWN',
            source_reference=e['source_reference']))
    unique={fingerprint(normalize(row)):normalize(row) for row in rows}
    return sorted(unique.values(),key=canonical)


def verify(asin: str, api: list[dict], sc: list[dict], *, as_of: datetime) -> dict:
    """No evidence silently overrides a contradiction; positives must be fresh."""
    if not ASIN.fullmatch(asin) or as_of.utcoffset() is None:
        raise ValueError('Explicit ASIN and aware evaluation clock required')
    api_rows=[e for e in api if e.get('asin')==asin]
    sc_rows=[e for e in sc if e.get('asin')==asin]
    evidence_refs=[]
    evidence=[]
    invalid=False
    api_states=set()
    api_fresh=set();api_dates=[];offer_dates=[];fba_dates=[]
    for e in api_rows:
        valid=(e.get('marketplace')==US and e.get('condition')==CONDITION
               and e.get('eligibility') in STATES and e.get('operation_status')=='SUCCEEDED'
               and observed(e.get('observed_at')) and e.get('source_reference'))
        if not valid:
            invalid=True;continue
        api_states.add(e['eligibility'])
        if fresh(e['observed_at'],as_of):
            api_fresh.add(e['eligibility'])
            if e['eligibility']=='NO_REPORTED_RESTRICTIONS':api_dates.append(datetime.fromisoformat(observed(e['observed_at'])))
        evidence_refs.append(e['source_reference'])
        evidence.append(dict(source_reference=e['source_reference'],observed_at=e['observed_at'],
                             verification_method='SAVED_SP_API_LISTINGS_RESTRICTIONS',marketplace=US,condition=CONDITION,asin=asin))
    negatives=api_states-{'UNKNOWN','NO_REPORTED_RESTRICTIONS'}
    conflict=('NO_REPORTED_RESTRICTIONS' in api_states and bool(negatives)) or len(negatives)>1
    api_state=('UNKNOWN' if conflict else 'NOT_ELIGIBLE' if 'NOT_ELIGIBLE' in negatives else
               'APPROVAL_REQUIRED' if 'APPROVAL_REQUIRED' in negatives else 'OTHER_RESTRICTED' if negatives else
               'NO_REPORTED_RESTRICTIONS' if 'NO_REPORTED_RESTRICTIONS' in api_fresh and 'UNKNOWN' not in api_states else 'UNKNOWN')
    sc_states=set();sc_fresh=set();fba_states=set();fba_fresh=set();restriction_codes=set()
    for raw in sc_rows:
        try:e=normalize(raw)
        except (ValueError,TypeError):invalid=True;continue
        sc_states.update(e['seller_central_states'])
        restriction_codes.update(e['restriction_codes'])
        fba_states.add(e['fba_state'])
        if fresh(e['observed_at'],as_of):
            sc_fresh.update(e['seller_central_states']);fba_fresh.add(e['fba_state'])
            if 'OFFER_CREATION_AVAILABLE' in e['seller_central_states']:offer_dates.append(datetime.fromisoformat(observed(e['observed_at'])))
            if e['fba_state']=='FBA_ELIGIBLE':fba_dates.append(datetime.fromisoformat(observed(e['observed_at'])))
        evidence_refs.append(e['source_reference'])
        evidence.append(dict(source_reference=e['source_reference'],observed_at=e['observed_at'],
                             verification_method=e['verification_method'],marketplace=US,condition=CONDITION,asin=asin))
    blockers={'APPROVAL_APPLICATION_REQUIRED','BRAND_VALIDATION_BLOCKED','NEW_LISTINGS_NOT_ACCEPTED'}
    conflict=bool(conflict or ('OFFER_CREATION_AVAILABLE' in sc_states and bool(sc_states&blockers))
                  or ('NO_REPORTED_RESTRICTIONS' in api_states and bool(sc_states&blockers))
                  or (restriction_codes and ('NO_REPORTED_RESTRICTIONS' in api_states or 'OFFER_CREATION_AVAILABLE' in sc_states))
                  or (negatives and 'OFFER_CREATION_AVAILABLE' in sc_states))
    fba_conflict={'FBA_ELIGIBLE','FBA_INELIGIBLE'}<=fba_states
    fba=('FBA_UNKNOWN' if fba_conflict else 'FBA_INELIGIBLE' if 'FBA_INELIGIBLE' in fba_states else
         'FBA_ELIGIBLE' if 'FBA_ELIGIBLE' in fba_fresh else 'FBA_UNKNOWN')
    listing_verified=(api_state=='NO_REPORTED_RESTRICTIONS' and 'OFFER_CREATION_AVAILABLE' in sc_fresh
                      and not conflict and not invalid and not sc_states&blockers and not restriction_codes)
    return dict(asin=asin,marketplace=US,condition=CONDITION,account_reference=ACCOUNT,
        api_state=api_state,seller_central_states=sorted(sc_states) or ['UNVERIFIED'],fba_state=fba,
        listing_review_gate_complete=listing_verified,conflict_requires_review=conflict or invalid,
        selling_authorization_confirmed=False,offer_submission_status='NOT_SUBMITTED',
        catalog_match_grants_permission=False,fba_eligibility_program='INBOUND',
        listing_valid_until=(min(max(api_dates),max(offer_dates))+timedelta(hours=24)).isoformat() if listing_verified else None,
        fba_valid_until=(max(fba_dates)+timedelta(hours=24)).isoformat() if fba=='FBA_ELIGIBLE' else None,
        fba_conflict_requires_review=fba_conflict,evaluated_at=as_of.isoformat(),
        manual_restriction_codes=sorted(restriction_codes),
        evidence_references=sorted(set(evidence_refs)),purchase_authorized=False,
        evidence=sorted(evidence,key=canonical),
        interpretation='Historical restrictions retained conservatively; positive verification expires after 24 hours')
