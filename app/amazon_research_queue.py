"""Publish the frozen original cohort into the existing Walmart workbook."""
import argparse
import fcntl
import json
import os
from pathlib import Path
from urllib.parse import quote

from app.sheets_intake import SheetsClient, SPREADSHEET
from app.sheets_publisher import update as publisher_update

SOURCE = '1FcbY7OLu5Vz50IehxuA23E6obwuxt6_SYtFgRUac0ps'
TAB = 'Amazon_Research_Queue'
ORIGINAL_ASINS = tuple('B00004OCNJ B00004Z4CY B000255NH8 B0002AR73G B0002YTVJA B00061SL0Y B0009J4YAO B000AQSCE0 B000ND1YTU B000NP2SBG B000YZ8N46 B000YZASYO B002ACOEPS B0058PTK6M B005HVZ59I B007I6FS10 B007OX6E3S B008OAE82E B00979EMAO B00BTGSGFK'.split())
IDENTITY = 'priority asin amazon_title brand upc gtin model pack_count size variant amazon_url'.split()
RESEARCH = 'walmart_url walmart_price shipping_cost seller fulfillment displayed_zip stock match_status evidence_url research_timestamp notes'.split()
HEADERS = IDENTITY + RESEARCH
HISTORY = ('Walmart_Intake', 'Walmart_Batches', 'Walmart_Benchmark')


def candidates(values: list) -> list[list[str]]:
    if not values or len(set(values[0])) != len(values[0]) or not set(IDENTITY) <= set(values[0]):
        raise ValueError('Required source headers missing or duplicated')
    positions = [values[0].index(k) for k in IDENTITY]
    rows = [[str(row[i]) if i < len(row) and row[i] != '' else 'UNKNOWN' for i in positions]
            for row in values[1:] if any(row)]
    keys = [row[1] for row in rows]
    if len(keys) != 20 or len(set(keys)) != 20 or set(keys) != set(ORIGINAL_ASINS):
        raise ValueError('Exactly the original 20 unique ASINs required')
    for row in rows:
        if row[-1] != 'https://www.amazon.com/dp/' + row[1]:
            raise ValueError('Amazon URL does not match ASIN')
    return rows


def update(sid: int, row: int, values: list[str]) -> dict:
    return publisher_update(sid, row, 0, values)


def index(values: list) -> dict[str, int]:
    if not values:
        return {}
    if values[0][:len(HEADERS)] != HEADERS or len(set(values[0])) != len(values[0]):
        raise ValueError('Destination headers mismatch')
    found = {}
    for n, row in enumerate(values[1:], 1):
        if not any(row):
            continue
        if len(row) < 2 or row[1] not in ORIGINAL_ASINS or row[1] in found:
            raise ValueError('Missing, unexpected or duplicate destination ASIN')
        found[row[1]] = n
    return found


def plan(rows: list, metadata: dict, existing: list) -> list[dict]:
    candidates([IDENTITY] + rows)
    found = index(existing)
    props = {s['properties']['title']: s['properties'] for s in metadata['sheets']}
    if not set(HISTORY) <= props.keys():
        raise ValueError('Existing Walmart history tabs required')
    requests = []
    if TAB not in props:
        if existing:
            raise ValueError('Inconsistent destination snapshot')
        used = {p['sheetId'] for p in props.values()}
        sid = next(i for i in range(100, 1000) if i not in used)
        requests.append({'addSheet': {'properties': {'sheetId': sid, 'title': TAB,
            'gridProperties': {'rowCount': 1000, 'columnCount': 26, 'frozenRowCount': 1}}}})
    else:
        sid = props[TAB]['sheetId']
        grid = props[TAB]['gridProperties']
        if grid['rowCount'] < max(len(existing), 1) + 20 or grid['columnCount'] < len(HEADERS):
            raise ValueError('Queue grid needs operator review')
    if not existing:
        requests.append(update(sid, 0, HEADERS))
    next_row = max(len(existing), 1)
    for row in rows:
        if row[1] in found:
            # Only publisher-owned identity cells; never touch existing research cells.
            requests.append(update(sid, found[row[1]], row))
        else:
            research = ['REVIEW_REQUIRED' if k == 'match_status' else 'UNKNOWN' for k in RESEARCH]
            requests.append(update(sid, next_row, row + research))
            next_row += 1
    return requests


class QueueClient(SheetsClient):
    """Reuse intake credentials, JWT exchange, bounded TLS transport and reads."""
    def select(self, spreadsheet: str) -> None:
        if spreadsheet not in (SOURCE, SPREADSHEET):
            raise ValueError('Unexpected workbook')
        self.base = 'https://sheets.googleapis.com/v4/spreadsheets/' + spreadsheet + '/'

    def metadata(self) -> dict:
        # A query belongs on the spreadsheet resource, with no trailing slash.
        return self.request('?fields=spreadsheetId,sheets.properties')

    def values(self, tab: str) -> list:
        props = next(s['properties'] for s in self.metadata()['sheets']
                     if s['properties']['title'] == tab)
        grid = props['gridProperties']
        if grid['rowCount'] > 20002 or grid['columnCount'] > 26:
            raise ValueError('Sheet exceeds supported snapshot bound')
        end = chr(64 + grid['columnCount']) + str(grid['rowCount'])
        return self.request('values/' + quote("'" + tab + "'!A1:" + end, safe='') +
                            '?valueRenderOption=FORMULA').get('values', [])


def publish(client: QueueClient, live: bool = False) -> dict:
    client.select(SOURCE)
    rows = candidates(client.values('Amazon_Candidates'))
    client.select(SPREADSHEET)
    metadata = client.metadata()
    titles = {s['properties']['title'] for s in metadata['sheets']}
    existing = client.values(TAB) if TAB in titles else []
    history = {tab: client.values(tab) for tab in HISTORY}
    requests = plan(rows, metadata, existing)
    if not live:
        return dict(mode='preview', unique_asins=20, requests=len(requests))
    # Require a single writer; stop if source/destination changed during planning.
    client.select(SOURCE)
    if candidates(client.values('Amazon_Candidates')) != rows:
        raise ValueError('Source changed during planning')
    client.select(SPREADSHEET)
    if client.metadata() != metadata or (TAB in titles and client.values(TAB) != existing):
        raise ValueError('Destination changed during planning')
    client.request(':batchUpdate', {'requests': requests})
    saved = client.values(TAB)
    found = index(saved)
    if len(found) != 20 or any(saved[found[r[1]]][:len(IDENTITY)] != r for r in rows):
        raise ValueError('Queue readback failed')
    for key, position in index(existing).items():
        if saved[found[key]][len(IDENTITY):] != existing[position][len(IDENTITY):]:
            raise ValueError('Research changed during publication; inspect concurrent edits')
    if any(client.values(tab) != history[tab] for tab in HISTORY):
        raise ValueError('History changed during publication; inspect concurrent edits')
    return dict(mode='published', unique_asins=20, history_unchanged=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    path = Path(os.environ['ARBITRAGE_SHEETS_CREDENTIAL_FILE'])
    if not path.is_absolute() or 'WeinsteinAgent' in path.parts:
        raise ValueError('Existing dedicated absolute credential path required')
    with Path('/tmp/arbitrage-amazon-research-queue.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        client = QueueClient(path, writable=args.live)
        try:
            print(json.dumps(publish(client, args.live)))
        except Exception:
            raise SystemExit('Queue publication stopped; reread state before retry. No automatic retries.') from None


if __name__ == '__main__':
    main()
