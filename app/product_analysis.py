"""Offline Walmart product research, independent of seller permission and buying."""
import argparse
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from app.amazon_evaluation import COSTS, MODES, SCENARIOS, EvaluationPolicy, amount, mapping
from app.analysis_engine import analyze_record, attributed, normalized_observation
from app.evidence_io import offline, publication, json_write, safe
from app.m66_opportunity import exact_match
from app.m70_sources import strict_json
from app.observations import fingerprint

UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class ResearchPolicy:
    financial: EvaluationPolicy = EvaluationPolicy()
    minimum_monthly_demand: int = 30
    maximum_new_offers: int = 10

    def __post_init__(self):
        if any(type(v) is not int or v < 0 for v in
               (self.minimum_monthly_demand, self.maximum_new_offers)):
            raise ValueError('Nonnegative integer market thresholds required')


def reference(value: object) -> bool:
    return isinstance(value, str) and value.strip().upper() not in ('', UNKNOWN)


def usable(item: object, now: datetime) -> bool:
    observation = normalized_observation(item)
    return (attributed(observation, now) and observation['confidence'] in ('HIGH', 'MEDIUM')
            and observation.get('verified') is True
            and reference(observation.get('source_reference')))


def unknown_financial(missing: list[str]) -> dict:
    return dict(complete=False, missing=sorted(set(missing)), net_profit=UNKNOWN,
                net_margin_percent=UNKNOWN, gross_margin_percent=UNKNOWN,
                roi_percent=UNKNOWN, break_even_price=UNKNOWN)


