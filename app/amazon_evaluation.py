"""Manual Amazon evaluation; offline by default, never purchase authorization."""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re

from app.m66_opportunity import exact_match
from app.profitability import analyze

UNKNOWN = 'UNKNOWN'
ELIGIBILITY = ('ELIGIBLE', 'APPROVAL_REQUIRED', 'RESTRICTED', UNKNOWN)
SCENARIOS = ('conservative', 'base', 'optimistic')
MODES = ('FBA', 'FBM')
COSTS = ('purchase', 'sales_tax', 'inbound_shipping', 'preparation', 'packaging',
         'other_cost', 'referral_fee', 'fulfillment_fee', 'storage', 'placement',
         'returns_allowance', 'transaction_cost')
# Fixed, documented screening heuristics, not demand forecasts.
MIN_MONTHLY_SALES = 30
MAX_OFFERS = 10


@dataclass(frozen=True)
class EvaluationPolicy:
    minimum_profit: Decimal = Decimal('5')
    minimum_roi: Decimal = Decimal('50')

    def __post_init__(self):
        if any(not isinstance(v, Decimal) or not v.is_finite() or v < 0
               for v in (self.minimum_profit, self.minimum_roi)):
            raise ValueError('Finite nonnegative Decimal thresholds required')


def timestamp(value: object, now: datetime, hours: int = 24) -> bool:
    try:
        date = datetime.fromisoformat(value)
        return date.utcoffset() is not None and 0 <= (now-date).total_seconds() <= hours*3600
    except (ValueError, TypeError):
        return False


def evidence(value: object, now: datetime) -> bool:
    """Every observation retains its own provenance; unknown stays unknown."""
    return (isinstance(value, dict) and isinstance(value.get('source'), str)
            and value['source'].strip() not in ('', UNKNOWN)
            and timestamp(value.get('observed_at'), now))


def amount(item: object, now: datetime) -> Decimal | None:
    if not evidence(item, now) or item.get('currency') != 'USD':
        return None
    try:
        value = Decimal(str(item.get('value')))
        return value if value.is_finite() and value >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def financial(record: dict, mode: str, scenario: str, now: datetime,
              policy: EvaluationPolicy = EvaluationPolicy()) -> dict:
    inputs = mapping(mapping(mapping(record.get('financials')).get(mode)).get(scenario))
    sale = amount(inputs.get('selling_price'), now)
    missing = [] if sale is not None and sale > 0 else ['selling_price']
    price_observation = mapping(inputs.get('selling_price'))
    if (price_observation.get('asin') != record['asin']
            or price_observation.get('condition') != 'New'):
        missing.append('selling_price.asin_condition_scope')
    values = {}
    for key in COSTS:
        item = inputs.get(key)
        value = amount(item, now)
        if value is None:
            missing.append(key)
        else:
            values[key] = value
        if key in ('referral_fee', 'fulfillment_fee'):
            if (not isinstance(item, dict) or item.get('asin') != record['asin']
                    or item.get('condition') != 'New' or item.get('mode') != mode
                    or amount(item.get('price_basis'), now) != sale or sale is None):
                missing.append(key+'.scope_and_price_basis')
    if values.get('purchase', Decimal(0)) <= 0:
        missing.append('positive_purchase')
    if missing:
        return dict(complete=False, missing=sorted(set(missing)), net_profit=UNKNOWN,
                    net_margin_percent=UNKNOWN, roi_percent=UNKNOWN, break_even_price=UNKNOWN)
    mapped = {k: values[k] for k in ('sales_tax', 'inbound_shipping', 'preparation',
              'packaging', 'other_cost', 'referral_fee', 'fulfillment_fee', 'storage', 'transaction_cost')}
    mapped['transaction_cost'] += values['placement'] + values['returns_allowance']
    result = analyze(values['purchase'], sale, mapped, policy.minimum_roi, policy.minimum_profit)
    return dict(complete=True, missing=[], net_profit=str(result.net_profit),
        net_margin_percent=str(result.net_profit/sale*100), roi_percent=str(result.roi),
        invested_cost=str(result.acquisition_cost), break_even_price=str(result.break_even_price),
        passes=result.net_profit >= policy.minimum_profit and result.roi >= policy.minimum_roi)


def observed_check(record: dict, key: str, now: datetime) -> bool:
    item = record.get(key)
    return evidence(item, now) and item.get('value') is True


