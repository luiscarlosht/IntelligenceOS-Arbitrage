"""M79 credential-free offline inspection of original M76/M77 exports; no executor."""
import argparse
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from io import BytesIO
import json
import hashlib
import os
from pathlib import Path
import re
import sys
import zipfile

from openpyxl import Workbook
from openpyxl.writer.excel import ExcelWriter
from openpyxl.worksheet._writer import WorksheetWriter
from app.m70_sources import file_hash, ingest, strict_json
from app.m78_analysis import analyze as consolidate_catalog
from app.m78_reporting import cell, encoded, write
from app.m79_analysis import analyze

M76_PIN = '0e8c1840d7f9860c36422baa5d828bfc9d29493bac77d2c80af71daf0b67577b'
ACTIVE = ContextVar('m79_offline', default=False)
INSTALLED = False
WRITES = ContextVar('m79_output', default=None)
SENSITIVE = re.compile(r'credential|authorization|account.context|token|secret|\.env|\.aws|\.ssh', re.I)


@contextmanager
def offline(output=None):
    global INSTALLED
    if not INSTALLED:
        def audit(event, args):
            if not ACTIVE.get(): return
            if event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.spawn', 'os.posix_spawn', 'os.system', 'ctypes.')) or event == 'sqlite3.connect':
                raise PermissionError('M79 offline operation denied')
            if event in ('open', 'os.mkdir', 'os.remove', 'os.rename', 'os.symlink', 'os.link') and args and isinstance(args[0], (str, bytes, os.PathLike)):
                writing = event != 'open' or len(args) > 2 and isinstance(args[2], int) and bool(args[2] & (os.O_WRONLY | os.O_RDWR))
                if writing:
                    path = Path(os.fsdecode(args[0])).resolve()
                    allowed = WRITES.get()
                    if allowed is None or not path.is_relative_to(allowed):
                        raise PermissionError('M79 writes outside new report directory denied')
            if event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(args[0])).resolve()
                is_code = path.suffix == '.py' and path.is_relative_to(Path(__file__).resolve().parent)
                if SENSITIVE.search(str(path)) and not is_code:
                    raise PermissionError('M79 credential/owner artifact access denied')
        sys.addaudithook(audit)
        INSTALLED = True
    token = ACTIVE.set(True)
    write_token = WRITES.set(Path(output).resolve() if output else None)
    try: yield
    finally:
        WRITES.reset(write_token)
        ACTIVE.reset(token)


def safe(path):
    if SENSITIVE.search(str(path)) or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('Explicit nonsymlink noncredential paths required')


