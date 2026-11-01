"""M66 offline review CLI. No live, purchase, listing or submission action."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import csv
import json
import os
from pathlib import Path

from app.m65 import manual_import, write_json, SEEDS, PRIVATE
from app.m65_intelligence import import_report, read_json, sha256
from app.m66_discovery import build, validate
from app.m66_opportunity import template, decide
from app.m66_verification import VerificationStore, verification_rows, verify
from app.observations import canonical

SC_SEEDS=Path(__file__).resolve().parent.parent/'ops/examples/m66-seller-central-observations.json'


def import_verifications(path: Path,store: VerificationStore) -> dict:
    data,_=read_json(path)
    rows=data.get('observations') if isinstance(data,dict) else data
    if not isinstance(rows,list) or len(rows)>10000:raise ValueError('Bounded observations required')
    return store.append_verifications(rows)


def csv_export(path: Path,rows: list[dict]) -> None:
    fields=('asin','brand','title','category','product_type','selected','score','selection_score',
            'eligibility','observed_at','identity_features','exclusion_reasons','selection_explanation','source_references')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in rows:
            out={}
            for field in fields:
                value=row.get(field)
                if isinstance(value,(dict,list)):value=canonical(value)
                if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):value="'"+value
                out[field]=value
            writer.writerow(out)


def prepare(paths: list[Path],store: VerificationStore,history_dir: Path,output: Path,*,as_of: datetime,
            maximum: int=20,max_per_brand: int=2,minimum_score: int=0) -> dict:
    m,ranking,audit=build(paths,store,history_dir,as_of=as_of,maximum=maximum,max_per_brand=max_per_brand,minimum_score=minimum_score)
    selected=[r for r in ranking['rows'] if r['selected']]
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    write_json(output/'M66_review_manifest.json',m)
    write_json(output/'M66_historical_exclusions.json',audit)
    write_json(output/'M66_candidate_ranking.json',ranking)
    write_json(output/'M66_manual_verification.json',dict(observations=verification_rows(store)))
    csv_export(output/'M66_candidates.csv',ranking['rows'])
    csv_export(output/'M66_cohort.csv',selected)
    digest=sha256(output/'M66_review_manifest.json')
    inner=m['restrictions_proposal']
    summary=dict(mode='M66_OFFLINE_REVIEW',candidates_evaluated=len(ranking['rows']),
        historical_exclusions=len(audit['excluded_asins']),historical_asins_in_input=sum(r['asin'] in audit['excluded_asins'] for r in ranking['rows']),
        m63_permanent_exclusions=len(audit['m63_permanent_excluded_asins']),
        proposed_asins=inner['asins'],proposed_count=len(selected),
        brand_counts=dict(Counter(r['brand'] for r in selected)),category_counts=dict(Counter(r['category'] for r in selected)),
        brand_group_counts=dict(Counter(r.get('diversification_brand') or r['brand'] for r in selected)),
        selected_outside_original_seeds=sum(r['score_components'].get('outside_previous_seed_brands',0)>0 for r in selected),
        missing_identity_counts=dict(Counter(k for r in selected for k,v in r['identity_features'].items() if not v)),
        eligibility='UNKNOWN',fba_state='FBA_UNKNOWN',manifest_sha256=digest,budget=inner['budget'],
        execution_authorized=False,live_requests=0,retailer_requests=0,purchase_authorized=False,
        discovery_assessment='Additional saved observations broaden the reviewed pool without live discovery. Less-represented does not mean unrestricted or a smaller company. Fresh external discovery remains separately authorized.')
    write_json(output/'M66_summary.json',summary)
    # Ready-to-fill contracts contain no fabricated identity or prices.
    write_json(output/'M66_downstream_templates.json',dict(opportunities=[template(a) for a in inner['asins']]))
    text=('# M66 authorization review — NOT AUTHORIZED\n\n'
        f'Manifest SHA-256: `{digest}`\n\n'
        f'Proposed distinct ASINs: {len(selected)}; maximum 20. '
        f'Restrictions requests: {inner["budget"]["restrictions"]}; authentication: {inner["budget"]["authentication"]}; '
        f'hard total: {inner["budget"]["maximum_requests"]}; retries: 0.\n\n'
        'No Catalog, Pricing, Fees, retailer or follow-on operations. No live executor is provided. '
        'A separate current human authorization, exact digest and explicit execution flag must precede any future permanent reservation. '
        'All ASINs below are unchecked and UNKNOWN, not approved products.\n\n'+
        '\n'.join(f'- `{r["asin"]}` — {r["brand"]}, {r["category"]}' for r in selected)+'\n')
    fd=os.open(output/'M66_AUTHORIZATION_REVIEW.md',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(text)
    fd=os.open(output/'M66_manifest.sha256',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(digest+'  M66_review_manifest.json\n')
    return summary


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('init','import-history','import-verification','export-verification','prepare','validate','template','evaluate'))
    p.add_argument('--store',type=Path,default=Path('var/m66/intelligence.sqlite3'))
    p.add_argument('--input',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--catalog',type=Path,action='append',default=[])
    p.add_argument('--history-dir',type=Path,default=PRIVATE)
    p.add_argument('--max-checks',type=int,default=20);p.add_argument('--max-per-brand',type=int,default=2)
    p.add_argument('--minimum-score',type=int,default=0)
    p.add_argument('--sha256');p.add_argument('--asin');p.add_argument('--as-of',default=datetime.now(timezone.utc).isoformat())
    args=p.parse_args();store=None
    try:
        as_of=datetime.fromisoformat(args.as_of.replace('Z','+00:00'))
        if as_of.utcoffset() is None:raise ValueError('Aware evaluation time required')
        if args.action=='template':
            if not args.output or not args.asin:raise ValueError('ASIN and exclusive output required')
            write_json(args.output,template(args.asin));result=dict(status='template_only',live_requests=0)
        else:
            store=VerificationStore(args.store)
            if args.action=='init':
                result=dict(m64=manual_import(SEEDS,store),m66=import_verifications(SC_SEEDS,store))
            elif args.action=='import-history':
                if not args.input:raise ValueError('Existing report required')
                result=store.append(import_report(args.input))
            elif args.action=='import-verification':
                if not args.input:raise ValueError('Observation JSON required')
                result=import_verifications(args.input,store)
            elif args.action=='export-verification':
                if not args.output:raise ValueError('Exclusive output required')
                write_json(args.output,dict(observations=verification_rows(store)));result=dict(status='exported_offline')
            elif args.action=='prepare':
                if not args.catalog or not args.output:raise ValueError('Saved catalogs and output required')
                result=prepare(args.catalog,store,args.history_dir,args.output,as_of=as_of,maximum=args.max_checks,
                               max_per_brand=args.max_per_brand,minimum_score=args.minimum_score)
            elif args.action=='validate':
                if not args.input or not args.sha256 or not args.catalog:raise ValueError('Reviewed manifest, digest and sources required')
                validate(args.input,args.sha256,args.catalog,store,args.history_dir);result=dict(status='validated_offline',live_requests=0)
            else:
                if not args.input or not args.output:raise ValueError('Supplied opportunity and output required')
                record,_=read_json(args.input)
                state=verify(record['asin'],store.events('eligibility'),verification_rows(store),as_of=as_of)
                decision=decide(record,state,as_of=as_of)
                write_json(args.output,dict(verification=state,opportunity=decision,live_requests=0))
                result=dict(decision=decision['decision'],live_requests=0,purchase_authorized=False)
        print(canonical(result));return 0
    except (Exception,KeyboardInterrupt):
        print('M66 offline validation stopped. No request or submission was made; inspect input privately.')
        return 1
    finally:
        if store is not None:store.close()


if __name__=='__main__':
    raise SystemExit(main())
