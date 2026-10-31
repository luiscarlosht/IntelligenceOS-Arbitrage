"""Offline SP-API catalog snapshots and conservative Amazon target aggregation."""
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from app.amazon_catalog import MARKETPLACE, clean_text, marketplace_row, parse_catalog
from app.amazon_targets import ASIN, AmazonTarget, Identifier
from app.catalog_saved_evidence import saved_evidence
from app.normalization import timestamp
from app.observations import canonical, fingerprint, normalized

NATIONAL_BRANDS = ('Sharpie', 'Post-it', 'Rubbermaid', 'Ziploc', 'Clorox',
                   'Dove', 'Energizer', 'Finish', 'Scotch', 'OXO')
REPORT_PATTERNS = ('catalog-pilot.json', 'catalog-details-pilot.json',
                   'candidates-*.json', 'candidate-details-*.json', 'amazon-first-catalog-*.json')
TARGET_DATA = 'summaries,identifiers,relationships,attributes,salesRanks'
ATTRIBUTES = ('brand', 'size', 'color', 'style', 'number_of_items', 'unit_count',
              'included_components', 'model_number', 'part_number')


def stamp(value):
    result = timestamp(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.utcoffset() is None:
        raise ValueError('Aware evidence observation time required')
    return result


def sales_ranks(item, observed_at, provenance, secrets=()):
    """Rank capture time is local observation time, not an Amazon source timestamp."""
    row = marketplace_row(item, 'salesRanks')
    output = []
    if row is None:
        return output
    for key, id_key in (('classificationRanks', 'classificationId'),
                        ('displayGroupRanks', 'websiteDisplayGroup')):
        values = row.get(key, [])
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError('Invalid sales rank dataset')
        for value in values:
            if (not isinstance(value, dict) or type(value.get('rank')) is not int or value['rank'] <= 0
                    or not isinstance(value.get(id_key), str) or not value[id_key]
                    or not isinstance(value.get('title'), str) or not value['title']):
                raise ValueError('Rank requires category identity, title and positive integer')
            output.append(dict(rank=value['rank'], category_id=clean_text(value[id_key], secrets),
                category_title=clean_text(value['title'], secrets), rank_type=key, marketplace=MARKETPLACE,
                observed_at=normalized(stamp(observed_at)), provenance=provenance + ':salesRanks.' + key,
                source_updated_at=None, interpretation='catalog snapshot; not sales or demand history'))
    return output


def parse_target_item(item, *, observed_at, provenance, is_mock=False, secrets=()):
    """Extend the existing parser for this pilot without changing legacy mappings."""
    observed_at = stamp(observed_at)
    asin = item.get('asin')
    if not isinstance(asin, str) or not ASIN.fullmatch(asin):
        raise ValueError('Invalid ASIN')
    evidence = parse_catalog(item, expected_asin=asin, is_mock=is_mock, secrets=secrets)
    catalog = normalized(replace(evidence.value, retrieved_at=observed_at))
    summary = marketplace_row(item, 'summaries')
    extras = {k: clean_text(summary.get(k), secrets) for k in
              ('brand', 'size', 'color', 'style', 'partNumber')}
    attrs = item.get('attributes', {})
    if not isinstance(attrs, dict):
        raise ValueError('Invalid attribute object')
    package = {}
    for key in ATTRIBUTES:
        values = attrs.get(key, [])
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError('Invalid attribute list')
        scoped = []
        for value in values:
            if not isinstance(value, dict):
                raise ValueError('Invalid attribute value')
            if value.get('marketplace_id') != MARKETPLACE:
                continue
            # Preserve structured unit values and units; do not flatten count into pack.
            allowed = {k: value[k] for k in ('value', 'unit', 'type') if k in value}
            def sanitized(v):
                if isinstance(v, str):
                    return clean_text(v, secrets)
                if isinstance(v, dict):
                    return {k: sanitized(x) for k, x in v.items() if k in ('value', 'unit', 'type')}
                if type(v) in (int, float) and str(v) not in ('nan', 'inf', '-inf'):
                    return v
                return None
            scoped.append(sanitized(allowed))
        if scoped:
            package[key] = scoped
    return dict(asin=asin, marketplace=MARKETPLACE, observed_at=normalized(observed_at),
        provenance=provenance, is_mock=is_mock, kind='catalog_item', catalog=catalog,
        package_attributes=package, summary_fields=extras,
        sales_ranks=sales_ranks(item, observed_at, provenance, secrets))


def read_report(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Bounded nonsymlink evidence file required')
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def audit_saved(directory):
    """Read only named evidence reports. Never enumerate/read credential contents or ledgers."""
    directory = Path(directory)
    paths = sorted({p for pattern in REPORT_PATTERNS for p in directory.glob(pattern)})
    if len(paths) > 100:
        raise ValueError('Audit limited to 100 allowlisted catalog reports')
    snapshots, inventory, blocked, known = [], [], set(), set()
    for path in paths:
        document, digest = read_report(path)
        ref = path.name + '#sha256=' + digest
        inventory.append(dict(file=path.name, sha256=digest, status=document.get('status')))
        if document.get('is_mock') is True:
            continue
        manifest = document.get('manifest') or {}
        if document.get('mode') == 'sp_api_amazon_first_v1' and document.get('is_mock') is False:
            specs = {r['query_id']: r for r in manifest.get('requests', [])}
            received = {a.get('query_id') for a in document.get('attempts', [])
                        if a.get('kind') == 'search' and a.get('status') == 'response_received'}
            values = document.get('catalog_snapshots', [])
            if not isinstance(values, list) or len(values) > 20:
                raise ValueError('Bounded normalized target snapshots required')
            for value in values:
                spec = specs.get(value.get('query_id'), {})
                if (value.get('query_id') not in received or spec.get('params', {}).get('marketplaceIds') != MARKETPLACE
                        or value.get('marketplace') != MARKETPLACE or value.get('is_mock') is not False
                        or not ASIN.fullmatch(value.get('asin', ''))):
                    raise ValueError('Unbound saved target snapshot')
                snapshots.append(dict(value, provenance=ref + ':' + value['provenance']))
            continue
        rows = document.get('rows') or []
        if not isinstance(rows, list):
            raise ValueError('Invalid saved report rows')
        # Existing helper enforces source fingerprints, marketplace and successful detail attempts.
        if 'manifest' in document and 'requests' in manifest:
            cache, attempted, _ = saved_evidence([path])
            blocked.update(attempted)
            for asin, evidence in cache.items():
                value = evidence['value']
                catalog = value['catalog']
                observed = stamp(evidence['observed_at'])
                snapshots.append(dict(asin=asin, marketplace=MARKETPLACE,
                    observed_at=normalized(observed), provenance=ref + ':' + evidence['provenance'],
                    kind='saved_catalog_detail', is_mock=False, catalog=catalog,
                    package_attributes=value.get('package_attributes', {}), summary_fields={}, sales_ranks=[]))
        # Standalone normalized catalog pilots: successful catalog evidence may survive a later-stage failure.
        evidence = document.get('catalog') or {}
        catalog = evidence.get('value') or {}
        if (document.get('marketplace_id') == MARKETPLACE and evidence.get('is_mock') is False
                and catalog.get('is_mock') is False and ASIN.fullmatch(catalog.get('asin', ''))
                and 'Catalog Items' in evidence.get('provenance', '')):
            snapshots.append(dict(asin=catalog['asin'], marketplace=MARKETPLACE,
                observed_at=normalized(stamp(evidence['observed_at'])), provenance=ref + ':' + evidence['provenance'],
                kind='saved_catalog_detail', is_mock=False, catalog=catalog,
                package_attributes={}, summary_fields={}, sales_ranks=[]))
        for row in rows:
            search = row.get('search') or {}
            source = row.get('source') or {}
            specs = [s for s in manifest.get('requests', []) if s.get('ordinal') == row.get('ordinal')]
            success = any(a.get('kind') == 'search' and a.get('ordinal') == row.get('ordinal')
                          and a.get('status') == 'response_received' for a in document.get('attempts', []))
            compatible = (document.get('is_mock') is False and len(specs) == 1
                and specs[0].get('source_fingerprint') == fingerprint(source)
                and specs[0].get('search', {}).get('params', {}).get('marketplaceIds') == MARKETPLACE)
            for candidate in search.get('candidates', []):
                asin = candidate.get('asin', '')
                if not isinstance(asin, str) or not ASIN.fullmatch(asin):
                    raise ValueError('Invalid saved candidate ASIN')
                known.add(asin)
                if not compatible or not success or not search.get('observed_at'):
                    continue
                snapshots.append(dict(asin=asin, marketplace=MARKETPLACE,
                    observed_at=normalized(stamp(search['observed_at'])), provenance=ref + ':search:ordinal=' + str(row['ordinal']),
                    kind='saved_search_summary', is_mock=False,
                    catalog=dict(asin=asin, title=candidate.get('title'), identifiers=[]),
                    package_attributes={}, summary_fields={'brand': candidate.get('brand')}, sales_ranks=[]))
    return snapshots, dict(reports=inventory, report_count=len(inventory),
        known_search_asins=len(known), attempted_detail_asins=sorted(blocked),
        normalized_snapshots=len(snapshots), credential_files_read=0, live_requests=0)


def attribute_values(values):
    output = []
    for value in values:
        if isinstance(value, dict) and set(value) <= {'value'}:
            value = value.get('value')
        if value is not None and value != '':
            output.append(value)
    return output


def aggregate_targets(snapshots, *, now):
    """Deduplicate by marketplace/ASIN; retain every conflicting value and provenance."""
    now = stamp(now)
    grouped = defaultdict(list)
    for snapshot in snapshots:
        if snapshot.get('marketplace') != MARKETPLACE or snapshot.get('is_mock') is not False:
            continue
        if stamp(snapshot['observed_at']) > now:
            raise ValueError('Future snapshot')
        grouped[snapshot['asin']].append(snapshot)
    targets = []
    for asin, records in sorted(grouped.items()):
        evidence = defaultdict(dict)
        identifiers, ranks, issues, kinds = {}, {}, set(), set()
        for record in records:
            observed = stamp(record['observed_at'])
            catalog = record['catalog']
            ref = record['provenance']
            kinds.add(record['kind'])
            issues.update(catalog.get('mapping_issues', []))
            def add(key, value, field):
                if value is None or value == '' or value == []:
                    return
                point = dict(value=value, observed_at=record['observed_at'], provenance=ref + ':' + field)
                evidence[key][fingerprint(point)] = point
            for key in ('title', 'manufacturer', 'model', 'variation', 'package_quantity', 'item_classification', 'relationships'):
                add(key, catalog.get(key), 'catalog.' + key)
            for key, value in record.get('summary_fields', {}).items():
                add(key, value, 'summaries.' + key)
            for key, values in record.get('package_attributes', {}).items():
                for value in attribute_values(values):
                    add(key, value, 'attributes.' + key)
            for item in catalog.get('identifiers', []):
                if item.get('identifier_type') not in ('UPC', 'EAN', 'GTIN'):
                    continue
                ident = Identifier(item['identifier_type'], item['value'], ref + ':identifiers', observed)
                identifiers[fingerprint(ident)] = ident
            for rank in record.get('sales_ranks', []):
                ranks[fingerprint(rank)] = rank
        resolved = {}
        for key, points in evidence.items():
            values = {canonical(p['value']): p['value'] for p in points.values()}
            resolved[key] = dict(value=next(iter(values.values())) if len(values) == 1 else None,
                                 status='reported' if len(values) == 1 else 'conflicting',
                                 evidence=list(points.values()))
        value = lambda key: resolved.get(key, {}).get('value')
        missing = [key for key in ('brand', 'manufacturer', 'model', 'size', 'variation', 'package_quantity') if value(key) is None]
        if not identifiers:
            missing.append('identifiers')
        canonical_ids = set()
        from app.normalization import gtin
        for ident in identifiers.values():
            try:
                canonical_ids.add(gtin(ident.value))
            except ValueError:
                issues.add('Invalid identifier retained for review')
        if len(canonical_ids) > 1:
            issues.add('Ambiguous GTIN identifiers')
        if not ranks:
            missing.append('sales_rank_not_saved_or_not_returned')
        missing += ['demand_history', 'monthly_sales', 'current_price', 'fees', 'seller_restrictions', 'retailer_exact_match']
        stamps = [stamp(r['observed_at']) for r in records]
        target = AmazonTarget(asin=asin, created_at=min(stamps), observed_at=max(stamps), fetched_at=now,
            provenance='Saved SP-API evidence; ' + '; '.join(sorted(kinds)),
            title=value('title'), brand=value('brand'), manufacturer=value('manufacturer'), model=value('model'),
            identifiers=tuple(identifiers.values()), exact_package_evidence=resolved,
            historical_metrics=dict(sales_rank_snapshots=list(ranks.values()), monthly_sales=None,
                demand_history=None, evidence_kinds=sorted(kinds), mapping_issues=sorted(issues),
                interpretation='catalog presence and search position are not demand; ranks only within same category'),
            current_price_context=dict(executable_sale_price=None, source_updated_at=None),
            missing_fields=tuple(missing))
        targets.append(target)
    return targets


def identity_priority(target):
    """No numeric sales rank enters selection or sorting."""
    detail = any(k != 'saved_search_summary' for k in target.historical_metrics['evidence_kinds'])
    conflicts = sum(v['status'] == 'conflicting' for v in target.exact_package_evidence.values())
    issues = target.historical_metrics['mapping_issues']
    complete = sum(bool(getattr(target, k)) for k in ('brand', 'manufacturer', 'model'))
    complete += sum(target.exact_package_evidence.get(k, {}).get('value') is not None
                    for k in ('size', 'package_quantity', 'variation'))
    return (-int(detail), len(issues), conflicts, -complete, -int(bool(target.identifiers)), target.asin)


def select_targets(targets, maximum=20):
    if type(maximum) is not int or not 1 <= maximum <= 20:
        raise ValueError('Target cap must be one to twenty')
    allowed = {b.casefold() for b in NATIONAL_BRANDS}
    eligible = [t for t in targets if (t.brand or '').casefold() in allowed
                and t.asin != 'B0G1MJ24B4'
                and t.exact_package_evidence.get('item_classification', {}).get('value') != 'VARIATION_PARENT']
    return sorted(eligible, key=identity_priority)[:maximum]
