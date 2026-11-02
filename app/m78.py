"""M78 offline consolidation. Inputs must be explicitly supplied local copies."""
import argparse
import csv
from contextvars import ContextVar
from functools import wraps
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from app.m70_identity import FIELDS
from app.m70_sources import file_hash, ingest, source_manifest, strict_json
from app.m78_analysis import analyze
from app.m78_reporting import encoded, serialize, write

SENSITIVE = re.compile(r'credential|authorization|account.context|token|secret|\.env|(?:^|/)\.aws|(?:^|/)\.ssh', re.I)
EXPECTED = dict(distinct_catalog_asins=1397, catalog_identity_complete=236, conflict_asins=80,
                identity_complete=0, purchase_ready=0, excluded_catalog_records=41,
                historical_permanent_exclusions=97, historical_seller_checks=40,
                historical_excluded_in_catalog=41, historical_excluded_outside_catalog=56,
                m76_asins=777, m77_asins=620, overlap_asins=0)


def safe_path(path: Path):
    if SENSITIVE.search(str(path)) or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('Nonsymlink noncredential local paths required')


_root = Path(__file__).resolve().parent.parent
_code_files = frozenset(str(p) for p in (_root/'app').rglob('*.py')) | {str(_root/'ops/m78_offline.py')}


def implementation():
    root = Path(__file__).resolve().parent.parent
    paths = sorted((root/'app').rglob('*.py')) + [root/'ops/m78_offline.py']
    if any(p.is_symlink() or any(parent.is_symlink() for parent in p.parents) for p in paths):
        raise ValueError('Nonsymlink implementation required')
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


_active = ContextVar("m78_offline", default=False)
_installed = False
_reads = ContextVar("m78_reads", default=frozenset())
_created = ContextVar("m78_created", default=None)


def guard():
    """Process-lifetime defense in depth, NOT an OS network sandbox."""
    global _installed
    if _installed:
        return
    _installed = True
    def audit(event, args):
        if not _active.get():
            return
        if event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.spawn', 'os.posix_spawn', 'os.system', 'ctypes.dlopen', 'ctypes.dlsym')):
            raise PermissionError('M78 offline operation denied')
        if event in ('open', 'sqlite3.connect') and args and isinstance(args[0], (str, bytes, os.PathLike)):
            path = os.fsdecode(args[0])
            real = os.path.realpath(path)
            if real not in _code_files and (SENSITIVE.search(path) or SENSITIVE.search(real)):
                raise PermissionError('M78 private input access denied')
            writing = event == 'open' and len(args) > 2 and isinstance(args[2], int) and bool(args[2] & (os.O_WRONLY | os.O_RDWR))
            created = _created.get()
            if writing:
                if created is not None:
                    created.add(real)
            elif (real not in _reads.get() and real not in _code_files
                  and (created is None or real not in created)
                  and not (real.endswith(('.py', '.pyc', '.so')) and any(
                      Path(real).is_relative_to(p) for p in (sys.base_prefix, sys.prefix, str(_root/'app'))))):
                raise PermissionError('M78 undeclared input read denied')
    sys.addaudithook(audit)


def curated_csv(path: Path):
    # M76 export_csv escapes literal strings for spreadsheet safety. Decode once.
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if len(reader.fieldnames or []) != len(set(reader.fieldnames or [])):
            raise ValueError('Duplicate CSV headers')
        if not {'asin', *FIELDS, 'identity_conflicts', 'permanently_excluded'} <= set(reader.fieldnames or []):
            raise ValueError('Curated M76 catalog schema required')
        rows = []
        structured = {'cohorts', 'identity_conflicts', 'missing_fields', 'source_references', 'source_sha256',
                      'historical_m73_record', 'field_provenance', 'observed_alternatives', 'review_blocks', 'field_status'}
        boolean = {'permanently_excluded', 'previously_checked_seller_specific', 'identity_complete',
                   'catalog_identity_complete', 'identity_verified'}
        for row in reader:
            parsed = {}
            for key, value in row.items():
                if key is None or value is None:
                    raise ValueError('Malformed curated CSV')
                if value.startswith("'") and value[1:].lstrip().startswith(('=', '+', '-', '@')):
                    value = value[1:]
                if key in structured:
                    value = json.loads(value) if value else ({} if key in ('field_provenance', 'field_status', 'observed_alternatives') else [])
                elif key in boolean:
                    if value not in ('True', 'False'):
                        raise ValueError('Explicit curated boolean required')
                    value = value == 'True'
                elif key == 'pack_quantity':
                    value = int(value) if value else None
                elif value == '':
                    value = None
                parsed[key] = value
            rows.append(parsed)
            if len(rows) > 10000:
                raise ValueError('Catalog bound exceeded')
    return rows


