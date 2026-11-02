"""M76 deterministic offline catalog consolidation; M77 proposal only."""
import argparse
import json
import os
from pathlib import Path

from app.m65 import write_json
from app.m65_intelligence import sha256
from app.m69 import export_csv
from app.m70_sources import file_hash
from app.m73 import TABLES
from app.m74 import workbook_bytes
from app.m75_policy import implementation as prior_implementation
from app.m76_evidence import load, CHECKPOINT
from app.m76_analysis import analyze
from app.observations import fingerprint


def implementation():
    root=Path(__file__).parent
    return dict(prior_implementation(), **{p.name:sha256(p) for p in sorted(root.glob('*.py'))})


def write_bytes(path, content):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(content); stream.flush(); os.fsync(stream.fileno())


def export(report, output, hashes, code, unchanged):
    if output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError('New nonsymlink output required')
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    tables=dict(catalog=(TABLES['catalog']+['historical_m73_record','economics'],report['catalog']),
        identity_gaps=(TABLES['identity_quality'],report['catalog']),
        conflicts=(['asin','field','observed_values','field_provenance','resolution'],report['conflicts']))
    for name,rows in (('annotations',report['annotations']),('coverage',report['coverage']),
                      ('m77_queries',report['proposal']['queries']),('m77_scenarios',report['proposal']['scenarios'])):
        tables[name]=(list(rows[0]) if rows else ['asin'],rows)
    tables['summary']=(['metric','value'],[dict(metric=k,value=v) for k,v in report['summary'].items()])
    for name,(fields,rows) in tables.items(): export_csv(output/f'M76_{name}.csv',rows,fields)
    write_bytes(output/'M76_catalog_review.xlsx',workbook_bytes(tables))
    for name,value in (('report',report),('summary',report['summary']),('M77_proposal',report['proposal']),
                       ('identity_gaps_conflicts',dict(gaps=[dict(asin=p['asin'],missing_fields=p['missing_fields'])
                            for p in report['catalog']],conflicts=report['conflicts'])),('historical_annotations',report['annotations'])):
        write_json(output/f'M76_{name}.json',value)
    s=report['summary']
    text=(f"# M76 offline catalog consolidation\n\n{s['real_asins']} distinct real observed ASINs = "
          f"{s['baseline_asins']} M73 + {s['m75_distinct_new']} new M75. Remaining target: 223.\n\n"
          f"Identity complete: {s['identity_complete']}; catalog structurally complete: {s['catalog_identity_complete']}; "
          f"unresolved conflict ASINs: {s['conflict_asins']}. Missing fields: {json.dumps(s['missing_fields'],sort_keys=True)}.\n\n"
          "97 permanent exclusions and 40 historical seller checks remain separate annotations. "
          "These are observed catalog records; purchase-ready inventory is zero. Eligibility and economics remain unknown.\n\n"
          "M75 consumed 21 historical requests and completed 20 keyword pages with 400 new distinct ASINs. "
          "M76 made zero requests and read no credentials. The M75 checkpoint is the terminal registry event-chain digest, "
          f"{CHECKPOINT}, not the database file hash.\n\n"
          "M77 proposes 23 unused first-page queries (460 hypothetical slots). At an assumed 50% duplicate rate "
          "this projects 230 incremental ASINs against a target of 223. Yield is not guaranteed. "
          "Ranking favors intents without M75 pages, then original reviewed order; prior observed yield was 20 new ASINs/page. "
          "No executor or authorization artifact is created. See scenario and coverage tables for assumptions.\n")
    write_bytes(output/'M76_executive_summary.md',text.encode())
    unchanged()
    if implementation()!=code: raise ValueError('Implementation drift')
    manifest=dict(schema=1,mode='M76_COMPLETED_OFFLINE_CONSOLIDATION',checkpoint_sha256=CHECKPOINT,
        input_sha256=hashes,implementation_sha256=code,execution_authorized=False,
        report_sha256=fingerprint(report),output_sha256={p.name:file_hash(p) for p in sorted(output.iterdir())})
    write_json(output/'M76_evidence_manifest.json',manifest)
    digest=file_hash(output/'M76_evidence_manifest.json')
    write_bytes(output/'M76_digest_report.txt',('M76_evidence_manifest.json  '+digest+'\n'+
        ''.join(f'{name}  {value}\n' for name,value in manifest['output_sha256'].items())).encode())
    return dict(s,evidence_manifest_sha256=digest,digest_report_sha256=file_hash(output/'M76_digest_report.txt'))


def run(output: Path,m74_dir: Path,**kwargs):
    protected=[kwargs[n] for n in ('m73_dir','baseline_dir','private')]+[kwargs['sources'].parent,m74_dir]
    if any(output.resolve().is_relative_to(p.resolve()) for p in protected):
        raise ValueError('Output must be outside historical evidence')
    code=implementation()
    prior,observations,pages,manifest,hashes,coverage,unchanged=load(m74_dir,**kwargs)
    report=analyze(prior,observations,pages,manifest,hashes['m73:M73_report.json'])
    report['source_coverage']=dict(m73=prior['source_coverage'],m75=coverage)
    unchanged()
    return export(report,output,hashes,code,unchanged)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    for name in ('m74-dir','m73-dir','baseline-dir','proposal','private','sources','summary','store','m67-manifest','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    for name in ('m73-digests-sha256','baseline-report-sha256','checkpoint','m67-sha256'):
        parser.add_argument('--'+name,required=True)
    try:
        result=run(**vars(parser.parse_args(argv)))
        print(json.dumps(result,sort_keys=True)); return 0
    except (Exception,KeyboardInterrupt):
        print('M76_BLOCKED_OFFLINE: invalid evidence, counts, hash, source drift or output'); return 2


if __name__=='__main__': raise SystemExit(main())
