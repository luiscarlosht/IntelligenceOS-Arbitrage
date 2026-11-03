"""M85 manual evidence validation and complete gap reports; no write transport."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from app.amazon_evaluation import MODES, SCENARIOS, mapping, timestamp
from app.amazon_evaluation_sheets import plan, snapshot, TAB
from app.amazon_research_queue import ORIGINAL_ASINS
from app.analysis import client, load, output
from app.analysis_adapters import ManualAmazon, ManualKeepa, SheetsEvidence
from app.analysis_engine import analyze_record
from app.m66_opportunity import exact_match
from app.observations import fingerprint
from app.sheets_intake import SPREADSHEET

UNKNOWN = 'UNKNOWN'
ACQUISITION = ('purchase', 'sales_tax', 'inbound_shipping', 'preparation', 'packaging', 'other_cost')


def known(value):
    return isinstance(value, str) and value.strip().upper() not in ('', UNKNOWN)


def prepare(record: dict, seller: str, now: datetime) -> tuple[dict, list[str]]:
    """Keep original separately; unusable observations cannot enter engine gates."""
    clean = deepcopy(record)
    issues = []

    def visit(node, path=''):
        if not isinstance(node, dict):
            return
        observation = 'observed_at' in node or 'value' in node or path == 'eligibility'
        if observation:
            problems = []
            if not known(node.get('source_reference')):
                problems.append('source_reference')
            if not known(node.get('source')):
                problems.append('source')
            if not timestamp(node.get('observed_at'), now):
                problems.append('fresh_aware_timestamp')
            if node.get('verified') is not True or node.get('assumed') is True:
                problems.append('verified_observation')
            expected = dict(seller_alias=seller, marketplace='ATVPDKIKX0DER', condition='New')
            problems.extend(k for k, v in expected.items() if node.get(k) != v)
            if node.get('confidence') not in ('HIGH', 'MEDIUM', 'LOW'):
                problems.append('confidence')
            metric = path.removeprefix('market.')
            if metric in ('monthly_sales', 'competing_offers'):
                if type(node.get('value')) is not int or node['value'] < 0:
                    problems.append('nonnegative_integer')
                basis = node.get('basis')
                supported = (basis == 'new_offer_count' if metric == 'competing_offers' else
                    basis in ('authorized_sales', 'bought_past_month_lower_bound') or
                    basis == 'validated_estimate' and known(node.get('model_validation_reference')))
                if not supported:
                    problems.append('supported_evidence_basis')
            if problems:
                issues.extend(path+'.'+p for p in problems)
                # Keep explicit restrictions even if stale or incompletely attributed.
                if path == 'eligibility':
                    if node.get('status') not in ('APPROVAL_REQUIRED', 'RESTRICTED'):
                        node['status'] = UNKNOWN
                elif path.startswith('identity.'):
                    node['observed_at'] = UNKNOWN
                else:
                    node['value'] = UNKNOWN
        for key, value in list(node.items()):
            visit(value, path+'.'+key if path else key)

    visit(clean)
    return clean, sorted(issues)


def cohort(rows: list[dict]) -> list[dict]:
    rows = ManualAmazon(rows).records()
    if any(r.get('asin') not in ORIGINAL_ASINS for r in rows):
        raise ValueError('Only original twenty ASINs accepted')
    by_asin = {r['asin']: r for r in rows}
    return [by_asin.get(asin, dict(asin=asin)) for asin in ORIGINAL_ASINS]


def report(rows: list[dict], seller: str, now: datetime) -> dict:
    if not known(seller) or now.utcoffset() is None:
        raise ValueError('Seller alias and aware review time required')
    results = []
    for original in cohort(rows):
        clean, issues = prepare(original, seller, now)
        analysis = analyze_record(clean, now)
        identity = deepcopy(mapping(clean.get('identity')))
        # Reuse the engine normalization of UNKNOWN identity values.
        identity['asin'] = clean['asin']
        for side in ('amazon_product', 'retailer_product'):
            identity[side] = {k: None if v == UNKNOWN else v for k, v in mapping(identity.get(side)).items()}
        match = exact_match(identity, as_of=now)
        eligibility = mapping(clean.get('eligibility'))
        eligible = eligibility.get('status') == 'ELIGIBLE' and timestamp(eligibility.get('observed_at'), now)
        gaps = dict(eligibility=[] if eligible else ['Fresh verified seller-specific ELIGIBLE observation'],
            documentation=[k for k in ('seller_documentation', 'policy_checks')
                if mapping(clean.get(k)).get('value') is not True],
            exact_identity=match['missing']+match['mismatches'],
            new_condition_price=[], demand=[], competing_offers=[], fees=[], acquisition_costs=[])
        for field, group in (('monthly_sales', 'demand'), ('competing_offers', 'competing_offers')):
            item = analysis['market'][field]
            gate = 'gates.'+field+'.attributed_new_condition_evidence'
            if (not item['usable'] or gate in analysis['missing_data']
                    or type(item['value']) is not int or item['value'] < 0):
                gaps[group].append(field)
        for mode in MODES:
            for scenario in SCENARIOS:
                missing = analysis['financials'][mode][scenario]['missing']
                for field in missing:
                    group = ('new_condition_price' if field.startswith('selling_price') else
                             'acquisition_costs' if field.split('.')[0] in ACQUISITION or field == 'positive_purchase' else 'fees')
                    gaps[group].append(f'{mode}.{scenario}.{field}')
        if mapping(clean.get('fba_eligible')).get('value') is not True:
            gaps['eligibility'].append('Independent FBA eligibility required for FBA')
        results.append(dict(asin=clean['asin'], decision=analysis['decision'],
            next_action='DETAILED_RESEARCH' if eligible else 'ELIGIBILITY_SCREEN_FIRST',
            gaps=gaps, validation_issues=issues, analysis=analysis,
            original_evidence_sha256=fingerprint(original), original_evidence=original))
    groups = results[0]['gaps']
    return dict(schema='amazon_evidence_gaps_v1', mode='read_only', workbook=SPREADSHEET,
        seller_alias=seller, evaluated_at=now.isoformat(), records=results,
        coverage=dict(asins=len(results), populated_records=sum(len(r['original_evidence']) > 1 for r in results),
            eligibility_screen_first=sum(r['next_action'] == 'ELIGIBILITY_SCREEN_FIRST' for r in results),
            decisions={d: sum(r['decision'] == d for r in results) for d in sorted({r['decision'] for r in results})},
            complete_by_group={g: sum(not r['gaps'][g] for r in results) for g in groups}),
        purchase_authorized=False, requests=[])


def evaluation_proposal(connection, rows: list[dict], seller: str, now: datetime) -> dict:
    """Existing sparse seed planner: never updates an existing researcher row."""
    coverage = report(rows, seller, now)
    submitted = []
    for original in ManualAmazon(rows).records():
        clean, issues = prepare(original, seller, now)
        clean["manual_import_audit"] = dict(original_evidence=original,
            original_sha256=fingerprint(original), validation_issues=issues)
        submitted.append(clean)
    connection.select(SPREADSHEET)
    metadata = connection.metadata()
    existing = snapshot(connection, metadata)
    from app.amazon_evaluation_sheets import seed
    if any(len(cell) > 49000 for row in submitted for cell in seed(row)):
        raise ValueError("Evidence exceeds cell bound; reduce notes or private references")
    requests = plan(submitted, metadata, existing)
    return dict(schema='amazon_evidence_seed_proposal_v1', mode='proposal_only', workbook=SPREADSHEET,
        tab=TAB, evaluated_at=now.isoformat(), snapshot_sha256=fingerprint([metadata, existing]),
        input_sha256=fingerprint(submitted), requests=requests, coverage=coverage['coverage'],
        existing_rows_preserved=True, publication_authorized=False,
        limitation='Seed only; existing rows skipped. Separate owner approval and fresh revalidation required; not executable by analysis publisher.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--input', type=Path)
    source.add_argument('--sheets', action='store_true')
    parser.add_argument('--seller-alias', required=True)
    parser.add_argument('--keepa-manual', type=Path)
    parser.add_argument('--evaluation-proposal', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--as-of')
    args = parser.parse_args(argv)
    if args.evaluation_proposal and (not args.input or args.sheets):
        parser.error('Evaluation proposal requires explicit local --input')
    now = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc)
    connection = client() if args.sheets or args.evaluation_proposal else None
    rows = SheetsEvidence(connection).records() if args.sheets else load(args.input) if args.input else [{'asin': a} for a in ORIGINAL_ASINS]
    if args.keepa_manual:
        rows = ManualKeepa(load(args.keepa_manual)).merge(cohort(rows))
    result = (evaluation_proposal(connection, rows, args.seller_alias, now) if args.evaluation_proposal
              else report(rows, args.seller_alias, now))
    output(args.output, result)


if __name__ == '__main__':
    main()
