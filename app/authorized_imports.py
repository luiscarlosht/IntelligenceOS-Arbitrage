"""Validate owner-authorized CSV exports offline; never fetch URLs or prove licensing."""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from app.connectors import CsvConnector, WALMART_FIELDS
from app.normalization import http_url

HEADERS = ('retailer', 'name', 'url', 'gtin', 'manufacturer', 'model',
           'package_quantity', 'purchase_price', 'availability', 'retrieved_at',
           'provenance', 'asin_hint', 'variation', 'authorization_reference')


def validate(path: Path, now: datetime, maximum_rows: int = 10000) -> list[str]:
    """Return field/row diagnostics only, without echoing commercially sensitive values."""
    if now.utcoffset() is None:
        raise ValueError('Aware audit time required')
    issues = []
    with path.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) not in (HEADERS, HEADERS + WALMART_FIELDS):
            return ['Header must exactly match the authorized import template']
        count = 0
        for count, (raw, product) in enumerate(zip(reader, CsvConnector(path).products()), 1):
            if count > maximum_rows:
                return issues + ['Maximum candidate limit exceeded; partition input']
            row_issues = list(product.issues)
            for field in ('retailer', 'name', 'url', 'package_quantity', 'purchase_price',
                          'retrieved_at', 'provenance', 'variation'):
                if not getattr(product, field):
                    row_issues.append('Missing ' + field)
            if not (product.gtin or (product.manufacturer and product.model)):
                row_issues.append('Missing GTIN or manufacturer/model identity')
            if not (raw.get('authorization_reference') or '').strip():
                row_issues.append('Missing authorization_reference')
            if not http_url(product.url):
                row_issues.append('Invalid source URL')
            if product.availability != 'in_stock':
                row_issues.append('Inventory not confirmed in stock')
            if product.retrieved_at:
                age = (now - product.retrieved_at).total_seconds()
                if age < 0: row_issues.append('Future source timestamp')
                elif age > 86400: row_issues.append('Stale source timestamp')
            issues.extend(f'Row {count}: {issue}' for issue in dict.fromkeys(row_issues))
        if not count:
            issues.append('No product rows supplied')
    return issues


def remediation(issue: str) -> str:
    """Actionable guidance, without copying supplied values into reports."""
    text = issue.lower()
    rules = (
        ('header', 'Copy the exact column names and order from templates/authorized_products.csv.'),
        ('authorization_reference', 'Supply the actual permission/license record reference; a placeholder proves no rights.'),
        ('provenance', 'Identify the authorized export/feed and original observation basis.'),
        ('purchase_price', 'Supply a finite positive per-package USD purchase price.'),
        ('quantity', 'Supply a positive integer package count and verify it against the destination package.'),
        ('url', 'Supply an HTTP(S) source product URL without embedded credentials.'),
        ('gtin', 'Supply a valid GTIN including its check digit, or remove it and supply manufacturer/model.'),
        ('identity', 'Supply a valid GTIN or both manufacturer and model; an ASIN hint alone is insufficient.'),
        ('timestamp', 'Supply the original timezone-aware ISO-8601 observation time; obtain fresh authorized evidence if stale. Never relabel old data as current.'),
        ('retrieved_at', 'Supply the original timezone-aware ISO-8601 observation time.'),
        ('stock', 'Obtain authorized evidence confirming in_stock; do not infer stock.'),
        ('variation', 'Supply and verify the exact size/color/variation.'),
    )
    return next((action for token, action in rules if token in text),
                'Correct the named field using authorized source evidence, then rerun preflight.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    args = parser.parse_args()
    try:
        issues = validate(args.csv, datetime.now(timezone.utc))
    except (OSError, ValueError, csv.Error):
        issues = ['Import could not be validated']
    print(json.dumps({'event': 'authorized_import_validation', 'issues': issues,
                      'findings': [{'issue': issue, 'action': remediation(issue)} for issue in issues],
                      'authorization_verified': False, 'marketplace_verified': False}))
    raise SystemExit(bool(issues))


if __name__ == '__main__':
    main()
