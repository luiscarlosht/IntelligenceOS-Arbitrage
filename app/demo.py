"""Deterministic offline DEMO using existing matching, screening and reporting."""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

from app.authorized_imports import validate, remediation
from app.config import Config, ROOT
from app.connectors import CsvConnector
from app.discovery import discover
from app.marketplace import MockAmazonProvider
from app.reporting import write_report

DEMO_NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def demo_rows(config: Config) -> list[dict]:
    rows = discover(CsvConnector(config.input), MockAmazonProvider(config.amazon_fixture),
                    config, DEMO_NOW)
    for row in rows:
        row['data_mode'] = 'DEMO — fictional fixtures; never live deals'
    return rows


def generate(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    config = Config(input=ROOT / 'sample_data/demo_authorized.csv',
                    output=directory / 'DEMO.xlsx', database=directory / 'unused.sqlite3',
                    mode='discovery', amazon_fixture=ROOT / 'sample_data/demo_amazon.json')
    rows = demo_rows(config)
    variants = [('defaults', config), ('budget_600', replace(config, inventory_budget=600)),
                ('profit_4', replace(config, minimum_profit=4)),
                ('roi_40', replace(config, minimum_roi=40))]
    scenarios = {name: [r['product'] for r in demo_rows(c) if r['status'] == 'REVIEW']
                 for name, c in variants}
    validation = {}
    for name in ('demo_authorized.csv', 'demo_invalid_authorized.csv'):
        issues = validate(ROOT / 'sample_data' / name, DEMO_NOW)
        validation[name] = [{'issue': issue, 'action': remediation(issue)} for issue in issues]
    result = dict(label='DEMO — fictional fixtures; never live deals',
                  evaluation_time=DEMO_NOW.isoformat(), clock_basis='fixed fixture clock, not live freshness',
                  thresholds=dict(inventory_budget=500, minimum_profit=5, minimum_roi=50),
                  budget_basis='Per-unit affordability; budget_units is independent per row, not a $500 basket allocation',
                  scenarios=scenarios, rows=rows, validation=validation,
                  authorization_verified=False, marketplace_verified=False, live_requests=0)
    write_report(rows, config.output, discovery=True, demo=True,
                 job={'mode': 'DEMO — fictional fixtures only', 'evaluation_time': DEMO_NOW.isoformat(),
                      'budget_usd': 500, 'minimum_profit_usd': 5, 'minimum_roi_percent': 50,
                      'email': 'disabled; no credentials loaded', 'live_requests': 0})
    (directory / 'DEMO.json').write_text(json.dumps(result, indent=2, default=str) + '\n')
    lines = ['# DEMO — fictional fixtures; never live deals', '',
             'Fixed evaluation clock: ' + DEMO_NOW.isoformat() + '. No live freshness or authorization is claimed.', '',
             '$500 is a per-unit gate, not a portfolio allocation. Both $5 profit and 50% acquisition ROI must pass.', '',
             '| Fixture | Profit USD | ROI % | Status | Reason |', '| --- | --- | --- | --- | --- |']
    lines += [f"| {r['product']} | {r['profit']} | {r['roi']} | {r['status']} | {r['reason']} |" for r in rows]
    lines += ['', '## Threshold sensitivity (other gates unchanged)', '']
    lines += [f"- {name}: {', '.join(selected)}" for name, selected in scenarios.items()]
    lines += ['', '## Authorized-source CSV validation', '',
              'Schema validation does not prove a license, seller eligibility, fees or live marketplace evidence.', '']
    for name, issues in validation.items():
        lines += ['### ' + name, '']
        lines += [f"- {i['issue']}: {i['action']}" for i in issues] or ['No field issues at the fixed DEMO clock.']
        lines += ['']
    (directory / 'DEMO.md').write_text('\n'.join(lines) + '\n')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, default=ROOT / 'var/demo')
    args = parser.parse_args()
    result = generate(args.output_directory)
    print(json.dumps({key: result[key] for key in ('label', 'live_requests', 'scenarios')}))


if __name__ == '__main__':
    main()
