"""Offline stored-row binding and explicit catalog-only variable-batch execution."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
from urllib.parse import urlsplit

from app import amazon_candidates as stage, amazon_pilot as pilot
from app.amazon_catalog import AmazonCatalogListing, CatalogIdentifier, CatalogRelationship
from app.normalization import timestamp
from app.observations import canonical, fingerprint, normalized
from app.provider_contracts import Evidence
from app.sheets_candidate_plan import audit_database, read_json, MARKETPLACE
from app.source_keywords import search_keywords

MODE = 'stored_candidate_search'
DETAIL_DATA = 'summaries,identifiers,relationships,attributes'
REPORT_PATTERNS = ('candidates-*.json', 'candidate-details-*.json')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


from app.catalog_saved_evidence import saved_evidence


def prepare(plan_path: Path, private_path: Path = pilot.DIRECTORY) -> tuple[dict, tuple]:
    """Convert a planning-only manifest by rebuilding every source/request binding."""
    plan, plan_sha = read_json(plan_path)
    if (plan.get('schema') != 1 or plan.get('action') != 'offline_missing_candidate_evidence_plan'
            or plan.get('execution_authorized') is not False or plan.get('live_requests') != 0):
        raise ValueError('Offline missing-evidence plan required')
    database = Path(plan['database']).resolve()
    if sha(database) != plan['database_signature']['sha256']:
        raise ValueError('Database bytes changed since planning')
    source_requests = plan['requests']
    count = len(source_requests)
    if not 1 <= count <= 38 or plan['new_records'] != count:
        raise ValueError('One to 38 unique stored rows required')
    batch_ids = sorted({r['batch_id'] for r in source_requests})
    if len(batch_ids) != plan['new_batches']:
        raise ValueError('Batch coverage mismatch')
    expected_rows, products, bindings = {}, {}, []
    for bid in batch_ids:
        audit, rows, values = audit_database(database, bid)
        bindings.append(dict(batch_id=bid, content_hash=audit['batch_content_hash']))
        for row, product in zip(rows, values):
            expected_rows[row['record_id']] = row
            products[row['record_id']] = product
    if {r['record_id'] for r in source_requests} != set(expected_rows) or len(expected_rows) != count:
        raise ValueError('Exact complete batch coverage required')
    requests, ordered = [], []
    for ordinal, spec in enumerate(source_requests, 1):
        row = expected_rows[spec['record_id']]
        product = products[row['record_id']]
        if not product.name.strip() or len(product.name) > 512 or any(not c.isprintable() for c in product.name):
            raise ValueError('Bounded printable source title required')
        search = dict(method='GET', path=stage.CATALOG_PATH, params=dict(marketplaceIds=MARKETPLACE,
            keywords=search_keywords(product), keywordsLocale='en_US', locale='en_US',
            includedData='summaries', pageSize=stage.PAGE_SIZE))
        detail = dict(method='GET', path=stage.CATALOG_PATH+'/{reviewed_asin}',
            params=dict(marketplaceIds=MARKETPLACE, includedData=DETAIL_DATA, locale='en_US'),
            conditional=True, maximum=1,
            selection='Review returned candidates; skip rejected or insufficient candidates; never infer exact identity from title',
            saved_evidence_policy='Before any detail, reuse compatible completed scoped ASIN evidence; block every prior attempted or uncertain ASIN, including B0000AQOAB')
        if (spec['ordinal'] != ordinal or spec['batch_id'] != row['batch_id']
                or spec['walmart_item_id'] != row['walmart_item_id']
                or spec['original_row_sha256'] != fingerprint(row)
                or spec['original_raw_sha256'] != hashlib.sha256(row['raw_record_json'].encode()).hexdigest()
                or spec['source_fingerprint'] != fingerprint(product) or spec['source'] != normalized(product)
                or spec['observed_at_utc'] != row['observed_at_utc'] or spec['exported_at_utc'] != row['exported_at_utc']
                or spec['search'] != search or spec['detail'] != detail):
            raise ValueError('Stored source or request binding mismatch')
        ordered.append(product)
        requests.append(dict(ordinal=ordinal, source_fingerprint=fingerprint(product),
            record_id=row['record_id'], batch_id=row['batch_id'], original_intake_row=row,
            search=search, detail=detail))
    limits = dict(authentication=1, search=count, detail_at_most=count, total_at_most=1+2*count,
                  pricing=0, fees=0, restrictions=0, retries=0, automatic_refresh=0, pagination=0)
    if plan['limits'] != limits or plan['marketplace_id'] != MARKETPLACE:
        raise ValueError('Catalog-only attempt limits required')
    inventory_path = plan_path.parent / plan['evidence_inventory']
    inventory, inventory_sha = read_json(inventory_path)
    evidence = []
    for item in inventory['reports']:
        path = Path(item['path']).resolve()
        if path.parent != private_path.resolve() or sha(path) != item['sha256']:
            raise ValueError('Saved evidence binding mismatch')
        evidence.append(dict(path=str(path), sha256=item['sha256']))
    current_paths = {p.resolve() for pattern in REPORT_PATTERNS for p in private_path.glob(pattern)}
    if not current_paths <= {Path(e['path']) for e in evidence}:
        raise ValueError('New candidate evidence requires replanning')
    _, _, searched = saved_evidence([Path(e['path']) for e in evidence])
    if any(p.source_context['retailer_item_id'] in searched for p in ordered):
        raise ValueError('Prior search attempt must not be repeated')
    ledger = private_path / 'candidate-executions.sqlite3'
    ledger_sha = sha(ledger) if ledger.exists() else None
    identity = fingerprint(dict(bindings=bindings, rows=[r['original_intake_row'] for r in requests]))
    return dict(schema=1, mode=MODE, source=str(database), source_sha256=identity,
        database_sha256=sha(database), planning_manifest=str(plan_path.resolve()), planning_sha256=plan_sha,
        evidence_inventory=str(inventory_path.resolve()), evidence_inventory_sha256=inventory_sha,
        evidence=evidence, prior_ledger_sha256=ledger_sha, private_directory=str(private_path.resolve()),
        batch_bindings=bindings, marketplace_id=MARKETPLACE, requests=requests,
        limits=dict(authentication=1, search=count, detail=count, total=1+2*count, retries=0),
        selection_policy='stored-title-lead-v1', pages_per_search=1, pagination_enabled=False,
        pricing=False, fees=False, restrictions=False, deadline_seconds=300,
        minimum_interval_seconds=0.5, stop_on_failure=True, live_requests=0, execution_authorized=False), tuple(ordered)


class Reservations:
    """Use the existing shared ASIN ledger; claim all source rows before credentials."""
    def __init__(self, directory: int, manifest: dict, report: dict):
        self.report, self.manifest = report, manifest
        self.cache, self.blocked, _ = saved_evidence([Path(e['path']) for e in manifest['evidence']])
        fd = os.open('candidate-executions.sqlite3', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                raise ValueError('Private ledger required')
        finally:
            os.close(fd)
        self.db = sqlite3.connect(f'/proc/self/fd/{directory}/candidate-executions.sqlite3', timeout=5)
        self.run_key = manifest['source_sha256']
        try:
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.executescript('''CREATE TABLE IF NOT EXISTS candidate_executions (
                run_key TEXT PRIMARY KEY, manifest_sha256 TEXT NOT NULL, plan_sha256 TEXT NOT NULL,
                batch_id TEXT NOT NULL, batch_content_hash TEXT NOT NULL, status TEXT NOT NULL, checkpoint_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS candidate_operations (
                request_key TEXT PRIMARY KEY, run_key TEXT NOT NULL REFERENCES candidate_executions(run_key),
                kind TEXT NOT NULL, asin TEXT, state TEXT NOT NULL);''')
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                self.db.execute('INSERT INTO candidate_executions VALUES (?,?,?,?,?,?,?)',
                    (self.run_key, fingerprint(manifest), manifest['planning_sha256'], MODE,
                     fingerprint(manifest['batch_bindings']), 'reserved', canonical(report)))
                for spec in manifest['requests']:
                    self.db.execute('INSERT INTO candidate_operations VALUES (?,?,?,?,?)',
                        (self.search_key(spec), self.run_key, 'search', None, 'claimed_not_attempted'))
        except BaseException:
            self.db.close()
            raise
        self.last_key = None

    @staticmethod
    def search_key(spec: dict) -> str:
        row = spec['original_intake_row']
        return fingerprint(dict(kind='search', marketplace_id=MARKETPLACE,
                                walmart_item_id=row['walmart_item_id']))

    @staticmethod
    def select(product, search: dict) -> str | None:
        """Select an evidence lead, retaining alternatives and unresolved ties."""
        from app.candidate_quality import review_candidates
        audit = review_candidates(normalized(product), search)
        search['selection_audit'] = audit
        return audit['selected_asin']

    def saved_detail(self, asin: str) -> Evidence | None:
        saved = self.cache.get(asin)
        if saved:
            value = dict(saved['value'])
            catalog = dict(value['catalog'])
            for key in ('sale_price', 'referral_rate'):
                if catalog.get(key) is not None:
                    catalog[key] = Decimal(catalog[key])
            catalog['costs'] = {k: Decimal(v) if v is not None else None for k, v in catalog.get('costs', {}).items()}
            catalog['retrieved_at'] = timestamp(catalog.get('retrieved_at'))
            catalog['verified_costs'] = tuple(catalog.get('verified_costs', ()))
            catalog['identifiers'] = tuple(CatalogIdentifier(**i) for i in catalog.get('identifiers', ()))
            catalog['relationships'] = tuple(CatalogRelationship(**dict(r,
                parent_asins=tuple(r['parent_asins']), child_asins=tuple(r['child_asins']),
                theme_attributes=tuple(r['theme_attributes']))) for r in catalog.get('relationships', ()))
            for key in ('mapping_issues', 'missing_fields'):
                catalog[key] = tuple(catalog.get(key, ()))
            value['catalog'] = AmazonCatalogListing(**catalog)
            return Evidence(value, timestamp(saved['observed_at']), saved['provenance'], False)
        if asin in self.blocked or self.db.execute('SELECT 1 FROM candidate_operations WHERE kind=\'detail\' AND asin=?', (asin,)).fetchone():
            raise ValueError('Prior detail operation is reserved or uncertain')
        return None

    def reserve(self, kind: str, ordinal: int | None, request) -> None:
        asin = urlsplit(request.full_url).path.rsplit('/', 1)[-1] if kind == 'detail' else None
        key = (self.search_key(self.manifest['requests'][ordinal-1]) if kind == 'search' else
               fingerprint(dict(kind='catalog_detail', marketplace_id=MARKETPLACE, asin=asin, included_data=DETAIL_DATA))
               if kind == 'detail' else fingerprint(dict(run_key=self.run_key, kind='authentication')))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if kind == 'search':
                changed = self.db.execute("UPDATE candidate_operations SET state='reserved' WHERE request_key=? AND run_key=? AND state='claimed_not_attempted'", (key, self.run_key)).rowcount
                if changed != 1:
                    raise ValueError('Search already attempted')
            else:
                if kind == 'detail' and (asin in self.blocked or self.db.execute("SELECT 1 FROM candidate_operations WHERE kind='detail' AND asin=?", (asin,)).fetchone()):
                    raise ValueError('Detail already attempted')
                self.db.execute('INSERT INTO candidate_operations VALUES (?,?,?,?,?)', (key, self.run_key, kind, asin, 'reserved'))
            self.db.execute('UPDATE candidate_executions SET checkpoint_json=? WHERE run_key=?', (canonical(self.report), self.run_key))
        self.last_key = key

    def received(self) -> None:
        with self.db:
            self.db.execute("UPDATE candidate_operations SET state='response_received' WHERE request_key=?", (self.last_key,))

    def close(self) -> None:
        try:
            with self.db:
                self.db.execute('UPDATE candidate_executions SET status=?,checkpoint_json=? WHERE run_key=?',
                                (self.report['status'], canonical(self.report), self.run_key))
        finally:
            self.db.close()


def verify(manifest_path: Path, expected_sha256: str, maximum: int = 77) -> tuple[dict, tuple]:
    manifest, digest = read_json(manifest_path)
    if digest != expected_sha256 or manifest.get('mode') != MODE:
        raise ValueError('Executable manifest hash/mode mismatch')
    expected, products = prepare(Path(manifest['planning_manifest']), Path(manifest['private_directory']))
    if manifest != expected or type(maximum) is not int or not manifest['limits']['total'] <= maximum <= 77:
        raise ValueError('Executable bindings or explicit request cap mismatch')
    ledger = Path(manifest['private_directory']) / 'candidate-executions.sqlite3'
    if ledger.exists():
        with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            for spec in manifest['requests']:
                if db.execute('SELECT 1 FROM candidate_operations WHERE request_key=?', (Reservations.search_key(spec),)).fetchone():
                    raise ValueError('Prior source search reservation')
    return manifest, products


def run(manifest_path: Path, expected_sha256: str, maximum: int = 77, **kwargs) -> dict:
    manifest, _ = verify(manifest_path, expected_sha256, maximum)
    return stage.execute(Path(manifest['source']), manifest, Path(manifest['private_directory']),
        source_binding=lambda: verify(manifest_path, expected_sha256, maximum),
        guard_factory=Reservations, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'check', 'run'))
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--private-directory', type=Path, default=pilot.DIRECTORY)
    parser.add_argument('--expected-sha256')
    parser.add_argument('--max-attempts', type=int, default=77)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.execute != (args.action == 'run') or (args.action == 'prepare' and not args.plan):
        parser.error('run requires --execute; preparation requires --plan')
    try:
        if args.action == 'prepare':
            manifest, _ = prepare(args.plan, args.private_directory)
            with args.manifest.open('x') as output:
                args.manifest.chmod(0o600)
                output.write(canonical(manifest)+'\n')
            print(json.dumps(dict(manifest=str(args.manifest), sha256=sha(args.manifest), limits=manifest['limits'], live_requests=0)))
        elif args.action == 'check':
            manifest, _ = verify(args.manifest, args.expected_sha256, args.max_attempts)
            print(json.dumps(dict(status='offline_verified', rows=len(manifest['requests']), limits=manifest['limits'], live_requests=0)))
        else:
            previous = signal.signal(signal.SIGALRM, pilot.deadline)
            try:
                signal.alarm(300)
                result = run(args.manifest, args.expected_sha256, args.max_attempts)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous)
            print(json.dumps(dict(status=result['status'], attempts=len(result['attempts']), purchase_approved=False)))
            return 0 if result['status'] == 'succeeded' else 1
        return 0
    except (Exception, KeyboardInterrupt):
        print('Stored candidate stage stopped; no retry. Inspect retained reservations and sanitized report.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
