import copy
import json
import sqlite3
import pytest
from app.sheets_intake import FIELDS, BATCH_FIELDS, IntakeStore, process, product


def fixture():
    row = dict.fromkeys(FIELDS, '')
    row.update(schema_version='1',batch_id='b1',record_id='r1',source='browser-use-walmart',
        walmart_item_id='00123',product_url='https://www.walmart.com/ip/widget/00123',title='Widget',
        item_price_usd='10.25',currency='USD',displayed_zip='00123',shipping_availability='UNKNOWN',
        observed_at_utc='2026-01-01T00:00:00Z',exported_at_utc='2026-01-01T00:01:00Z')
    row['raw_record_json'] = json.dumps({k:v for k,v in row.items() if k!='raw_record_json'})
    batch = ['b1','1','1','COMPLETE','2026-01-01T00:02:00Z','','']
    return row, batch


class Client:
    def __init__(self):
        row, batch = fixture()
        self.rows = [FIELDS, [row[k] for k in FIELDS]]
        self.batches = [BATCH_FIELDS, batch]
        self.writes = []
        self.fail = False
    def read(self, tab, _):
        return copy.deepcopy(self.rows if tab=='Walmart_Intake' else self.batches)
    def ack(self, row, stamp):
        if self.fail:
            raise OSError('mock')
        self.writes.append((row,stamp))


def test_read_only(tmp_path):
    c = Client()
    assert process(c)['accepted']==1
    assert not c.writes
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('change', ['incomplete','count','price','raw','duplicate','timestamp','url'])
def test_invalid(tmp_path, change):
    c = Client()
    if change=='incomplete': c.batches[1][3]='WRITING'
    elif change=='count': c.batches[1][1]='2'
    elif change=='duplicate': c.rows.append(c.rows[1][:]); c.batches[1][1:3]=['2','2']
    else:
        field = dict(price='item_price_usd',raw='raw_record_json',timestamp='observed_at_utc',url='product_url')[change]
        c.rows[1][FIELDS.index(field)] = 'invalid'
    s = IntakeStore(tmp_path/'db')
    result=process(c,s)
    assert result['accepted']==0
    assert not c.writes
    with s.connect() as db:
        assert db.execute('SELECT count(*) FROM source_observations').fetchone()[0]==0


def test_duplicate_conflict_recovery(tmp_path):
    c=Client(); s=IntakeStore(tmp_path/'db'); c.fail=True
    assert process(c,s)['pending_acknowledgment']==1
    c.fail=False
    assert process(c,s)['already_stored']==1
    assert process(c,s)['pending_acknowledgment']==0
    with s.connect() as db:
        assert db.execute('SELECT count(*) FROM source_observations').fetchone()[0]==1
    row,batch=fixture(); row['title']='Changed'
    row['raw_record_json']=json.dumps({k:v for k,v in row.items() if k!='raw_record_json'})
    c.rows[1]=[row[k] for k in FIELDS]
    before=len(c.writes)
    assert process(c,s)['rejected']==1
    assert len(c.writes)==before


def test_rollback_and_history(tmp_path):
    s=IntakeStore(tmp_path/'db'); row,b=fixture(); batch=dict(zip(BATCH_FIELDS,b))
    with pytest.raises(sqlite3.IntegrityError):
        s.store(batch,[row,row],[product(row),product(row)])
    with s.connect() as db:
        assert db.execute('SELECT count(*) FROM sheets_batches').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM source_observations').fetchone()[0]==0
    c=Client(); process(c,s)
    p=s.products('b1')[0]
    assert p.source_context['retailer_item_id']=='00123'
    assert p.source_context['source_shipping_cost'] is None
    assert p.source_context['shipping_availability'] is None
    assert p.package_quantity is None
    c.batches[1][0]='b2'; row['batch_id']='b2'; row['record_id']='r2'
    row['observed_at_utc']='2026-01-01T00:00:30Z'
    row['raw_record_json']=json.dumps({k:v for k,v in row.items() if k!='raw_record_json'})
    c.rows[1]=[row[k] for k in FIELDS]
    assert process(c,s)['accepted']==1
    assert s.products('b2')[0].source_context['product_identity']==p.source_context['product_identity']


