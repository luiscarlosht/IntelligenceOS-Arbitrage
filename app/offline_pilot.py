"""Offline fixture composition; no secrets, mail, remote selector or live transport."""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.config import Config, ROOT
from app.connectors import CsvConnector
from app.discovery import screen
from app.keepa_adapter import KeepaAdapter, KeepaRequest, KeepaResponse, MAX_RESPONSE_BYTES, US_MARKETPLACE
from app.marketplace import MockAmazonProvider
from app.observations import ObservationStore, canonical, fingerprint
from app.provider_contracts import Evidence, SellerContext
from app.provider_runtime import BudgetExceeded, Policy, ProviderFailure, UsageLedger
from app.reporting import write_report

FIXTURE_NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
LABEL = 'FIXTURE PILOT — fictional products; no live evidence or purchase approval'
KINDS = ('catalog', 'amazon_price', 'sales_rank', 'bought_past_month', 'fees', 'eligibility')


class FixtureKeepaTransport:
    """Only reads an explicitly labeled local fictional response fixture."""
    is_mock = True

    def __init__(self, path: Path):
        if path.stat().st_size > MAX_RESPONSE_BYTES:
            raise ValueError('Fixture exceeds bounded size')
        data = json.loads(path.read_text())
        if data.get('label') != 'FICTIONAL KEEPA FIXTURES' or not isinstance(data.get('responses'), dict):
            raise ValueError('Explicit fictional Keepa fixture required')
        self.responses = data['responses']
        self.calls = 0

    def product(self, request: KeepaRequest, *, timeout_seconds: float, maximum_bytes: int):
        self.calls += 1
        response = self.responses.get(request.asin, dict(status=200, payload=dict(products=[])))
        body = json.dumps(response['payload']).encode()
        if len(body) > maximum_bytes:
            raise ValueError('Fixture response exceeds bounded size')
        return KeepaResponse(response['status'], body)


