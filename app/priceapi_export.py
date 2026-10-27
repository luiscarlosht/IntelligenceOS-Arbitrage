"""Offline eBay Price API export adapter. No transport, settings or credentials."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from app.amazon_source_plan import prepare
from app.authorized_imports import HEADERS
from app.connectors import SOURCE_FIELDS
from app.normalization import timestamp
from app.reporting import write_report


def rows_from_export(document: dict, reference: str, digest: str, imported: datetime) -> list[dict]:
    if document.get('status') != 'finished':
        raise ValueError('Completed export required')
    results = document.get('results')
    if not isinstance(results, list) or len(results) != 1:
        raise ValueError('Exactly one result scope required')
    result = results[0]
    query = result.get('query', {})
    if result.get('success') is not True or any(query.get(k) != v for k, v in
            dict(source='ebay', country='us', topic='search_results').items()):
        raise ValueError('Successful eBay US search export required')
    items = result.get('content', {}).get('search_results')
    if not isinstance(items, list):
        raise ValueError('Search results required')
    rows, seen = [], set()
    for rank, item in enumerate(items, 1):
        def text(key):
            value = item.get(key)
            return str(value) if type(value) in (str, int, float) else ''
        url = text('url')
        parsed = urlsplit(url)
        match = re.search(r'/itm/(?:[^/]+/)?([0-9]+)(?:/|$)', parsed.path)
        if parsed.hostname not in ('ebay.com', 'www.ebay.com') or not match:
            raise ValueError('Distinct eBay listing identity required')
        item_id = match[1]
        if item_id in seen:
            continue
        seen.add(item_id)
        observed = text('updated_at')
        # Search metadata time is not an individual offer observation timestamp.
        source_time = timestamp(observed) if observed else None
        row = dict.fromkeys(HEADERS + SOURCE_FIELDS, '')
        issues = ['Search observation is not a verified purchase quote',
                  'Package and variation unverified', 'Stock unknown',
                  'Destination ZIP and shipping conditions unknown',
                  'Source authorization/license not independently verified']
        if source_time is None:
            issues.append('Individual offer observation time unknown')
        row.update(retailer='eBay', name=text('name'), url=url,
            availability='unknown', retrieved_at=source_time.isoformat() if source_time else '',
            provenance=f'Price API ebay/us search_results; job={document.get("job_id", "unknown")}; '
                       f'result_rank={rank}; export={reference}; sha256={digest}; '
                       f'search_updated_at={result.get("metadata", {}).get("updated_at", "unknown")}; '
                       f'offline_imported_at={imported.isoformat()}',
            authorization_reference='', source_provider='priceapi',
            provider_product_id=text('id'), retailer_item_id=item_id,
            source_seller=text('shop_name'), source_seller_id=text('shop_id'),
            source_shipping_cost=text('shipping_costs'), source_condition=text('condition_text'),
            source_price_with_shipping=text('price_with_shipping'),
            source_observed_at=observed, search_price=text('price'), search_currency=text('currency'),
            source_issues='; '.join(issues))
        rows.append(row)
        if len(rows) == 10:
            break
    if len(rows) != 10:
        raise ValueError('Ten distinct listings required')
    return rows


def import_export(source: Path, directory: Path) -> dict:
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    document = json.loads(raw)
    now = datetime.now(timezone.utc)
    rows = rows_from_export(document, str(source.resolve()), digest, now)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    csv_path = directory / 'observations.csv'
    with csv_path.open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS + SOURCE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    prepared = prepare(csv_path, (), {}, {}, {}, directory / 'report',
                       seller_reference='', now=now, expected_rows=10)
    searches = [dict(ordinal=i, ebay_item_id=r['retailer_item_id'], keywords=r['name'],
                    status='candidate_search_only', exact_match=False,
                    required_evidence=['Valid GTIN or verified manufacturer and model',
                        'Exact package contents and quantity', 'Exact size/color/material/variation',
                        'Independent source and Amazon identity evidence'])
                for i, r in enumerate(rows, 1)]
    plan = dict(source=str(source.resolve()), source_sha256=digest,
        run_id=prepared['run_id'], imported_rows=10, live_requests=0,
        candidate_searches=searches,
        matching_rule='Title similarity only retrieves candidates; never establishes exact identity. '
                      'No title-derived package count or brand is verified. Ambiguity blocks enrichment.',
        budget=dict(authentication_maximum=1, catalog_search_maximum=10,
                    catalog_detail_maximum=10, maximum_http_attempts=21,
                    pages_per_search=1, candidates_for_detail_per_listing=1,
                    retries=0, pricing=0, restrictions=0, fees=0,
                    requests_enabled=False, live_requests=0),
        next_stage='Only after identity verification and separate authorization: pricing, seller restrictions, '
                   'FBA eligibility and explicit sale-price fee scenarios; no requests reserved here.',
        source_findings=prepared['source_findings'])
    write_report(prepared['rows'], directory/'report'/'SOURCE-PLAN.xlsx', discovery=True,
                 job=dict(label='OFFLINE eBay candidate-search plan; requests disabled',
                          run_id=prepared['run_id'], live_requests=0,
                          maximum_http_attempts=21, purchase_approved=False),
                 enrichment_rows=[dict(kind='supplied_ebay_source', asin='',
                                       value=json.dumps(row), provenance=row['provenance'])
                                  for row in rows])
    (directory/'candidate-search-plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise ValueError('Original export changed during import')
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    plan = import_export(args.source, args.output_directory)
    print(json.dumps({k: plan[k] for k in ('source_sha256', 'run_id', 'imported_rows', 'live_requests', 'budget')}))


if __name__ == '__main__':
    main()