def atomic_publish(stage: Path, output: Path, rename):
    # Linux renameat2(RENAME_NOREPLACE) closes the exists()/rename race.
    if rename(-100, os.fsencode(stage), -100, os.fsencode(output), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def offline(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        guard()
        token = _active.set(True)
        read_token = _reads.set(frozenset(str(Path(kwargs[n]).resolve()) for n in ('catalog', 'annotations', 'sources')))
        created_token = _created.set(set())
        try:
            return function(*args, **kwargs)
        finally:
            _created.reset(created_token)
            _reads.reset(read_token)
            _active.reset(token)
    return wrapped


@offline
def run(*, catalog: Path, annotations: Path, sources: Path, output: Path,
        verify_expected: bool = True, before_completion=lambda: None):
    inputs = [Path(p).absolute() for p in (catalog, annotations, sources)]
    output = Path(output).absolute()
    for p in inputs + [output]:
        safe_path(p)
    inputs = [p.resolve() for p in inputs]
    output = output.resolve()
    if not output.parent.is_dir() or output.exists():
        raise ValueError('Existing parent and fresh output required')
    initial_sources_hash = file_hash(inputs[2])
    declared = strict_json(inputs[2])
    if not isinstance(declared, dict) or not isinstance(declared.get('sources'), list) or not 1 <= len(declared['sources']) <= 100:
        raise ValueError('Bounded explicit saved page manifest required')
    allowed = set(_reads.get())
    for entry in declared['sources']:
        path = Path(entry['path'])
        path = path if path.is_absolute() else inputs[2].parent/path
        safe_path(path)
        allowed.add(str(path.resolve()))
    _reads.set(frozenset(allowed))
    entries, manifest_hash = source_manifest(inputs[2])
    if initial_sources_hash != manifest_hash:
        raise ValueError("Source manifest drift")
    if any(e['adapter'] != 'amazon_catalog_pages' for e in entries):
        raise ValueError('M77 saved pages only')
    queries = set()
    for entry in entries:
        if file_hash(entry['path']) != entry['sha256']:
            raise ValueError('Saved page drift')
        doc = strict_json(entry['path'])
        if doc.get('status') != 'COMPLETED_NO_REPLAY':
            raise ValueError('Completed immutable M77 saved pages required')
        for page in doc.get('pages', []):
            query = page.get('query_reference')
            if page.get('page_index') != 0 or page.get('page_token') is not None or not query or query in queries:
                raise ValueError('Unique first-page keyword searches required')
            queries.add(query)
    paths = inputs + [e['path'].resolve() for e in entries]
    for p in paths:
        safe_path(p)
        if output.is_relative_to(p.parent) or p.is_relative_to(output):
            raise ValueError('Output must be outside protected input directories')
    hashes = {str(p): file_hash(p) for p in sorted(set(paths))}
    if hashes[str(inputs[2])] != manifest_hash or any(hashes[str(e['path'].resolve())] != e['sha256'] for e in entries):
        raise ValueError('Saved page or source manifest drift')
    code = implementation()
    # Resolve libc symbol before installing the CLI guard; no later dynamic loads.
    rename = _rename
    rows = curated_csv(inputs[0])
    historical = strict_json(inputs[1])
    if not isinstance(historical, list):
        raise ValueError('M76 historical annotation list required')
    observations, coverage = ingest(inputs[2])
    if any(s['rejected'] for s in coverage['sources']):
        raise ValueError('All saved observations must normalize successfully')
    report = analyze(rows, observations, historical)
    report['source_coverage'] = coverage
    if verify_expected:
        if any(report['summary'][k] != v for k, v in EXPECTED.items()):
            raise ValueError('M76/M77 combined invariant mismatch')
        from collections import defaultdict
        from app.m70_identity import merge
        groups = defaultdict(list)
        for o in observations:
            groups[o['asin']].append(o)
        identities = [merge(g) for g in groups.values()]
        if (sum(bool(p['identity_conflicts']) for p in identities) != 31
                or sum(p['catalog_identity_complete'] for p in identities) != 125
                or sum(bool(p['identity_conflicts']) for p in rows) != 49
                or sum(p['catalog_identity_complete'] for p in rows) != 111
                or sum(p['permanently_excluded'] for p in rows) != 41
                or coverage['total_rows'] != 620 or sum(s['local_pages'] for s in coverage['sources']) != 31):
            raise ValueError('Individual M76/M77 invariant mismatch')
    stage = Path(tempfile.mkdtemp(prefix='.m78-stage-', dir=output.parent))
    _created.get().add(str(stage.resolve()))
    try:
        serialize(report, stage)
        before_completion()
        if {str(p): file_hash(p) for p in sorted(set(paths))} != hashes or implementation() != code:
            raise ValueError('Source or code drift')
        manifest = dict(schema=1, mode='M78_OFFLINE_ONLY', input_sha256=hashes,
                        implementation_sha256=code, execution_authorized=False,
                        output_sha256={p.name: file_hash(p) for p in sorted(stage.iterdir())})
        write(stage/'M78_manifest.json', encoded(manifest).encode())
        for p in stage.iterdir():
            with p.open('rb') as stream:
                os.fsync(stream.fileno())
        safe_path(output)
        safe_path(stage)
        if {str(p): file_hash(p) for p in sorted(set(paths))} != hashes or implementation() != code:
            raise ValueError('Source or code drift before publication')
        atomic_publish(stage, output, rename)
        return report['summary']
    finally:
        if stage.exists():
            shutil.rmtree(stage)


# This entry point is Linux-only and fails closed if atomic no-replace is unavailable.
_libc = ctypes.CDLL(None, use_errno=True)
_rename = _libc.renameat2
_rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
_rename.restype = ctypes.c_int


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ('catalog', 'annotations', 'sources', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(argv)
    guard()
    _active.set(True)
    try:
        print(json.dumps(run(**vars(args)), sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt):
        print('M78_BLOCKED_OFFLINE: invalid inputs, drift or unsafe output')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