def load(m76, m77, baseline):
    for root in (m76, m77):
        safe(root)
    safe(baseline)
    paths = [m76 / 'M76_evidence_manifest.json', baseline]
    if file_hash(paths[0]) != M76_PIN:
        raise ValueError('Original independently pinned M76 manifest required')
    manifest = strict_json(paths[0])
    expected_hashes = {str(paths[0].resolve()): M76_PIN}
    for name, sha in manifest['output_sha256'].items():
        if Path(name).name != name:
            raise ValueError('Flat M76 export inventory required')
        path = m76 / name
        if file_hash(path) != sha:
            raise ValueError('M76 export hash mismatch')
        paths.append(path)
        expected_hashes[str(path.resolve())] = sha
    expected_hashes[str(baseline.resolve())] = manifest['input_sha256']['baseline_report']
    if file_hash(baseline) != manifest['input_sha256']['baseline_report']:
        raise ValueError('Original pinned upstream history required')
    paths.append(m77 / 'M77_output_digests.json')
    expected_hashes[str(paths[-1].resolve())] = file_hash(paths[-1])
    digests = strict_json(paths[-1])
    if set(digests) != {'M77_catalog_pages.json', 'M77_M70_sources.json', 'M77_summary.json'}:
        raise ValueError('Complete original M77 output inventory required')
    for name, sha in digests.items():
        path = m77 / name
        if file_hash(path) != sha:
            raise ValueError('M77 export hash mismatch')
        paths.append(path)
        expected_hashes[str(path.resolve())] = sha
    sources = strict_json(m77 / 'M77_M70_sources.json')
    entries = sources.get('sources', [])
    if (len(entries) != 1 or entries[0].get('path') != 'M77_catalog_pages.json'
            or entries[0].get('adapter') != 'amazon_catalog_pages'):
        raise ValueError('Original local M77 saved-page reference required')
    pages = strict_json(m77 / 'M77_catalog_pages.json')
    summary = strict_json(m77 / 'M77_summary.json')
    if (pages.get('status') != 'COMPLETED_NO_REPLAY' or summary.get('status') != 'COMPLETED_NO_REPLAY'
            or summary.get('uncertain_slots') or summary.get('requests_consumed') != 32
            or len(pages['pages']) != 31 or len({p['query_reference'] for p in pages['pages']}) != 31
            or any(p.get('page_index') != 0 or p.get('page_token') is not None for p in pages['pages'])):
        raise ValueError('Completed original 31-page M77 export required; never replay')
    # Do not silently discard unexpected sales datasets in a future export.
    if any(set(item) & {'salesRanks', 'offers', 'prices', 'buyBox'} for p in pages['pages'] for item in p['items']):
        raise ValueError('Additional sales evidence needs a reviewed typed adapter')
    before = {str(p.resolve()): file_hash(p) for p in sorted(set(paths))}
    if before != expected_hashes:
        raise ValueError('Input changed after validation')
    m76_report = strict_json(m76 / 'M76_report.json')
    observations, coverage = ingest(m77 / 'M77_M70_sources.json')
    if coverage['accepted_observations'] != 620 or any(p['rejected'] for p in coverage['sources']):
        raise ValueError('All 620 original observations required')
    combined = consolidate_catalog(m76_report['catalog'], observations, m76_report['annotations'])
    expected = {'distinct_catalog_asins': 1397, 'm76_asins': 777, 'm77_asins': 620,
                'overlap_asins': 0, 'conflict_asins': 80, 'excluded_catalog_records': 41}
    if any(combined['summary'][key] != value for key,value in expected.items()):
        raise ValueError('Original M76/M77 union invariants required')
    return combined['catalog'], strict_json(baseline)['history'], pages['pages'], digests['M77_catalog_pages.json'], before


def handoff(row):
    result = {key: row[key] for key in ('asin', 'marketplace', 'gtin', 'upc_values', 'brand', 'model', 'title',
        'pack_quantity', 'size', 'variation', 'amazon_price', 'eligibility', 'bsr', 'offer_count', 'buy_box',
        'price_stability', 'research_position', 'identity_conflicts', 'permanently_excluded',
        'field_provenance', 'field_status', 'identity_verified', 'source_references', 'source_sha256', 'sourcing_allowed', 'purchase_authorized')}
    result['quantity'] = row['pack_quantity']
    result['quantity_basis'] = 'CATALOG_PACKAGE_QUANTITY' if row['pack_quantity'] != 'UNKNOWN' else 'UNKNOWN'
    result['amazon_price_currency'] = 'UNKNOWN'
    return result


class MemoryExcelWriter(ExcelWriter):
    """Tabular reports only: keep worksheet XML in memory, not global /tmp."""
    def write_worksheet(self, sheet):
        sheet._drawing = None
        writer = WorksheetWriter(sheet, out=BytesIO())
        writer.write()
        sheet._rels = writer._rels
        self._archive.writestr(sheet.path[1:], writer.read())
        self.manifest.append(sheet)


