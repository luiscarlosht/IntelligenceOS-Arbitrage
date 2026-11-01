"""Descriptive frozen-cohort outcomes only; reporting never dispatches requests."""
from collections import Counter
from datetime import datetime
import csv
import os
from pathlib import Path
import json

from app.m65 import write_json
from app.m65_intelligence import US, CONDITION, STATES, observed, read_json
from app.observations import fingerprint, canonical


def measure(manifest: dict,ranking: dict,store,digest: str) -> dict:
    inner=manifest['restrictions_proposal'];asins=inner['asins']
    if (manifest.get('mode')!='M66_ELIGIBILITY_REVIEW_ONLY' or inner.get('marketplace_id')!=US
            or inner.get('condition')!=CONDITION or len(asins)>20 or len(asins)!=len(set(asins))
            or fingerprint(ranking)!=inner['ranking_sha256']):
        raise ValueError('Exact frozen cohort and ranking required')
    by_asin={r['asin']:r for r in ranking['rows']}
    if not set(asins)<=set(by_asin):raise ValueError('Cohort labels missing')
    after=observed(manifest.get('evaluated_at'))
    if not after:raise ValueError('Cohort observation boundary required')
    facts={a:[] for a in asins}
    for event in store.events('eligibility'):
        a=event.get('asin');date=observed(event.get('observed_at'))
        if (a not in facts or event.get('marketplace')!=US or event.get('condition')!=CONDITION
                or not date or datetime.fromisoformat(date)<datetime.fromisoformat(after)
                or event.get('operation_status') not in ('SUCCEEDED','FAILED','UNCERTAIN')):continue
        facts[a].append((event['operation_status'],event['eligibility'],event['source_reference']))
    for (payload,) in store.db.execute('SELECT payload FROM m66_results WHERE digest=?',(digest,)):
        e=json.loads(payload);a=e.get('asin')
        if a in facts and e.get('marketplace')==US and e.get('condition')==CONDITION:
            facts[a].append((e['operation_status'],e['api_state'],'sha256:'+e['source_sha256']))
    rows=[]
    for a in asins:
        observations=facts[a];ops={v[0] for v in observations};states={v[1] for v in observations}
        operation='NOT_CHECKED' if not ops else next(iter(ops)) if len(ops)==1 else 'UNCERTAIN'
        state=next(iter(states)) if operation=='SUCCEEDED' and len(states)==1 and next(iter(states)) in STATES else 'UNKNOWN'
        rows.append(dict(asin=a,brand=by_asin[a]['brand'],category=by_asin[a]['category'],
            checked=bool(ops),operation_status=operation,api_state=state,conflicting_evidence=len(states)>1 or len(ops)>1,
            evidence_references=sorted({v[2] for v in observations}),fba_inbound_evidence_evaluated=False,
            offer_submission_status='NOT_SUBMITTED',selling_authorization_confirmed=False))
    def counts(items):
        checked=[r for r in items if r['checked']]
        outcomes=Counter(r['api_state'] for r in checked)
        return dict(selected=len(items),checked=len(checked),not_checked=len(items)-len(checked),
            operation_succeeded=sum(r['operation_status']=='SUCCEEDED' for r in checked),
            failed_or_uncertain=sum(r['operation_status']!='SUCCEEDED' for r in checked),
            conflicting_evidence=sum(r['conflicting_evidence'] for r in checked),
            **{state:outcomes[state] for state in STATES},
            observed_no_restrictions_fraction=outcomes['NO_REPORTED_RESTRICTIONS']/len(checked) if checked else None)
    def group(key):
        return [dict(group=label,**counts([r for r in rows if r[key]==label])) for label in sorted({r[key] for r in rows})]
    return dict(schema=1,cohort_manifest_sha256=digest,evaluated_cohort_size=len(rows),
        by_brand=group('brand'),by_category=group('category'),overall=counts(rows),rows=rows,
        interpretation='Observed descriptive outcomes within this exact cohort; not eligibility probabilities or brand-wide permissions',
        additional_live_requests=0,offers_submitted=0)


def load(path: Path,digest: str,store) -> dict:
    manifest,actual=read_json(path)
    if actual!=digest:raise ValueError('Reviewed cohort file digest required')
    ranking,_=read_json(path.parent/'M66_candidate_ranking.json')
    # Outcome reporting intentionally uses the immutable original snapshot even
    # after new evidence changes the store revision. It grants no execution.
    return measure(manifest,ranking,store,digest)


def export(result: dict,output: Path) -> None:
    write_json(output/'M66_experiment_outcomes.json',result)
    for name,rows in (('results',result['rows']),('by_brand',result['by_brand']),('by_category',result['by_category'])):
        fd=os.open(output/('M66_experiment_'+name+'.csv'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',newline='',encoding='utf-8-sig') as stream:
            fields=list(rows[0]) if rows else ['asin']
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
            for row in rows:
                cells={}
                for k,value in row.items():
                    if isinstance(value,(dict,list)):value=canonical(value)
                    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):value="'"+value
                    cells[k]=value
                writer.writerow(cells)
