"""Reuses M65 parsing, scoring and accounting; M66 only prepares offline reviews."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json

from app import m65_batch
from app.m65_intelligence import build_audit, read_json, sha256
from app.m65_ranking import candidates, rank
from app.m66_verification import VerificationStore, verification_rows, verify
from app.normalization import identity
from app.observations import fingerprint, canonical


def implementation() -> dict:
    root=Path(__file__).resolve().parent
    return {name:sha256(root/name) for name in ('m66.py','m66_verification.py','m66_opportunity.py','m66_discovery.py',
        'm65.py','m65_intelligence.py','m65_ranking.py','m65_batch.py','m63_history.py','profitability.py','marketplace.py')}


def combined(paths: list[Path]) -> tuple[list[dict],list[str]]:
    grouped={};sources=[];loaded=[]
    for path in paths:
        rows=candidates(path)
        digest=rows[0]['source_sha256'] if rows else sha256(path)
        if sha256(path)!=digest:raise ValueError('Source changed')
        loaded.append((digest,rows))
    for digest,rows in sorted(loaded,key=lambda value:value[0]):
        if digest in sources:continue
        sources.append(digest)
        for row in rows:
            row['diversification_brand']='PHILIPS' if identity(row['brand'])=='philips led' else row['brand']
            prior=grouped.get(row['asin'])
            if prior:
                prior['identity_conflict']|=row['identity_conflict'] or prior['identity_fingerprint']!=row['identity_fingerprint'] or identity(prior['brand'])!=identity(row['brand'])
                prior['source_references']=sorted(set(prior['source_references']+row['source_references']))
            else:grouped[row['asin']]=row
    return [grouped[a] for a in sorted(grouped)],sorted(sources)


def build(paths: list[Path],store: VerificationStore,history_dir: Path,*,as_of: datetime,
          maximum: int=20,max_per_brand: int=2,minimum_score: int=0) -> tuple[dict,dict,dict]:
    if type(maximum) is not int or not 1<=maximum<=20:raise ValueError('M66 maximum is 20 unchecked ASINs')
    pool,sources=combined(paths)
    audit=build_audit(history_dir,store)
    # A new/empty derived store must not erase the completed M63 cohort.
    # Require the original permanent scope proof instead of treating missing
    # historical files as permission to check those products again.
    proof,_=read_json(history_dir/'m63-eligibility-authorization-01.json')
    original=proof.get('asins') if isinstance(proof,dict) else None
    if (not isinstance(original,list) or len(original)!=20 or len(set(original))!=20
            or not set(original)<=set(audit['excluded_asins'])):
        raise ValueError('Original permanent 20-ASIN M63 exclusion proof required')
    historical=store.events('eligibility');manual=store.events('manual_approval');sc=verification_rows(store)
    seen_brands={identity(e['brand']) for e in historical if e.get('brand')}
    pattern_brands={identity(e['brand']) for e in sc if 'APPROVAL_APPLICATION_REQUIRED' in e['seller_central_states']}
    manual_invoice={identity(e['brand']) for e in manual if e['invoice_required'] is True and (e['minimum_invoiced_units'] or 0)>=100}
    additional_invoice={identity(e['brand']) for e in sc if e['invoice_required'] is True and (e['minimum_invoiced_units'] or 0)>=100}-manual_invoice
    adjustments={row['asin']:dict(less_represented_brand=8 if identity(row['brand']) not in seen_brands else 0,
                                 observed_approval_pattern=-8 if identity(row['brand']) in pattern_brands else 0,
                                 additional_invoice_pathway=-35 if identity(row['brand']) in additional_invoice else 0) for row in pool}
    manual_blocked=set()
    checks={}
    for row in pool:
        result=verify(row['asin'],historical,sc,as_of=as_of);checks[row['asin']]=result
        states=set(result['seller_central_states'])
        if (states&{'APPROVAL_APPLICATION_REQUIRED','BRAND_VALIDATION_BLOCKED','NEW_LISTINGS_NOT_ACCEPTED'}
                or result['conflict_requires_review'] or result['manual_restriction_codes']):
            manual_blocked.add(row['asin'])
    # Only exact-ASIN negative manual evidence defers an ASIN. Brand-only
    # patterns affect priority, never propagate eligibility or permanent bans.
    effective=set(audit['excluded_asins'])|manual_blocked
    ranked=rank(pool,historical,manual,effective,maximum=maximum,max_per_brand=max_per_brand,
                additional_points=adjustments,minimum_score=minimum_score)
    for row in ranked['rows']:
        row['verification']=checks[row['asin']]
        if row['asin'] in manual_blocked:
            row['exclusion_reasons']=[r for r in row['exclusion_reasons'] if r!='PREVIOUSLY_CHECKED_OR_RESERVED']+['EXACT_ASIN_MANUAL_REVIEW_BLOCK']
            if row['asin'] in audit['excluded_asins']:row['exclusion_reasons'].append('PREVIOUSLY_CHECKED_OR_RESERVED')
        row['selection_explanation']=dict(identity_points={k:v for k,v in row['score_components'].items() if v},
            diversity_adjusted_score=row.get('selection_score'),eligibility='UNKNOWN',
            meaning='Selected only for separately authorized restriction research, never a sellable product claim')
    # M65 excludes include every historical attempt. Manual blocks remain a
    # separate report field rather than rewriting the legacy exclusion record.
    review_audit=dict(audit,manual_review_blocked_asins=sorted(manual_blocked),m63_permanent_excluded_asins=sorted(original))
    # Inner M65 proposal retains its established authorization and accounting contract.
    inner=m65_batch.proposal(ranked,audit,fingerprint(sources))
    manifest=dict(schema=1,mode='M66_ELIGIBILITY_REVIEW_ONLY',evaluated_at=as_of.isoformat(),
        implementation_sha256=implementation(),catalog_source_sha256=sources,
        historical_audit_sha256=fingerprint(audit),review_audit_sha256=fingerprint(review_audit),
        verification_revision=store.revision(),restrictions_proposal=inner,
        execution_authorized=False,live_executor_enabled=False,automatic_follow_on=False,
        manual_review_required=True,purchase_authorized=False)
    return manifest,ranked,review_audit


def validate(path: Path,digest: str,paths: list[Path],store: VerificationStore,history_dir: Path) -> dict:
    manifest,actual=read_json(path)
    if actual!=digest or not isinstance(manifest,dict):raise ValueError('Exact fresh reviewed file SHA256 required')
    inner=manifest.get('restrictions_proposal') or {}
    m65_batch.validate_manifest(inner)
    expected,_,_=build(paths,store,history_dir,as_of=datetime.fromisoformat(manifest['evaluated_at']),
                        maximum=inner['maximum_checks'],max_per_brand=inner['ranking_policy']['max_per_brand'],
                        minimum_score=inner['ranking_policy']['minimum_score'])
    if manifest!=expected:raise ValueError('Source/code/history/verification/ranking drift')
    return manifest


def reserve_future(path: Path,digest: str,paths: list[Path],store: VerificationStore,history_dir: Path,
                   authorization: dict|None,*,execute: bool=False) -> None:
    """Offline accounting primitive only. No transport exists in M66."""
    m=validate(path,digest,paths,store,history_dir)
    m65_batch.reserve_future(store,m['restrictions_proposal'],digest,authorization,
        actual_file_sha256=sha256(path),execute=execute,audit=build_audit(history_dir,store))


def record_result(store: VerificationStore,digest: str,asin: str,operation: str,outcome: str,source_sha256: str,observed_at: str) -> None:
    """Immutable, scoped future result accounting; raw replies are not accepted."""
    import re
    from app.m65_intelligence import STATES,observed,US,CONDITION
    date=observed(observed_at)
    if (operation not in ('SUCCEEDED','FAILED','UNCERTAIN') or outcome not in STATES
            or not re.fullmatch(r'[a-f0-9]{64}',source_sha256) or not date
            or datetime.fromisoformat(date)>datetime.now(timezone.utc)):
        raise ValueError('Allowlisted result metadata required')
    if operation!='SUCCEEDED' and outcome!='UNKNOWN':raise ValueError('Failure cannot establish eligibility')
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        if not store.db.execute('SELECT 1 FROM request_attempts WHERE request_id=? AND digest=? AND kind=?',
            (digest+':'+asin,digest,'restrictions')).fetchone():raise ValueError('Durably consumed exact request required')
        record=dict(asin=asin,marketplace=US,condition=CONDITION,observed_at=observed(observed_at),
                    verification_method='SAVED_SP_API_LISTINGS_RESTRICTIONS',
                    operation_status=operation,api_state=outcome,source_sha256=source_sha256,
                    fba_state='FBA_UNKNOWN',purchase_authorized=False)
        store.db.execute('INSERT INTO m66_results VALUES (?,?,?)',(digest,asin,canonical(record)))
        if outcome=='UNKNOWN' or operation!='SUCCEEDED':
            store.db.execute('INSERT OR IGNORE INTO batch_stops VALUES (?,?)',(digest,'UNKNOWN'))
