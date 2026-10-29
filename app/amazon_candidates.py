"""Explicit, one-shot Catalog Items candidate stage; default CLI only writes a plan."""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import time

from app import amazon_pilot as pilot
from app.amazon_catalog import MARKETPLACE, AmazonCatalogAdapter, clean_text, parse_catalog
from app.authorized_imports import validate
from app.config import Config
from app.connectors import CsvConnector
from app.discovery import screen
from app.models import Match
from app.observations import ObservationStore, canonical, fingerprint, normalized
from app.provider_contracts import Evidence
from app.provider_runtime import ProviderFailure
from app.reporting import write_report

CATALOG_PATH = '/catalog/2022-04-01/items'
DETAIL_DATA = 'summaries,identifiers,relationships,attributes'
LIMITS = dict(authentication=1, search=10, detail=10, total=21, retries=0)
PAGE_SIZE = 10
LABEL = 'AMAZON CANDIDATES — no pricing, eligibility or purchase approval'


def source_plan(source: Path) -> tuple[dict, tuple]:
    """Bind every ordinal and full keyword query to the exact offline source bytes."""
    raw = source.read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError('Source exceeds bound')
    products = tuple(CsvConnector(source).products())
    if not 1 <= len(products) <= 1000:
        raise ValueError('Candidate batches must contain 1 to 1000 input rows')
    findings = validate(source, datetime.now(timezone.utc), maximum_rows=len(products))
    if any(x.startswith('Header') for x in findings):
        raise ValueError('Source template required')
    if source.read_bytes() != raw:
        raise ValueError('Source changed during planning')
    requests = []
    for ordinal, product in enumerate(products, 1):
        if not product.name.strip() or len(product.name) > 512 or any(not c.isprintable() for c in product.name):
            raise ValueError('Bounded printable source title required')
        requests.append(dict(ordinal=ordinal, source_fingerprint=fingerprint(product),
            retailer_item_id=product.source_context.get('retailer_item_id'),
            search=dict(method='GET', path=CATALOG_PATH,
                        params=dict(marketplaceIds=MARKETPLACE, keywords=product.name,
                                    keywordsLocale='en_US', locale='en_US',
                                    includedData='summaries', pageSize=PAGE_SIZE)),
            detail=dict(method='GET', path=CATALOG_PATH+'/{selected_asin}',
                        params=dict(marketplaceIds=MARKETPLACE, includedData=DETAIL_DATA, locale='en_US'),
                        selection='first distinct returned ASIN; candidate only; at most one per row')))
    return dict(schema=1, source=str(source.resolve()), source_sha256=hashlib.sha256(raw).hexdigest(),
        marketplace_id=MARKETPLACE, limits=dict(authentication=1, search=len(products), detail=len(products), total=1+2*len(products), retries=0), authentication=dict(method='POST',
        url='https://api.amazon.com/auth/o2/token', grant_type='refresh_token'),
        requests=requests, pages_per_search=1, pagination_enabled=False,
        stop_on_failure=True, deadline_seconds=300, minimum_interval_seconds=0.5,
        exact_match_policy='Identifier plus verified package quantity, package contents and variation; '
                           'titles and ASIN hints alone never verify identity; incomplete search remains ambiguous',
        live_requests=0, execution_authorized=False), products


def parse_search(document: dict, *, secrets: tuple[str, ...] = ()) -> dict:
    """Keep a bounded first page; never store or follow the provider's next token."""
    count = document.get('numberOfResults')
    items = document.get('items')
    pagination = document.get('pagination', {})
    if (type(count) is not int or count < 0 or not isinstance(items, list)
            or len(items) > PAGE_SIZE or count < len(items) or not isinstance(pagination, dict)):
        raise ProviderFailure('Invalid search result shape')
    for key in ('nextToken', 'previousToken'):
        if key in pagination and not isinstance(pagination[key], str):
            raise ProviderFailure('Invalid pagination shape')
    candidates, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('asin'), str) or not re.fullmatch(r'[A-Z0-9]{10}', item['asin']):
            raise ProviderFailure('Invalid candidate ASIN')
        summaries = item.get('summaries', [])
        if not isinstance(summaries, list) or any(not isinstance(s, dict) for s in summaries):
            raise ProviderFailure('Invalid candidate summaries')
        scoped = [s for s in summaries if s.get('marketplaceId') == MARKETPLACE]
        if len(scoped) > 1 or (summaries and not scoped):
            raise ProviderFailure('Candidate marketplace mismatch')
        asin = item['asin']
        if asin in seen:
            continue
        seen.add(asin)
        candidates.append(dict(asin=asin, title=clean_text(scoped[0].get('itemName'), secrets) if scoped else '',
                               rank=len(candidates)+1))
    more = bool(pagination.get('nextToken')) or count > len(items)
    if count and not candidates and not more:
        raise ProviderFailure('Contradictory empty search')
    return dict(candidates=candidates, total_results=count, more_results=more,
                complete=not more, selected_asin=candidates[0]['asin'] if candidates else None)