def assess(record: dict, now: datetime, policy: ResearchPolicy = ResearchPolicy()) -> dict:
    """Reuse PR82/83 math; preserve their purchasing decision without reinterpreting it."""
    original = deepcopy(record)
    record = deepcopy(record)
    if now.utcoffset() is None:
        raise ValueError('Aware evaluation clock required')
    for key in ('monthly_sales', 'competing_offers'):
        if (key in mapping(record.get('market')) and isinstance(record.get(key), dict)
                and record[key].get('value') != mapping(record['market'][key]).get('value')):
            record.setdefault('input_conflicts', []).append(key+'.conflicting_observations')
    asin = record.get('asin')
    has_asin = isinstance(asin, str) and re.fullmatch(r'B[A-Z0-9]{9}', asin) is not None
    identity = deepcopy(mapping(record.get('identity')))
    for side in ('amazon_product', 'retailer_product'):
        identity[side] = {k: None if v == UNKNOWN else v
                          for k, v in mapping(identity.get(side)).items()}
    match = exact_match(dict(identity, asin=asin), as_of=now)
    identity_gaps = list(match['missing']) + list(match['mismatches'])
    for side in ('amazon_product', 'retailer_product'):
        item = mapping(identity.get(side))
        if (item.get('confidence') not in ('HIGH', 'MEDIUM') or item.get('assumed') is True
                or item.get('verified') is not True):
            identity_gaps.append(side+'.confidence_or_assumption')
    retailer = mapping(identity.get('retailer_product'))
    try:
        url = urlsplit(retailer.get('url', ''))
        item_id = retailer.get('walmart_item_id')
        if (url.hostname not in ('walmart.com', 'www.walmart.com')
                or not isinstance(item_id, str) or not re.fullmatch(r'[0-9]{1,30}', item_id)
                or not url.path.startswith('/ip/') or url.path.rstrip('/').split('/')[-1] != item_id):
            identity_gaps.append('retailer_product.walmart_item_id_url')
    except (ValueError, TypeError):
        identity_gaps.append('retailer_product.walmart_item_id_url')
    if not has_asin:
        identity_gaps.append('matched_asin')
    if record.get('input_conflicts'):
        identity_gaps.append('input_conflicts')
    exact = match['exact'] and not identity_gaps
    # Retailer shipping is explicit here, then folded into the inherited other_cost
    # exactly once. M86 other_cost excludes retailer shipping.
    sanitized = deepcopy(record)
    quality = {}
    for mode in MODES:
        quality[mode] = {}
        for scenario in SCENARIOS:
            inputs = mapping(mapping(mapping(record.get('financials')).get(mode)).get(scenario))
            gaps = list(identity_gaps)
            for key in COSTS + ('selling_price', 'retailer_shipping'):
                item = inputs.get(key)
                if not usable(item, now):
                    gaps.append(key+'.fresh_attributed_confident_evidence')
                if key in ('referral_fee', 'fulfillment_fee') and not usable(mapping(item).get('price_basis'), now):
                    gaps.append(key+'.price_basis.quality')
            shipping = amount(inputs.get('retailer_shipping'), now)
            other = amount(inputs.get('other_cost'), now)
            if shipping is None:
                gaps.append('retailer_shipping')
            if shipping is not None and other is not None:
                target = sanitized.setdefault('financials', {}).setdefault(mode, {}).setdefault(scenario, {})
                target['other_cost'] = dict(inputs['other_cost'], value=str(other+shipping))
            quality[mode][scenario] = gaps
    # Legacy gates still run, with shipping included, even for UNKNOWN eligibility.
    legacy = analyze_record(sanitized, now, policy.financial) if has_asin else None
    finances, modes = {}, {}
    missing = list(identity_gaps)
    if legacy:
        missing.extend(g for g in legacy['missing_data'] if g.startswith('market.'))
    for mode in MODES:
        finances[mode] = {}
        for scenario in SCENARIOS:
            values = deepcopy(legacy['financials'][mode][scenario]) if legacy else unknown_financial(['matched_asin'])
            gaps = quality[mode][scenario] + values['missing']
            if gaps:
                values = unknown_financial(gaps)
            else:
                inputs = record['financials'][mode][scenario]
                sale = amount(inputs['selling_price'], now)
                purchase = amount(inputs['purchase'], now)
                # Gross margin here means (sale - source item price) / sale;
                # fully loaded profitability is net_margin_percent.
                values['gross_margin_percent'] = str((sale-purchase)/sale*100)
            finances[mode][scenario] = values
            missing.extend(f'financials.{mode}.{scenario}.{g}' for g in values['missing'])
        complete = all(v['complete'] for v in finances[mode].values())
        if complete:
            prices = [amount(record['financials'][mode][s]['selling_price'], now) for s in SCENARIOS]
            complete = prices == sorted(prices)
            if not complete:
                missing.append(f'financials.{mode}.scenario_price_order')
        modes[mode] = ('PROMISING' if finances[mode]['base'].get('passes') else 'BELOW_TARGET') if complete else 'INSUFFICIENT_DATA'
    financial_status = ('PROMISING' if 'PROMISING' in modes.values() else
                        'BELOW_TARGET' if all(v == 'BELOW_TARGET' for v in modes.values()) else 'INSUFFICIENT_DATA')
    base_inputs = {mode: {key: dict(normalized_observation(mapping(mapping(mapping(record.get('financials')).get(mode)).get('base')).get(key)),
        usable=usable(mapping(mapping(mapping(record.get('financials')).get(mode)).get('base')).get(key), now))
        for key in COSTS + ('retailer_shipping', 'selling_price')} for mode in MODES}
    market = deepcopy(legacy['market']) if legacy else {}
    supported = {}
    for key in ('monthly_sales', 'competing_offers'):
        item = mapping(market.get(key))
        basis = item.get('basis')
        basis_ok = (basis == 'new_offer_count' if key == 'competing_offers' else
                    basis in ('authorized_sales', 'bought_past_month_lower_bound') or
                    basis == 'validated_estimate' and reference(item.get('model_validation_reference')))
        valid = (exact and usable(item, now) and item.get('condition') == 'New' and basis_ok
                 and item.get('marketplace') == 'ATVPDKIKX0DER'
                 and item.get('asin') == asin and type(item.get('value')) is int and item['value'] >= 0
                 and not record.get('input_conflicts'))
        # A small lower bound does not establish demand below the target.
        if key == 'monthly_sales' and basis == 'bought_past_month_lower_bound' and valid:
            valid = item['value'] >= policy.minimum_monthly_demand
        supported[key] = item['value'] if valid else UNKNOWN
        if not valid:
            missing.append('market.'+key+'.supported_evidence')
    market_status = 'INSUFFICIENT_DATA'
    if UNKNOWN not in supported.values():
        market_status = ('ATTRACTIVE' if supported['monthly_sales'] >= policy.minimum_monthly_demand
                         and supported['competing_offers'] <= policy.maximum_new_offers else 'UNATTRACTIVE')
    price_history = {}
    for key in ('historical_30d', 'historical_90d'):
        item = mapping(market.get(key))
        try:
            low, high, mean = (Decimal(str(item['value'][k])) for k in ('min', 'max', 'mean'))
            valid_statistics = all(v.is_finite() for v in (low, high, mean)) and 0 < low <= mean <= high
        except (KeyError, TypeError, ValueError, InvalidOperation):
            valid_statistics = False
        if (valid_statistics and usable(item, now) and item.get('condition') == 'New' and item.get('currency') == 'USD'
                and item.get('asin') == asin and item.get('marketplace') == 'ATVPDKIKX0DER'
                and item.get('basis') not in (None, '', UNKNOWN)):
            price_history[key] = item
    if not price_history:
        missing.append('market.comparable_new_price_history')
    eligibility = mapping(record.get('eligibility')).get('status', UNKNOWN)
    if eligibility == 'ELIGIBLE' and not usable(dict(mapping(record['eligibility']), value=True), now):
        eligibility = UNKNOWN
    decision = legacy['decision'] if legacy else 'BLOCKED'
    # New research quality checks cannot expose a legacy candidate whose selected
    # modes have unverified costs, identity or unsupported market observations.
    if decision == 'BUY_CANDIDATE':
        trusted_modes = [m for m in legacy['buy_candidate_modes']
                         if modes[m] != 'INSUFFICIENT_DATA']
        if not exact or eligibility != 'ELIGIBLE' or UNKNOWN in supported.values() or not trusted_modes:
            decision = 'BLOCKED'
    return dict(schema='product_analysis_v1', candidate_id=record['candidate_id'], asin=asin or UNKNOWN,
                walmart_product=identity.get('retailer_product', {}), match_confidence='EXACT' if exact else 'UNRESOLVED',
                financial_assessment=financial_status, financial_assessment_by_mode=modes,
                market_assessment=market_status, selling_eligibility=eligibility,
                financials=finances, base_inputs=base_inputs, market=market, supported_market=supported,
                price_history=dict(status='AVAILABLE' if price_history else 'UNAVAILABLE', observations=price_history),
                evidence_quality=dict(identity='EXACT' if exact else 'UNRESOLVED',
                    mode='ILLUSTRATIVE' if record.get('is_synthetic') or record.get('is_mock') else 'SUPPLIED_EVIDENCE',
                    maximum_age_hours=24, limitation='Source and confidence are supplied assertions; inspect original references'),
                decision=decision, legacy_decision=legacy['decision'] if legacy else 'BLOCKED', purchase_authorized=False,
                missing_information=sorted(set(missing)), evidence_sha256=fingerprint(original),
                input_evidence=original, evaluated_at=now.isoformat(),
                thresholds=dict(minimum_profit=str(policy.financial.minimum_profit),
                    minimum_roi=str(policy.financial.minimum_roi),
                    minimum_monthly_demand=policy.minimum_monthly_demand, maximum_new_offers=policy.maximum_new_offers))


