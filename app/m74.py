"""M74 offline discovery planning only. No live execution or authorization action."""
import argparse
from datetime import datetime
from io import BytesIO
import json
import os
from pathlib import Path
import zipfile

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from app.m65 import write_json
from app.m69 import export_csv
from app.m70_sources import file_hash
from app.m71_manifest import implementation as prior_implementation
from app.m73 import cell
from app.m74_evidence import verify
from app.m74_plan import build
from app.observations import fingerprint

TABLES = {
    'queries': ['review_order','query_id','origin','evidence_class','keywords','category_intent','rationale',
                'definition_sha256','traceability','lexical_overlap_with_executed','future_asin_overlap',
                'marketplace_demand','uniqueness_probability','execution_authorized'],
    'coverage': ['query_id','keywords','category_intent','request_slot','returned_observations','distinct_asins',
                 'within_page_duplicates','baseline_overlap','conflict_asins','brand_counts','category_counts',
                 'has_unfollowed_cursor','source_sha256','response_sha256','evidence_class'],
    'overlap': ['query_a','query_b','shared_asins','union_asins','shared_brand_labels','shared_category_labels','jaccard','evidence_class'],
    'intent_gaps': ['category_intent','completed_m72_pages','observed_m72_distinct_asins',
                    'unexecuted_frozen_queries','status','limitation','evidence_class'],
    'diversity': ['dimension','value','asin_count','evidence_class'],
    'budgets': ['duplicate_percent','remaining_unique_target','result_slots','keyword_pages',
                'single_operation_authentication','single_operation_request_ceiling',
                'twenty_page_operation_count','twenty_page_authentication','twenty_page_total_request_ceiling',
                'planned_first_page_capacity','extra_query_definitions_required','m75_request_ceiling',
                'm75_maximum_raw_result_slots','m75_can_reach_remaining_target_at_zero_duplicates',
                'assumption','monetary_cost','execution_authorized','evidence_class'],
    'exclusions': ['asin','permanently_excluded','previously_checked_seller_specific','in_combined_catalog'],
    'conflicts': ['asin','conflict_fields','cohorts'],
}


def implementation() -> dict:
    root = Path(__file__).parent
    names = ('m74.py','m74_evidence.py','m74_plan.py','m73.py','m73_evidence.py','m73_analysis.py',
             'm72_policy.py','m72_registry.py','m67_state.py')
    return dict(prior_implementation(), **{n:file_hash(root/n) for n in names})


def validate(report: dict) -> None:
    manifest = report['manifest']; content = dict(manifest); digest = content.pop('manifest_sha256')
    if digest != fingerprint(content) or manifest['execution_authorized'] is not False or manifest['live_enabled'] is not False:
        raise ValueError('Hash-bound offline-only proposal required')
    queries = manifest['queries']; executed = set(manifest['executed_query_ids'])
    if (len({q['query_id'] for q in queries}) != len(queries)
            or executed & {q['query_id'] for q in queries}
            or any(q['execution_authorized'] is not False for q in queries)
            or any(set(q['request_parameters']) != {'marketplaceIds','includedData','pageSize','keywords'} for q in queries)):
        raise ValueError('Distinct unexecuted first-page candidates required')
    contract = report['contract']
    from app.m74_plan import BUDGET, OPERATION, parameters
    if (contract['execution_authorized'] is not False or contract['live_enabled'] is not False
            or contract['operation_id'] != OPERATION or contract['budget'] != BUDGET
            or manifest['proposed_m75_budget'] != BUDGET
            or any(type(v) is not int for v in contract['budget'].values())
            or contract['m74_manifest_sha256'] != digest
            or manifest['proposed_m75_query_ids'] != [q['query_id'] for q in queries[:20]]
            or len(contract['keyword_requests']) != 20):
        raise ValueError('Separate bounded M75 proposal required')
    from app.m71_manifest import HOST, PATH
    for slot,(request,query) in enumerate(zip(contract['keyword_requests'],queries),2):
        expected = dict(slot=slot,query_id=query['query_id'],method='GET',host=HOST,path=PATH,
                        parameters=parameters(query['keywords']))
        if request != expected or query['request_parameters'] != expected['parameters']:
            raise ValueError('Exact future request allowlist required')


