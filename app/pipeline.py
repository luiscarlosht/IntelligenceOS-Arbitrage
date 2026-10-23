"""Arbitrage MVP: CSV ingestion -> deterministic screening -> Excel report.
No live retailer scraping, marketplace authorization, or automatic purchases.
"""
import csv
from pathlib import Path
import math

ROOT = Path(__file__).resolve().parents[1]
HEADERS = ['source','product','upc','source_url','amazon_asin','destination','buy_cost','sale_price','referral_fee','fulfillment_fee','inbound_shipping','other_cost','eligible','exact_match']

def load_candidates(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        missing = set(HEADERS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f'Missing CSV columns: {sorted(missing)}')
        return list(reader)

def evaluate(row, minimum_roi=50, minimum_profit=5):
    result = dict(row)
    try:
        costs = {key: float(row[key]) for key in ['buy_cost','sale_price','referral_fee','fulfillment_fee','inbound_shipping','other_cost']}
        if any(not math.isfinite(v) or v < 0 for v in costs.values()) or costs['buy_cost'] <= 0:
            raise ValueError('Invalid cost or sale price')
        net = costs['sale_price'] - sum(costs[k] for k in ['buy_cost','referral_fee','fulfillment_fee','inbound_shipping','other_cost'])
        acquisition = costs['buy_cost'] + costs['inbound_shipping'] + costs['other_cost']
        roi = (net / acquisition * 100) if acquisition > 0 else 0
        result.update(profit=round(net,2), roi=round(roi,1))
        reasons = []
        if row['eligible'].strip().lower() != 'yes': reasons.append('Seller eligibility not verified')
        if row['exact_match'].strip().lower() != 'yes': reasons.append('Exact product match not verified')
        if net < minimum_profit: reasons.append('Profit below threshold')
        if roi < minimum_roi: reasons.append('ROI below threshold')
        result['status'] = 'REVIEW' if not reasons else 'REJECT'
        result['reason'] = '; '.join(reasons) or 'Requires manual validation of live data before purchase'
    except (ValueError, KeyError) as e:
        result.update(profit=0,roi=0,status='ERROR',reason=str(e))
    return result

def report(rows, destination):
    from app.reporting import write_report
    write_report(rows, destination)


def main():
    from app.orchestrator import main as run
    run()

if __name__ == '__main__':
    main()