def test_ack_relocation_and_producer_change(tmp_path):
    c=Client(); original=c.read; calls=0
    def read(tab, cols):
        nonlocal calls
        if tab=='Walmart_Batches':
            calls+=1
            if calls==2: c.batches.insert(1,[])
        return original(tab,cols)
    c.read=read
    assert process(c,IntakeStore(tmp_path/'db'))['accepted']==1
    assert c.writes[0][0]==3


def test_offline_summary(tmp_path, monkeypatch, capsys):
    from app.sheets_intake import main
    path=tmp_path/'db'
    process(Client(),IntakeStore(path))
    monkeypatch.setattr('sys.argv',['intake','summary','--database',str(path)])
    assert main()==0
    report=json.loads(capsys.readouterr().out)
    assert report['last_import']['accepted']==1
    assert report['pending_acknowledgment']==0


def test_changed_producer_blocks_ack(tmp_path):
    c=Client(); original=c.read; calls=0
    def read(tab, cols):
        nonlocal calls
        if tab=='Walmart_Batches':
            calls+=1
            if calls==2: c.batches[1][3]='WRITING'
        return original(tab,cols)
    c.read=read
    assert process(c,IntakeStore(tmp_path/'db'))['pending_acknowledgment']==1
    assert not c.writes


def test_ack_wire_contract():
    from app.sheets_intake import SheetsClient
    c=SheetsClient.__new__(SheetsClient)
    requests=[]
    c.request=lambda suffix, payload: (requests.append((suffix,payload)) or {'totalUpdatedCells':2})
    c.ack(7,'2026-01-01T00:00:00+00:00')
    assert requests==[(':batchUpdate',dict(valueInputOption='RAW',data=[dict(
        range="'Walmart_Batches'!F7:G7",values=[['STORED','2026-01-01T00:00:00+00:00']])]))]


def test_candidate_plan_is_offline(tmp_path):
    s=IntakeStore(tmp_path/'db'); process(Client(),s)
    plan=s.candidate_plan('b1')
    assert plan['live_requests']==0
    assert plan['execution_authorized'] is False
    assert plan['candidates'][0]['product_identity']=='walmart:00123'
    assert plan['candidates'][0]['keywords']=='Widget'


def browser_client():
    c = Client()
    row = dict(zip(FIELDS, c.rows[1]))
    row['item_price_usd'] = '1.97'
    raw = {k: v for k, v in row.items() if k not in
           ('raw_record_json', 'source', 'schema_version', 'batch_id', 'record_id', 'exported_at_utc')}
    raw['displayed_price'] = '$1.97'
    del raw['item_price_usd']
    raw['observation_timestamp'] = raw.pop('observed_at_utc')
    raw['shipping_charge'] = None
    del raw['shipping_charge_usd']
    row['raw_record_json'] = json.dumps(raw)
    c.rows[1] = [row[k] for k in FIELDS]
    return c


def test_original_browser_contract_read_only_and_storage(tmp_path):
    c = browser_client()
    assert process(c)['accepted'] == 1
    assert not c.writes
    assert not list(tmp_path.iterdir())
    store = IntakeStore(tmp_path/'db')
    assert process(c, store)['accepted'] == 1
    p = store.products('b1')[0]
    assert str(p.purchase_price) == '1.97'
    assert p.source_context['source_shipping_cost'] is None
    assert process(c, store)['already_stored'] == 1


@pytest.mark.parametrize('field,value', [
    ('item_price_usd', '2.00'), ('shipping_charge_usd', '0'),
    ('observed_at_utc', '2026-01-01T00:00:01Z'), ('seller', 'different'),
    ('selected_variant', 'different'), ('displayed_zip', '90210'),
    ('product_url', 'https://walmart.com/ip/other/00123'),
])
def test_browser_consistency_not_weakened(field, value):
    c = browser_client()
    c.rows[1][FIELDS.index(field)] = value
    result = process(c)
    assert result['rejected'] == 1
    assert result['rejections'] == [{'code': 'RAW_EXPORT_MISMATCH', 'field': field}]
    assert not c.writes


