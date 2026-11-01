"""Offline proposal and future execution accounting. There is NO live adapter.

Authorization validation and permanent claim helpers are tested in temporary
stores only. CLI preparation never claims work or executes a request.
"""
from datetime import datetime, timezone
from pathlib import Path
import re

from app.m65_intelligence import ASIN, US, CONDITION, IntelligenceStore, observed, sha256
from app.observations import canonical, fingerprint

PATH='/listings/2021-08-01/restrictions'


def implementation() -> dict:
    root=Path(__file__).resolve().parent
    return {name:sha256(root/name) for name in ('m65.py','m65_batch.py','m65_intelligence.py',
                                                'm65_ranking.py','m65_readiness.py','m63_history.py')}


def proposal(ranking: dict, audit: dict, source_sha256: str) -> dict:
    asins=ranking['selected_asins']
    if len(asins)>ranking['requested_maximum'] or len(asins)!=len(set(asins)):
        raise ValueError('Explicit unique bounded cohort required')
    if set(asins)&set(audit['excluded_asins']):
        raise ValueError('Previously checked ASIN cannot enter future cohort')
    return dict(schema=1,mode='M65_RESTRICTIONS_PROPOSAL_ONLY',marketplace_id=US,condition=CONDITION,
        implementation_sha256=implementation(),
        account_reference='existing-authorized-us-account',asins=asins,
        source_sha256=source_sha256,audit_sha256=fingerprint(audit),store_revision=audit['store_revision'],
        ranking_sha256=fingerprint(ranking),maximum_checks=ranking['requested_maximum'],
        ranking_policy=dict(max_per_brand=ranking['max_per_brand'],minimum_score=ranking['minimum_score']),
        requests=[dict(method='GET',path=PATH,params=dict(asin=a,marketplaceIds=US,
                       conditionType=CONDITION,reasonLocale='en_US',sellerId='[private runtime value]')) for a in asins],
        budget=dict(restrictions=len(asins),authentication=1 if asins else 0,
                    maximum_requests=len(asins)+(1 if asins else 0),retries=0,
                    catalog=0,pricing=0,fees=0,retailer=0),
        stop_on_unknown=True,no_retry=True,execution_authorized=False,live_executor_enabled=False,
        separate_human_authorization_required=True,purchase_authorized=False)


def validate_manifest(manifest: dict) -> None:
    if manifest.get('implementation_sha256')!=implementation():
        raise ValueError('Reviewed implementation changed')
    if (manifest.get('mode')!='M65_RESTRICTIONS_PROPOSAL_ONLY' or manifest.get('schema')!=1
            or manifest.get('marketplace_id')!=US or manifest.get('condition')!=CONDITION
            or manifest.get('account_reference')!='existing-authorized-us-account'
            or manifest.get('execution_authorized') is not False
            or manifest.get('live_executor_enabled') is not False
            or manifest.get('separate_human_authorization_required') is not True
            or manifest.get('stop_on_unknown') is not True or manifest.get('no_retry') is not True
            or manifest.get('purchase_authorized') is not False):
        raise ValueError('M65 offline scope required')
    maximum=manifest.get('maximum_checks')
    asins=manifest.get('asins')
    if (type(maximum) is not int or not 1<=maximum<=100 or not isinstance(asins,list)
            or not 0<=len(asins)<=maximum or any(not isinstance(a,str) or not ASIN.fullmatch(a) for a in asins)
            or len(asins)!=len(set(asins))):
        raise ValueError('Bounded unique ASINs required')
    policy=manifest.get('ranking_policy',{})
    if (set(policy)!={'max_per_brand','minimum_score'} or type(policy['max_per_brand']) is not int
            or not 1<=policy['max_per_brand']<=maximum or type(policy['minimum_score']) is not int
            or not -100<=policy['minimum_score']<=100):
        raise ValueError('Bounded explicit ranking policy required')
    expected=[dict(method='GET',path=PATH,params=dict(asin=a,marketplaceIds=US,
                  conditionType=CONDITION,reasonLocale='en_US',sellerId='[private runtime value]')) for a in asins]
    budget=dict(restrictions=len(asins),authentication=1 if asins else 0,maximum_requests=len(asins)+(1 if asins else 0),
                retries=0,catalog=0,pricing=0,fees=0,retailer=0)
    if manifest.get('requests')!=expected or manifest.get('budget')!=budget:
        raise ValueError('Request scope or budget drift')
    for key in ('source_sha256','audit_sha256','store_revision','ranking_sha256'):
        if not re.fullmatch(r'[a-f0-9]{64}',manifest.get(key,'')):
            raise ValueError('Bound source/revision hashes required')


