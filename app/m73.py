"""M73 offline consolidation of the original M70 baseline and completed M72 pilot."""
import argparse
import json
import os
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from app.m65 import write_json
from app.m69 import export_csv
from app.m70_identity import FIELDS
from app.m70_sources import file_hash, source_manifest
from app.m72_policy import REGISTRY
from app.m73_evidence import load
from app.m73_analysis import analyze
from app.observations import canonical


TABLES = {
    'catalog': ['asin', *FIELDS, 'cohorts', 'permanently_excluded', 'previously_checked_seller_specific',
                'identity_complete', 'catalog_identity_complete', 'identity_verified', 'eligibility',
                'missing_fields', 'identity_conflicts', 'source_references', 'source_sha256', 'identity_sha256'],
    'identity_quality': ['asin', 'missing_fields', 'identity_conflicts', 'field_status', 'observed_alternatives',
                         'field_provenance', 'baseline_field_provenance', 'baseline_source_references',
                         'baseline_unsupported_observations', 'baseline_source_classes', 'identity_confidence_percent'],
    'conflicts': ['cohort', 'asin', 'field', 'observed_values', 'resolution', 'investigation', 'next_action',
                 'source_references', 'field_provenance', 'conflict_kind', 'raw_catalog_evidence'],
    'ranking': ['review_position', 'asin', 'brand', 'title', 'category', 'observed_field_score',
                'research_reviewable', 'blockers', 'missing_fields', 'identity_complete', 'eligibility',
                'purchase_authorized', 'source_references'],
    'diversity': ['dimension', 'value', 'asin_count'],
    'exclusions': ['asin', 'permanently_excluded', 'previously_checked_seller_specific', 'in_combined_catalog'],
    'scenarios': ['duplicate_rate_percent', 'additional_result_slots', 'minimum_full_20_item_pages', 'assumption'],
}


def cell(value):
    if isinstance(value, (dict, list)): value = canonical(value)
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')): value = "'" + value
    # openpyxl silently truncates long cells; fail rather than publish lost evidence.
    if isinstance(value, str) and len(value) > 32767: raise ValueError('Excel evidence cell exceeds bound')
    return value


def export(report: dict, output: Path, before_publish=lambda: None) -> dict:
    if output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError('New nonsymlink private output required')
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    workbook = Workbook(); workbook.remove(workbook.active)
    tables = dict(summary=[dict(metric=k, value=v) for k,v in report['summary'].items()],
                  audit=[dict(input=k, sha256=v) for k,v in report['input_sha256'].items()],
                  **{k: report['catalog'] if k == 'identity_quality' else report[k] for k in TABLES})
    for name, rows in tables.items():
        fields = ['metric','value'] if name == 'summary' else ['input','sha256'] if name == 'audit' else TABLES[name]
        export_csv(output/f'M73_{name}.csv', rows, fields)
        sheet = workbook.create_sheet(name)
        sheet.append(fields)
        for row in rows: sheet.append([cell(row.get(f)) for f in fields])
        sheet.freeze_panes = 'A2'; sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(65, max(16, len(str(column[0].value))+2))
        for header in sheet[1]:
            header.font = Font(color='FFFFFF', bold=True); header.fill = PatternFill('solid', fgColor='24445C')
    fd = os.open(output/'M73_review.xlsx', os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd,'wb') as stream:
        workbook.save(stream); stream.flush(); os.fsync(stream.fileno())
    write_json(output/'M73_report.json', report)
    write_json(output/'M73_summary.json', report['summary'])
    before_publish()
    write_json(output/'M73_output_digests.json', {p.name: file_hash(p) for p in sorted(output.iterdir())})
    return report['summary']


def run(baseline_dir: Path, baseline_report_sha256: str, proposal: Path, private: Path,
        checkpoint: str, sources: Path, summary: Path, store: Path, m67_manifest: Path,
        m67_sha256: str, output: Path) -> dict:
    output_resolved = output.resolve()
    if any(output_resolved.is_relative_to(p.resolve()) for p in (private, baseline_dir, sources.parent)):
        raise ValueError('Reports must be outside original evidence directories')
    entries, _ = source_manifest(sources)
    inputs = dict(baseline=baseline_dir/'M70_catalog_1000.csv', baseline_report=baseline_dir/'M70_report.json',
                  proposal=proposal, registry=private/REGISTRY, m72_sources=sources, m72_summary=summary,
                  m72_pages=entries[0]['path'], store=store, m67_manifest=m67_manifest)
    from app.m72_policy import history_files
    before = {k: file_hash(p) for k,p in inputs.items()}
    before['historical_inventory'] = history_files(private, store, m67_manifest)
    evidence = load(inputs['baseline'], inputs['baseline_report'], baseline_report_sha256, proposal,
                    inputs['registry'], checkpoint, sources, summary, store, private, m67_manifest, m67_sha256)
    report = analyze(evidence)
    report['input_sha256'] = before
    report['summary']['count_reconciliation'] = 'baseline + M72 distinct - cross-cohort duplicates'
    def unchanged():
        current = {k:file_hash(p) for k,p in inputs.items()}
        current['historical_inventory'] = history_files(private, store, m67_manifest)
        if current != before: raise ValueError('Input changed during consolidation')
    unchanged()
    return export(report, output, before_publish=unchanged)


class Parser(argparse.ArgumentParser):
    def error(self, message): self.exit(2, 'M73_BLOCKED_OFFLINE: invalid arguments\n')


def main(argv=None) -> int:
    parser = Parser(description=__doc__)
    for name in ('baseline-dir','proposal','private','sources','summary','store','m67-manifest','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    for name in ('baseline-report-sha256','checkpoint','m67-sha256'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args(argv)
    try:
        result = run(**vars(args))
        print(json.dumps(result, sort_keys=True)); return 0
    except (Exception, KeyboardInterrupt):
        print('M73_BLOCKED_OFFLINE: invalid completed evidence, source drift, history, identity or private output'); return 2


if __name__ == '__main__': raise SystemExit(main())
