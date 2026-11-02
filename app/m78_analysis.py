"""Curated M76 decisions plus M70-normalized saved observations."""
from collections import defaultdict
from copy import deepcopy

from app.m65_intelligence import ASIN
from app.m70_identity import FIELDS, merge


def analyze(curated: list[dict], observations: list[dict], annotations: list[dict]) -> dict:
    catalog = {}
    for original in curated:
        p = deepcopy(original)
        asin = p['asin']
        if not ASIN.fullmatch(asin) or asin in catalog:
            raise ValueError('Unique curated ASINs required')
        historical_record = p.get('historical_m73_record')
        if isinstance(historical_record, dict):
            p['review_blocks'] = sorted(set(p.get('review_blocks', []) + historical_record.get('review_blocks', [])))
        # Preserve curated values and conflict decisions; never re-merge as observations.
        if ((p.get('identity_complete') is False and all(p.get(f) is not None for f in FIELDS))
                or (p.get('catalog_identity_complete') is False and all(p.get(f) is not None for f in FIELDS if f != 'condition'))):
            p.setdefault('review_blocks', []).append('CURATED_INCOMPLETE_DECISION')
        p['cohorts'] = sorted(set(p.get('cohorts', []) + ['M76']))
        catalog[asin] = p
    historical = {}
    for row in annotations:
        asin = row['asin']
        if not ASIN.fullmatch(asin) or asin in historical:
            raise ValueError('Unique historical annotations required')
        historical[asin] = deepcopy(row)
    grouped = defaultdict(list)
    for obs in observations:
        if obs['role'] != 'amazon':
            raise ValueError('Amazon catalog observations required')
        grouped[obs['asin']].append(obs)
    overlap = sorted(catalog.keys() & grouped.keys())
    for asin, rows in sorted(grouped.items()):
        normalized = merge(rows)
        if asin in catalog:
            # Curated decisions win; retain later evidence separately for human review.
            catalog[asin]['m77_overlap_evidence'] = normalized
            catalog[asin].setdefault('review_blocks', []).append('M76_M77_OVERLAP_REVIEW')
            catalog[asin]['cohorts'].append('M77')
        else:
            normalized.update(cohorts=['M77'])
            catalog[asin] = normalized
    for asin, p in sorted(catalog.items()):
        historical_row = historical.get(asin, {})
        p['permanently_excluded'] = bool(p.get('permanently_excluded') or historical_row.get('permanently_excluded'))
        p['previously_checked_seller_specific'] = bool(p.get('previously_checked_seller_specific') or historical_row.get('previously_checked_seller_specific'))
        p['missing_fields'] = [f for f in FIELDS if p.get(f) is None]
        p.setdefault('identity_conflicts', [])
        p.setdefault('review_blocks', [])
        p.setdefault('field_provenance', {})  # Missing provenance remains unknown.
        blocked = bool(p['permanently_excluded'] or p['identity_conflicts'] or p['review_blocks'])
        p['classification'] = 'Blocked' if blocked else 'Needs review' if p['missing_fields'] else 'Identity ready'
        p['identity_complete'] = not blocked and not p['missing_fields']
        p['catalog_identity_complete'] = not p['identity_conflicts'] and not p['review_blocks'] and all(p.get(f) is not None for f in FIELDS if f != 'condition')
        p.update(eligibility='UNKNOWN', economics='UNKNOWN', purchase_ready=False, purchase_authorized=False)
    records = [catalog[a] for a in sorted(catalog)]
    for asin, row in historical.items():
        row['in_catalog'] = asin in catalog
    summary = dict(distinct_catalog_asins=len(records), m76_asins=len(curated), m77_asins=len(grouped),
        overlap_asins=len(overlap), duplicate_m77_observations=len(observations)-len(grouped),
        catalog_identity_complete=sum(p['catalog_identity_complete'] for p in records),
        identity_complete=sum(p['identity_complete'] for p in records),
        conflict_asins=sum(bool(p['identity_conflicts']) for p in records),
        excluded_catalog_records=sum(p['permanently_excluded'] for p in records),
        historical_permanent_exclusions=sum(bool(p.get('permanently_excluded')) for p in historical.values()),
        historical_excluded_in_catalog=sum(bool(p.get('permanently_excluded')) and p['in_catalog'] for p in historical.values()),
        historical_excluded_outside_catalog=sum(bool(p.get('permanently_excluded')) and not p['in_catalog'] for p in historical.values()),
        historical_seller_checks=sum(bool(p.get('previously_checked_seller_specific')) for p in historical.values()),
        purchase_ready=sum(bool(p['purchase_ready']) for p in records), eligibility='UNKNOWN', economics='UNKNOWN', network_requests=0,
        missing_fields={f: sum(p.get(f) is None for p in records) for f in FIELDS})
    return dict(summary=summary, catalog=records, annotations=[historical[a] for a in sorted(historical)], overlap=overlap)