def detail_evidence(document: dict, asin: str, *, is_mock: bool, secrets: tuple[str, ...]) -> Evidence:
    """Reuse the catalog mapper, retaining allowlisted package/variant attributes."""
    evidence = parse_catalog(document, expected_asin=asin, is_mock=is_mock, secrets=secrets)
    attrs = document.get('attributes', {})
    if not isinstance(attrs, dict):
        raise ProviderFailure('Invalid catalog attributes')
    package = {}
    for key in ('included_components', 'number_of_items', 'unit_count', 'material', 'color', 'size', 'style'):
        values = attrs.get(key, [])
        if not isinstance(values, list) or len(values) > 100:
            raise ProviderFailure('Invalid package attribute')
        scoped = []
        for value in values:
            if not isinstance(value, dict):
                raise ProviderFailure('Invalid package attribute value')
            # Marketplace-less product-type attributes are unscoped and cannot verify identity.
            if value.get('marketplace_id') == MARKETPLACE:
                item = value.get('value')
                if type(item) in (str, int, float):
                    scoped.append(clean_text(str(item), secrets))
                elif key == 'unit_count':
                    scoped.append('structured unit count requires verification')
        if scoped:
            package[key] = sorted(scoped)
    return Evidence(dict(catalog=evidence.value, package_attributes=package), evidence.observed_at,
                    evidence.provenance+'; attributes (allowlisted, US-scoped)', is_mock)


def decide(product, search: dict, detail: Evidence | None) -> tuple[str, Match]:
    empty = Match(None, False, Decimal('0'), ('No verified catalog identity',))
    if not search['candidates']:
        return ('ambiguous' if search['more_results'] else 'unmatched'), empty
    if detail is None:
        return 'candidate_unverified', empty
    listing = detail.value['catalog']
    match = AmazonCatalogAdapter(Evidence(listing, detail.observed_at, detail.provenance, detail.is_mock)).match(product)
    reasons = list(match.reasons)
    attrs = detail.value['package_attributes']
    if attrs.get('number_of_items'):
        if product.package_quantity is None:
            reasons.append('Source package count unknown')
        elif attrs['number_of_items'] != [str(product.package_quantity)]:
            reasons.append('Catalog item count and source package count require basis verification')
    if attrs.get('unit_count'):
        reasons.append('Unit count requires independent source verification')
    try:
        catalog_variant = json.loads(listing.variation)
    except (ValueError, TypeError):
        catalog_variant = {}
    for dimension in ('color', 'size', 'style'):
        if attrs.get(dimension) and (not isinstance(catalog_variant, dict) or
                attrs[dimension] != [catalog_variant.get(dimension)]):
            reasons.append('Catalog variation attributes conflict or remain unverified')
    if attrs.get('material'):
        try:
            source_variant = json.loads(product.variation)
        except (ValueError, TypeError):
            source_variant = {}
        if not isinstance(source_variant, dict) or [source_variant.get('material')] != attrs['material']:
            reasons.append('Material variation unverified')
    # Composition evidence must come from supplied structured source evidence,
    # never from either title or a guessed interpretation of a piece count.
    source_contents = product.source_context.get('source_package_contents')
    target_contents = detail.value['package_attributes'].get('included_components')
    if not source_contents or not target_contents:
        reasons.append('Package contents evidence missing')
    elif source_contents != canonical(target_contents):
        reasons.append('Package contents differ; composition verification required')
    if product.issues:
        reasons.append('Source normalization/evidence issues unresolved')
    if len(search['candidates']) != 1 or not search['complete']:
        reasons.append('Multiple or unexamined catalog candidates remain')
    exact = match.exact and not reasons
    result = replace(match, exact=exact, confidence=Decimal('1') if exact else Decimal('0'),
                     reasons=tuple(dict.fromkeys(reasons)))
    return ('exact' if exact else 'ambiguous' if len(search['candidates']) > 1 or not search['complete']
            else 'candidate_unverified'), result