@pytest.mark.parametrize('raw,code,field', [
    ('not-json SECRET', 'INVALID_JSON', 'raw_record_json'),
    ('[]', 'INVALID_JSON_OBJECT', 'raw_record_json'),
    ('{}', 'RAW_FIELDS_MISMATCH', 'raw_record_json'),
])
def test_sanitized_rejections(raw, code, field):
    c = browser_client()
    c.rows[1][FIELDS.index('raw_record_json')] = raw
    result = process(c)
    assert result['rejections'] == [{'code': code, 'field': field}]
    assert 'SECRET' not in json.dumps(result)
    assert 'Widget' not in json.dumps(result)


def test_browser_missing_field_and_conflicting_alias():
    c = browser_client()
    raw = json.loads(c.rows[1][-1])
    del raw['seller']
    c.rows[1][-1] = json.dumps(raw)
    assert process(c)['rejections'] == [{'code': 'RAW_FIELD_MISSING', 'field': 'seller'}]
    raw['seller'] = ''
    raw['item_price_usd'] = '99.00'
    c.rows[1][-1] = json.dumps(raw)
    assert process(c)['rejections'] == [{'code': 'RAW_EXPORT_MISMATCH', 'field': 'item_price_usd'}]


@pytest.mark.parametrize('field', ['expected_record_count', 'actual_record_count'])
def test_count_diagnostic(field):
    c = browser_client()
    c.batches[1][BATCH_FIELDS.index(field)] = '2'
    assert process(c)['rejections'] == [{'code': 'COUNT_MISMATCH', 'field': field}]


PRODUCER_BATCH_ID = 'walmart-76063-20261029T010727Z-five-v1'
PRODUCER_RECORD_IDS = (
    'walmart-76063-20261029T010727Z-five-v1:17617453',
    'walmart-76063-20261029T010727Z-five-v1:14922696',
    'walmart-76063-20261029T010727Z-five-v1:14906288',
    'walmart-76063-20261029T010727Z-five-v1:10310568',
    'walmart-76063-20261029T010727Z-five-v1:12443828',
)
PRODUCER_RECORD_ID = PRODUCER_RECORD_IDS[0]


def producer_record_client(record_id=PRODUCER_RECORD_ID):
    c = browser_client()
    c.batches[1][0] = PRODUCER_BATCH_ID
    c.rows[1][FIELDS.index('batch_id')] = PRODUCER_BATCH_ID
    c.rows[1][FIELDS.index('record_id')] = record_id
    return c


@pytest.mark.parametrize('record_id', PRODUCER_RECORD_IDS)
def test_producer_colon_record_original_browser_json(tmp_path, record_id):
    c = producer_record_client(record_id)
    assert process(c)['accepted'] == 1
    assert not c.writes
    store = IntakeStore(tmp_path/'db')
    assert process(c, store)['accepted'] == 1
    assert process(c, store)['already_stored'] == 1
    with store.connect() as db:
        assert db.execute('SELECT record_id, batch_id FROM sheets_records').fetchall() == [
            (record_id, PRODUCER_BATCH_ID)]


@pytest.mark.parametrize('record_id', ['', 'x'*129, 'id with space', 'id\n',
                                     '=formula', '+formula', '@formula', 'id;cmd',
                                     'id/part', "id' OR 1=1", 'id$(cmd)'])
def test_record_id_invalid_literals(record_id):
    result = process(producer_record_client(record_id))
    assert result['rejections'] == [{'code': 'INVALID_VALUE', 'field': 'record_id'}]


@pytest.mark.parametrize('record_id', ['a', 'a'*128, 'a'*126+':1'])
def test_record_id_length_boundaries(record_id):
    assert process(producer_record_client(record_id))['accepted'] == 1


@pytest.mark.parametrize('field', ['batch_id', 'source'])
def test_colon_does_not_expand_other_identifiers(field):
    c = browser_client()
    c.rows[1][FIELDS.index(field)] = 'invalid:identifier'
    if field == 'batch_id':
        c.batches[1][0] = 'invalid:identifier'
    assert process(c)['rejections'] == [{'code': 'INVALID_VALUE', 'field': field}]


