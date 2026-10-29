"""Read-only stored-batch audit and offline Amazon candidate request planning."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from app.normalization import timestamp
from app.observations import canonical, fingerprint, normalized
from app.sheets_intake import BATCH_FIELDS, product
from app.source_keywords import search_keywords

MARKETPLACE = 'ATVPDKIKX0DER'


def read_json(path):
    raw = Path(path).read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('Offline evidence exceeds bound')
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def audit_database(path, batch_id):
    """No schema initialization, database creation, acknowledgment or history writes."""
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('Database integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Database foreign-key check failed')
        counts = {name: db.execute('SELECT count(*) FROM '+name).fetchone()[0]
                  for name in ('sheets_batches', 'sheets_records', 'source_observations')}
        batches = db.execute('SELECT batch_id,content_hash,metadata_json,acknowledged_at FROM sheets_batches WHERE batch_id=?', (batch_id,)).fetchall()
        if len(batches) != 1:
            raise ValueError('Expected one selected intake batch')
        stored_id, digest, metadata_json, acknowledged = batches[0]
        if stored_id != batch_id or not acknowledged:
            raise ValueError('Expected acknowledged batch not found')
        metadata = json.loads(metadata_json)
        count_text = metadata.get('actual_record_count', '')
        if not re.fullmatch(r'[1-9][0-9]{0,3}', count_text) or not 1 <= int(count_text) <= 1000:
            raise ValueError('Batch must contain 1 to 1000 records')
        count = int(count_text)
        records = db.execute('''SELECT r.record_id,r.batch_id,r.content_hash,r.original_json,
            o.fingerprint,o.observed_at,o.payload_json,r.observation_id
            FROM sheets_records r JOIN source_observations o ON o.id=r.observation_id
            WHERE r.batch_id=? ORDER BY r.record_id''', (batch_id,)).fetchall()
        if len(records) != count or len({r[0] for r in records}) != count or len({r[7] for r in records}) != count:
            raise ValueError('Unique source records and observation links required for every batch row')
        rows, products = [], []
        for rid, bid, row_hash, original_json, source_hash, observed, payload_json, _ in records:
            row = json.loads(original_json)
            p = product(row)
            raw = json.loads(row['raw_record_json'])
            if (row['record_id'] != rid or row['batch_id'] != bid or bid != batch_id
                    or fingerprint(row) != row_hash or fingerprint(p) != source_hash
                    or canonical(p) != canonical(json.loads(payload_json))):
                raise ValueError('Stored source/hash association mismatch')
            raw_stamp = raw.get('observation_timestamp', raw.get('observed_at_utc'))
            if not (timestamp(raw_stamp) == timestamp(row['observed_at_utc']) == timestamp(observed)):
                raise ValueError('Observation timestamp not preserved')
            rows.append(row); products.append(p)
        if (metadata.get('status') != 'COMPLETE' or metadata.get('batch_id') != batch_id
                or metadata.get('expected_record_count') != str(count) or metadata.get('actual_record_count') != str(count)
                or set(metadata) != set(BATCH_FIELDS[:5])
                or fingerprint(dict(batch=metadata, rows=rows)) != digest):
            raise ValueError('Batch metadata/content hash mismatch')
        if any(timestamp(row['exported_at_utc']) > timestamp(metadata['completed_at_utc']) for row in rows):
            raise ValueError('Batch timestamp order mismatch')
    return dict(**counts, unique_record_ids=count, unique_observation_links=count,
                batch_id=batch_id, acknowledged_at=acknowledged, batch_content_hash=digest,
                original_json_hashes_verified=True, observation_timestamps_verified=True,
                normalized_payloads_verified=True, sqlite_integrity='ok'), rows, products


def compatible_search(report, row, p):
    if report.get('is_mock') is not False or report.get('manifest', {}).get('marketplace_id') != MARKETPLACE:
        return None
    matches = []
    for saved in report.get('rows', []):
        source = saved.get('source') or {}; context = source.get('source_context') or {}
        if (source.get('retailer') == 'Walmart' and context.get('retailer_item_id') == row['walmart_item_id']
                and source.get('url') == row['product_url']):
            left, right = context.get('brand'), p.source_context.get('brand')
            if left and right and left.casefold() != right.casefold():
                continue
            search = saved.get('search')
            specs = [s for s in report['manifest'].get('requests', []) if s['ordinal'] == saved['ordinal']]
            attempts = [a for a in report.get('attempts', [])
                        if a.get('kind') == 'search' and a.get('ordinal') == saved['ordinal']]
            if (search and len(specs) == 1 and specs[0]['source_fingerprint'] == fingerprint(source)
                    and specs[0]['search']['params'].get('marketplaceIds') == MARKETPLACE
                    and specs[0]['search']['params'].get('keywords') == search.get('keywords')
                    and len(attempts) == 1 and attempts[0].get('status') == 'response_received'
                    and timestamp(search.get('observed_at')) is not None):
                matches.append(saved)
    if len(matches) > 1:
        raise ValueError('Ambiguous saved source binding')
    return matches[0] if matches else None


def plan(database, batch_id, reports, selections, *, evaluated_at=None):
    evaluated_at = evaluated_at or datetime.now(timezone.utc)
    audit, rows, products = audit_database(database, batch_id)
    if set(selections) != {r['walmart_item_id'] for r in rows}:
        raise ValueError('Exactly the stored item selections required')
    evidence = []
    for path in reports:
        report, digest = read_json(path)
        evidence.append((Path(path), digest, report))
    results, requests, detail_cache, attempted_details = [], {}, {}, set()
    # Retain prior completed details by ASIN; never replace their timestamps.
    for path, digest, report in evidence:
        if report.get('is_mock') is not False or report.get('manifest', {}).get('marketplace_id') != MARKETPLACE:
            continue
        for saved in report.get('rows', []):
            detail = saved.get('detail') or {}; catalog = (detail.get('value') or {}).get('catalog') or {}
            asin = catalog.get('asin')
            attempts = [a for a in report.get('attempts', [])
                        if a.get('kind') == 'detail' and a.get('ordinal') == saved.get('ordinal')]
            if attempts and (saved.get('search') or {}).get('selected_asin'):
                attempted_details.add(saved['search']['selected_asin'])
            specs = [s for s in report['manifest'].get('requests', []) if s['ordinal'] == saved['ordinal']]
            scope_ok = (len(specs) == 1 and specs[0].get('detail', {}).get('params', {}).get('marketplaceIds') == MARKETPLACE
                        and (saved.get('search') or {}).get('selected_asin') == asin)
            successful = any(a.get('kind') == 'detail' and a.get('ordinal') == saved.get('ordinal')
                             and a.get('status') == 'response_received' for a in report.get('attempts', []))
            if (asin and scope_ok and detail.get('is_mock') is False and catalog.get('is_mock') is False
                    and successful and timestamp(detail.get('observed_at')) is not None):
                detail_cache.setdefault(asin, []).append(dict(report=str(path), sha256=digest,
                    observed_at=detail['observed_at'], evidence=detail))
    for row, p in zip(rows, products):
        item = row['walmart_item_id']; choice = selections[item]
        asin = choice['asin']
        if not re.fullmatch(r'[A-Z0-9]{10}', asin) or not choice.get('reason'):
            raise ValueError('Explicit reviewed ASIN and selection reason required')
        sources = [(path, digest, report, saved) for path, digest, report in evidence
                   if (saved := compatible_search(report, row, p)) is not None]
        if len(sources) != 1:
            raise ValueError('One compatible saved search required; no automatic replacement search')
        path, digest, report, saved = sources[0]
        search = saved['search']
        candidates = [c for c in search.get('candidates', []) if c['asin'] == asin]
        if len(candidates) != 1:
            raise ValueError('Reviewed ASIN must occur once in retained candidate search')
        stamp = timestamp(search['observed_at'])
        if stamp > evaluated_at:
            raise ValueError('Saved search timestamp is in the future')
        age = (evaluated_at-stamp).total_seconds()/3600
        details = detail_cache.get(asin, [])
        if len({fingerprint(d['evidence']['value']) for d in details}) > 1:
            raise ValueError('Conflicting saved catalog details require manual review')
        if not details and asin in attempted_details:
            raise ValueError('Chosen catalog stage was already attempted; manual review required')
        if not details:
            requests.setdefault(asin, dict(kind='catalog_detail', asin=asin, method='GET',
                path='/catalog/2022-04-01/items/'+asin,
                params=dict(marketplaceIds=MARKETPLACE, includedData='summaries,identifiers,relationships,attributes'),
                reason='Reviewed candidate lacks retained catalog detail', source_record_ids=[]))['source_record_ids'].append(row['record_id'])
        results.append(dict(record_id=row['record_id'], walmart_item_id=item, title=p.name,
            item_price_usd=row['item_price_usd'], selected_variant=p.variation,
            observed_at_utc=row['observed_at_utc'], original_raw_sha256=hashlib.sha256(row['raw_record_json'].encode()).hexdigest(),
            source_fingerprint=fingerprint(p), keywords=search_keywords(p), candidate_asin=asin,
            candidate_title=candidates[0]['title'], selection_reason=choice['reason'], exact=False,
            search_reuse=dict(report=str(path), report_sha256=digest, original_ordinal=saved['ordinal'],
                observed_at=search['observed_at'], historical_keywords=search['keywords'],
                original_source_fingerprint=fingerprint(saved['source']),
                current_keywords_equal=search['keywords'] == search_keywords(p),
                scope='Historical candidate leads for same Walmart ID/URL; not current-query coverage or identity proof',
                incomplete=bool(search.get('more_results') or not search.get('complete')),
                age_hours=round(age, 3), older_than_24_hours=age > 24),
            catalog_detail_reuse=details, previous_selected_asin=search.get('selected_asin'),
            previous_selection_disposition=choice['previous_selection_disposition'],
            missing_source_evidence=['Verified barcode or manufacturer/model',
                'Independent retail package quantity/composition and selected variant confirmation'],
            missing_downstream_evidence=['New/Consumer pricing','Seller-scoped new_new restrictions','Price-bound FBA fee scenario'],
            purchase_approved=False))
    count = len(requests)
    return dict(schema=1, action='offline_stored_batch_candidate_plan', evaluated_at=normalized(evaluated_at),
        audit=audit, selections_sha256=fingerprint(selections), rows=results, requests=list(requests.values()),
        budget=dict(authentication=1 if count else 0, search=0, catalog_detail=count,
                    pricing=0, fees=0, restrictions=0, maximum_requests=count+(1 if count else 0),
                    retries=0, pagination=0, automatic_refresh=0),
        deferred_enrichment_budget=dict(conditional_on_identity_and_seller_review=True,
            authentication=1, pricing=len(rows), restrictions=len(rows), fees_at_most=len(rows), maximum_requests=1+3*len(rows),
            fee_condition='Skip fees without explicit valid scenario price; missing charges never become zero'),
        reused_searches=len(results), live_requests=0, execution_authorized=False,
        execution_supported=False, notice='Offline preview only; prepare a separate hash-bound execution manifest with amazon_candidates prepare-details. No automatic retries, refreshes or repeat calls.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, help='Offline input manifest instead of individual input flags')
    parser.add_argument('--database', type=Path)
    parser.add_argument('--batch-id')
    parser.add_argument('--saved-report', type=Path, action='append')
    parser.add_argument('--selections', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.inputs:
            if any((args.database, args.batch_id, args.saved_report, args.selections)):
                raise ValueError('Use one input configuration')
            inputs, _ = read_json(args.inputs)
            args.database = Path(inputs['database'])
            args.batch_id = inputs['batch_id']
            args.saved_report = [Path(p) for p in inputs['saved_reports']]
            args.selections = Path(inputs['selections'])
        if not all((args.database, args.batch_id, args.saved_report, args.selections)):
            raise ValueError('All offline inputs required')
        selections, _ = read_json(args.selections)
        result = plan(args.database, args.batch_id, args.saved_report, selections)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write(canonical(result)+'\n')
        print(canonical(dict(audit=result['audit'], reused_searches=result['reused_searches'],
            budget=result['budget'], live_requests=0, execution_authorized=False)))
        return 0
    except (OSError, ValueError, KeyError, sqlite3.Error):
        print('Offline plan stopped; input validation failed or output already exists. No live calls.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
