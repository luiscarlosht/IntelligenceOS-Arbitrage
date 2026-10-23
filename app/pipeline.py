"""Arbitrage MVP: CSV ingestion -> deterministic screening -> Excel report.
No live retailer scraping, marketplace authorization, or automatic purchases.
"""
import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from artifact_tool import Workbook, SpreadsheetFile

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
        if any(v < 0 for v in costs.values()) or costs['buy_cost'] <= 0:
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
    wb = Workbook.create()
    summary = wb.worksheets.add('Executive Summary')
    summary.get_range('A1:B7').values = [
        ['INTELLIGENCEOS ARBITRAGE','MVP • illustrative inputs'],
        ['Run (UTC)', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')],
        ['Candidates',len(rows)],
        ['Review candidates',sum(r['status']=='REVIEW' for r in rows)],
        ['Rejected',sum(r['status']=='REJECT' for r in rows)],
        ['Errors',sum(r['status']=='ERROR' for r in rows)],
        ['Notice','Not live quotes. Verify listing, fees, rights and availability.'],
    ]
    summary.get_range('A1:B1').format.fill='#12304A'
    summary.get_range('A1:B1').format.font.color='#FFFFFF'
    summary.get_range('A:A').format.column_width=28
    summary.get_range('B:B').format.column_width=66
    cols=['source','product','upc','amazon_asin','destination','buy_cost','sale_price','profit','roi','status','reason','source_url']
    for name, selected in [('Top Opportunities', sorted([r for r in rows if r['status']=='REVIEW'], key=lambda r:r['roi'],reverse=True)),('All Candidates',rows),('Rejected Products',[r for r in rows if r['status']!='REVIEW'])]:
        sheet=wb.worksheets.add(name)
        data=[[str(r.get(k,'')) if k in ('upc','amazon_asin','source_url') else r.get(k,'') for k in cols] for r in selected]
        sheet.get_range_by_indexes(0,0,1,len(cols)).values=[cols]
        if data: sheet.get_range_by_indexes(1,0,len(data),len(cols)).values=data
        sheet.get_range('A1:L1').format.fill='#12304A'
        sheet.get_range('A1:L1').format.font.color='#FFFFFF'
        sheet.get_range('A:A').format.column_width=19
        sheet.get_range('B:B').format.column_width=35
        sheet.get_range('K:K').format.column_width=60
        sheet.get_range('L:L').format.column_width=48
        sheet.freeze_panes.freeze_rows(1)
    Path(destination).parent.mkdir(parents=True,exist_ok=True)
    SpreadsheetFile.export_xlsx(wb).save(str(destination))

def main():
    source=Path(os.getenv('ARBITRAGE_INPUT', ROOT/'sample_data'/'candidates.csv'))
    output=Path(os.getenv('ARBITRAGE_REPORT',ROOT/'reports'/'arbitrage_report.xlsx'))
    candidates=[evaluate(row) for row in load_candidates(source)]
    report(candidates,output)
    print(f'Generated {output}; {len(candidates)} candidates; {sum(r["status"]=="REVIEW" for r in candidates)} review candidates')

if __name__=='__main__': main()
