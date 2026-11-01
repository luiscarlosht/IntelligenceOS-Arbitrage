"""Deterministic research priority on authorized saved sources, never permission."""
from collections import Counter
from datetime import datetime, timezone
import csv
from pathlib import Path

from app.m65_intelligence import read_json, sha256, US, CONDITION
from app.m65_ranking import rank
from app.m66_discovery import combined
from app.m66_verification import verify
from app.m69_history import consolidate, risk_groups
from app.normalization import identity
from app.observations import fingerprint


def implementation() -> dict:
    root=Path(__file__).parent
    return {name:sha256(root/name) for name in ('m69.py','m69_history.py','m69_discovery.py','m69_workflow.py',
        'm65.py','m65_intelligence.py','m65_ranking.py','m63_history.py','m66_discovery.py',
        'm66_verification.py','m66_opportunity.py','m67_state.py','m67_reporting.py',
        'profitability.py','marketplace.py','normalization.py','observations.py','models.py')}


def source_profiles(paths: list[Path]) -> tuple[dict,dict]:
    profiles={};conditions={}
    for path in paths:
        digest=sha256(path)
        if path.suffix.lower()=='.csv':
            with path.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
            quality='SUPPLIED_CATALOG_CSV';points=3
        else:
            doc,_=read_json(path)
            direct=(isinstance(doc,dict) and doc.get('mode')=='M63_CATALOG_DISCOVERY' and doc.get('is_mock') is False)
            quality='SAVED_SP_API_CATALOG' if direct else 'SUPPLIED_CATALOG_JSON'
            points=6 if direct else 1
            rows=doc.get('candidates',[]) if isinstance(doc,dict) else doc
            if isinstance(rows,dict):rows=list(rows.values())
        for row in rows:
            asin=row.get('asin') or (row.get('catalog') or {}).get('asin')
            condition=row.get('condition') or row.get('condition_type')
            if condition:
                value=CONDITION if str(condition).casefold() in ('new','new_new') else 'INCOMPATIBLE'
                conditions.setdefault(asin,set()).add(value)
        if sha256(path)!=digest:raise ValueError('Catalog source changed while reading')
        profiles[digest]=dict(source_sha256=digest,source_class=quality,quality_points=points)
    return profiles,conditions