def export(report, output):
    wb = Workbook()
    wb.remove(wb.active)
    tables = {'All_ASINs': report['catalog'], 'Coverage': report['coverage'],
        'Demand_Top100': report['top100'], 'Demand_Top20': report['top20'],
        'Research_Top100': report['research100'], 'Research_Top20': report['research20'],
        'Category_Coverage': report['categories'],
        'Method': [dict(metric=k, interpretation=v) for k,v in report['method'].items()],
        'Provenance': [dict(path=k, sha256=v) for k,v in report['input_sha256'].items()]}
    wb.properties.created = wb.properties.modified = datetime(2000, 1, 1)
    for name, rows in tables.items():
        sheet = wb.create_sheet(name)
        fields = sorted({k for row in rows for k in row}) or ['status']
        sheet.append(fields)
        if not rows:
            sheet.append(['NO QUALIFIED PRODUCTS: demand/eligibility evidence missing'])
        for row in rows:
            sheet.append([cell(row.get(f, 'UNKNOWN')) for f in fields])
        sheet.freeze_panes = 'B2'
        sheet.auto_filter.ref = sheet.dimensions
    raw = BytesIO()
    MemoryExcelWriter(wb, zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED)).save()
    result = BytesIO()
    with zipfile.ZipFile(raw) as src, zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(src.namelist()):
            info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            info.create_system = 3
            dst.writestr(info, src.read(name))
    write(output / 'M79_amazon_intelligence.xlsx', result.getvalue())
    write(output / 'M79_report.json', encoded(report).encode())
    machine = dict(schema=1, ready_for_walmart_sourcing=False, purchase_authorized=False,
        status='BLOCKED_AMAZON_DEMAND_AND_ELIGIBILITY_UNKNOWN', approved_shortlist=[],
        research_queue_purpose='AMAZON_METRIC_ACQUISITION_ONLY_NOT_WALMART_SOURCING',
        research_queue=[handoff(r) for r in report['research100']],
        priority20=[handoff(r) for r in report['research20']],
        all_asins=[handoff(r) for r in report['catalog']], input_sha256=report['input_sha256'])
    write(output / 'M79_walmart_handoff.json', encoded(machine).encode())
    text = '# M79 offline findings\n\n' + json.dumps(report['summary'], indent=2) + '\n\n'
    text += 'No supported demand shortlist can be produced. Research sheets order identity coverage only.\n'
    text += 'Catalog list prices are not Amazon offer prices. BSR-to-sales conversion is not fitted.\n'
    text += 'New Amazon calls require separate explicit authorization; see docs/M79_AMAZON_SALES_INTELLIGENCE.md.\n'
    write(output / 'M79_findings.md', text.encode())


def run(*, m76_dir, m77_dir, baseline_report, output, as_of):
    roots = [Path(p).absolute() for p in (m76_dir, m77_dir, baseline_report)]
    output = Path(output).absolute()
    for path in roots + [output]: safe(path)
    roots = [p.resolve() for p in roots]
    output = output.resolve()
    if (output.exists() or not output.parent.is_dir() or output.is_relative_to('/mnt')
            or any(output.is_relative_to(p if p.is_dir() else p.parent) or p.is_relative_to(output) for p in roots)):
        raise ValueError('Fresh local output outside all historical inputs required; never write /mnt')
    with offline(output):
        code_paths = sorted(Path(__file__).parent.rglob('*.py'))
        if any(p.is_symlink() for p in code_paths):
            raise ValueError('Nonsymlink implementation required')
        code = {str(p.relative_to(Path(__file__).parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths}
        catalog, history, pages, digest, before = load(*roots)
        report = analyze(catalog, history, pages, digest, as_of)
        report['input_sha256'] = before
        report['implementation_sha256'] = code
        output.mkdir(mode=0o700)
        export(report, output)
        if ({path: file_hash(Path(path)) for path in before} != before
                or {str(p.relative_to(Path(__file__).parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths} != code):
            raise ValueError('Historical input drift; no completion manifest published')
        write(output / 'M79_completion.json', encoded(dict(input_sha256=before,
            implementation_sha256=report['implementation_sha256'], output_sha256={p.name:file_hash(p) for p in output.iterdir()},
            actual_requests=0, ready_for_walmart_sourcing=False)).encode())
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ('m76-dir', 'm77-dir', 'baseline-report', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--as-of', required=True)
    args = parser.parse_args(argv)
    when = datetime.fromisoformat(args.as_of.replace('Z', '+00:00'))
    result = run(m76_dir=args.m76_dir, m77_dir=args.m77_dir, baseline_report=args.baseline_report,
                 output=args.output, as_of=when)
    print(json.dumps(result['summary'], sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
