"""Computed analysis only. Saved read-only preview required before publication."""
from datetime import datetime
from decimal import Decimal

from app.amazon_evaluation import EvaluationPolicy, timestamp
from app.analysis_adapters import ManualAmazon, SheetsEvidence
from app.analysis_engine import analyze_record
from app.observations import canonical, fingerprint
from app.sheets_publisher import index, update
from app.sheets_intake import SPREADSHEET as SOURCE
from urllib.parse import quote

TAB = 'Amazon_Analysis'
HEADERS = ('asin decision eligibility fba_base_profit fbm_base_profit financials_json '
           'missing_data_json market_json evaluated_at evidence_sha256 result_json').split()


def values(client, meta: dict) -> list:
    props = next((s['properties'] for s in meta['sheets'] if s['properties']['title'] == TAB), None)
    if props is None:
        return []
    if props['gridProperties']['rowCount'] > 20002:
        raise ValueError('Analysis snapshot row bound')
    return client.request('values/'+quote("'"+TAB+"'!A1:K"+str(props['gridProperties']['rowCount']),safe='')+
                          '?valueRenderOption=FORMULA').get('values', [])


def cells(report: dict) -> list[str]:
    return [report['asin'], report['decision'], report['eligibility']['status'],
        report['financials']['FBA']['base']['net_profit'], report['financials']['FBM']['base']['net_profit'],
        canonical(report['financials']), canonical(report['missing_data']), canonical(report['market']),
        report['evaluated_at'], report['evidence_sha256'], canonical(report)]


def plan(reports: list[dict], meta: dict, existing: list) -> list[dict]:
    positions, _ = index(existing, HEADERS)
    keys = [r['asin'] for r in reports]
    if not 1 <= len(keys) <= 1000 or len(keys) != len(set(keys)):
        raise ValueError('1–1000 unique analysis ASINs required')
    props = {s['properties']['title']: s['properties'] for s in meta['sheets']}
    requests = []
    if TAB not in props:
        if existing:
            raise ValueError('Inconsistent analysis snapshot')
        used = {p['sheetId'] for p in props.values()}
        sid = next(n for n in range(100,1000) if n not in used)
        requests.append({'addSheet': {'properties': dict(sheetId=sid,title=TAB,
            gridProperties=dict(rowCount=2002,columnCount=len(HEADERS),frozenRowCount=1))}})
    else:
        sid = props[TAB]['sheetId']
        grid = props[TAB]['gridProperties']
        if grid['rowCount'] < max(1,len(existing))+sum(k not in positions for k in keys) or grid['columnCount'] < len(HEADERS):
            raise ValueError('Analysis grid capacity requires review')
    if not existing:
        requests.append(update(sid,0,0,HEADERS))
    next_row=max(1,len(existing))
    for report in reports:
        row=cells(report)
        if any(len(str(v)) > 49000 for v in row):
            raise ValueError('Analysis exceeds cell bound; reduce input notes')
        n=positions.get(report['asin'])
        if n is None:
            n=next_row;next_row+=1
        requests.append(update(sid,n,0,row))
    if len(canonical(requests).encode()) > 1800000:
        raise ValueError('Analysis batch too large; use smaller partition')
    return requests


def preview(client, records: list[dict], now: datetime, policy: EvaluationPolicy = EvaluationPolicy(),
            from_sheets: bool = False) -> dict:
    client.select(SOURCE)
    source_sha256 = None
    if from_sheets:
        evidence = SheetsEvidence(client)
        records = evidence.records()
        source_sha256 = evidence.snapshot_sha256
    records=ManualAmazon(records).records()
    reports=[analyze_record(r,now,policy) for r in records]
    meta=client.metadata();existing=values(client,meta)
    requests=plan(reports,meta,existing)
    return dict(schema='analysis_publication_preview_v2',workbook=SOURCE,
        evaluated_at=now.isoformat(), from_sheets=from_sheets, source_sha256=source_sha256,
        records=records,reports=reports,
        policy=dict(minimum_profit=str(policy.minimum_profit),minimum_roi=str(policy.minimum_roi)),
        snapshot_sha256=fingerprint([meta,existing]), requests=requests)


def publish(client, proposal: dict, now: datetime, *, approved: bool = False) -> dict:
    if not approved:
        raise PermissionError('Explicit owner approval required')
    if (proposal.get('schema') != 'analysis_publication_preview_v2' or proposal.get('workbook') != SOURCE
            or not timestamp(proposal.get('evaluated_at'),now,hours=0.25)):
        raise ValueError('Fresh fifteen-minute preview required')
    when=datetime.fromisoformat(proposal['evaluated_at'])
    policy=EvaluationPolicy(**{k:Decimal(v) for k,v in proposal['policy'].items()})
    fresh=preview(client,proposal['records'],when,policy,proposal['from_sheets'])
    if canonical(fresh) != canonical(proposal):
        raise ValueError('Source, output, policy or snapshot changed; generate another read-only preview')
    for record, report in zip(fresh['records'], fresh['reports']):
        current=analyze_record(record,now,policy)
        current['evaluated_at']=report['evaluated_at']
        if canonical(current) != canonical(report):
            raise ValueError('Evidence expired since preview; regenerate analysis')
    client.request(':batchUpdate',{'requests':fresh['requests']})
    saved=values(client,client.metadata());positions,_=index(saved,HEADERS)
    for report in fresh['reports']:
        if saved[positions[report['asin']]][:len(HEADERS)] != cells(report):
            raise ValueError('Analysis publication readback failed; inspect before retry')
    return dict(mode='published',asins=len(fresh['reports']),purchase_authorized=False)