def test_colon_record_duplicate_and_cross_batch_conflicts(tmp_path):
    c = producer_record_client()
    c.rows.append(c.rows[1][:])
    c.batches[1][1:3] = ['2', '2']
    assert process(c)['rejections'] == [{'code': 'DUPLICATE_RECORD', 'field': 'record_id'}]
    c.rows[2][FIELDS.index('batch_id')] = 'other_batch'
    c.batches[1][1:3] = ['1', '1']
    assert process(c)['rejections'] == [{'code': 'CONFLICTING_RECORD', 'field': 'record_id'}]
    c = producer_record_client()
    store = IntakeStore(tmp_path/'db')
    assert process(c, store)['accepted'] == 1
    # Reusing an existing exact record key in a new batch fails transactionally.
    c.batches[1][0] = 'other_batch'
    c.rows[1][FIELDS.index('batch_id')] = 'other_batch'
    before = len(c.writes)
    assert process(c, store)['rejected'] == 1
    assert len(c.writes) == before
    with store.connect() as db:
        assert db.execute('SELECT record_id, batch_id FROM sheets_records').fetchall() == [
            (PRODUCER_RECORD_ID, PRODUCER_BATCH_ID)]
        assert db.execute('SELECT count(*) FROM sheets_batches').fetchone()[0] == 1


def test_colon_record_changed_batch_still_rejected(tmp_path):
    c = producer_record_client()
    store = IntakeStore(tmp_path/'db')
    assert process(c, store)['accepted'] == 1
    c.rows[1][FIELDS.index('record_id')] += '-changed'
    assert process(c, store)['rejections'] == [
        {'code': 'CHANGED_BATCH_PAYLOAD', 'field': 'batch_id'}]



def five_producer_records_client():
    # Exact owner-supplied IDs; other product values are illustrative test data.
    c = producer_record_client()
    c.rows = [FIELDS]
    for record_id in PRODUCER_RECORD_IDS:
        row = dict(zip(FIELDS, producer_record_client(record_id).rows[1]))
        item_id = record_id.rsplit(':', 1)[1]
        row['walmart_item_id'] = item_id
        row['product_url'] = 'https://www.walmart.com/ip/widget/' + item_id
        raw = json.loads(row['raw_record_json'])
        raw.update(walmart_item_id=item_id, product_url=row['product_url'])
        row['raw_record_json'] = json.dumps(raw)
        c.rows.append([row[k] for k in FIELDS])
    c.batches[1][1:3] = ['5', '5']
    return c


def test_all_five_producer_ids_original_browser_batch(tmp_path):
    c = five_producer_records_client()
    for cells in c.rows[1:]:
        raw = json.loads(cells[FIELDS.index('raw_record_json')])
        assert raw['displayed_price'] == '$1.97'
        assert raw['shipping_charge'] is None
        assert 'observation_timestamp' in raw
        assert not {'source', 'batch_id', 'record_id', 'schema_version', 'exported_at_utc'} & raw.keys()
    result = process(c)
    assert result['accepted'] == 1
    assert result['rejected'] == 0
    assert result['rejections'] == []
    assert not c.writes
    assert not list(tmp_path.iterdir())
    store = IntakeStore(tmp_path/'db')
    assert process(c, store)['accepted'] == 1
    assert process(c, store)['already_stored'] == 1
    with store.connect() as db:
        records = db.execute('SELECT record_id, batch_id FROM sheets_records ORDER BY record_id').fetchall()
        assert records == sorted((rid, PRODUCER_BATCH_ID) for rid in PRODUCER_RECORD_IDS)
        assert db.execute('SELECT count(*) FROM source_observations').fetchone()[0] == 5
    assert len(store.products(PRODUCER_BATCH_ID)) == 5