def run_offline(source: Path, catalog: Path, keepa_fixture: Path, directory: Path,
                *, now: datetime = FIXTURE_NOW, maximum_products: int = 10) -> dict:
    """Compose existing normalization/matching/Keepa/screening/reporting offline.

    Repeat imports deduplicate evidence, not runs. Every input ordinal is linked,
    but duplicate normalized rows are screened/reported only once per run.
    """
    if now.utcoffset() is None or type(maximum_products) is not int or not 1 <= maximum_products <= 10:
        raise ValueError('Aware fixture evaluation clock and 1–10 products required')
    source, catalog, keepa_fixture, directory = map(Path, (source, catalog, keepa_fixture, directory))
    database, report, summary = (directory/name for name in ('pilot.sqlite3', 'PILOT-FIXTURE.xlsx', 'PILOT-FIXTURE.json'))
    paths = [p.resolve() for p in (source, catalog, keepa_fixture, database, report, summary)]
    if len(set(paths)) != len(paths) or any(p.is_symlink() for p in (directory, database, report, summary)):
        raise ValueError('Pilot inputs and outputs must be separate nonsymlink paths')
    if any(path.stat().st_size > 1024*1024 for path in (source, catalog, keepa_fixture)):
        raise ValueError('Pilot input files must each fit the 1 MiB bound')
    # Config is constructed directly: inherited mail/provider settings cannot opt in.
    config = Config(source, report, database, mode='discovery', amazon_fixture=catalog,
                    maximum_candidates=maximum_products)
    manifest = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                for name, path in (('source_sha256', source), ('catalog_sha256', catalog), ('keepa_fixture_sha256', keepa_fixture))}
    store = ObservationStore(database)
    run_id = store.start_run(now, manifest)
    adapter = None
    rows, evidence_rows = [], []
    input_count = 0
    try:
        provider = MockAmazonProvider(catalog)
        transport = FixtureKeepaTransport(keepa_fixture)
        adapter = KeepaAdapter(transport, UsageLedger(database), enabled=True,
            initial_tokens=10, monthly_token_limit=30, policy=Policy(max_attempts=1),
            clock=lambda: now, sleep=lambda _: None)
        seen, lookups = {}, {}
        for ordinal, product in enumerate(CsvConnector(source).products(), 1):
            input_count = ordinal
            if ordinal > maximum_products:
                raise ValueError('Pilot row limit exceeded; provide at most ten rows')
            if not product.authorization_reference:
                product = replace(product, issues=product.issues + ('Missing authorization_reference',))
            key = fingerprint(product)
            if key not in seen:
                match = provider.match(product)
                row = screen(product, match, config, now)
                row['data_mode'] = LABEL
                enrichments = []
                if match.listing:
                    asin = match.listing.asin
                    if asin not in lookups:
                        try:
                            record = adapter.lookup(asin)
                        except (ProviderFailure, BudgetExceeded, ValueError):
                            # Provider text/payloads never enter reports. Continue all products.
                            lookups[asin] = (None, 'Keepa enrichment unavailable')
                        else:
                            lookups[asin] = (record, '')
                    record, error = lookups[asin]
                    if error:
                        row['rejection_reasons'].append(error)
                        row.update(status='REJECT', ranking_score=0, budget_units=0)
                        row['reason'] = row['quality_issues'] = '; '.join(row['rejection_reasons'])
                    fetched_at = record.fetched_at if record else now
                    context = SellerContext('FICTIONAL-PILOT-SELLER', US_MARKETPLACE)
                    for kind in KINDS:
                        evidence = getattr(record, kind, None) if record else None
                        if not error and kind == 'eligibility':
                            evidence = adapter.eligibility(asin, context)
                        elif not error and kind == 'fees' and match.listing.sale_price is not None:
                            evidence = adapter.quote(asin, context, match.listing.sale_price, 'FBA')
                        if evidence is None:
                            evidence = Evidence(None, fetched_at,
                                'FICTIONAL KEEPA: ' + (error or kind + ' unavailable; no observation'), True)
                        enrichments.append((asin, kind, evidence, fetched_at))
                seen[key] = (product, match, row, enrichments)
                rows.append(row)
            product, match, row, enrichments = seen[key]
            source_id = store.record_item(run_id, ordinal, product, match, row, enrichments,
                                          datetime.now(timezone.utc))
            # Keep supplementary observations separate; never fill sale price, fees,
            # eligibility or monthly sales from historical price/rank/bracket fields.
            if not any(item['source_observation_id'] == source_id for item in evidence_rows):
                for asin, kind, evidence, fetched_at in enrichments:
                    evidence_rows.append(dict(source_observation_id=source_id, asin=asin, kind=kind,
                        value=canonical(evidence.value) if evidence.value is not None else None,
                        observed_at=evidence.observed_at.isoformat() if evidence.value is not None else None,
                        fetched_at=fetched_at.isoformat(), provenance=evidence.provenance,
                        is_mock=True, fresh=evidence.fresh(now, config.maximum_data_age_hours*3600) if evidence.value is not None else None,
                        notice='Supplement only; historical price/rank/bracket is not sale quote/units/eligibility'))
        if not input_count:
            raise ValueError('At least one fixture product required')
        rows.sort(key=lambda r: (-r['ranking_score'], r['amazon_asin'], r['product']))
        result = dict(label=LABEL, run_id=run_id, input_rows=input_count, distinct_observations=len(rows),
            evaluation_at=now.isoformat(), clock_basis='explicit fixture clock, never live freshness',
            live_requests=0, mock_keepa_requests=transport.calls, manifest=manifest,
            rows=rows, enrichment=evidence_rows)
        write_report(rows, report, discovery=True, demo=True, enrichment_rows=evidence_rows,
                     job=dict(run_id=run_id, mode=LABEL, evaluation_at=now.isoformat(), live_requests=0,
                              input_rows=input_count, distinct_observations=len(rows),
                              phase='Report generated; final run status in SQLite'))
        temporary = None
        try:
            with NamedTemporaryFile(mode='w', dir=directory, delete=False, encoding='utf-8') as stream:
                temporary = Path(stream.name)
                stream.write(canonical(result) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, summary)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        store.history.finish(run_id, 'succeeded', len(rows), sum(r['status']=='REVIEW' for r in rows), report)
        return result
    except Exception as error:
        store.history.finish(run_id, 'failed', len(rows), sum(r['status']=='REVIEW' for r in rows),
                             error=type(error).__name__)
        raise
    finally:
        if adapter is not None:
            adapter.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'sample_data/pilot_source_fixture.csv')
    parser.add_argument('--catalog', type=Path, default=ROOT/'sample_data/pilot_catalog_fixture.json')
    parser.add_argument('--keepa-fixture', type=Path, default=ROOT/'sample_data/pilot_keepa_fixture.json')
    parser.add_argument('--output-directory', type=Path, default=ROOT/'var/pilot-offline')
    args = parser.parse_args()
    try:
        result = run_offline(args.source, args.catalog, args.keepa_fixture, args.output_directory)
    except Exception:
        print('Offline fixture pilot failed; inspect local run status, not provider responses.')
        raise SystemExit(1) from None
    print(json.dumps({key: result[key] for key in ('label', 'run_id', 'input_rows', 'distinct_observations', 'live_requests', 'mock_keepa_requests')}))


if __name__ == '__main__':
    main()