def validate_authorization(manifest: dict, manifest_sha256: str, authorization: dict | None,
                           *, actual_file_sha256: str, execute: bool, audit: dict,
                           now: datetime | None=None) -> None:
    """Validate a separate human review record, never create one automatically."""
    validate_manifest(manifest)
    if (not execute or not authorization or not re.fullmatch(r'[a-f0-9]{64}',manifest_sha256)
            or actual_file_sha256!=manifest_sha256):
        raise ValueError('Explicit execution flag, reviewed file digest and separate authorization required')
    if (fingerprint(audit)!=manifest['audit_sha256'] or audit['store_revision']!=manifest['store_revision']
            or set(manifest['asins'])&set(audit['excluded_asins'])):
        raise ValueError('Historical intelligence changed or checked ASIN selected')
    a=authorization
    if (a.get('approved') is not True or a.get('manifest_sha256')!=manifest_sha256
            or a.get('asins')!=manifest['asins'] or a.get('marketplace_id')!=US
            or a.get('condition')!=CONDITION or a.get('budget')!=manifest['budget']
            or not re.fullmatch(r'manual:[A-Za-z0-9._-]{1,80}',a.get('review_reference',''))):
        raise ValueError('Exact human-reviewed scope and budget required')
    review=observed(a.get('reviewed_at'))
    expires=observed(a.get('expires_at'))
    clock=now or datetime.now(timezone.utc)
    if (not manifest['asins'] or not review or not expires
            or not datetime.fromisoformat(review)<=clock<datetime.fromisoformat(expires)):
        raise ValueError('Nonempty cohort and current authorization required')


def reserve_future(store: IntelligenceStore, manifest: dict, digest: str, authorization: dict | None,
                   *, actual_file_sha256: str, execute: bool, audit: dict) -> None:
    """Permanent accounting only; never accesses credentials or sends requests."""
    validate_authorization(manifest,digest,authorization,actual_file_sha256=actual_file_sha256,execute=execute,audit=audit)
    if store.revision()!=manifest['store_revision']:
        raise ValueError('Store drift')
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        if store.revision()!=manifest['store_revision']:
            raise ValueError('Store changed while reserving')
        store.db.execute('INSERT INTO batch_claims VALUES (?,?)',(digest,canonical(manifest)))
        for asin in manifest['asins']:
            store.db.execute('INSERT INTO asin_claims VALUES (?,?)',(US+':'+CONDITION+':'+asin,digest))


def consume_attempt(store: IntelligenceStore, digest: str, kind: str, asin: str | None=None) -> None:
    """Durably consume exactly once before a future transport may be invoked.

    Failed/unknown operations remain consumed. There is no reset/resume/retry API.
    The production network adapter is intentionally absent from M65.
    """
    import json
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        saved=store.db.execute('SELECT payload FROM batch_claims WHERE digest=?',(digest,)).fetchone()
        if not saved or store.db.execute('SELECT 1 FROM batch_stops WHERE digest=?',(digest,)).fetchone():
            raise ValueError('Unclaimed or stopped batch')
        manifest=json.loads(saved[0])
        if kind=='authentication' and asin is None:
            request_id=digest+':authentication'
        elif kind=='restrictions' and asin in manifest['asins']:
            if not store.db.execute('SELECT 1 FROM request_attempts WHERE request_id=?',(digest+':authentication',)).fetchone():
                raise ValueError('Authentication reservation required first')
            request_id=digest+':'+asin
        else:
            raise ValueError('Operation outside manifest')
        counts=dict(store.db.execute('SELECT kind,count(*) FROM request_attempts WHERE digest=? GROUP BY kind',(digest,)))
        if sum(counts.values())>=manifest['budget']['maximum_requests'] or counts.get(kind,0)>=manifest['budget'][kind]:
            raise ValueError('Request budget exhausted')
        store.db.execute('INSERT INTO request_attempts VALUES (?,?,?)',(request_id,digest,kind))


def stop_ambiguous(store: IntelligenceStore,digest: str,outcome: str) -> None:
    if outcome not in ('UNKNOWN','FAILED','UNCERTAIN','BUDGET_EXHAUSTED'):
        raise ValueError('Fixed stop category required')
    with store.db:
        if not store.db.execute('SELECT 1 FROM batch_claims WHERE digest=?',(digest,)).fetchone():
            raise ValueError('Unknown batch')
        store.db.execute('INSERT OR IGNORE INTO batch_stops VALUES (?,?)',(digest,outcome))