def execute(source: Path, manifest: dict, private_path: Path = pilot.DIRECTORY, *,
            transport=None, credential_loader=None, is_mock: bool = False,
            sleep=time.sleep, monotonic=time.monotonic) -> dict:
    """Explicit future operator execution; injectable transport for offline regression tests."""
    expected, products = source_plan(source)
    if manifest != expected:
        raise ValueError('Manifest differs from exact source-bound plan')
    directory = pilot.private_directory(private_path)
    # Stable source-byte reservation prevents replay even if a new manifest/report name is supplied.
    stem = 'candidates-'+manifest['source_sha256']
    results = [dict(ordinal=i, source=normalized(p), status='not_attempted', exact=False,
                    search=None, detail=None, reasons=['Stage not attempted']) for i, p in enumerate(products, 1)]
    matches = [Match(None, False, Decimal('0'), ('Stage not attempted',)) for _ in products]
    report = dict(label=LABEL, manifest=manifest, rows=results, attempts=[],
                  live_requests=0, is_mock=is_mock, status='reserved', purchase_approved=False)
    try:
        fd = pilot.create_file(directory, stem+'.json')
    except BaseException:
        os.close(directory)
        raise
    now = datetime.now(timezone.utc)
    start, last = monotonic(), None
    counts = dict(authentication=0, search=0, detail=0)
    output = os.fdopen(fd, 'w')

    def checkpoint():
        output.seek(0)
        output.write(canonical(report)+'\n')
        output.truncate()
        output.flush()
        os.fsync(output.fileno())

    def call(kind, ordinal, request):
        nonlocal last
        if counts[kind] >= manifest['limits'][kind] or len(report['attempts']) >= manifest['limits']['total']:
            raise ProviderFailure('Attempt ceiling reached')
        current = monotonic()
        if last is not None:
            sleep(max(0, 0.5-(current-last)))
        if monotonic()-start >= 300:
            raise TimeoutError('Candidate stage deadline')
        counts[kind] += 1
        report['attempts'].append(dict(kind=kind, ordinal=ordinal, status='reserved'))
        report['live_requests'] = 0 if is_mock else len(report['attempts'])
        checkpoint()  # Reserve before I/O; errors/uncertain outcomes are consumed attempts.
        last = monotonic()
        value = (transport or pilot.request_json)(request)
        if not isinstance(value, dict):
            raise ProviderFailure('Invalid response document')
        report['attempts'][-1]['status'] = 'response_received'
        return value

    try:
        checkpoint()  # Every original source row is durable before credentials or HTTP.
        credentials = (credential_loader or pilot.load_credentials)(directory)
        access = pilot.exchange_token(credentials, lambda req: call('authentication', None, req))
        secrets = (*credentials.values(), access)
        for row, product, spec in zip(results, products, manifest['requests']):
            row['status'], row['reasons'] = 'search_pending', []
            request = spec['search']
            search = parse_search(call('search', row['ordinal'], pilot.amazon_request(
                access, request['path'], request['params'])), secrets=secrets)
            row['search'] = dict(**search, observed_at=datetime.now(timezone.utc).isoformat(),
                                 provenance='Amazon SP-API searchCatalogItems 2022-04-01; US; first page',
                                 request_ordinal=row['ordinal'], keywords=product.name)
            checkpoint()
            detail = None
            if search['selected_asin']:
                row['status'] = 'detail_pending'
                request = spec['detail']
                asin = search['selected_asin']
                detail = detail_evidence(call('detail', row['ordinal'], pilot.amazon_request(
                    access, CATALOG_PATH+'/'+asin, request['params'])), asin,
                    is_mock=is_mock, secrets=secrets)
                row['detail'] = normalized(detail)
            row['status'], match = decide(product, search, detail)
            matches[row['ordinal']-1] = match
            row['exact'], row['reasons'] = match.exact, list(match.reasons)
            checkpoint()
        report['status'] = 'succeeded'
    except (Exception, KeyboardInterrupt):
        report['status'] = 'failed_no_retry'
        if report['attempts']:
            report['attempts'][-1]['status'] = 'failed_or_parser_rejected'
        for row in results:
            if row['status'] in ('search_pending', 'detail_pending'):
                row['status'] = 'failed'
                row['reasons'] = ['Catalog request or parsing failed; no retry']
        # Do not persist exception messages, request headers, credentials or raw response bodies.
    finally:
        checkpoint()
        output.close()
        os.close(directory)
    persist(private_path, stem, products, report, now, matches)
    return report


