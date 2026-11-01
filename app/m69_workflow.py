"""Explicit, auditable offline stages. This database contains NO request claims."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import sqlite3

from app.m65_intelligence import US, CONDITION, ASIN, observed
from app.m66_verification import verify, fresh, ACCOUNT
from app.m66_opportunity import exact_match, economics, PRODUCT_FIELDS
from app.m67_state import readonly, secure
from app.normalization import gtin
from app.observations import canonical, fingerprint

STAGES=('DISCOVERED','IDENTITY_VERIFIED','OFFLINE_RISK_REVIEWED','LIVE_ELIGIBILITY_PENDING',
        'ELIGIBILITY_OBSERVED','FBA_REVIEW_PENDING','PROFITABILITY_REVIEWED','READY_FOR_HUMAN_DECISION')
APPLICATION_ID=0x4D36394F


def thresholds(roi='50',profit='5',budget='500') -> dict:
    try:values=[Decimal(str(v)) for v in (roi,profit,budget)]
    except (InvalidOperation,TypeError):raise ValueError('Explicit finite financial thresholds required') from None
    if any(not v.is_finite() or v<0 for v in values) or values[2]<=0:
        raise ValueError('Nonnegative thresholds and positive inventory budget required')
    return dict(minimum_roi=str(values[0]),minimum_profit=str(values[1]),inventory_budget=str(values[2]))


def unchecked_reviewable(asin: str,history: dict,now: datetime) -> bool:
    if asin in history['excluded_asins'] or not history['history_complete']:return False
    v=verify(asin,history['events'],history['manual_verifications'],as_of=now)
    return (not v['conflict_requires_review'] and not v['manual_restriction_codes']
            and not set(v['seller_central_states'])&{'APPROVAL_APPLICATION_REQUIRED','BRAND_VALIDATION_BLOCKED','NEW_LISTINGS_NOT_ACCEPTED'})


def catalog_identity(product: dict, row: dict, now: datetime) -> bool:
    if (not isinstance(product,dict) or set(product)!=set(PRODUCT_FIELDS)
            or not row['catalog_identity_complete'] or row['identity_conflict']
            or not fresh(product.get('observed_at'),now)
            or product.get('url')!='https://www.amazon.com/dp/'+row['asin']
            or any(product.get(k) in (None,'') for k in PRODUCT_FIELDS)
            or any(k!='pack_quantity' and not isinstance(product.get(k),str) for k in PRODUCT_FIELDS)
            or not isinstance(product.get('source_reference'),str)
            or not re.fullmatch(r'(manual|sha256):[A-Za-z0-9:._-]{1,100}',product['source_reference'])
            or type(product.get('pack_quantity')) is not int or product['pack_quantity']<=0):return False
    try:
        normalized=gtin(product['gtin'])
        bound=fingerprint(dict(ids=[normalized],model=product['model'],pack=product['pack_quantity'],
                               size=product['size'],variation=product['variation']))
    except (ValueError,TypeError,AttributeError):return False
    return bool(normalized) and bound==row['identity_fingerprint'] and product['brand'].casefold()==row['brand'].casefold()


def financial_review(opportunity: dict, row: dict, history: dict, now: datetime, limits: dict) -> dict:
    v=verify(row['asin'],history['events'],history['manual_verifications'],as_of=now)
    if (v['api_state']!='NO_REPORTED_RESTRICTIONS' or not v['listing_review_gate_complete']
            or v['conflict_requires_review'] or v['fba_state']!='FBA_ELIGIBLE' or v['fba_conflict_requires_review']):
        raise ValueError('Fresh API, offer-creation and independent FBA inbound evidence required before economics')
    if (not isinstance(opportunity,dict) or opportunity.get('asin')!=row['asin']
            or opportunity.get('marketplace')!=US or opportunity.get('condition')!=CONDITION
            or opportunity.get('is_mock') is True or opportunity.get('is_synthetic') is True
            or opportunity.get('purchase_authorized') is not False
            or opportunity.get('offer_submission_authorized') is not False
            or opportunity.get('create_new_asin_authorized') is not False
            or opportunity.get('intended_listing_workflow')!='EXISTING_ASIN_OFFER_ONLY'):
        raise ValueError('Scoped existing-ASIN review-only opportunity required')
    if not catalog_identity(opportunity.get('amazon_product'),row,now):
        raise ValueError('Financial product identity must match frozen catalog fingerprint')
    match=exact_match(opportunity,as_of=now)
    if not match['exact']:raise ValueError('Exact UPC/model/size/variation/pack retailer match required')
    result=economics(opportunity,as_of=now)
    if not result['complete']:raise ValueError('Complete fresh evidenced prices and fees required')
    result['passes']=(Decimal(result['roi_percent'])>=Decimal(limits['minimum_roi'])
        and Decimal(result['net_profit'])>=Decimal(limits['minimum_profit'])
        and Decimal(result['estimated_inventory_investment'])<=Decimal(limits['inventory_budget']))
    result['thresholds']=limits
    return result


def guard(target: str, row: dict, history: dict, evidence: dict, now: datetime, limits: dict) -> dict:
    common={'schema','asin','marketplace','condition','observed_at','review_reference','payload'}
    if (not isinstance(evidence,dict) or set(evidence)!=common or type(evidence['schema']) is not int or evidence['schema']!=1
            or evidence['asin']!=row['asin'] or evidence['marketplace']!=US or evidence['condition']!=CONDITION
            or not fresh(evidence['observed_at'],now)
            or not re.fullmatch(r'manual:[A-Za-z0-9._-]{1,80}',evidence.get('review_reference',''))
            or not isinstance(evidence['payload'],dict)):
        raise ValueError('Exact fresh nonsecret review envelope required')
    payload=evidence['payload']
    if target=='IDENTITY_VERIFIED':
        if set(payload)!={'amazon_product'} or not catalog_identity(payload['amazon_product'],row,now):
            raise ValueError('Complete exact catalog identity and fresh manual review required')
    elif target=='OFFLINE_RISK_REVIEWED':
        if (set(payload)!={'score_components_sha256','unknowns_acknowledged','condition_reviewed_new'}
                or payload['score_components_sha256']!=fingerprint(row['score_components'])
                or payload['unknowns_acknowledged'] is not True or payload['condition_reviewed_new'] is not True
                or row['condition_compatibility']=='INCOMPATIBLE'):
            raise ValueError('Explicit risk, unknowns and New-condition review required')
    elif target=='LIVE_ELIGIBILITY_PENDING':
        if (set(payload)!={'separate_live_authorization_required'} or payload['separate_live_authorization_required'] is not True
                or not unchecked_reviewable(row['asin'],history,now)):
            raise ValueError('Unclaimed ASIN and complete permanent history required; pending is not authorization')
    elif target=='ELIGIBILITY_OBSERVED':
        facts=[r for r in history['rows'] if r['asin']==row['asin']]
        if (set(payload)!={'history_sha256'} or payload['history_sha256']!=history['evidence_sha256']
                or len(facts)!=1 or facts[0]['operation_status']!='SUCCEEDED'
                or facts[0]['api_state']=='UNKNOWN' or facts[0]['conflicting_evidence']):
            raise ValueError('Scoped immutable nonambiguous account-specific API outcome required')
        return dict(api_state=facts[0]['api_state'],proceed_unrestricted_path=False)
    elif target=='FBA_REVIEW_PENDING':
        v=verify(row['asin'],history['events'],history['manual_verifications'],as_of=now)
        if (set(payload)!={'independent_fba_review_required'} or payload['independent_fba_review_required'] is not True or v['api_state']!='NO_REPORTED_RESTRICTIONS'
                or not v['listing_review_gate_complete'] or v['conflict_requires_review']):
            raise ValueError('No reported restrictions alone is insufficient; fresh offer-creation verification required')
    elif target in ('PROFITABILITY_REVIEWED','READY_FOR_HUMAN_DECISION'):
        expected={'opportunity'} if target=='PROFITABILITY_REVIEWED' else {'opportunity','human_review_requested'}
        if set(payload)!=expected or (target=='READY_FOR_HUMAN_DECISION' and payload['human_review_requested'] is not True):
            raise ValueError('Explicit complete financial review required')
        result=financial_review(payload['opportunity'],row,history,now,limits)
        if target=='READY_FOR_HUMAN_DECISION' and not result['passes']:raise ValueError('Financial thresholds or budget failed')
        return result
    else:raise ValueError('Supported explicit next stage required')
    return dict(guard='PASSED_OFFLINE_REVIEW',purchase_authorized=False,execution_authorized=False)


class WorkflowStore:
    """Separate append-only review journal; refuses all existing non-M69 DBs."""
    def __init__(self,path: Path,*,create: bool=False,read_only: bool=False):
        if read_only and create:raise ValueError('Read-only journals cannot be created')
        if path.exists() or path.is_symlink():
            db=readonly(path)
            try:
                if db.execute('PRAGMA application_id').fetchone()[0]!=APPLICATION_ID:
                    raise ValueError('Dedicated M69 database required; original records may never be migrated')
                tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables!={'m69_reports','m69_events'}:raise ValueError('Unexpected workflow schema')
                for table in tables:
                    for operation in ('UPDATE','DELETE'):
                        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?",
                            ('immutable_'+table+'_'+operation,)).fetchone():raise ValueError('Immutable workflow protections missing')
            finally:db.close()
        elif not create:raise ValueError('Existing workflow journal required')
        else:
            if path.absolute().is_relative_to((Path.home()/'.intelligenceos-arbitrage-amazon').absolute()):
                raise ValueError('Workflow journal cannot be placed among protected execution records')
            path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
            os.fchmod(fd,0o600);os.close(fd)
        secure(path)
        if read_only:
            self.db=readonly(path)
            return
        self.db=sqlite3.connect(path);self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA journal_mode=DELETE')
        if create:
            self.db.execute(f'PRAGMA application_id={APPLICATION_ID}')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS m69_reports(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS m69_events(id TEXT PRIMARY KEY,asin TEXT NOT NULL,previous_id TEXT,payload TEXT NOT NULL);
            ''')
            for table in ('m69_reports','m69_events'):
                for operation in ('UPDATE','DELETE'):
                    self.db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'append only offline review'); END")
            self.db.commit()

    def current(self,asin: str) -> dict | None:
        previous=None;result=None;report_id=None
        for index,(key,parent,payload) in enumerate(self.db.execute('SELECT id,previous_id,payload FROM m69_events WHERE asin=? ORDER BY rowid',(asin,))):
            event=json.loads(payload)
            if (fingerprint(dict(asin=asin,**event))!=key or parent!=previous or event['previous_id']!=previous
                    or index>=len(STAGES) or event['stage']!=STAGES[index]
                    or event['purchase_authorized'] is not False or event['execution_authorized'] is not False
                    or (report_id is not None and event['report_id']!=report_id)):
                raise ValueError('Workflow hash chain or stage integrity failure')
            previous=key;report_id=event['report_id'];result=dict(id=key,**event)
        if result:
            saved=self.db.execute('SELECT payload FROM m69_reports WHERE id=?',(report_id,)).fetchone()
            if not saved or fingerprint(json.loads(saved[0]))!=report_id:raise ValueError('Frozen report integrity failure')
        return result

    def register(self,report: dict,asin: str,history: dict,now: datetime) -> dict:
        if not ASIN.fullmatch(asin) or not unchecked_reviewable(asin,history,now):
            raise ValueError('Previously unchecked, fully audited ASIN required')
        matches=[r for r in report['ranking']['rows'] if r['asin']==asin and r['selected']]
        if (len(matches)!=1 or report['history_sha256']!=history['evidence_sha256']
                or matches[0]['identity_fingerprint']!=history['catalog_identity_sha256'].get(asin)):
            raise ValueError('Current selected candidate and bound report required')
        report_id=fingerprint(report)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.current(asin):raise ValueError('Existing workflow cannot reset or replay discovery')
            self.db.execute('INSERT OR IGNORE INTO m69_reports VALUES (?,?)',(report_id,canonical(report)))
            event=dict(stage='DISCOVERED',report_id=report_id,observed_at=now.isoformat(),previous_id=None,
                       evidence_sha256=report_id,history_sha256=history['evidence_sha256'],
                       purchase_authorized=False,execution_authorized=False)
            key=fingerprint(dict(asin=asin,**event))
            self.db.execute('INSERT INTO m69_events VALUES (?,?,?,?)',(key,asin,None,canonical(event)))
        return dict(asin=asin,stage='DISCOVERED',event_sha256=key)

    def advance(self,asin: str,target: str,history: dict,evidence: dict,now: datetime,limits: dict) -> dict:
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            current=self.current(asin)
            if not current or target not in STAGES or STAGES.index(target)!=STAGES.index(current['stage'])+1:
                raise ValueError('Only explicit next-stage transitions allowed')
            if now<datetime.fromisoformat(current['observed_at']):raise ValueError('Workflow clock cannot go backwards')
            saved=self.db.execute('SELECT payload FROM m69_reports WHERE id=?',(current['report_id'],)).fetchone()
            report=json.loads(saved[0]);row=next(r for r in report['ranking']['rows'] if r['asin']==asin)
            from app.m69_discovery import implementation
            if (report['implementation_sha256']!=implementation()
                    or sorted(r['source_sha256'] for r in report['source_profiles'])!=history['catalog_source_sha256']):
                raise ValueError('Frozen source or code changed')
            if target=='LIVE_ELIGIBILITY_PENDING':
                prior=[json.loads(r[0]) for r in self.db.execute('SELECT payload FROM m69_events WHERE asin=?',(asin,))]
                if any(not fresh(e['observed_at'],now) for e in prior if e['stage'] in ('IDENTITY_VERIFIED','OFFLINE_RISK_REVIEWED')):
                    raise ValueError('Fresh explicit identity and risk reviews required')
            result=guard(target,row,history,evidence,now,limits)
            event=dict(stage=target,report_id=current['report_id'],observed_at=now.isoformat(),previous_id=current['id'],
                evidence_sha256=fingerprint(evidence),history_sha256=history['evidence_sha256'],guard_result=result,
                purchase_authorized=False,execution_authorized=False)
            key=fingerprint(dict(asin=asin,**event))
            self.db.execute('INSERT INTO m69_events VALUES (?,?,?,?)',(key,asin,current['id'],canonical(event)))
        return dict(asin=asin,stage=target,event_sha256=key,purchase_authorized=False)

    def proposed_manifest(self,asins: list[str],history: dict,now: datetime) -> dict:
        if not history['history_complete'] or not 1<=len(asins)<=20 or len(set(asins))!=len(asins):
            raise ValueError('One to twenty distinct audited candidates required')
        if set(asins)&set(history['excluded_asins']):raise ValueError('Permanent claims cannot enter a new review manifest')
        events=[]
        for asin in asins:
            if not unchecked_reviewable(asin,history,now):raise ValueError('Current exact-ASIN manual evidence blocks new live review')
            event=self.current(asin)
            if not event or event['stage']!='LIVE_ELIGIBILITY_PENDING' or not fresh(event['observed_at'],now):raise ValueError('Fresh explicit identity and offline risk reviews required')
            from app.m69_discovery import implementation
            saved=json.loads(self.db.execute('SELECT payload FROM m69_reports WHERE id=?',(event['report_id'],)).fetchone()[0])
            if (saved['implementation_sha256']!=implementation()
                    or sorted(r['source_sha256'] for r in saved['source_profiles'])!=history['catalog_source_sha256']):
                raise ValueError('Frozen proposal source/code drift')
            events.append(event['id'])
        return dict(schema=1,mode='M69_LIVE_REVIEW_PROPOSAL_ONLY',account_reference=ACCOUNT,asins=asins,marketplace_id=US,condition=CONDITION,
            history_sha256=history['evidence_sha256'],workflow_event_sha256=events,evaluated_at=now.isoformat(),
            budget=dict(authentication=1,restrictions=len(asins),maximum_requests=len(asins)+1,retries=0,catalog=0,pricing=0,fees=0,retailer=0),
            execution_authorized=False,live_executor_enabled=False,separate_frozen_review_and_owner_authorization_required=True,
            purchase_authorized=False,listing_submission_authorized=False,
            interpretation='Proposal only; not an M67 executable manifest or authorization')