def analyze(paths: list[Path], store_path: Path, private: Path, manifest: Path, digest: str,
            *, as_of: datetime, maximum: int=100, max_per_brand: int=10) -> tuple[dict,dict]:
    if as_of.tzinfo is None or as_of>datetime.now(timezone.utc):raise ValueError('Aware nonfuture analysis clock required')
    pool,sources=combined(paths)
    profiles,conditions=source_profiles(paths)
    if sorted(profiles)!=sources:raise ValueError('Catalog source binding drift')
    history=consolidate(private,store_path,manifest,digest,pool)
    brand_stats={r['group']:r for r in risk_groups(history,'brand')}
    category_stats={r['group']:r for r in risk_groups(history,'category')}
    extra={};blocked=set(history['excluded_asins']);condition_states={};verifications={}
    for row in pool:
        brand=identity(row.get('diversification_brand') or row['brand']);category=identity(row['category'])
        b=brand_stats.get(brand,{});c=category_stats.get(category,{})
        checked=verify(row['asin'],history['events'],history['manual_verifications'],as_of=as_of)
        verifications[row['asin']]=checked
        sc=set(checked['seller_central_states'])
        if sc&{'APPROVAL_APPLICATION_REQUIRED','BRAND_VALIDATION_BLOCKED','NEW_LISTINGS_NOT_ACCEPTED'} or checked['conflict_requires_review'] or checked['manual_restriction_codes']:
            blocked.add(row['asin'])
        condition=conditions.get(row['asin'],set())
        compatibility='INCOMPATIBLE' if 'INCOMPATIBLE' in condition else 'OBSERVED_NEW' if CONDITION in condition else 'UNKNOWN'
        condition_states[row['asin']]=compatibility
        if compatibility=='INCOMPATIBLE':blocked.add(row['asin'])
        referenced={ref.split(':')[1] for ref in row['source_references']}
        quality=max(profiles[h]['quality_points'] for h in referenced)
        extra[row['asin']]=dict(source_quality=quality,
            source_freshness=2 if (as_of-datetime.fromisoformat(row['observed_at'])).total_seconds()<=86400 else 0,
            condition_evidence=2 if compatibility=='OBSERVED_NEW' else 0,
            brand_observed_approval=-min(12,2*b.get('APPROVAL_REQUIRED',0)),
            brand_observed_ineligibility=-min(20,4*b.get('NOT_ELIGIBLE',0)),
            category_observed_blocks=-min(6,(c.get('APPROVAL_REQUIRED',0)+c.get('NOT_ELIGIBLE',0)+c.get('OTHER_RESTRICTED',0))//3),
            exact_account_evidence=-80 if checked['api_state'] in ('APPROVAL_REQUIRED','NOT_ELIGIBLE','OTHER_RESTRICTED') else 0)
    # Concentration uses distinct observed ASINs, never duplicated report/import rows.
    ranking_history=[dict(asin=r['asin'],brand=r['brand']) for r in history['rows']
                     if r['operation_status']=='SUCCEEDED' and r['api_state']!='UNKNOWN']
    ranked=rank(pool,ranking_history,history['manual_approvals'],blocked,maximum=maximum,
                max_per_brand=max_per_brand,minimum_score=-100,additional_points=extra)
    for row in ranked['rows']:
        condition=condition_states[row['asin']]
        if row['asin'] in blocked and row['asin'] not in history['excluded_asins']:
            row['exclusion_reasons']=[r for r in row['exclusion_reasons'] if r!='PREVIOUSLY_CHECKED_OR_RESERVED']
            row['exclusion_reasons'].append('CONDITION_INCOMPATIBLE' if condition=='INCOMPATIBLE' else 'EXACT_ASIN_MANUAL_REVIEW_BLOCK')
        row.update(condition_required=CONDITION,condition_compatibility=condition,
            account_evidence=verifications[row['asin']]['api_state'],eligibility='UNKNOWN',
            workflow_state='DISCOVERED',identity_verified=False,
            catalog_identity_complete=all(row['identity_features'][k] for k in ('gtin','model','size','pack','variation')) and not row['identity_conflict'],
            brand_history=brand_stats.get(identity(row.get('diversification_brand') or row['brand']),dict(sample_size=0,inference='UNKNOWN')),
            category_history=category_stats.get(identity(row['category']),dict(sample_size=0,inference='UNKNOWN')),
            verification=verifications[row['asin']],
            score_explanation='Sum score_components, then diversity penalties; sample counts are not probabilities or brand-wide restrictions')
    selected=[r for r in ranked['rows'] if r['selected']]
    if set(ranked['selected_asins'])&set(history['excluded_asins']):raise ValueError('Permanent exclusion invariant violated')
    report=dict(schema=1,mode='M69_OFFLINE_CANDIDATE_ANALYSIS',as_of=as_of.isoformat(),
        implementation_sha256=implementation(),source_profiles=[profiles[h] for h in sources],
        history_sha256=history['evidence_sha256'],history_complete=history['history_complete'],data_gaps=history['data_gaps'],
        ranking=ranked,brand_risk=risk_groups(history,'brand'),category_risk=risk_groups(history,'category'),
        cohort_summary=history['cohort_summary'],excluded_asins=history['excluded_asins'],
        summary=dict(candidates_evaluated=len(pool),selected_count=len(selected),permanent_exclusions=len(history['excluded_asins']),
            historical_candidates_in_sources=sum(r['asin'] in history['excluded_asins'] for r in pool),
            brand_distribution=dict(Counter(r['brand'] for r in selected)),category_distribution=dict(Counter(r['category'] for r in selected)),
            missing_identity=dict(Counter(k for r in selected for k,v in r['identity_features'].items() if not v)),
            catalog_identity_complete=sum(r['catalog_identity_complete'] for r in selected),
            eligibility='UNKNOWN',listing_permission='UNKNOWN',fba_state='FBA_UNKNOWN'),
        live_requests=0,retailer_requests=0,new_reservations=0,execution_authorized=False,purchase_authorized=False,
        limitations=['Catalog presence is not verified identity or selling authorization',
                    'Only saved sources are ranked; no new product discovery requests',
                    'Small selected historical samples do not estimate Amazon-wide eligibility',
                    'Unknown condition and identity require explicit evidence before progression'])
    return report,history
