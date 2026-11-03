"""ASIN upserts through the official Sheets v4 API; dry-run is credential-free."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import re
import time
import uuid

from app.research_contract import SCHEMAS, candidates, browser_contract, validate_candidates

LOG = logging.getLogger(__name__)
API = 'https://sheets.googleapis.com/v4/spreadsheets/'


def cell(value):
    # Literal strings protect leading-zero barcodes and prevent formula execution.
    return {'userEnteredValue': {'stringValue': str(value)}}


def update(sheet_id, row, column, values):
    return {'updateCells': {'start': {'sheetId': sheet_id, 'rowIndex': row, 'columnIndex': column},
        'rows': [{'values': [cell(v) for v in values]}], 'fields': 'userEnteredValue'}}


def index(values, schema, key='asin'):
    if not values: return {}, list(schema)
    header = values[0]
    if len(set(header)) != len(header) or header[:len(schema)] != schema:
        raise ValueError('Sheet schema mismatch')
    pos = header.index(key)
    found = {}
    for n, row in enumerate(values[1:], 1):
        if not row or not any(row): continue
        if len(row) <= pos or not row[pos] or row[pos] in found:
            raise ValueError('Missing/duplicate sheet key')
        found[row[pos]] = n
    return found, header


def plan(rows, metadata, existing, run_id, published_at, scope, source_sha):
    """Pure sparse mutation plan. Existing Browser Use cells are never rewritten."""
    validate_candidates(rows)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', run_id): raise ValueError('Invalid run identifier')
    if not re.fullmatch(r'[a-f0-9]{64}', source_sha): raise ValueError('Source digest required')
    if datetime.fromisoformat(published_at).utcoffset() is None: raise ValueError('Aware publication time required')
    sheets = {s['properties']['title']:s['properties'] for s in metadata.get('sheets', [])}
    requests = []
    ids = {p['sheetId'] for p in sheets.values()}
    indexes = {}
    for title, schema in SCHEMAS.items():
        values = existing.get(title, [])
        indexes[title], _ = index(values, schema, 'run_id' if title == 'Run_Log' else 'asin')
        if title == 'Run_Log' and run_id in indexes[title]:
            prior = values[indexes[title][run_id]]
            if len(prior) < 6 or prior[2:5] != [scope,str(len(rows)),source_sha]:
                raise ValueError('Run ID already binds different publication inputs')
        if title not in sheets:
            sid = next(i for i in range(100, 1000) if i not in ids); ids.add(sid)
            sheets[title] = dict(sheetId=sid, gridProperties={'rowCount':10002,'columnCount':max(26,len(schema))})
            requests.append({'addSheet': {'properties': dict(title=title, **sheets[title])}})
        sid = sheets[title]['sheetId']
        needed = len(values) + len(rows) + 2
        grid = sheets[title].get('gridProperties', {})
        if grid.get('rowCount', 0) < needed:
            requests.append({'updateSheetProperties': {'properties': {'sheetId':sid,'gridProperties':{'rowCount':needed}},'fields':'gridProperties.rowCount'}})
        if grid.get('columnCount',0) < len(schema):
            requests.append({'updateSheetProperties': {'properties': {'sheetId':sid,'gridProperties':{'columnCount':len(schema)}},'fields':'gridProperties.columnCount'}})
        if not values:
            requests.append(update(sid, 0, 0, schema))
            requests.extend([
                {'updateSheetProperties': {'properties': {'sheetId':sid,'gridProperties':{'frozenRowCount':1}},'fields':'gridProperties.frozenRowCount'}},
                {'repeatCell': {'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1,'endColumnIndex':len(schema)},
                    'cell':{'userEnteredFormat':{'backgroundColor':{'red':0.9,'green':0.9,'blue':0.9},'textFormat':{'bold':True},'wrapStrategy':'WRAP'}},
                    'fields':'userEnteredFormat'}},
                {'updateDimensionProperties': {'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':len(schema)},'properties':{'pixelSize':180},'fields':'pixelSize'}},
            ])
    for title in ('Amazon_Candidates','Walmart_Research','Profitability','Review_Queue'):
        schema = SCHEMAS[title]; positions = indexes[title]
        next_row = max(len(existing.get(title, [])), 1)
        for candidate in rows:
            asin = candidate['asin']; found = positions.get(asin)
            if found is None:
                found = next_row; next_row += 1; positions[asin] = found
                if title == 'Amazon_Candidates': values = [candidate[k] for k in schema]
                elif title == 'Walmart_Research': values = [asin] + ['UNKNOWN']*(len(schema)-1); values[schema.index('match_status')] = 'REVIEW_REQUIRED'
                elif title == 'Profitability': values = [asin,'BLOCKED'] + ['UNKNOWN']*5 + ['Fresh Amazon demand/eligibility; exact Walmart receipt; all costs; seller/documentation review']
                else: values = [asin,'REVIEW_REQUIRED','Research only; demand/eligibility/fees and sourcing documentation unverified. See Amazon identity evidence and restrictions.']
                requests.append(update(sheets[title]['sheetId'],found,0,values))
            elif title == 'Amazon_Candidates':
                # Status and all custom columns belong to researchers. Update only owned metadata.
                for col, name in enumerate(schema):
                    if name != 'research_status': requests.append(update(sheets[title]['sheetId'],found,col,[candidate[name]]))
    log_values = existing.get('Run_Log', [])
    log_row = indexes['Run_Log'].get(run_id, max(len(log_values),1))
    requests.append(update(sheets['Run_Log']['sheetId'],log_row,0,
        [run_id,published_at,scope,str(len(rows)),source_sha,'COMPLETE']))
    return requests


class GoogleSheets:
    """Explicit credential selection; no implicit production or ADC discovery."""
    def __init__(self, spreadsheet_id, session, sleep=time.sleep):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', spreadsheet_id): raise ValueError('Spreadsheet ID required')
        self.spreadsheet_id, self.session, self.sleep = spreadsheet_id, session, sleep

    @classmethod
    def from_env(cls):
        spreadsheet_id = os.environ.get('ARBITRAGE_SHEETS_ID', '')
        filename = os.environ.get('ARBITRAGE_SHEETS_CREDENTIALS')
        if not spreadsheet_id or not filename: raise ValueError('ARBITRAGE_SHEETS_ID and ARBITRAGE_SHEETS_CREDENTIALS required')
        from google.auth.transport.requests import AuthorizedSession
        import google.auth
        # Only the explicitly selected, authorized credential file is read.
        try:
            credentials, _ = google.auth.load_credentials_from_file(filename,
                scopes=['https://www.googleapis.com/auth/spreadsheets'])
        except Exception:
            raise RuntimeError('Sheets credential initialization failed') from None
        return cls(spreadsheet_id, AuthorizedSession(credentials))

    def request(self, method, suffix='', **kwargs):
        for attempt in range(5):
            try:
                response = self.session.request(method, API+self.spreadsheet_id+suffix,
                    timeout=30, allow_redirects=False, **kwargs)
            except Exception:
                # Ambiguous transport errors stop; rerun from a fresh read instead of replaying structural changes.
                raise RuntimeError('Sheets transport failed; reread state before recovery') from None
            status = response.status_code
            if 200 <= status < 300: return response.json()
            if status not in (429,500,502,503,504) or attempt == 4:
                raise RuntimeError(f'Sheets API failure status={status}') from None
            LOG.warning(json.dumps(dict(event='sheets_retry',status=status,attempt=attempt+1)))
            self.sleep(min(16, 2**attempt + random.random()))
        raise RuntimeError('Retry exhausted')

    def snapshot(self):
        meta = self.request('GET', params={'fields':'spreadsheetId,spreadsheetUrl,sheets.properties'})
        titles = {s['properties']['title']:s['properties'] for s in meta['sheets']}
        existing = {}
        for title, schema in SCHEMAS.items():
            if title not in titles: continue
            grid = titles[title]['gridProperties']
            # Read all schema columns and all rows within the supported catalog bound.
            if grid['rowCount'] > 20002: raise ValueError('Sheet exceeds supported row bound')
            end = chr(64+len(schema))
            payload = self.request('GET','/values/'+title+'!A1:'+end+str(grid['rowCount']),
                                   params={'valueRenderOption':'FORMULA'})
            existing[title] = payload.get('values', [])
        return meta, existing

    def publish(self, rows, run_id, published_at, scope, source_sha):
        validate_candidates(rows)
        if len(rows) > 25:
            # Each partition is independently atomic and repeatable. Only the
            # parent COMPLETE marker certifies all partitions were verified.
            for offset in range(0, len(rows), 25):
                self.publish(rows[offset:offset+25], run_id+'_'+str(offset//25),
                             published_at, scope+':partition', source_sha)
            meta, existing = self.snapshot()
            positions, _ = index(existing['Run_Log'], SCHEMAS['Run_Log'], 'run_id')
            sid = next(s['properties']['sheetId'] for s in meta['sheets'] if s['properties']['title']=='Run_Log')
            self.request('POST', ':batchUpdate', json={'requests':[update(sid,
                positions.get(run_id,max(len(existing['Run_Log']),1)),0,
                [run_id,published_at,scope,str(len(rows)),source_sha,'COMPLETE'])]})
            return meta.get('spreadsheetUrl')
        meta, existing = self.snapshot()
        requests = plan(rows, meta, existing, run_id, published_at, scope, source_sha)
        # A single Sheets batch is atomic, including the COMPLETE run marker.
        # Bound payload avoids partial multi-batch publications and resource spikes.
        body = {'requests':requests}
        if len(json.dumps(body).encode()) > 1800000:
            raise ValueError('Batch exceeds 1.8 MB; publish catalog partitions with unique run IDs')
        # Structural requests are idempotent by explicit sheet IDs. On an ambiguous
        # reply a retry may fail already-exists; next invocation replans from live state.
        self.request('POST', ':batchUpdate', json=body)
        _, saved = self.snapshot()
        positions, _ = index(saved['Amazon_Candidates'], SCHEMAS['Amazon_Candidates'])
        for row in rows:
            actual = saved['Amazon_Candidates'][positions[row['asin']]]
            for col, name in enumerate(SCHEMAS['Amazon_Candidates']):
                if name != 'research_status' and (len(actual)<=col or actual[col]!=row[name]):
                    raise RuntimeError('Publication readback failed')
        LOG.info(json.dumps(dict(event='sheets_published',run_id=run_id,count=len(rows))))
        return meta.get('spreadsheetUrl')


def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handoff', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--scope', choices=['20','100','all'], default='20')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--run-id', default=None)
    args = parser.parse_args()
    rows, digest = candidates(args.handoff, args.sha256, args.scope)
    # Fresh output keeps prior exports and source evidence unchanged.
    output = args.output.resolve()
    protected = args.handoff.parent.resolve()
    if output.is_relative_to(protected) or protected.is_relative_to(output): raise ValueError('Output overlaps historical evidence')
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    import csv
    with (output/'Amazon_Candidates.csv').open('w', newline='') as f:
        writer=csv.DictWriter(f,fieldnames=SCHEMAS['Amazon_Candidates']);writer.writeheader();writer.writerows(rows)
    (output/'browser_contract.json').write_text(json.dumps(browser_contract(rows),indent=2,ensure_ascii=False)+'\n')
    run_id=args.run_id or uuid.uuid4().hex
    published_at=datetime.now(timezone.utc).isoformat()
    manifest=dict(run_id=run_id,published_at=published_at,scope=args.scope,count=len(rows),source_sha256=digest,mode='live' if args.live else 'dry-run')
    (output/'publication.json').write_text(json.dumps(manifest,indent=2)+'\n')
    if args.live:
        # Serialize this host's publishers. One writer per configured spreadsheet is required across hosts.
        lock=Path('/tmp')/('arbitrage-sheets-'+hashlib.sha256(os.environ.get('ARBITRAGE_SHEETS_ID','').encode()).hexdigest()+'.lock')
        with lock.open('a') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            url=GoogleSheets.from_env().publish(rows,run_id,published_at,args.scope,digest)
        manifest['spreadsheet_url']=url
        (output/'publication.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest))


if __name__ == '__main__': main()