def evaluate(record: dict, now: datetime,
             policy: EvaluationPolicy = EvaluationPolicy()) -> dict:
    if now.utcoffset() is None or not re.fullmatch(r'B[A-Z0-9]{9}', record.get('asin', '')):
        raise ValueError('ASIN and aware evaluation time required')
    eligibility = mapping(record.get('eligibility'))
    status = eligibility.get('status', UNKNOWN)
    if status not in ELIGIBILITY:
        raise ValueError('Invalid eligibility status')
    finances = {mode: {s: financial(record, mode, s, now, policy) for s in SCENARIOS} for mode in MODES}
    result = dict(asin=record['asin'], decision='BLOCKED_DATA', reasons=[], financials=finances,
                  purchase_authorized=False, evaluated_at=now.isoformat(), buy_candidate_modes=[])
    # Positive approval/restriction observations always block, even if now stale.
    if status == 'APPROVAL_REQUIRED':
        result.update(decision='BLOCKED_APPROVAL_REQUIRED', reasons=['Seller approval required'])
        return result
    if status == 'RESTRICTED':
        result.update(decision='REJECTED', reasons=['Selling restricted'])
        return result
    if status != 'ELIGIBLE' or not evidence(eligibility, now):
        result['reasons'] = ['Fresh seller-specific eligibility evidence required']
        return result
    identity = mapping(record.get('identity'))
    identity = dict(identity, asin=record['asin'])
    for side in ('amazon_product', 'retailer_product'):
        identity[side] = {key: None if isinstance(value, str) and value.strip().upper() == UNKNOWN
                          else value for key, value in mapping(identity.get(side)).items()}
    match = exact_match(identity, as_of=now)
    if not match['exact']:
        result.update(decision='BLOCKED_IDENTITY', reasons=match['missing']+match['mismatches'])
        return result
    missing = []
    for key in ('seller_documentation', 'policy_checks'):
        if not observed_check(record, key, now):
            missing.append(key)
    demand, offers = mapping(record.get('monthly_sales')), mapping(record.get('competing_offers'))
    for key, item in (('monthly_sales', demand), ('competing_offers', offers)):
        if not evidence(item, now) or type(item.get('value')) is not int or item['value'] < 0:
            missing.append(key)
    if missing:
        result['reasons'] = missing
        return result
    if demand['value'] < MIN_MONTHLY_SALES or offers['value'] > MAX_OFFERS:
        result.update(decision='REJECTED', reasons=['Demand/competition thresholds failed'])
        return result
    complete_modes = [m for m in MODES if all(finances[m][s]['complete'] for s in SCENARIOS)]
    ordered_modes = []
    for mode in complete_modes:
        prices = [amount(record['financials'][mode][s]['selling_price'], now) for s in SCENARIOS]
        if prices == sorted(prices):
            ordered_modes.append(mode)
    if complete_modes and not ordered_modes:
        result['reasons'] = ['Selling prices must satisfy conservative <= base <= optimistic']
        return result
    complete_modes = ordered_modes
    if not complete_modes:
        result['reasons'] = ['Complete scenario costs required for at least one fulfillment mode']
        return result
    passing = [m for m in complete_modes if finances[m]['base']['passes']]
    if not passing:
        result.update(decision='REJECTED', reasons=['Base profit/ROI thresholds failed'])
        return result
    # FBA requires independent fresh fulfillment eligibility; FBM does not inherit it.
    passing = [m for m in passing if m != 'FBA' or observed_check(record, 'fba_eligible', now)]
    safe = [m for m in passing if finances[m]['conservative']['passes']]
    if not safe or record.get('is_synthetic') is True or record.get('is_mock') is True:
        result.update(decision='REVIEW', reasons=['Conservative scenario, FBA eligibility or synthetic inputs require review'])
    else:
        result.update(decision='BUY_CANDIDATE', buy_candidate_modes=safe,
                      reasons=['Evidence gates pass; human review required, no purchase authorization'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--as-of', help='Aware ISO timestamp; defaults to current UTC')
    args = parser.parse_args()
    now = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc)
    rows = json.loads(args.input.read_text())
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError('At most 1000 evaluation records required')
    keys = [r['asin'] for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate input ASIN')
    print(json.dumps([evaluate(r, now) for r in rows], indent=2))


if __name__ == '__main__':
    main()
