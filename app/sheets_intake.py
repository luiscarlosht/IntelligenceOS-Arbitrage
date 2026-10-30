"""Manual Sheets ingestion. Sheet values are data; no Amazon operations."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import time
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, ProxyHandler

from app.gmail_api import NoRedirect, read_private, post
from app.models import RetailProduct
from app.normalization import money, timestamp
from app.observations import ObservationStore, canonical, fingerprint, normalized

SPREADSHEET = '1q9TPwNTka_wzSo_T283LBP7iFpfAorR3_QYB19LKDHA'
FIELDS = 'schema_version,batch_id,record_id,source,walmart_item_id,product_url,title,brand,selected_variant,item_price_usd,currency,seller,fulfiller,displayed_zip,shipping_availability,local_delivery_availability,pickup_availability,shipping_charge_usd,observed_at_utc,exported_at_utc,raw_record_json'.split(',')
BATCH_FIELDS = 'batch_id,expected_record_count,actual_record_count,status,completed_at_utc,consumer_status,consumer_acknowledged_at_utc'.split(',')
MAX_ROWS = 1000
ENVELOPE_FIELDS = frozenset(('source', 'schema_version', 'batch_id', 'record_id', 'exported_at_utc'))
# Only observation fields whose exported cells may represent missing evidence.
NULLABLE_OBSERVATION_FIELDS = frozenset((
    'brand', 'selected_variant', 'seller', 'fulfiller',
    'shipping_availability', 'local_delivery_availability', 'pickup_availability',
    'shipping_charge_usd',
))


class ValidationFailure(ValueError):
    """Only fixed internal labels may be exposed to operators."""

    def __init__(self, code, field):
        super().__init__(code)
        self.code, self.field = code, field


def checked(field, validator, value):
    try:
        return validator(value)
    except (ValueError, TypeError, AttributeError):
        raise ValidationFailure('INVALID_VALUE', field) from None


def validate_raw(row):
    try:
        raw = json.loads(row['raw_record_json'],
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError):
        raise ValidationFailure('INVALID_JSON', 'raw_record_json') from None
    if not isinstance(raw, dict):
        raise ValidationFailure('INVALID_JSON_OBJECT', 'raw_record_json')
    # Preserve the earlier exact exported-text mirror as well as original browser JSON.
    mirror = {k: v for k, v in row.items() if k != 'raw_record_json'}
    if raw == mirror:
        return
    browser = any(k in raw for k in ('displayed_price', 'observation_timestamp', 'shipping_charge'))
    if not browser and set(raw) != set(mirror):
        raise ValidationFailure('RAW_FIELDS_MISMATCH', 'raw_record_json')
    # Envelope values are validated independently by product/process. They are
    # never required in original browser JSON. Optional legacy copies must agree.
    if browser:
        for field in sorted(ENVELOPE_FIELDS & raw.keys()):
            if type(raw[field]) is not str or raw[field] != row[field]:
                raise ValidationFailure('RAW_EXPORT_MISMATCH', field)
    aliases = {'item_price_usd': 'displayed_price', 'observed_at_utc': 'observation_timestamp',
               'shipping_charge_usd': 'shipping_charge'}
    for field, exported in mirror.items():
        if browser and field in ENVELOPE_FIELDS:
            continue
        key = aliases.get(field, field) if browser else field
        if key not in raw:
            raise ValidationFailure('RAW_FIELD_MISSING', field)
        value = raw[key]
        if field in NULLABLE_OBSERVATION_FIELDS and (value is None or value == ''):
            # JSON null means missing evidence, exactly like a literal blank cell.
            # No title parsing, whitespace trimming or populated-value substitution.
            agrees = exported == ''
        elif browser and field in ('item_price_usd', 'shipping_charge_usd'):
            if isinstance(value, str) and value.startswith('$'):
                value = value[1:]
            raw_money = checked(field, money, value) if type(value) is str else None
            agrees = (raw_money is not None and
                      raw_money == checked(field, money, exported))
        elif browser and field == 'displayed_zip':
            # Accept only an explicit city, ZIP pair; never search arbitrary text.
            match = (re.fullmatch(r"(?:[A-Za-z]+(?:[ .'-][A-Za-z]+)*, )?([0-9]{5})", value)
                     if type(value) is str else None)
            agrees = match is not None and match[1] == exported
        elif browser and field == 'observed_at_utc':
            agrees = checked(field, stamp, value) == checked(field, stamp, exported)
        else:
            agrees = type(value) is str and value == exported
        if not agrees:
            raise ValidationFailure('RAW_EXPORT_MISMATCH', field)
        # A duplicate canonical field cannot contradict its browser alias.
        if browser and key != field and field in raw:
            canonical_value = raw[field]
            missing = (field in NULLABLE_OBSERVATION_FIELDS and
                       canonical_value is None and exported == '')
            if not missing and not (type(canonical_value) is str and canonical_value == exported):
                raise ValidationFailure('RAW_EXPORT_MISMATCH', field)


class Deadline(BaseException):
    """Overall deadline must escape per-batch failure recovery."""



def now():
    return datetime.now(timezone.utc)


def table(values, fields):
    if not values or values[0] != fields or len(values) > MAX_ROWS + 1:
        raise ValueError('Invalid sheet schema or row bound')
    rows = []
    for cells in values[1:]:
        if not cells or all(x == '' for x in cells):
            continue
        if len(cells) > len(fields) or any(type(x) is not str for x in cells):
            raise ValueError('Text cells required')
        rows.append(dict(zip(fields, cells + [''] * (len(fields)-len(cells)))))
    return rows


def stamp(value):
    result = timestamp(value)
    if result is None or result.utcoffset().total_seconds() != 0 or result > now():
        raise ValueError('UTC timestamp required')
    return result


def identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise ValueError('Invalid identifier')


def record_identifier(value):
    """Producer record keys are opaque literals, including batch:item keys."""
    if not re.fullmatch(r'[A-Za-z0-9_:-]{1,128}', value):
        raise ValueError('Invalid record identifier')


def availability_description(field, value):
    """Keep source wording separate from conservative, channel-specific evidence."""
    if len(value) > 1000 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValidationFailure('INVALID_VALUE', field)
    if value in ('', 'UNKNOWN'):
        return None
    if value in ('AVAILABLE', 'UNAVAILABLE'):
        return value
    text = value.casefold().strip()
    channel = {'shipping_availability': 'shipping',
               'local_delivery_availability': 'delivery',
               'pickup_availability': 'pickup'}[field]
    # Recognize only explicit wording for this channel. Unrecognized descriptions
    # remain literal evidence with unknown normalized availability.
    negative = re.fullmatch(rf'{channel} (?:unavailable|not available)', text)
    if negative:
        return 'UNAVAILABLE'
    day = r'(?:today|tomorrow|(?:mon|tues|wednes|thurs|fri|satur|sun)day|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec) [0-9]{1,2})'
    if channel == 'shipping':
        positive = re.fullmatch(rf'shipping arrives {day}', text)
    else:
        arrival = rf'(?:[0-9]+ (?:min|mins|minutes|hour|hours)|(?:[1-9]|1[0-2])(?::[0-5][0-9])?(?:am|pm)(?: {day})?)'
        positive = re.fullmatch(rf'{channel} as soon as {arrival}', text)
    if positive:
        return 'AVAILABLE'
    # Contradictory wording must never turn into an available channel.
    if re.search(r'\b(?:unavailable|not available)\b', text) and re.search(r'\b(?:arrives|as soon as|available)\b', text.replace('not available', '')):
        raise ValidationFailure('CONFLICTING_AVAILABILITY', field)
    return None


def product(row):
    for field, expected in (('schema_version', '1'), ('currency', 'USD')):
        if row[field] != expected:
            raise ValidationFailure('UNSUPPORTED_VALUE', field)
    for key in ('batch_id', 'source'):
        checked(key, identifier, row[key])
    checked('record_id', record_identifier, row['record_id'])
    item = row['walmart_item_id']
    if not re.fullmatch(r'[0-9]{1,30}', item):
        raise ValidationFailure('INVALID_VALUE', 'walmart_item_id')
    url = checked('product_url', urlsplit, row['product_url'])
    if (url.scheme != 'https' or url.hostname not in ('walmart.com', 'www.walmart.com')
            or url.username or url.password or not url.path.startswith('/ip/')
            or url.path.rstrip('/').split('/')[-1] != item):
        raise ValidationFailure('INVALID_VALUE', 'product_url')
    if not row['title'].strip():
        raise ValidationFailure('INVALID_VALUE', 'title')
    if not re.fullmatch(r'[0-9]{5}', row['displayed_zip']):
        raise ValidationFailure('INVALID_VALUE', 'displayed_zip')
    observed, exported = checked('observed_at_utc', stamp, row['observed_at_utc']), checked('exported_at_utc', stamp, row['exported_at_utc'])
    if observed > exported:
        raise ValidationFailure('TIMESTAMP_ORDER', 'observed_at_utc')
    price, shipping = checked('item_price_usd', money, row['item_price_usd']), checked('shipping_charge_usd', money, row['shipping_charge_usd'])
    if price is None or price <= 0:
        raise ValidationFailure('INVALID_VALUE', 'item_price_usd')
    validate_raw(row)
    channels = {}
    for key in ('shipping_availability', 'local_delivery_availability', 'pickup_availability'):
        channels[key] = availability_description(key, row[key])
        channels[key + '_description'] = row[key]
    context = dict(source_provider=row['source'], retailer_item_id=item, brand=row['brand'],
        source_seller=row['seller'] or None, fulfiller=row['fulfiller'] or None,
        observed_zip=row['displayed_zip'], source_shipping_cost=shipping,
        product_identity='walmart:'+item, **channels)
    return RetailProduct('Walmart', row['title'], row['product_url'], '', '', '', None,
        price, 'unknown', observed, 'Google Sheets '+SPREADSHEET+'; source='+row['source'],
        variation=row['selected_variant'], issues=('Package quantity and identity unverified',),
        source_context=context)


class IntakeStore(ObservationStore):
    def __init__(self, path):
        super().__init__(path)
        with self.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS sheets_batches (
                batch_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, metadata_json TEXT NOT NULL,
                stored_at TEXT NOT NULL, acknowledged_at TEXT);
              CREATE TABLE IF NOT EXISTS sheets_import_summaries (
                id INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL, summary_json TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS sheets_records (
                record_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES sheets_batches(batch_id),
                content_hash TEXT NOT NULL, original_json TEXT NOT NULL,
                observation_id INTEGER NOT NULL REFERENCES source_observations(id));
            ''')

    def store(self, batch, rows, products):
        metadata = {k: batch[k] for k in BATCH_FIELDS[:5]}
        digest = fingerprint(dict(batch=metadata, rows=sorted(rows, key=lambda r: r['record_id'])))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT content_hash FROM sheets_batches WHERE batch_id=?', (batch['batch_id'],)).fetchone()
            if previous:
                if previous[0] != digest:
                    raise ValidationFailure('CHANGED_BATCH_PAYLOAD', 'batch_id')
                return False
            db.execute('INSERT INTO sheets_batches VALUES (?,?,?,?,NULL)',
                (batch['batch_id'], digest, canonical(metadata), normalized(now())))
            for row, p in zip(rows, products):
                key = fingerprint(p)
                db.execute('''INSERT OR IGNORE INTO source_observations
                    (fingerprint,retailer,gtin,observed_at,provenance,authorization_reference,purchase_price,payload_json,first_seen_at)
                    VALUES (?,?,?,?,?,?,?,?,?)''', (key,p.retailer,p.gtin,normalized(p.retrieved_at),p.provenance,
                        p.authorization_reference,normalized(p.purchase_price),canonical(p),normalized(now())))
                oid = db.execute('SELECT id FROM source_observations WHERE fingerprint=?', (key,)).fetchone()[0]
                db.execute('INSERT INTO sheets_records VALUES (?,?,?,?,?)',
                    (row['record_id'], batch['batch_id'], fingerprint(row), canonical(row), oid))
        return True

    def products(self, batch_id):
        """Offline connector for candidate planning; no ten/twenty-row executor assumptions."""
        with self.connect() as db:
            payloads = db.execute('SELECT original_json FROM sheets_records WHERE batch_id=? ORDER BY record_id',
                                  (batch_id,)).fetchall()
        return tuple(product(json.loads(p[0])) for p in payloads)


    def candidate_plan(self, batch_id):
        """Reuse existing keyword planning without product collection or Amazon calls."""
        from app.source_keywords import search_keywords
        return dict(batch_id=batch_id, execution_authorized=False, live_requests=0,
            candidates=[dict(product_identity=p.source_context['product_identity'],
                             source_fingerprint=fingerprint(p), keywords=search_keywords(p))
                        for p in self.products(batch_id)])



def process(client, store=None):
    batches = table(client.read('Walmart_Batches', 'A:G'), BATCH_FIELDS)
    rows = table(client.read('Walmart_Intake', 'A:U'), FIELDS)
    summary = dict(accepted=0, rejected=0, already_stored=0, pending_acknowledgment=0, incomplete=0, rejections=[])
    ids = [b['batch_id'] for b in batches]
    for batch in batches:
        if batch['status'] != 'COMPLETE':
            summary['incomplete'] += 1
            continue
        try:
            checked('batch_id', identifier, batch['batch_id'])
            if ids.count(batch['batch_id']) != 1:
                raise ValidationFailure('DUPLICATE_BATCH', 'batch_id')
            selected = [r for r in rows if r['batch_id'] == batch['batch_id']]
            count = str(len(selected))
            for field in ('expected_record_count', 'actual_record_count'):
                if count == '0' or batch[field] != count:
                    raise ValidationFailure('COUNT_MISMATCH', field)
            if len({r['record_id'] for r in selected}) != len(selected):
                raise ValidationFailure('DUPLICATE_RECORD', 'record_id')
            if any(sum(r['record_id'] == other['record_id'] for other in rows) != 1 for r in selected):
                raise ValidationFailure('CONFLICTING_RECORD', 'record_id')
            completed = checked('completed_at_utc', stamp, batch['completed_at_utc'])
            products = [product(r) for r in selected]
            if any(stamp(r['exported_at_utc']) > completed for r in selected):
                raise ValidationFailure('TIMESTAMP_ORDER', 'completed_at_utc')
            fresh = store.store(batch, selected, products) if store else True
        except Exception as exc:
            summary['rejections'].append(dict(
                code=exc.code if isinstance(exc, ValidationFailure) else 'BATCH_VALIDATION_FAILED',
                field=exc.field if isinstance(exc, ValidationFailure) else 'batch'))
            summary['rejected'] += 1
            continue
        summary['accepted' if fresh else 'already_stored'] += 1
        if store:
            try:
                # Revalidate producer metadata and ID immediately before cell-specific write.
                current = client.read('Walmart_Batches', 'A:G')
                current_rows = table(current, BATCH_FIELDS)
                matches = [b for b in current_rows if b['batch_id'] == batch['batch_id']]
                if len(matches) != 1 or any(matches[0][k] != batch[k] for k in BATCH_FIELDS[:5]):
                    raise ValueError('Batch moved or changed')
                positions = [i for i, cells in enumerate(current[1:], 2) if cells and cells[0] == batch['batch_id']]
                if len(positions) != 1:
                    raise ValueError('Ambiguous batch location')
                acknowledged = normalized(now())
                client.ack(positions[0], acknowledged)
                with store.connect() as db:
                    db.execute('UPDATE sheets_batches SET acknowledged_at=? WHERE batch_id=?', (acknowledged,batch['batch_id']))
            except Exception:
                summary['pending_acknowledgment'] += 1
    if store:
        with store.connect() as db:
            summary['pending_acknowledgment'] = db.execute('SELECT count(*) FROM sheets_batches WHERE acknowledged_at IS NULL').fetchone()[0]
            db.execute('INSERT INTO sheets_import_summaries(recorded_at,summary_json) VALUES (?,?)',
                       (normalized(now()), canonical(summary)))
    return summary


class SheetsClient:
    def __init__(self, path, writable=False):
        from google.oauth2.service_account import Credentials
        data = read_private(path)
        if data.get('type') != 'service_account' or data.get('token_uri') != 'https://oauth2.googleapis.com/token':
            raise ValueError('Dedicated service account required')
        scope = 'https://www.googleapis.com/auth/spreadsheets' + ('' if writable else '.readonly')
        credentials = Credentials.from_service_account_info(data, scopes=[scope])
        from urllib.parse import urlencode
        # Sign locally, then one bounded token POST using the existing verified transport.
        from google.auth import jwt
        issued = int(time.time())
        assertion = jwt.encode(credentials.signer, dict(iss=credentials.service_account_email,
            scope=scope, aud='https://oauth2.googleapis.com/token', iat=issued,
            exp=issued+3600)).decode('ascii')
        token = post('https://oauth2.googleapis.com/token', urlencode(dict(
            grant_type='urn:ietf:params:oauth:grant-type:jwt-bearer', assertion=assertion)).encode(),
            {'Content-Type': 'application/x-www-form-urlencoded'})
        self.access = token.get('access_token')
        if not isinstance(self.access, str) or not self.access:
            raise ValueError('Invalid token response')
        self.base = 'https://sheets.googleapis.com/v4/spreadsheets/'+SPREADSHEET+'/values/'

    def request(self, suffix, payload=None):
        req = Request(self.base.rstrip('/')+suffix if suffix.startswith(':') else self.base+suffix, data=None if payload is None else canonical(payload).encode(),
            headers={'Authorization':'Bearer '+self.access, 'Content-Type':'application/json'},
            method='GET' if payload is None else 'POST')
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=15) as response:
            raw = response.read(4*1024*1024+1)
            if len(raw) > 4*1024*1024:
                raise ValueError('Response bound')
            return json.loads(raw)

    def read(self, tab, columns):
        start, end = columns.split(':')
        values = self.request(quote(f"'{tab}'!{start}:{end}", safe='')+
            '?valueRenderOption=UNFORMATTED_VALUE&dateTimeRenderOption=SERIAL_NUMBER').get('values', [])
        if len(values) > MAX_ROWS+1:
            raise ValueError('Row bound reached; split sheet before ingestion')
        return values

    def ack(self, row, acknowledged):
        result = self.request(':batchUpdate', dict(valueInputOption='RAW', data=[dict(
            range=f"'Walmart_Batches'!F{row}:G{row}", values=[['STORED', acknowledged]])]))
        if result.get('totalUpdatedCells') != 2:
            raise ValueError('Acknowledgment response not confirmed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'ingest', 'summary'))
    parser.add_argument('--database', type=Path, default=Path('var/sheets-intake.sqlite3'))
    args = parser.parse_args()
    def deadline(*_):
        raise Deadline()
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(120)
    try:
        if args.action == 'summary':
            if not args.database.is_file():
                raise ValueError('Existing intake database required')
            store = IntakeStore(args.database)
            with store.connect() as db:
                stored, pending = db.execute('SELECT count(*), count(*) FILTER (WHERE acknowledged_at IS NULL) FROM sheets_batches').fetchone()
                latest = db.execute('SELECT summary_json FROM sheets_import_summaries ORDER BY id DESC LIMIT 1').fetchone()
            print(canonical(dict(stored_batches=stored, pending_acknowledgment=pending,
                last_import=json.loads(latest[0]) if latest else None)))
            return 0
        path = Path(os.environ['ARBITRAGE_SHEETS_CREDENTIAL_FILE'])
        if 'WeinsteinAgent' in path.parts or not path.is_absolute():
            raise ValueError('Dedicated absolute credential path required')
        client = SheetsClient(path, writable=args.action == 'ingest')
        print(canonical(process(client, IntakeStore(args.database) if args.action == 'ingest' else None)))
        return 0
    except (Exception, Deadline):
        print('Sheets intake stopped; inspect setup and retry manually. No automatic retries.')
        return 1
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    raise SystemExit(main())