@pytest.mark.parametrize('record_id', PRODUCER_RECORD_IDS)
def test_all_five_ids_duplicate_detection(record_id):
    c = five_producer_records_client()
    cells = next(row for row in c.rows[1:] if row[FIELDS.index('record_id')] == record_id)
    c.rows.append(cells[:])
    c.batches[1][1:3] = ['6', '6']
    assert process(c)['rejections'] == [{'code': 'DUPLICATE_RECORD', 'field': 'record_id'}]
    assert not c.writes


def representative_description_client():
    from pathlib import Path
    snapshot = json.loads((Path(__file__).parent/'fixtures/sheets_browser_five_representative.json').read_text())
    c = Client()
    c.rows, c.batches = snapshot['Walmart_Intake'], snapshot['Walmart_Batches']
    return c


def test_representative_descriptive_five_batch_end_to_end(tmp_path):
    c = representative_description_client()
    result = process(c)
    assert result['accepted'] == 1 and result['rejections'] == []
    assert not c.writes and not list(tmp_path.iterdir())
    store = IntakeStore(tmp_path/'fixture.sqlite3')
    assert process(c, store)['accepted'] == 1
    assert process(c, store)['already_stored'] == 1
    with store.connect() as db:
        records = db.execute('SELECT record_id, batch_id, original_json FROM sheets_records').fetchall()
        assert {(rid, bid) for rid, bid, _ in records} == {
            (rid, PRODUCER_BATCH_ID) for rid in PRODUCER_RECORD_IDS}
        originals = {cells[FIELDS.index('record_id')]: dict(zip(FIELDS, cells)) for cells in c.rows[1:]}
        for rid, _, original in records:
            assert json.loads(original) == originals[rid]
    for p in store.products(PRODUCER_BATCH_ID):
        context = p.source_context
        assert context['shipping_availability'] == 'AVAILABLE'
        assert context['local_delivery_availability'] == 'AVAILABLE'
        assert context['pickup_availability'] == 'AVAILABLE'
        assert context['shipping_availability_description'] in (
            'Shipping Arrives tomorrow', 'Shipping Arrives Oct 31')
        assert context['local_delivery_availability_description'] == 'Delivery As soon as 23 mins'
        assert context['pickup_availability_description'] == 'Pickup As soon as 7am tomorrow'
        assert context['source_shipping_cost'] is None
        assert p.availability == 'unknown'


@pytest.mark.parametrize('field,value,expected', [
    ('shipping_availability', 'Shipping Arrives tomorrow', 'AVAILABLE'),
    ('shipping_availability', 'Shipping Arrives Oct 31', 'AVAILABLE'),
    ('local_delivery_availability', 'Delivery As soon as 23 mins', 'AVAILABLE'),
    ('pickup_availability', 'Pickup As soon as 7am tomorrow', 'AVAILABLE'),
    ('shipping_availability', 'Delivery As soon as 23 mins', None),
    ('local_delivery_availability', 'Shipping Arrives tomorrow', None),
    ('shipping_availability', 'Shipping options depend on ZIP', None),
    ('shipping_availability', 'Shipping unavailable', 'UNAVAILABLE'),
    ('local_delivery_availability', 'Delivery not available', 'UNAVAILABLE'),
    ('pickup_availability', 'UNKNOWN', None),
    ('shipping_availability', '', None),
])
def test_description_normalization_separate_from_literal(field, value, expected):
    from app.sheets_intake import availability_description
    c = browser_client()
    row = dict(zip(FIELDS, c.rows[1]))
    row[field] = value
    raw = json.loads(row['raw_record_json'])
    raw[field] = value
    row['raw_record_json'] = json.dumps(raw)
    p = product(row)
    assert availability_description(field, value) == expected
    assert p.source_context[field] == expected
    assert p.source_context[field+'_description'] == value
    assert p.source_context['source_shipping_cost'] is None


