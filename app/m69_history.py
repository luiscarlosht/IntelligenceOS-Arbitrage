"""Read-only consolidation of immutable M63/M67 evidence and all permanent claims."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import re

from app.m65_intelligence import (ASIN, US, CONDITION, STATES, import_report, read_json,
                                build_audit, observed, sha256)
from app.m67_state import ReadOnlyStore, ledger_snapshot, secure, readonly
from app.m67_reporting import records, validate_snapshot, quiescent
from app.m66_verification import verification_rows, ACCOUNT
from app.observations import fingerprint


def normalize(row: dict, source: str) -> dict:
    asin = row.get('asin')
    if not isinstance(asin,str) or not ASIN.fullmatch(asin):
        raise ValueError('Historical ASIN required')
    date = observed(row.get('observed_at'))
    state = row.get('eligibility',row.get('api_state','UNKNOWN'))
    operation = row.get('operation_status','UNCERTAIN')
    valid = (row.get('marketplace')==US and row.get('condition')==CONDITION and date
             and datetime.fromisoformat(date)<=datetime.now(timezone.utc)
             and state in STATES and operation=='SUCCEEDED')
    source_hash=row.get('source_sha256')
    if not isinstance(source_hash,str) or not re.fullmatch('[a-f0-9]{64}',source_hash):source_hash=fingerprint(row)
    reference=row.get('source_reference','')
    if not isinstance(reference,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}(?::row:[0-9]+)?',reference):reference='sha256:'+source_hash
    return dict(asin=asin,marketplace=US if row.get('marketplace')==US else 'UNKNOWN',
        condition=CONDITION if row.get('condition')==CONDITION else 'UNKNOWN',observed_at=date,
        operation_status='SUCCEEDED' if valid else 'UNCERTAIN',eligibility=state if valid else 'UNKNOWN',
        source_reference=reference,source_sha256=source_hash,evidence_kind=source,
        verification_method='SAVED_SP_API_LISTINGS_RESTRICTIONS')


def consolidate(private: Path, store_path: Path, manifest_path: Path, digest: str,
                catalog: list[dict]) -> dict:
    secure(private,directory=True)
    if (private/'candidate-execution.lock').is_symlink():raise ValueError('Ambiguous execution lock')
    legacy=readonly(private/'candidate-executions.sqlite3');legacy.close()
    if not (private/'m67-executions.sqlite3').is_file() or (private/'m67-executions.sqlite3').is_symlink():
        raise ValueError('Original M67 global ledger required; never assume missing means unchecked')
    with quiescent(private/'m67-executions.sqlite3'):
        store=ReadOnlyStore(store_path)
        try:
            audit=build_audit(private,store)
            proof,proof_sha=read_json(private/'m63-eligibility-authorization-01.json')
            original=proof.get('asins',[])
            if (proof.get('state')!='claimed_no_replay' or proof.get('maximum_checks')!=20 or len(original)!=20 or len(set(original))!=20
                    or any(not isinstance(a,str) or not ASIN.fullmatch(a) for a in original)):
                raise ValueError('Original permanent twenty-ASIN M63 proof required')
            manifest,actual=read_json(manifest_path)
            if actual!=digest:raise ValueError('Original M67 frozen manifest digest mismatch')
            snapshot=ledger_snapshot(private/'m67-executions.sqlite3')
            if any(not isinstance(a,str) or not ASIN.fullmatch(a) for a in snapshot['claims']):
                raise ValueError('Malformed permanent global claim')
            validate_snapshot(snapshot,manifest,digest)
            frozen=manifest['restrictions_proposal']['asins']
            if (len(frozen)!=20 or set(frozen)&set(original) or digest not in snapshot['batches']
                    or manifest['restrictions_proposal'].get('account_reference')!=ACCOUNT):
                raise ValueError('Distinct original M63 and permanently reserved M67 cohorts required')
            if not set(frozen)<=set(snapshot['claims']):raise ValueError('Missing global permanent claims')
            ranking,ranking_sha=read_json(manifest_path.parent/'M66_candidate_ranking.json')
            if fingerprint(ranking)!=manifest['restrictions_proposal']['ranking_sha256']:
                raise ValueError('Frozen label/ranking evidence changed')
            labels={r['asin']:dict(brand=r['brand'],category=r['category']) for r in catalog}
            # Historical outcomes retain their observed labels; current catalog
            # changes never silently reassign the sample to another brand.
            labels.update({r['asin']:dict(brand=r['brand'],category=r['category']) for r in ranking['rows'] if r['asin'] in frozen})
            events=[];sources=[dict(kind='M63_PERMANENT_RESERVATION',sha256=proof_sha),
                dict(kind='M67_FROZEN_MANIFEST',sha256=digest),dict(kind='M67_FROZEN_RANKING',sha256=ranking_sha)]
            paths=sorted(p for p in private.glob('m63-eligibility-*.json') if p.name!='m63-eligibility-authorization-01.json')
            if not paths or len(paths)>100:raise ValueError('Bounded original M63 outcome reports required')
            for path in paths:
                for event in import_report(path):
                    events.append(normalize(event,'M63'))
                    prior=labels.get(event['asin'],dict(brand='UNKNOWN',category='UNKNOWN'))
                    labels[event['asin']]=dict(brand=event.get('brand') or prior['brand'],category=event.get('category') or prior['category'])
                sources.append(dict(kind='M63_OUTCOME_REPORT',sha256=sha256(path)))
            for row in records(snapshot,digest):
                raw=snapshot['outcomes'].get(digest+':'+row['asin'],{})
                if raw.get('http_status')!=200:
                    row=dict(row,operation_status='UNCERTAIN',api_state='UNKNOWN')
                events.append(normalize(dict(row,marketplace=US,condition=CONDITION),'M67'))
            for event in store.events('eligibility'):
                events.append(normalize(event,'DERIVED_ELIGIBILITY'))
            for (payload,) in store.db.execute('SELECT payload FROM m66_results'):
                event=json.loads(payload)
                events.append(normalize(event,'DERIVED_M66_RESULT'))
            unique={fingerprint(e):e for e in events}
            events=[unique[key] for key in sorted(unique)]
            excluded=set(audit['excluded_asins'])|set(snapshot['claims'])|set(original)|set(frozen)|{e['asin'] for e in events}
            # Claims are conservative exclusions even without any recorded response.
            rows=[]
            for asin in sorted({e['asin'] for e in events}|set(original)|set(frozen)|set(snapshot['claims'])):
                facts={fingerprint(e):e for e in events if e['asin']==asin}
                facts=[facts[k] for k in sorted(facts)]
                states={e['eligibility'] for e in facts};ops={e['operation_status'] for e in facts}
                conflict=len(states)>1 or len(ops)>1
                valid=bool(facts) and ops=={'SUCCEEDED'} and len(states)==1
                state=next(iter(states)) if valid else 'UNKNOWN'
                label=labels.get(asin,dict(brand='UNKNOWN',category='UNKNOWN'))
                rows.append(dict(asin=asin,candidate_id='amazon-us:'+asin,**label,
                    api_state=state,operation_status='SUCCEEDED' if valid else 'UNCERTAIN',
                    conflicting_evidence=conflict,observation_count=len(facts),observations=facts,
                    permanently_excluded=True,listing_authorization='UNKNOWN',fba_state='FBA_UNKNOWN'))
            cohort=set(original)|set(frozen)
            checked=[r for r in rows if r['asin'] in cohort]
            complete=all(r['operation_status']=='SUCCEEDED' and r['api_state']!='UNKNOWN' for r in checked) and len(checked)==40
            unbound=set(snapshot['batches'])-{digest}
            gaps=[]
            authentication=[a for a in snapshot['attempts'] if a['digest']==digest and a['kind']=='authentication']
            auth=snapshot['outcomes'].get(authentication[0]['id'],{}) if len(authentication)==1 else {}
            if auth.get('operation_status')!='SUCCEEDED' or auth.get('http_status')!=200:
                gaps.append('M67_AUTHENTICATION_EVIDENCE_INCOMPLETE')
            if not complete:gaps.append('ORIGINAL_40_OUTCOMES_INCOMPLETE_OR_CONFLICTING')
            if unbound:gaps.append('ADDITIONAL_GLOBAL_BATCHES_REQUIRE_FROZEN_PROVENANCE')
            result=dict(schema=1,mode='M69_OFFLINE_HISTORY',account_reference=ACCOUNT,rows=rows,events=events,
                original_m63_asins=sorted(original),original_m67_asins=list(frozen),
                cohort_summary=dict(unique_asins=len(cohort),**{s:sum(r['api_state']==s for r in checked) for s in STATES}),
                excluded_asins=sorted(excluded),legacy_exclusion_count=len(audit['legacy']['excluded_asins']),
                global_claim_count=len(snapshot['claims']),sources=sources,
                catalog_source_sha256=sorted({ref.split(':')[1] for r in catalog for ref in r['source_references']}),
                catalog_identity_sha256={r['asin']:r['identity_fingerprint'] for r in catalog},
                legacy_audit=dict(reports=[dict(sha256=r['sha256']) for r in audit['legacy']['reports']],
                                  ledger_operations=audit['legacy']['ledger_operations']),store_revision=store.revision(),
                global_snapshot_sha256=fingerprint(snapshot),manual_approvals=store.events('manual_approval'),
                manual_verifications=verification_rows(store),data_gaps=gaps,history_complete=not gaps,
                interpretation='Counts describe observed ASINs in these selected cohorts, never Amazon-wide rates or brand-wide permission',
                live_requests=0,new_reservations=0)
            result['evidence_sha256']=fingerprint(result)
            return result
        finally:store.db.close()


def risk_groups(history: dict, field: str) -> list[dict]:
    if field not in ('brand','category'):raise ValueError('Explicit group dimension required')
    from app.normalization import identity
    groups={}
    for row in history['rows']:
        key=identity(row[field])
        if field=='brand' and key=='philips led':key='philips'
        groups.setdefault(key,[]).append(row)
    result=[]
    for key,rows in sorted(groups.items()):
        valid=[r for r in rows if r['operation_status']=='SUCCEEDED' and r['api_state']!='UNKNOWN']
        result.append(dict(group=key,sample_size=len(valid),distinct_asins=len(rows),
            **{s:sum(r['api_state']==s for r in valid) if s!='UNKNOWN' else len(rows)-len(valid) for s in STATES},
            conflicting_asins=sum(r['conflicting_evidence'] for r in rows),
            inference='OBSERVED_SAMPLE_ONLY',brand_wide_permission=None))
    return result