def comparison(manifest: dict, now: datetime, policy: ResearchPolicy = ResearchPolicy()) -> dict:
    if manifest.get('schema') != 'walmart_product_analysis_input_v1':
        raise ValueError('M86 input manifest required')
    expected = manifest.get('expected_candidates', 6)
    if type(expected) is not int or not 1 <= expected <= 1000:
        raise ValueError('Positive expected candidate count required')
    records = manifest.get('candidates')
    if not isinstance(records, list) or len(records) > 1000:
        raise ValueError('At most 1000 candidates required')
    keys = [r['candidate_id'] for r in records]
    if any(not isinstance(k, str) or not k.strip() for k in keys) or len(keys) != len(set(keys)):
        raise ValueError('Unique nonempty original source candidate IDs required')
    reports = [assess(r, now, policy) for r in records]
    # No profitability ordering unless all products have both complete modes.
    financial_ranking = bool(reports) and all(
        r['market_assessment'] != 'INSUFFICIENT_DATA'
        and all(v != 'INSUFFICIENT_DATA' for v in r['financial_assessment_by_mode'].values())
        for r in reports)
    if financial_ranking:
        reports.sort(key=lambda r: (-max(Decimal(r['financials'][m]['base']['net_profit']) for m in MODES), r['candidate_id']))
    else:
        reports.sort(key=lambda r: (r['match_confidence'] != 'EXACT', len(r['missing_information']), r['candidate_id']))
    for rank, report in enumerate(reports, 1):
        report['rank'] = rank
    return dict(schema='walmart_product_comparison_v1', evaluated_at=now.isoformat(),
                input_manifest_sha256=fingerprint(manifest),
                expected_candidates=manifest.get('expected_candidates', 6), recovered_candidates=len(reports),
                recovery_status='RECOVERED' if len(reports) == manifest.get('expected_candidates', 6) else 'INCOMPLETE',
                recovery_blockers=manifest.get('recovery_blockers', []), source_inventory=manifest.get('source_inventory', []),
                ranking_basis='BASE_NET_PROFIT_BEST_MODE' if financial_ranking else 'RESEARCH_PRIORITY_ONLY',
                ranking_limitation='Best-mode base profit; not sales velocity, risk-adjusted return or purchase approval' if financial_ranking else 'Exact identity, then fewest evidence gaps; ties by source ID; no profitability claim',
                purchase_authorized=False, records=reports)


