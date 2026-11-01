"""M69 offline eligibility-first research. No live execution or reservations."""
import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from app.m65 import write_json
from app.m65_intelligence import read_json, sha256
from app.m66_discovery import combined
from app.m69_discovery import analyze, implementation
from app.m69_history import consolidate
from app.m69_workflow import WorkflowStore, thresholds, STAGES
from app.observations import canonical, fingerprint

PRIVATE=Path.home()/'.intelligenceos-arbitrage-amazon'


def export_csv(path: Path,rows: list[dict],fields: list[str]) -> None:
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in rows:
            cells={}
            for key in fields:
                value=row.get(key)
                if isinstance(value,(dict,list)):value=canonical(value)
                if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):value="'"+value
                cells[key]=value
            writer.writerow(cells)
        stream.flush();os.fsync(stream.fileno())


def export_analysis(report: dict,history: dict,output: Path) -> dict:
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    write_json(output/'M69_analysis.json',report)
    write_json(output/'M69_history.json',history)
    selected=[r for r in report['ranking']['rows'] if r['selected']]
    fields=['candidate_id','asin','title','brand','category','score','selection_score','score_components',
            'eligibility','account_evidence','condition_required','condition_compatibility','workflow_state',
            'catalog_identity_complete','identity_verified','identity_features','identity_fingerprint',
            'identity_conflict','brand_history','category_history','source_references','observed_at']
    export_csv(output/'M69_candidates.csv',selected,fields)
    export_csv(output/'M69_history.csv',history['rows'],['candidate_id','asin','brand','category','api_state',
               'operation_status','conflicting_evidence','observation_count','permanently_excluded','listing_authorization','fba_state'])
    export_csv(output/'M69_exclusions.csv',[dict(asin=a,permanently_excluded=True) for a in history['excluded_asins']],['asin','permanently_excluded'])
    write_json(output/'M69_exclusions.json',dict(excluded_asins=history['excluded_asins'],
        original_m63_asins=history['original_m63_asins'],original_m67_asins=history['original_m67_asins'],
        global_claim_count=history['global_claim_count'],history_sha256=history['evidence_sha256']))
    for name in ('brand','category'):
        rows=report[name+'_risk'];write_json(output/('M69_'+name+'_risk.json'),rows)
        export_csv(output/('M69_'+name+'_risk.csv'),rows,list(rows[0]) if rows else ['group','sample_size'])
    write_json(output/'M69_review_pool.json',dict(mode='M69_OFFLINE_REVIEW_POOL_ONLY',
        asins=report['ranking']['selected_asins'],analysis_sha256=sha256(output/'M69_analysis.json'),
        history_sha256=history['evidence_sha256'],eligibility='UNKNOWN',execution_authorized=False,
        interpretation='Not a live eligibility manifest; explicit workflow reviews and fresh owner authorization are still required'))
    summary=dict(report['summary'],history_complete=history['history_complete'],data_gaps=history['data_gaps'],
        cohort_summary=history['cohort_summary'],analysis_sha256=sha256(output/'M69_analysis.json'),
        live_requests=0,retailer_requests=0,new_reservations=0,purchase_authorized=False)
    write_json(output/'M69_summary.json',summary)
    return summary


def load_analysis(path: Path,digest: str) -> dict:
    report,actual=read_json(path)
    if (actual!=digest or report.get('mode')!='M69_OFFLINE_CANDIDATE_ANALYSIS'
            or report.get('implementation_sha256')!=implementation()):
        raise ValueError('Exact code-bound offline analysis required')
    return report


class PrivateParser(argparse.ArgumentParser):
    def error(self,message):self.exit(2,'M69_BLOCKED_OFFLINE: invalid arguments\n')


