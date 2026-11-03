"""Reusable analysis report over the existing evaluation engine; no network I/O."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from app.amazon_evaluation import EvaluationPolicy, evaluate, mapping, timestamp
from app.analysis_adapters import MARKET_FIELDS, legacy_market
from app.decision_history import database
from app.observations import canonical, fingerprint

CONFIDENCE = ('HIGH', 'MEDIUM', 'LOW', 'UNKNOWN')
UNKNOWN = 'UNKNOWN'


def normalized_observation(item: object) -> dict:
    item = deepcopy(mapping(item))
    for key in ('value', 'source', 'observed_at', 'confidence', 'condition', 'basis'):
        if item.get(key) is None or item.get(key) == '':
            item[key] = UNKNOWN
    # Retain unsupported confidence labels as notes; never imply measured confidence.
    if item['confidence'] not in CONFIDENCE:
        item['confidence_note'] = item['confidence']
        item['confidence'] = UNKNOWN
    return item


def attributed(item: dict, now: datetime, hours: int = 24) -> bool:
    return (item['value'] != UNKNOWN and isinstance(item['source'], str)
            and item['source'].strip() not in ('', UNKNOWN)
            and timestamp(item['observed_at'], now, hours)
            and item['confidence'] != UNKNOWN and item.get('assumed') is not True)


def evidence_tree(value: object) -> object:
    if isinstance(value, list):
        return [evidence_tree(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {k: evidence_tree(v) for k, v in value.items()}
    if 'value' in result or 'observed_at' in result:
        result.setdefault('confidence', UNKNOWN)
        result.setdefault('source', result.get('source_reference', UNKNOWN))
        result.setdefault('observed_at', UNKNOWN)
    return result


def observation_paths(value: object, predicate, path: str = '') -> list[str]:
    if not isinstance(value, dict):
        return []
    found = [path] if predicate(value) else []
    for key, child in value.items():
        found.extend(observation_paths(child, predicate, path+'.'+key if path else key))
    return found


def market_summary(record: dict, now: datetime) -> tuple[dict, list[str]]:
    source = legacy_market(record)
    market = {key: normalized_observation(source.get(key)) for key in MARKET_FIELDS}
    missing = []
    for key, item in market.items():
        # Historical statistics may describe up to 90 days, but their export still
        # needs a recent observation timestamp; the period is not the export age.
        item['usable'] = attributed(item, now)
        if not item['usable']:
            missing.append('market.'+key)
    if market['price_volatility']['value'] == UNKNOWN:
        stats = market['historical_30d']
        try:
            low, high, mean = (Decimal(str(stats['value'][k])) for k in ('min', 'max', 'mean'))
            if (not stats['usable'] or stats.get('condition') != 'New' or stats.get('currency') != 'USD'
                    or stats.get('basis') in (None, '', UNKNOWN) or
                    any(not n.is_finite() for n in (low, high, mean)) or not 0 < low <= mean <= high):
                raise ValueError('Invalid comparable price statistics')
            market['price_volatility'] = dict(value=str((high-low)/mean*100),
                source='Derived from '+stats['source'], observed_at=stats['observed_at'],
                confidence=stats['confidence'], condition='New', basis='30d (max-min)/mean percent',
                usable=True, limitation='Observed range only; not future volatility or sales velocity')
            missing.remove('market.price_volatility')
        except (KeyError, TypeError, ValueError, InvalidOperation):
            pass
    return market, missing


def analyze_record(record: dict, now: datetime, policy: EvaluationPolicy = EvaluationPolicy()) -> dict:
    original = deepcopy(record)
    record = deepcopy(record)
    market, missing = market_summary(record, now)
    conflicts=list(record.get('input_conflicts', []))
    for key in ('monthly_sales', 'competing_offers'):
        if (key in mapping(record.get('market')) and isinstance(record.get(key), dict)
                and record[key].get('value') != market[key]['value']):
            conflicts.append(key+'.conflicting_observations')
    record['input_conflicts']=conflicts
    # Only properly scoped, attributed manual demand/offer evidence may enter gates.
    for key in ('monthly_sales', 'competing_offers'):
        item = market[key]
        basis_ok = (item.get('basis') == 'new_offer_count' if key == 'competing_offers' else
            item.get('basis') in ('authorized_sales', 'bought_past_month_lower_bound') or
            item.get('basis') == 'validated_estimate' and
            item.get('model_validation_reference') not in (None, '', UNKNOWN))
        if item['usable'] and item.get('condition') == 'New' and basis_ok:
            record[key] = item
        else:
            record.pop(key, None)
            missing.append('gates.'+key+'.attributed_new_condition_evidence')
    result = evaluate(record, now, policy)
    assumptions = observation_paths(original, lambda v: v.get('assumed') is True)
    for mode, scenarios in result['financials'].items():
        for scenario, values in scenarios.items():
            missing.extend('financials.'+mode+'.'+scenario+'.'+field for field in values['missing'])
    raw = result['decision']
    decision = 'BLOCKED' if raw.startswith('BLOCKED_') else raw
    # PR82 names restrictions REJECTED; the MVP exposes all ineligible statuses as BLOCKED.
    if mapping(record.get('eligibility')).get('status', UNKNOWN) != 'ELIGIBLE':
        decision = 'BLOCKED'
    confidence_gaps = observation_paths(original, lambda v: 'observed_at' in v
        and v.get('confidence', UNKNOWN) not in ('HIGH', 'MEDIUM', 'LOW'))
    if decision == 'BUY_CANDIDATE' and (assumptions or confidence_gaps):
        decision = 'REVIEW'
        result['reasons'].append('Assumptions or unknown observation confidence require review')
    if record.get('input_conflicts'):
        decision = 'BLOCKED'
        result['reasons'].append('Input observations conflict: '+', '.join(record['input_conflicts']))
    missing.extend('confidence.'+path for path in confidence_gaps)
    return dict(schema='analysis_engine_v1', asin=record['asin'], evaluated_at=now.isoformat(),
        decision=decision, detailed_decision=raw, reasons=result['reasons'],
        eligibility=dict(normalized_observation(dict(mapping(record.get('eligibility')),
            value=mapping(record.get('eligibility')).get('status', UNKNOWN))),
            status=mapping(record.get('eligibility')).get('status', UNKNOWN)),
        financials=result['financials'], market=market, missing_data=sorted(set(missing)),
        assumptions=assumptions, purchase_authorized=False,
        buy_candidate_modes=result['buy_candidate_modes'] if decision == 'BUY_CANDIDATE' else [],
        thresholds=dict(minimum_profit=str(policy.minimum_profit), minimum_roi=str(policy.minimum_roi)),
        evidence_sha256=fingerprint(original), input_evidence=evidence_tree(original))


def remember(path: Path, reports: list[dict]) -> None:
    """Append exact snapshots using the existing private SQLite hash-chain boundary."""
    with database(path) as db:
        rows = db.execute('SELECT payload FROM observations').fetchall()
        if any(json.loads(row[0]).get('schema') != 'analysis_engine_v1' for row in rows):
            raise ValueError('Separate analysis-only history required')
        last = db.execute('SELECT sequence,digest FROM observations ORDER BY sequence DESC LIMIT 1').fetchone()
        sequence, previous = last if last else (0, '0'*64)
        for report in reports:
            if report.get('schema') != 'analysis_engine_v1':
                raise ValueError('Analysis report required')
            marker = fingerprint(report)
            if db.execute('SELECT 1 FROM observations WHERE identity=?', (marker,)).fetchone():
                continue
            sequence += 1
            payload = canonical(report)
            digest = fingerprint([sequence, marker, payload, previous])
            db.execute('INSERT INTO observations VALUES (?,?,?,?,?)', (sequence, marker, payload, previous, digest))
            previous = digest