def workbook(report: dict, destination: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    wb = Workbook()
    summary = wb.active
    summary.title = 'Executive Summary'
    for key in ('schema', 'evaluated_at', 'expected_candidates', 'recovered_candidates', 'recovery_status', 'ranking_basis', 'ranking_limitation', 'purchase_authorized', 'recovery_blockers'):
        summary.append([key, json.dumps(report[key]) if isinstance(report[key], (dict, list)) else str(report[key])])
    sheet = wb.create_sheet('Product Comparison')
    fields = ('walmart_product', 'asin', 'match_confidence', 'financial_assessment', 'financial_assessment_by_mode',
              'market_assessment', 'selling_eligibility', 'supported_market', 'price_history', 'evidence_quality', 'base_inputs', 'financials', 'market', 'missing_information', 'evidence_sha256')
    sheet.append(['Field'] + [r['candidate_id'] for r in report['records']])
    for field in fields:
        sheet.append([field] + [json.dumps(r[field], ensure_ascii=False) for r in report['records']])
    for key in ('title', 'walmart_item_id', 'gtin', 'model', 'size', 'pack_quantity', 'variation', 'url', 'observed_at', 'source_reference'):
        sheet.append(['walmart.'+key] + [str(r['walmart_product'].get(key, UNKNOWN)) for r in report['records']])
    for key in ('monthly_sales', 'competing_offers'):
        sheet.append([key] + [r['supported_market'][key] for r in report['records']])
    for mode in MODES:
        for key in COSTS + ('retailer_shipping', 'selling_price'):
            sheet.append([mode+'.base.'+key] + [json.dumps(r['base_inputs'][mode][key], ensure_ascii=False) for r in report['records']])
        for key in ('net_profit', 'roi_percent', 'gross_margin_percent', 'break_even_price'):
            sheet.append([mode+'.base.'+key] + [r['financials'][mode]['base'].get(key, UNKNOWN) for r in report['records']])
    scenarios = wb.create_sheet('Financial Scenarios')
    scenarios.append(['Candidate', 'Mode', 'Scenario', 'Complete', 'Net profit', 'ROI %', 'Gross margin %', 'Net margin %', 'Break-even', 'Invested cost', 'Missing'])
    for row in report['records']:
        for mode in MODES:
            for scenario in SCENARIOS:
                v = row['financials'][mode][scenario]
                scenarios.append([row['candidate_id'], mode, scenario, str(v['complete'])] +
                    [v.get(k, UNKNOWN) for k in ('net_profit', 'roi_percent', 'gross_margin_percent', 'net_margin_percent', 'break_even_price', 'invested_cost')] + [', '.join(v['missing'])])
    gaps = wb.create_sheet('Data Quality and Missing Info')
    gaps.append(['Candidate', 'Gap'])
    for row in report['records']:
        for gap in row['missing_information']:
            gaps.append([row['candidate_id'], gap])
    for gap in report['recovery_blockers']:
        gaps.append(['SOURCE RECOVERY', str(gap)])
    inventory = wb.create_sheet('Source Inventory')
    inventory.append(['Saved source populations; membership in requested six unproven'])
    for item in report['source_inventory']:
        inventory.append([json.dumps(item, ensure_ascii=False)])
    evidence = wb.create_sheet('Evidence')
    evidence.append(['Candidate', 'SHA256', 'Original evidence JSON'])
    for row in report['records']:
        evidence.append([row['candidate_id'], row['evidence_sha256'], json.dumps(row['input_evidence'], ensure_ascii=False)])
    for tab in wb:
        tab.freeze_panes = 'B2'
        for cell in tab[1]:
            cell.font = Font(bold=True)
        for row in tab:
            for cell in row:
                cell.alignment = Alignment(vertical='top', wrap_text=True)
                if isinstance(cell.value, str):
                    if len(cell.value) > 32000:
                        raise ValueError('Excel cell bound; JSON retains full evidence')
                    if cell.value.lstrip().startswith(('=', '+', '-', '@')):
                        cell.value = "'" + cell.value
        tab.column_dimensions['A'].width = 40
        from openpyxl.utils import get_column_letter
        for column in range(2, tab.max_column+1):
            tab.column_dimensions[get_column_letter(column)].width = 50
    wb.save(destination)
    destination.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New private output directory')
    parser.add_argument('--as-of')
    parser.add_argument('--minimum-profit', type=Decimal, default=Decimal('5'))
    parser.add_argument('--minimum-roi', type=Decimal, default=Decimal('50'))
    parser.add_argument('--minimum-monthly-demand', type=int, default=30)
    parser.add_argument('--maximum-new-offers', type=int, default=10)
    args = parser.parse_args()
    path = safe(args.input)
    if path.stat().st_size > 8*1024*1024:
        raise ValueError('Input size limit')
    now = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc)
    policy = ResearchPolicy(EvaluationPolicy(args.minimum_profit, args.minimum_roi), args.minimum_monthly_demand, args.maximum_new_offers)
    with publication(args.output, [path]) as stage:
        previous_temp = tempfile.tempdir
        try:
            tempfile.tempdir = str(stage)
            with offline(reads=[path], writes=[stage]):
                report = comparison(strict_json(path), now, policy)
                json_write(stage/'comparison.json', report)
                workbook(report, stage/'comparison.xlsx')
        finally:
            tempfile.tempdir = previous_temp


if __name__ == '__main__':
    main()