def persist(directory: Path, stem: str, products: tuple, report: dict, now: datetime, matches: list) -> None:
    """All ordinals, including failure/unmatched/ambiguous, enter existing evidence/report boundaries."""
    store = ObservationStore(directory/(stem+'.sqlite3'))
    run_id = store.start_run(now, report['manifest'], label=LABEL)
    config = Config(input=Path(report['manifest']['source']), output=directory/(stem+'.xlsx'),
                    database=store.path, maximum_candidates=len(products))
    rows, enrichments = [], []
    for product, result in zip(products, report['rows']):
        match = matches[result['ordinal']-1]
        if not match.exact:
            match = replace(match, reasons=tuple(result['reasons']))
        row = screen(product, match, config, now)
        row.update(input_ordinal=result['ordinal'], candidate_status=result['status'],
                   candidate_exact=result['exact'], candidate_asins=[c['asin'] for c in
                       (result['search'] or {}).get('candidates', [])])
        evidence = Evidence(result, now, LABEL, report['is_mock'])
        store.record_item(run_id, result['ordinal'], product, match, row,
                          [('', 'catalog_candidate_stage', evidence, now)], now, provider='amazon-catalog-candidates')
        rows.append(row)
        enrichments.append(dict(kind='catalog_candidate_stage', asin='', value=canonical(result), provenance=LABEL))
    from app.candidate_review_report import build_review
    report_rows, review, report_enrichments = build_review(report)
    write_report(report_rows, config.output, discovery=True, candidate_review=review,
        job=dict(label=LABEL,maximum_http_attempts=report['manifest']['limits']['total'],actual_attempts=len(report['attempts']),
                 live_requests=report['live_requests'],status=report['status']),
        enrichment_rows=report_enrichments)
    store.history.finish(run_id, 'succeeded' if report['status']=='succeeded' else 'failed', len(products), 0,
                         config.output, error=None if report['status']=='succeeded' else 'CandidateStageFailure')


def main() -> int:
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in ('prepare-details', 'run-details'):
        from app.candidate_execution import main as stored_main
        return stored_main()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'run'))
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--execute', action='store_true', help='Explicit operator opt-in; never used during preparation')
    args = parser.parse_args()
    if args.execute and args.action != 'run':
        parser.error('--execute is only valid with run')
    try:
        if args.action == 'plan':
            manifest, _ = source_plan(args.source)
            with args.manifest.open('x', encoding='utf-8') as output:
                output.write(json.dumps(manifest, indent=2)+'\n')
            print('Offline request manifest created; zero HTTP attempts.')
            return 0
        if not args.execute:
            parser.error('run requires explicit --execute')
        manifest = json.loads(args.manifest.read_text())
        previous = signal.signal(signal.SIGALRM, pilot.deadline)
        try:
            signal.alarm(300)
            report = execute(args.source, manifest)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
        print(json.dumps(dict(status=report['status'], attempts=len(report['attempts']), purchase_approved=False)))
        return 0 if report['status']=='succeeded' else 1
    except (Exception, KeyboardInterrupt):
        print('Candidate stage stopped; no retry. Inspect the exclusive private report.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