def workbook_bytes(tables: dict) -> bytes:
    workbook = Workbook(); workbook.remove(workbook.active)
    fixed = datetime(2000,1,1)
    workbook.properties.created = fixed; workbook.properties.modified = fixed
    for name,(fields,rows) in tables.items():
        sheet = workbook.create_sheet(name); sheet.append(fields)
        for row in rows: sheet.append([cell(row.get(f)) for f in fields])
        sheet.freeze_panes='A2'; sheet.auto_filter.ref=sheet.dimensions
        for column in sheet.columns: sheet.column_dimensions[column[0].column_letter].width=28
        for header in sheet[1]:
            header.font=Font(color='FFFFFF',bold=True); header.fill=PatternFill('solid',fgColor='24445C')
    from openpyxl.writer.excel import ExcelWriter
    raw=BytesIO()
    ExcelWriter(workbook,zipfile.ZipFile(raw,'w',zipfile.ZIP_DEFLATED)).save()
    # Normalize ZIP metadata too: equal inputs produce byte-identical workbooks.
    result=BytesIO()
    with zipfile.ZipFile(raw) as source, zipfile.ZipFile(result,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as target:
        for name in sorted(source.namelist()):
            info=zipfile.ZipInfo(name,date_time=(2000,1,1,0,0,0)); info.compress_type=zipfile.ZIP_DEFLATED
            info.create_system=3; info.external_attr=0o600<<16
            target.writestr(info,source.read(name))
    return result.getvalue()


def export(report: dict, output: Path, hashes: dict, code: dict, unchanged) -> dict:
    validate(report)
    if output.is_symlink() or any(p.is_symlink() for p in output.parents): raise ValueError('Nonsymlink output required')
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    tables = dict(summary=(['metric','value'],[dict(metric=k,value=v) for k,v in report['summary'].items()]),
        queries=(TABLES['queries'],report['manifest']['queries']), coverage=(TABLES['coverage'],report['coverage']),
        overlap=(TABLES['overlap'],report['overlaps']), intent_gaps=(TABLES['intent_gaps'],report['gaps']),
        diversity=(TABLES['diversity'],report['diversity']),budgets=(TABLES['budgets'],report['scenarios']),
        exclusions=(TABLES['exclusions'],report['historical']['exclusions']),
        conflicts=(TABLES['conflicts'],report['historical']['conflict_summary']),
        m75_contract=(['requirement','proposal'],[dict(requirement=k,proposal=v) for k,v in report['contract'].items()]))
    for name,(fields,rows) in tables.items(): export_csv(output/f'M74_{name}.csv',rows,fields)
    fd=os.open(output/'M74_discovery_plan.xlsx',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(workbook_bytes(tables)); stream.flush(); os.fsync(stream.fileno())
    for name,data in (('query_manifest',report['manifest']),('M75_contract_proposal',report['contract']),
                      ('executive_summary',report['summary']),('budget_scenarios',report['scenarios']),
                      ('history_summary',report['historical']),('coverage_overlap',dict(coverage=report['coverage'],
                           overlaps=report['overlaps'],gaps=report['gaps'])),('planning_report',report)):
        write_json(output/f'M74_{name}.json',data)
    unchanged()
    if implementation()!=code: raise ValueError('Implementation changed during planning')
    write_json(output/'M74_evidence_digests.json',dict(schema=1,mode='M74_COMPLETED_OFFLINE_PLAN',
        execution_authorized=False, input_sha256=hashes,implementation_sha256=code,
        manifest_sha256=report['manifest']['manifest_sha256'],
        output_sha256={p.name:file_hash(p) for p in sorted(output.iterdir())}))
    return dict(report['summary'],manifest_sha256=report['manifest']['manifest_sha256'],
                completion_file_sha256=file_hash(output/'M74_evidence_digests.json'))


def run(output: Path, **kwargs) -> dict:
    protected = [kwargs[name] for name in ('m73_dir','baseline_dir','private')]+[kwargs['sources'].parent]
    if any(output.resolve().is_relative_to(p.resolve()) for p in protected):
        raise ValueError('Reports outside original evidence directories required')
    code=implementation()
    report,evidence,frozen,account_binding,hashes,unchanged=verify(**kwargs)
    plan=build(report,evidence,frozen,account_binding,hashes,code)
    unchanged()
    return export(plan,output,hashes,code,unchanged)


class Parser(argparse.ArgumentParser):
    def error(self,message): self.exit(2,'M74_BLOCKED_OFFLINE: invalid arguments\n')


def main(argv=None) -> int:
    parser=Parser(description=__doc__,allow_abbrev=False)
    parser.add_argument('action',choices=('plan',))
    for name in ('m73-dir','baseline-dir','proposal','private','sources','summary','store','m67-manifest','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    for name in ('m73-digests-sha256','baseline-report-sha256','checkpoint','m67-sha256'):
        parser.add_argument('--'+name,required=True)
    args=vars(parser.parse_args(argv)); args.pop('action')
    try:
        print(json.dumps(run(**args),sort_keys=True)); return 0
    except (Exception,KeyboardInterrupt):
        print('M74_BLOCKED_OFFLINE: invalid immutable evidence, planning contract or private output'); return 2


if __name__=='__main__': raise SystemExit(main())