@pytest.mark.parametrize('value,code', [
    ('Shipping unavailable; Shipping Arrives tomorrow', 'CONFLICTING_AVAILABILITY'),
    ('Shipping Arrives tomorrow\n', 'INVALID_VALUE'),
    ('x'*1001, 'INVALID_VALUE'),
])
def test_malformed_conflicting_descriptions_reject(value, code):
    c = representative_description_client()
    c.rows[1][FIELDS.index('shipping_availability')] = value
    raw = json.loads(c.rows[1][-1]); raw['shipping_availability'] = value
    c.rows[1][-1] = json.dumps(raw)
    assert process(c)['rejections'] == [{'code': code, 'field': 'shipping_availability'}]
    assert not c.writes


def test_literal_description_conflict_still_rejects():
    c = representative_description_client()
    c.rows[1][FIELDS.index('shipping_availability')] = 'Shipping Arrives Oct 31'
    assert process(c)['rejections'] == [
        {'code': 'RAW_EXPORT_MISMATCH', 'field': 'shipping_availability'}]


@pytest.mark.parametrize('field,value,code', [
    ('schema_version', '2', 'UNSUPPORTED_VALUE'),
    ('currency', 'EUR', 'UNSUPPORTED_VALUE'),
    ('walmart_item_id', 'wrong', 'INVALID_VALUE'),
    ('product_url', 'https://example.org/ip/17617453', 'INVALID_VALUE'),
    ('displayed_zip', '7606', 'INVALID_VALUE'),
    ('title', '', 'INVALID_VALUE'),
    ('observed_at_utc', '2026-01-01T00:00:00', 'INVALID_VALUE'),
    ('observed_at_utc', '2026-01-01T00:02:00Z', 'TIMESTAMP_ORDER'),
    ('item_price_usd', '0', 'INVALID_VALUE'),
    ('item_price_usd', 'NaN', 'INVALID_VALUE'),
    ('shipping_charge_usd', '-1', 'INVALID_VALUE'),
    ('shipping_charge_usd', 'Infinity', 'INVALID_VALUE'),
])
def test_five_batch_contract_gates(field, value, code):
    c = representative_description_client()
    c.rows[1][FIELDS.index(field)] = value
    assert process(c)['rejections'] == [{'code': code, 'field': field}]
    assert not c.writes


@pytest.mark.parametrize('field,value', [
    ('source', ''), ('source', 'invalid source'), ('schema_version', '2'),
    ('batch_id', 'invalid:batch'), ('record_id', 'invalid record'),
    ('exported_at_utc', 'not-a-timestamp'),
])
def test_envelope_validated_without_embedded_metadata(field, value):
    c = browser_client()
    raw = json.loads(c.rows[1][-1])
    assert not {'source', 'schema_version', 'batch_id', 'record_id', 'exported_at_utc'} & raw.keys()
    c.rows[1][FIELDS.index(field)] = value
    if field == 'batch_id':
        c.batches[1][0] = value
    result = process(c)
    assert result['accepted'] == 0
    assert result['rejections'][0]['field'] == field
    assert not c.writes


@pytest.mark.parametrize('field', ['source', 'schema_version', 'batch_id', 'record_id', 'exported_at_utc'])
def test_optional_legacy_envelope_copies_cannot_conflict(field):
    c = browser_client()
    raw = json.loads(c.rows[1][-1])
    raw[field] = 'contradictory'
    c.rows[1][-1] = json.dumps(raw)
    assert process(c)['rejections'] == [{'code': 'RAW_EXPORT_MISMATCH', 'field': field}]


def test_keyword_planning_has_no_unpublished_amazon_dependency(tmp_path, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'app.amazon_candidates', None)
    c = browser_client()
    row = dict(zip(FIELDS, c.rows[1]))
    row.update(brand='Example', selected_variant='Small')
    raw = json.loads(row['raw_record_json'])
    raw.update(brand='Example', selected_variant='Small')
    row['raw_record_json'] = json.dumps(raw)
    c.rows[1] = [row[k] for k in FIELDS]
    store = IntakeStore(tmp_path/'db')
    assert process(c, store)['accepted'] == 1
    assert store.candidate_plan('b1')['candidates'][0]['keywords'] == 'Example Widget Small'


NULLABLE_FIELDS = (
    'brand', 'selected_variant', 'seller', 'fulfiller',
    'shipping_availability', 'local_delivery_availability', 'pickup_availability',
    'shipping_charge_usd',
)


