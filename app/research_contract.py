"""Versioned data boundary for candidate publication and Browser Use observations."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

UNKNOWN = 'UNKNOWN'
AMAZON = 'priority,asin,amazon_title,brand,upc,model,pack_count,amazon_url,amazon_price,category,eligibility_status,demand_status,source_reference,research_status'.split(',')
IDENTITY = 'gtin,size,variant,condition,identity_evidence,restrictions'.split(',')
WALMART = 'asin,walmart_url,walmart_title,walmart_upc,walmart_model,walmart_brand,walmart_pack_count,match_status,walmart_price,shipping_cost,seller,fulfillment,availability,research_timestamp,evidence_url,confidence,notes'.split(',')
STATUSES = ('EXACT_MATCH', 'POSSIBLE_MATCH', 'NO_MATCH', 'NOT_FOUND', 'REVIEW_REQUIRED')
SCHEMAS = {
    'Amazon_Candidates': AMAZON + IDENTITY,
    'Walmart_Research': WALMART,
    'Profitability': 'asin,status,acquisition_cost,sale_price,net_profit,margin_percent,roi_percent,missing_gates'.split(','),
    'Top_Opportunities': 'asin,status,net_profit,roi_percent,rank'.split(','),
    'Review_Queue': 'asin,status,reasons'.split(','),
    'Run_Log': 'run_id,published_at,scope,candidate_count,source_sha256,status'.split(','),
}


def text(value):
    if value is None or value == '' or value == []: return UNKNOWN
    return json.dumps(value, sort_keys=True, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)


def candidates(handoff: Path, expected_sha: str, scope: str = '20') -> tuple[list[dict], str]:
    """Read original hash-bound M79; no credential or acquisition-ledger access."""
    from app.m80_contract import source
    data, selected, digest = source(handoff, expected_sha)
    if scope not in ('20', '100', 'all'): raise ValueError('Unsupported scope')
    if scope == '100': selected = data['research_queue'][:100]
    if scope == 'all': selected = data['all_asins']
    # Category and historical restrictions live in the separately hash-bound report.
    completion = json.loads((handoff.parent / 'M79_completion.json').read_text())
    if completion['output_sha256']['M79_walmart_handoff.json'] != digest:
        raise ValueError('Completion handoff mismatch')
    report_path = handoff.parent / 'M79_report.json'
    raw = report_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != completion['output_sha256']['M79_report.json']:
        raise ValueError('Report hash mismatch')
    report = json.loads(raw)
    catalog = {r['asin']: r for r in report['catalog']}
    result = []
    for i, row in enumerate(selected, 1):
        extra = catalog[row['asin']]
        if any(row.get(k) for k in ('is_mock', 'is_synthetic', 'synthetic')):
            raise ValueError('Synthetic records cannot be published')
        refs = row.get('source_references', [])
        if not refs or not row.get('field_provenance'): raise ValueError('Observed identity provenance required')
        result.append(dict(zip(AMAZON, map(text, [
            row.get('research_position', i), row['asin'], row.get('title'), row.get('brand'),
            row.get('upc_values'), row.get('model'), row.get('pack_quantity'),
            'https://www.amazon.com/dp/' + row['asin'], row.get('amazon_price'), extra.get('category'),
            row.get('eligibility'), UNKNOWN, refs, 'PENDING',
        ])), gtin=text(row.get('gtin')), size=text(row.get('size')), variant=text(row.get('variation')),
            condition=text(row.get('condition')), identity_evidence=text({k:row.get(k) for k in
                ('field_provenance','field_status','identity_conflicts','identity_verified','quantity_basis')}),
            restrictions=text({k:extra.get(k) for k in ('historical_eligibility','historical_eligibility_status',
                'permanently_excluded','identity_conflicts','sourcing_allowed','purchase_authorized')})))
    validate_candidates(result)
    if scope == '20' and len(result) != 20: raise ValueError('Exactly 20 candidates required')
    return result, digest


def validate_candidates(rows):
    if not rows or len(rows) > 10000: raise ValueError('1 to 10000 candidates required')
    seen = set()
    for row in rows:
        if set(row) != set(SCHEMAS['Amazon_Candidates']): raise ValueError('Candidate schema mismatch')
        asin = row['asin']
        if not re.fullmatch(r'B[A-Z0-9]{9}', asin) or asin in seen: raise ValueError('Distinct ASIN required')
        if any(not isinstance(v, str) or not v or len(v) > 45000 for v in row.values()):
            raise ValueError('Bounded nonempty string cells required')
        seen.add(asin)


def validate_observation(row: dict, candidate: dict, identity_review: dict | None = None) -> dict:
    """Browser assertions never clear seller, demand, fee or purchase gates."""
    if set(row) != set(WALMART) or row['asin'] != candidate['asin']:
        raise ValueError('Observation schema/ASIN mismatch')
    if row['match_status'] not in STATUSES: raise ValueError('Invalid match status')
    for k, v in row.items():
        if not isinstance(v, str) or not v or len(v) > 45000: raise ValueError('Explicit strings/UNKNOWN required')
    for key in ('walmart_url', 'evidence_url'):
        if row[key] != UNKNOWN:
            u = urlsplit(row[key])
            if u.scheme != 'https' or u.hostname not in ('walmart.com', 'www.walmart.com') or u.username or u.password or u.port not in (None,443):
                raise ValueError('Walmart HTTPS evidence required')
    if row['research_timestamp'] != UNKNOWN:
        stamp = datetime.fromisoformat(row['research_timestamp'].replace('Z', '+00:00'))
        if stamp.utcoffset() is None: raise ValueError('Aware observation time required')
    for key in ('walmart_price', 'shipping_cost', 'confidence'):
        if row[key] != UNKNOWN:
            try: value = Decimal(row[key])
            except InvalidOperation: raise ValueError('Invalid numeric value') from None
            if not value.is_finite() or value < 0 or (key == 'confidence' and value > 1):
                raise ValueError('Invalid numeric bounds')
    if row['match_status'] == 'EXACT_MATCH':
        from app.normalization import gtin
        review = identity_review or {}
        if review.get('owner_reviewed') is not True or review.get('asin') != row['asin']:
            raise ValueError('Independent identity review required')
        if not re.fullmatch('[a-f0-9]{64}',str(review.get('artifact_sha256',''))):
            raise ValueError('Saved identity artifact hash required')
        for key in ('walmart_url','evidence_url','research_timestamp'):
            if row[key] == UNKNOWN or review.get(key) != row[key]: raise ValueError('Scoped identity review required')
        for a, w in (('brand','walmart_brand'),('model','walmart_model'),('pack_count','walmart_pack_count')):
            if candidate[a] == UNKNOWN or row[w] != candidate[a]: raise ValueError('Exact product identity required')
        if candidate['gtin'] == UNKNOWN or not gtin(row['walmart_upc']) or gtin(row['walmart_upc']) != gtin(candidate['gtin']):
            raise ValueError('Exact checksum-valid barcode required')
        for key in ('size','variant','condition'):
            a=review.get('amazon_'+key);w=review.get('walmart_'+key)
            if not isinstance(a,str) or a in ('',UNKNOWN) or a != w: raise ValueError('Exact size/variant/condition required')
            if candidate[key] != UNKNOWN and a != candidate[key]: raise ValueError('Frozen identity contradiction')
        if review['amazon_condition'] != 'NEW': raise ValueError('Explicit New condition required')
    return dict(row)


def browser_contract(rows: list[dict]) -> dict:
    validate_candidates(rows)
    return dict(schema_version=1, candidates=rows, output_columns=WALMART,
        allowed_match_statuses=list(STATUSES), writable_tab='Walmart_Research', key='asin',
        instructions=['Keep Amazon_Candidates read-only.', 'Use UNKNOWN for unavailable facts.',
            'Verify barcode, brand, model, pack count, size, variant and New condition with cited evidence.',
            'EXACT_MATCH requires independent richer identity_review (see documentation); use POSSIBLE_MATCH until reviewed.',
            'Catalog pack_count is preserved verbatim; title unit counts may describe inner units. Never infer pack conversions.',
            'Do not infer fees, eligibility, demand or purchase permission from a product match.'],
        sample_output={**dict.fromkeys(WALMART, UNKNOWN), 'asin':rows[0]['asin'],
                       'match_status':'REVIEW_REQUIRED', 'notes':'Contract example; research has not been performed.'})
