"""M65 offline intake, manual approval intelligence and next-cohort preparation.

There is deliberately no execute, network, approval, listing or purchase action.
"""
import argparse
from collections import Counter
import csv
import json
import os
from pathlib import Path

from app.m65_batch import proposal, validate_manifest
from app.m65_intelligence import (IntelligenceStore, STATES, build_audit, coverage,
    import_report, manual_observation, read_json, sha256)
from app.m65_ranking import candidates, rank
from app.m65_readiness import readiness
from app.observations import canonical

SEEDS=Path(__file__).resolve().parent.parent/'ops/examples/m64-approval-observations.json'
PRIVATE=Path.home()/'.intelligenceos-arbitrage-amazon'


def write_json(path: Path, data: object) -> None:
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        stream.write(canonical(data)+'\n')
        stream.flush()
        os.fsync(stream.fileno())


def manual_import(path: Path, store: IntelligenceStore) -> dict:
    document,_=read_json(path)
    rows=document.get('observations') if isinstance(document,dict) else document
    if not isinstance(rows,list) or len(rows)>10000:
        raise ValueError('Manual observations array required')
    return store.append([manual_observation(row) for row in rows])


def prepare(store: IntelligenceStore, catalog: Path, history_dir: Path, output: Path,
            maximum: int=20, max_per_brand: int=2, minimum_score: int=0) -> dict:
    items=candidates(catalog)
    source_hash=items[0]['source_sha256'] if items else sha256(catalog)
    history=build_audit(history_dir,store)
    ranked=rank(items,store.events('eligibility'),store.events('manual_approval'),set(history['excluded_asins']),
                maximum=maximum,max_per_brand=max_per_brand,minimum_score=minimum_score)
    if sha256(catalog)!=source_hash:
        raise ValueError('Candidate source changed while reading')
    manifest=proposal(ranked,history,source_hash)
    validate_manifest(manifest)
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    write_json(output/'M65_history_audit.json',history)
    write_json(output/'M65_candidate_ranking.json',ranked)
    write_json(output/'M65_proposed_manifest.json',manifest)
    write_json(output/'M65_manual_review_coverage.json',coverage(store))
    write_json(output/'M65_profitability_readiness.json',readiness())
    fields=('candidate_id','asin','brand','category','product_type','score','selection_score','selected',
            'eligibility','brand_pathway_signal','identity_features','identity_conflict','exclusion_reasons',
            'priority_review_required','score_components','observed_at','source_references')
    fd=os.open(output/'M65_candidate_ranking.csv',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        for row in ranked['rows']:
            cells={}
            for field in fields:
                value=row.get(field)
                value=canonical(value) if isinstance(value,(dict,list)) else str(value) if value is not None else ''
                cells[field]="'"+value if value.lstrip().startswith(('=','+','-','@')) else value
            writer.writerow(cells)
    summaries=Counter(event['eligibility'] for event in store.events('eligibility'))
    operations=Counter(event['operation_status'] for event in store.events('eligibility'))
    summary=dict(schema=1,mode='OFFLINE_DRY_RUN',candidate_count=len(items),proposed_count=len(manifest['asins']),
        historical_exclusions=len(history['excluded_asins']),historical_outcomes={key:summaries[key] for key in STATES},
        historical_operation_status=dict(operations),manual_observations=len(store.events('manual_approval')),
        invoice_heavy_brands=sorted({r['brand'] for r in ranked['rows'] if r['brand_pathway_signal']=='OBSERVED_INVOICE_HEAVY'}),
        selected_asins=manifest['asins'],manifest_sha256=sha256(output/'M65_proposed_manifest.json'),
        diversity_gaps=ranked['diversity_gaps'],live_requests=0,retries=0,
        execution_authorized=False,profitability_enabled=False,purchase_authorized=False)
    write_json(output/'M65_summary.json',summary)
    return summary


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('init','import-history','import-manual','export-history','export-manual','coverage','prepare','validate'))
    p.add_argument('--store',type=Path,default=Path('var/m65/intelligence.sqlite3'))
    p.add_argument('--input',type=Path)
    p.add_argument('--catalog',type=Path)
    p.add_argument('--history-dir',type=Path,default=PRIVATE)
    p.add_argument('--output',type=Path)
    p.add_argument('--max-checks',type=int,default=20)
    p.add_argument('--max-per-brand',type=int,default=2)
    p.add_argument('--minimum-score',type=int,default=0)
    p.add_argument('--sha256')
    args=p.parse_args()
    store=None
    try:
        if args.action=='validate':
            if not args.input or not args.sha256:
                raise ValueError('Reviewed manifest file and SHA256 required')
            document,digest=read_json(args.input)
            if digest!=args.sha256:raise ValueError('Manifest digest mismatch')
            validate_manifest(document)
            result=dict(status='validated_offline',live_requests=0,execution_authorized=False)
        else:
            store=IntelligenceStore(args.store)
            if args.action=='init':result=manual_import(SEEDS,store)
            elif args.action=='import-history':
                if not args.input:raise ValueError('Input evidence required')
                result=store.append(import_report(args.input))
            elif args.action=='import-manual':
                if not args.input:raise ValueError('Manual observation file required')
                result=manual_import(args.input,store)
            elif args.action in ('export-history','export-manual'):
                if not args.output:raise ValueError('Exclusive output required')
                if args.action=='export-manual':
                    payload=dict(observations=[{k:v for k,v in e.items() if k!='kind'} for e in store.events('manual_approval')])
                else:
                    payload=dict(events=store.events('eligibility'),manual_review_coverage=coverage(store),
                                 fba_eligibility=None,purchase_authorized=False,live_requests=0)
                write_json(args.output,payload)
                result=dict(status='exported_offline')
            elif args.action=='coverage':
                if not args.output:raise ValueError('Exclusive output required')
                write_json(args.output,coverage(store))
                result=dict(status='exported_offline')
            else:
                if not args.catalog or not args.output:raise ValueError('Catalog and exclusive output required')
                result=prepare(store,args.catalog,args.history_dir,args.output,args.max_checks,args.max_per_brand,args.minimum_score)
        print(canonical(result))
        return 0
    except (Exception,KeyboardInterrupt):
        print('M65 offline operation stopped; inspect input/schema privately. No request was sent.')
        return 1
    finally:
        if store is not None:store.close()


if __name__=='__main__':
    raise SystemExit(main())