def main(argv=None) -> int:
    p=PrivateParser(description=__doc__)
    p.add_argument('action',choices=('analyze','register','advance','manifest','status'))
    p.add_argument('--catalog',type=Path,action='append',required=True)
    p.add_argument('--store',type=Path,required=True,help='Existing M65/M66 store; read-only')
    p.add_argument('--history-dir',type=Path,default=PRIVATE)
    p.add_argument('--m67-manifest',type=Path,required=True)
    p.add_argument('--m67-sha256',required=True)
    p.add_argument('--output',type=Path)
    p.add_argument('--as-of')
    p.add_argument('--maximum',type=int,default=100)
    p.add_argument('--max-per-brand',type=int,default=10)
    p.add_argument('--analysis',type=Path)
    p.add_argument('--analysis-sha256')
    p.add_argument('--workflow-store',type=Path,default=Path('var/m69-review/workflow.sqlite3'))
    p.add_argument('--asin',action='append',default=[])
    p.add_argument('--target',choices=STAGES[1:])
    p.add_argument('--evidence',type=Path)
    p.add_argument('--minimum-roi')
    p.add_argument('--minimum-profit')
    p.add_argument('--inventory-budget')
    args=p.parse_args(argv)
    journal=None
    try:
        now=datetime.now(timezone.utc)
        financial_args=(args.minimum_roi,args.minimum_profit,args.inventory_budget)
        if any(v is not None for v in financial_args) and (args.action!='advance' or args.target not in ('PROFITABILITY_REVIEWED','READY_FOR_HUMAN_DECISION')):
            raise ValueError('Financial targets apply only to explicit financial review transitions')
        if args.action=='analyze':
            if not args.output:raise ValueError('New immutable output directory required')
            as_of=datetime.fromisoformat(args.as_of.replace('Z','+00:00')) if args.as_of else now
            report,history=analyze(args.catalog,args.store,args.history_dir,args.m67_manifest,args.m67_sha256,
                as_of=as_of,maximum=args.maximum,max_per_brand=args.max_per_brand)
            result=export_analysis(report,history,args.output)
        else:
            if args.as_of:raise ValueError('Workflow checks always use current UTC, never a backdated analysis clock')
            pool,sources=combined(args.catalog)
            history=consolidate(args.history_dir,args.store,args.m67_manifest,args.m67_sha256,pool)
            if args.action=='register':
                if not args.analysis or not args.analysis_sha256 or len(args.asin)!=1:raise ValueError('Exact analysis and one ASIN required')
                report=load_analysis(args.analysis,args.analysis_sha256)
                if sorted(r['source_sha256'] for r in report['source_profiles'])!=sources:raise ValueError('Catalog source drift')
                expected,_=analyze(args.catalog,args.store,args.history_dir,args.m67_manifest,args.m67_sha256,
                    as_of=datetime.fromisoformat(report['as_of']),maximum=report['ranking']['requested_maximum'],
                    max_per_brand=report['ranking']['max_per_brand'])
                if fingerprint(report)!=fingerprint(expected):raise ValueError('Analysis content or history changed')
                journal=WorkflowStore(args.workflow_store,create=True)
                result=journal.register(report,args.asin[0],history,now)
            else:
                journal=WorkflowStore(args.workflow_store,read_only=args.action in ('status','manifest'))
                if args.action=='advance':
                    if len(args.asin)!=1 or not args.target or not args.evidence:raise ValueError('Explicit one-ASIN transition and review evidence required')
                    current=journal.current(args.asin[0])
                    if not current:raise ValueError('Registered workflow required')
                    saved=json.loads(journal.db.execute('SELECT payload FROM m69_reports WHERE id=?',(current['report_id'],)).fetchone()[0])
                    if saved['implementation_sha256']!=implementation() or sorted(r['source_sha256'] for r in saved['source_profiles'])!=sources:
                        raise ValueError('Frozen source/code drift')
                    evidence,_=read_json(args.evidence)
                    result=journal.advance(args.asin[0],args.target,history,evidence,now,
                        thresholds(*[v if v is not None else d for v,d in zip(financial_args,('50','5','500'))]))
                elif args.action=='manifest':
                    if not args.output:raise ValueError('New proposal path required')
                    proposal=journal.proposed_manifest(args.asin,history,now)
                    proposal['implementation_sha256']=implementation()
                    write_json(args.output,proposal)
                    result=dict(mode=proposal['mode'],proposed_count=len(proposal['asins']),manifest_sha256=sha256(args.output),execution_authorized=False)
                else:
                    if len(args.asin)!=1:raise ValueError('One ASIN required')
                    event=journal.current(args.asin[0]);result=event or dict(stage='NOT_REGISTERED')
        print(json.dumps(result,sort_keys=True));return 0
    except (Exception,KeyboardInterrupt):
        print('M69_BLOCKED_OFFLINE: missing evidence, drift, restriction, invalid transition or storage failure')
        return 2
    finally:
        if journal is not None:journal.db.close()


if __name__=='__main__':raise SystemExit(main())
