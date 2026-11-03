"""Sparse seed and read-only evaluation of the existing research workbook."""
import argparse
import fcntl
import json
import os
from pathlib import Path
from urllib.parse import quote

from app.amazon_evaluation import UNKNOWN, evaluate
from app.amazon_research_queue import QueueClient, SOURCE
from app.sheets_publisher import index, update
from datetime import datetime, timezone

TAB = 'Amazon_Evaluation'
HEADERS = ('asin amazon_url brand amazon_selling_price price_observed_at price_basis '
    'eligibility_status approval_requirements referral_fee fba_fulfillment_fee '
    'fbm_estimated_fulfillment_cost storage_cost inbound_placement_cost sales_rank category '
    'estimated_monthly_sales competing_offers keepa_30_day_price_statistics '
    'keepa_90_day_price_statistics evidence_source evidence_observed_at data_confidence notes '
    'manual_evidence_json').split()


def seed(record):
    """Display observations are descriptive; no lowest-price to New-price inference."""
    view = record.get('observations', {})
    eligibility = record.get('eligibility', {})
    row = dict(asin=record['asin'], amazon_url='https://www.amazon.com/dp/'+record['asin'],
        eligibility_status=eligibility.get('status', UNKNOWN),
        approval_requirements=eligibility.get('approval_requirements', UNKNOWN),
        manual_evidence_json=json.dumps(record, sort_keys=True))
    row.update({k: view[k] for k in HEADERS if k in view and k not in row})
    return [str(row.get(k, UNKNOWN)) if row.get(k) is not None else UNKNOWN for k in HEADERS]


def plan(records, metadata, existing):
    # Validate all evidence before any write; approval blocks still allow unknown economics.
    now = datetime.now(timezone.utc)
    for record in records:
        evaluate(record, now)
    keys = [r['asin'] for r in records]
    if len(keys) != len(set(keys)) or not records or len(records) > 1000:
        raise ValueError('1–1000 unique ASINs required')
    found, _ = index(existing, HEADERS)
    props = {s['properties']['title']: s['properties'] for s in metadata['sheets']}
    requests = []
    if TAB not in props:
        if existing:
            raise ValueError('Inconsistent snapshot')
        used = {p['sheetId'] for p in props.values()}
        sid = next(i for i in range(100, 1000) if i not in used)
        requests.append({'addSheet': {'properties': dict(sheetId=sid, title=TAB,
            gridProperties=dict(rowCount=2002, columnCount=len(HEADERS), frozenRowCount=1))}})
    else:
        sid = props[TAB]['sheetId']
        grid = props[TAB]['gridProperties']
        if grid['columnCount'] < len(HEADERS) or grid['rowCount'] < max(1, len(existing))+len(records):
            raise ValueError('Evaluation grid capacity requires review')
    if not existing:
        requests.append({'repeatCell': {'range': dict(sheetId=sid, startRowIndex=0,
            endRowIndex=1, endColumnIndex=len(HEADERS)), 'cell': {'userEnteredFormat': {
            'backgroundColor': dict(red=0.9, green=0.9, blue=0.9),
            'textFormat': {'bold': True}, 'wrapStrategy': 'WRAP'}}, 'fields': 'userEnteredFormat'}})
        requests.append({'updateDimensionProperties': {'range': dict(sheetId=sid,
            dimension='COLUMNS', startIndex=0, endIndex=len(HEADERS)),
            'properties': {'pixelSize': 180}, 'fields': 'pixelSize'}})
        requests.append(update(sid, 0, 0, HEADERS))
    next_row = max(1, len(existing))
    for record in records:
        # Existing rows belong to researchers. Repeated publication never erases evidence.
        if record['asin'] not in found:
            requests.append(update(sid, next_row, 0, seed(record)))
            next_row += 1
    if len(json.dumps({'requests': requests}).encode()) > 1800000:
        raise ValueError('Batch exceeds 1.8 MB; use a smaller input partition')
    return requests


def snapshot(client, metadata):
    props = next((s['properties'] for s in metadata['sheets'] if s['properties']['title'] == TAB), None)
    if props is None:
        return []
    if props['gridProperties']['rowCount'] > 20002:
        raise ValueError('Snapshot exceeds row bound')
    return client.request('values/'+quote("'"+TAB+"'!A1:X"+str(props['gridProperties']['rowCount']), safe='')+
                          '?valueRenderOption=FORMULA').get('values', [])


def publish(client, records, live=False):
    client.select(SOURCE)  # Exact requested workbook; never Walmart intake workbook.
    metadata = client.metadata()
    existing = snapshot(client, metadata)
    requests = plan(records, metadata, existing)
    if not live:
        return dict(mode='preview', requests=requests, existing_asins=list(index(existing, HEADERS)[0]))
    if client.metadata() != metadata or snapshot(client, metadata) != existing:
        raise ValueError('Evaluation changed during planning')
    if requests:
        client.request(':batchUpdate', {'requests': requests})
    saved = snapshot(client, client.metadata())
    positions, _ = index(saved, HEADERS)
    prior, _ = index(existing, HEADERS)
    if any(saved[positions[k]] != existing[n] for k, n in prior.items()):
        raise ValueError('Concurrent manual edit; inspect evaluation')
    for record in records:
        if record['asin'] not in prior and saved[positions[record['asin']]][:len(HEADERS)] != seed(record):
            raise ValueError('Evaluation readback failed')
    return dict(mode='published', seeded_asins=len(records), existing_evidence_preserved=True)


def read_evaluations(client, now):
    client.select(SOURCE)
    values = snapshot(client, client.metadata())
    positions, _ = index(values, HEADERS)
    results = []
    for asin, row in positions.items():
        record = json.loads(values[row][HEADERS.index('manual_evidence_json')])
        if record.get('asin') != asin:
            raise ValueError('Manual JSON ASIN mismatch')
        result = evaluate(record, now)
        expected = seed(record)
        # A conflicting visible restriction must never be ignored in favor of JSON.
        for field in ('eligibility_status', 'approval_requirements'):
            col = HEADERS.index(field)
            if len(values[row]) <= col or str(values[row][col]) != expected[col]:
                result.update(decision='BLOCKED_DATA', buy_candidate_modes=[],
                    reasons=['Visible eligibility/approval conflicts with manual_evidence_json'])
        results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--live', action='store_true', help='Seed missing ASINs only')
    parser.add_argument('--read', action='store_true', help='Evaluate manual_evidence_json with read-only scope')
    args = parser.parse_args()
    if args.read and (args.live or args.input) or not args.read and not args.input:
        parser.error('Choose --read or --input [--live]')
    records = json.loads(args.input.read_text()) if args.input else None
    path = Path(os.environ['ARBITRAGE_SHEETS_CREDENTIAL_FILE'])
    if not path.is_absolute() or 'WeinsteinAgent' in path.parts:
        raise ValueError('Dedicated absolute credential path required')
    with Path('/tmp/arbitrage-amazon-evaluation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        client = QueueClient(path, writable=args.live)
        result = read_evaluations(client, datetime.now(timezone.utc)) if args.read else publish(client, records, args.live)
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
