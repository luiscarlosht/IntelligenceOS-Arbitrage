"""M70 offline catalog enrichment and non-executable API budget planning."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

from app.m65 import write_json
from app.m69 import export_csv
from app.m70_discovery import build
from app.m70_plan import plan
from app.m70_identity import FIELDS


class PrivateParser(argparse.ArgumentParser):
    def error(self,message):self.exit(2,'M70_BLOCKED_OFFLINE: invalid arguments\n')


def export(report: dict,output: Path) -> dict:
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    fields=['asin',*FIELDS,'upc_values','observed_at','last_observed_at','identity_complete','catalog_identity_complete',
        'identity_verified','identity_confidence_percent','missing_fields','identity_conflicts','field_status',
        'source_references','source_sha256','eligibility','fba_state','permanently_excluded','retailer_match_status']
    export_csv(output/'M70_catalog_1000.csv',report['catalog'],fields)
    quality=['asin','identity_complete','catalog_identity_complete','m69_core_complete','identity_confidence_percent',
        'identity_verified','missing_fields','identity_conflicts','unsupported_observations','field_status','field_provenance',
        'observed_alternatives','review_blocks','source_references']
    export_csv(output/'M70_identity_quality.csv',report['catalog'],quality)
    selected=[r for r in report['ranking'] if r['selected']]
    export_csv(output/'M70_candidate_ranking.csv',selected,['asin','brand','title','category','score','selection_score',
        'score_components','eligibility','identity_verified','identity_complete','identity_confidence_percent',
        'identity_conflicts','condition_compatibility','brand_history','category_history','source_references','retailer_match_status'])
    export_csv(output/'M70_exclusions.csv',[dict(asin=a,permanently_excluded=True) for a in report['history']['excluded_asins']],['asin','permanently_excluded'])
    write_json(output/'M70_source_coverage.json',report['source_coverage'])
    write_json(output/'M70_summary.json',report['summary'])
    write_json(output/'M70_report.json',report)
    return report['summary']


def main(argv=None) -> int:
    p=PrivateParser(description=__doc__)
    p.add_argument('action',choices=('analyze','plan'))
    p.add_argument('--sources',type=Path)
    p.add_argument('--store',type=Path)
    p.add_argument('--history-dir',type=Path,default=Path.home()/'.intelligenceos-arbitrage-amazon')
    p.add_argument('--m67-manifest',type=Path)
    p.add_argument('--m67-sha256')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--as-of')
    p.add_argument('--shortlist',type=int,default=150)
    p.add_argument('--max-per-brand',type=int,default=10)
    p.add_argument('--local-page-size',type=int,default=200)
    p.add_argument('--maximum-observations',type=int,default=100000)
    p.add_argument('--maximum-asins',type=int,default=10000)
    p.add_argument('--target',type=int,default=1000)
    p.add_argument('--query-slots',type=int,default=50)
    p.add_argument('--pages-per-query',type=int,default=4)
    p.add_argument('--page-size',type=int,default=20)
    p.add_argument('--keyword-budget',type=int,default=200)
    p.add_argument('--identifier-budget',type=int,default=50)
    p.add_argument('--detail-budget',type=int,default=0)
    p.add_argument('--maximum-requests',type=int,default=251)
    args=p.parse_args(argv)
    try:
        if args.output.absolute().is_relative_to(args.history_dir.absolute()):raise ValueError('Reports cannot be written among protected execution evidence')
        if args.action=='plan':
            result=plan(target=args.target,query_slots=args.query_slots,pages_per_query=args.pages_per_query,page_size=args.page_size,
                keyword_budget=args.keyword_budget,identifier_budget=args.identifier_budget,detail_budget=args.detail_budget,
                maximum_requests=args.maximum_requests)
            write_json(args.output,result)
            print(json.dumps(dict(mode=result['mode'],budget=result['budget'],executable=False,actual_requests=0),sort_keys=True))
        else:
            if not all((args.sources,args.store,args.m67_manifest,args.m67_sha256)):raise ValueError('Source manifest and original immutable history inputs required')
            now=datetime.fromisoformat(args.as_of.replace('Z','+00:00')) if args.as_of else datetime.now(timezone.utc)
            result=build(args.sources,args.store,args.history_dir,args.m67_manifest,args.m67_sha256,as_of=now,
                shortlist=args.shortlist,max_per_brand=args.max_per_brand,page_size=args.local_page_size,
                maximum_observations=args.maximum_observations,maximum_asins=args.maximum_asins)
            print(json.dumps(export(result,args.output),sort_keys=True))
        return 0
    except (Exception,KeyboardInterrupt):
        print('M70_BLOCKED_OFFLINE: missing evidence, invalid source, history drift, import bound or planning budget failure')
        return 2


if __name__=='__main__':raise SystemExit(main())
