"""Offline brand-first discovery. No transport, credentials or authorization writes."""
import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from app.amazon_catalog import MARKETPLACE
from app.amazon_pilot import DIRECTORY
from app.m63_history import audit
from ops.m95_eligibility import M69, M79, M94, read_json

REGISTRY = Path('data/m96/brand_registry.json')
ASIN = re.compile(r'[A-Z0-9]{10}')
LOWER_COMPLEXITY = {'drawer organizers', 'pencil holders', 'tool bags', 'tool boxes',
    'plant labels', 'garden twine & twist ties', 'letter trays & stacking supports',
    'shelf dividers', 'luggage tags', 'laundry bags', 'rulers', 'crochet hooks',
    'storage boxes & organizers', 'business card holders', 'magazine holders',
    'mail sorters', 'tool trays', 'supply organizers', 'spiral notebooks'}
FIELDS = ['brand', 'asin', 'marketplace', 'condition', 'observation',
          'approval_requirements', 'restriction_scope', 'invoice_requirements',
          'evidence_source', 'observed_at']


def brand_key(value: str) -> str:
    return ' '.join(value.split()).casefold()


def validate_record(row: dict) -> dict:
    if (not row['brand'].strip() or row['marketplace'] != MARKETPLACE
            or row['condition'] != 'new_new'
            or row['restriction_scope'] not in {'BRAND', 'ASIN'}
            or row['approval_status'] not in {'APPROVAL_REQUIRED', 'NOT_AVAILABLE', 'SELL_THIS_PRODUCT'}
            or not row['evidence_source'].strip()):
        raise ValueError('Invalid observation scope or status')
    if row['asin'] and not ASIN.fullmatch(row['asin']):
        raise ValueError('Invalid ASIN')
    if row['restriction_scope'] == 'ASIN' and not row['asin']:
        raise ValueError('ASIN scope requires ASIN')
    # Brand-wide positive permission cannot be inferred from one product screen.
    if row['approval_status'] == 'SELL_THIS_PRODUCT' and row['restriction_scope'] != 'ASIN':
        raise ValueError('Positive observation must be ASIN scoped')
    stamp = datetime.fromisoformat(row['observed_at'])
    if stamp.tzinfo is None:
        raise ValueError('Timezone required')
    return dict(row)


def import_observations(path: Path) -> list[dict]:
    result = []
    with path.open(newline='') as stream:
        for row in csv.DictReader(stream):
            if not row['observation'].strip():
                continue
            status = {'Sell this product': 'SELL_THIS_PRODUCT', 'Apply to sell': 'APPROVAL_REQUIRED',
                      'Not available': 'NOT_AVAILABLE'}.get(row['observation'])
            if status is None:
                raise ValueError('Unrecognized Seller Central observation')
            row['approval_status'] = status
            result.append(validate_record(row))
    return result


def build(catalog: list[dict], m69: dict, histories: list[dict], historical: dict,
          registry: list[dict], limit: int = 30) -> list[dict]:
    blocked = set(m69['excluded_asins']) | set(historical['excluded_asins'])
    blocked.update(event['asin'] for event in m69['events'] if event.get('asin'))
    for history in histories:
        blocked.update(history.get('asins', []))
        blocked.update(row['asin'] for row in history.get('rows', []) if row.get('asin'))
    records = [validate_record(row) for row in registry]
    blocked.update(r['asin'] for r in records if r['asin'])
    brands = {brand_key(r['brand']) for r in records
              if r['restriction_scope'] == 'BRAND' and r['approval_status'] != 'SELL_THIS_PRODUCT'}
    candidates = []
    seen = set()
    for item in catalog:
        asin = item['asin']
        if not ASIN.fullmatch(asin) or asin in seen:
            raise ValueError('Invalid or duplicate catalog ASIN')
        seen.add(asin)
        if (asin in blocked or brand_key(item.get('brand', '')) in brands
                or not item.get('brand') or item['brand'] == 'UNKNOWN'
                or item.get('marketplace') != MARKETPLACE
                or item.get('historical_seller_checked') or item.get('permanently_excluded')
                or item.get('historical_eligibility') or item.get('historical_eligibility_status')
                or item.get('identity_conflicts')):
            continue
        low = item.get('category', '').casefold() in LOWER_COMPLEXITY
        score = 100 * (item.get('identity_verified') is True) + 5 * min(int(item.get('identity_field_count') or 0), 10) + 25 * low
        candidates.append(dict(asin=asin, brand=item['brand'], title=item.get('title', ''),
            category=item.get('category', ''), marketplace=MARKETPLACE, condition='new_new',
            identity_verified=item.get('identity_verified') is True,
            identity_field_count=item.get('identity_field_count', 0), priority_score=score,
            complexity_hint='LOWER_APPARENT' if low else 'UNASSESSED',
            eligibility_status='UNKNOWN', fba_inbound_status='UNKNOWN',
            walmart_suitability='UNKNOWN', purchase_authorized=False, listing_authorized=False))
    candidates.sort(key=lambda r: (-r['priority_score'], r['asin']))
    selected = []
    counts = Counter()
    for row in candidates:
        key = brand_key(row['brand'])
        if counts[key] >= 2:
            continue
        counts[key] += 1
        selected.append(dict(rank=len(selected) + 1, **row))
        if len(selected) == limit:
            break
    if len(selected) != limit:
        raise ValueError('Insufficient candidates; do not relax evidence gates')
    return selected


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        # Protect spreadsheets while retaining raw JSON source evidence separately.
        writer.writerows({k: "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v
                          for k, v in row.items()} for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('var/m96-offline-review'))
    parser.add_argument('--observations', type=Path)
    args = parser.parse_args()
    paths = {'M79': M79, 'M69': M69, 'M94': M94, 'registry': REGISTRY}
    m95 = sorted(DIRECTORY.glob('m95-eligibility-*.json'))
    if not m95:
        raise ValueError('M95 history required')
    paths.update({f'M95_{i}': p for i, p in enumerate(m95)})
    docs = {key: read_json(path) for key, path in paths.items()}
    records = docs['registry']['records']
    if args.observations:
        records = records + import_observations(args.observations)
        paths['observations'] = args.observations
    historical = audit(DIRECTORY)
    queue = build(docs['M79']['catalog'], docs['M69'],
                  [docs['M94']] + [docs[f'M95_{i}'] for i in range(len(m95))], historical, records)
    args.output.mkdir(parents=True, exist_ok=False)
    write_csv(args.output / 'M96_candidate_queue.csv', queue, list(queue[0]))
    template = [{k: r.get(k, '') for k in FIELDS} for r in queue]
    write_csv(args.output / 'M96_screening_template.csv', template, FIELDS)
    (args.output / 'M96_registry.json').write_text(json.dumps({'records': records}, indent=2) + '\n')
    summary = dict(milestone='M96', mode='OFFLINE_RESEARCH', candidate_count=len(queue),
        verified_unrestricted=0, live_requests=0, execution_authorized=False,
        purchase_authorized=False, listing_authorized=False,
        source_sha256={key: hashlib.sha256(p.read_bytes()).hexdigest() for key, p in paths.items()},
        historical_audit=historical, distinct_brands=len({brand_key(r['brand']) for r in queue}),
        identity_verified=sum(r['identity_verified'] for r in queue))
    (args.output / 'M96_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k not in {'historical_audit', 'source_sha256'}}))


if __name__ == '__main__':
    main()