@pytest.mark.parametrize('field', NULLABLE_FIELDS)
def test_all_nullable_observations_null_blank_equivalence(field):
    c = browser_client()
    c.rows[1][FIELDS.index(field)] = ''
    raw = json.loads(c.rows[1][-1])
    raw['shipping_charge' if field == 'shipping_charge_usd' else field] = None
    c.rows[1][-1] = json.dumps(raw)
    assert process(c)['accepted'] == 1
    assert not c.writes


@pytest.mark.parametrize('field', NULLABLE_FIELDS)
@pytest.mark.parametrize('raw_value,exported', [
    (None, 'populated'), ('populated', ''), ('first', 'second'),
    ('null', ''), (' ', ''), (False, ''), (0, ''),
])
def test_nullable_observation_real_conflicts_stay_rejected(field, raw_value, exported):
    c = browser_client()
    # Use valid nonnegative monetary literals for the monetary conflict cases.
    if field == 'shipping_charge_usd':
        raw_value = {'populated': '1.00', 'first': '1.00'}.get(raw_value, raw_value) if type(raw_value) is str else raw_value
        exported = {'populated': '1.00', 'second': '2.00'}.get(exported, exported)
    c.rows[1][FIELDS.index(field)] = exported
    raw = json.loads(c.rows[1][-1])
    raw['shipping_charge' if field == 'shipping_charge_usd' else field] = raw_value
    c.rows[1][-1] = json.dumps(raw)
    assert process(c)['rejected'] == 1
    assert not c.writes


@pytest.mark.parametrize('field', ['walmart_item_id','product_url','title','currency',
                                 'displayed_zip','item_price_usd','observed_at_utc'])
def test_required_observation_null_never_becomes_missing(field):
    c = browser_client()
    raw = json.loads(c.rows[1][-1])
    key = {'item_price_usd': 'displayed_price', 'observed_at_utc': 'observation_timestamp'}.get(field, field)
    raw[key] = None
    c.rows[1][-1] = json.dumps(raw)
    assert process(c)['rejected'] == 1
    assert not c.writes


def test_five_producer_records_two_null_variants_and_null_shipping(tmp_path):
    c = representative_description_client()
    expected_null = {'17617453', '14906288'}
    found_null = set()
    for cells in c.rows[1:]:
        row = dict(zip(FIELDS, cells)); raw = json.loads(row['raw_record_json'])
        assert raw['shipping_charge'] is None
        assert row['shipping_charge_usd'] == ''
        if raw['selected_variant'] is None:
            found_null.add(row['walmart_item_id'])
            assert row['selected_variant'] == ''
    assert found_null == expected_null
    assert process(c)['accepted'] == 1
    assert not c.writes and not list(tmp_path.iterdir())
    store = IntakeStore(tmp_path/'fixture.sqlite3')
    assert process(c, store)['accepted'] == 1
    assert process(c, store)['already_stored'] == 1
    for p in store.products(PRODUCER_BATCH_ID):
        if p.source_context['retailer_item_id'] in expected_null:
            assert p.variation == ''
        assert p.source_context['source_shipping_cost'] is None
    with store.connect() as db:
        for payload, in db.execute('SELECT original_json FROM sheets_records'):
            row = json.loads(payload)
            raw = json.loads(row['raw_record_json'])
            if row['walmart_item_id'] in expected_null:
                assert raw['selected_variant'] is None


def test_null_canonical_shipping_alias_and_legacy_mirror():
    c = browser_client()
    raw = json.loads(c.rows[1][-1]); raw['shipping_charge_usd'] = None
    c.rows[1][-1] = json.dumps(raw)
    assert process(c)['accepted'] == 1
    raw['shipping_charge_usd'] = '0'
    c.rows[1][-1] = json.dumps(raw)
    assert process(c)['rejected'] == 1
    c = Client()
    raw = json.loads(c.rows[1][-1]); raw['selected_variant'] = None
    c.rows[1][-1] = json.dumps(raw)
    assert process(c)['accepted'] == 1
