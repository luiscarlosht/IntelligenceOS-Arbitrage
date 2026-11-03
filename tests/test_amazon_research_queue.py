from copy import deepcopy

import pytest

from app.amazon_research_queue import (
    HEADERS, HISTORY, IDENTITY, ORIGINAL_ASINS, RESEARCH, SOURCE, SPREADSHEET,
    TAB, candidates, index, plan, publish,
)


def rows():
    return [[str(n), asin, '=literal title', 'Brand', '000012345678', '00000123456789',
             'model', '1', 'size', 'variation', 'https://www.amazon.com/dp/' + asin]
            for n, asin in enumerate(ORIGINAL_ASINS, 1)]


def metadata(queue=False):
    names = list(HISTORY) + ([TAB] if queue else [])
    return {'sheets': [{'properties': {'title': name, 'sheetId': i,
            'gridProperties': {'rowCount': 1000, 'columnCount': 26}}}
            for i, name in enumerate(names)]}


@pytest.mark.parametrize('change', ['duplicate', 'missing', 'extra', 'replacement', 'headers', 'url'])
def test_invalid_source(change):
    values = [IDENTITY[:]] + rows()
    if change == 'duplicate': values[-1] = values[1]
    if change == 'missing': values.pop()
    if change == 'extra': values.append(values[1])
    if change == 'replacement': values[1][1] = 'B012345678'
    if change == 'headers': values[0][0] = 'wrong'
    if change == 'url': values[1][-1] = 'https://example.com'
    with pytest.raises(ValueError): candidates(values)


def test_initial_plan_literals_defaults_and_only_new_tab():
    requests = plan(rows(), metadata(), [])
    sid = requests[0]['addSheet']['properties']['sheetId']
    writes = [r['updateCells'] for r in requests[1:]]
    assert len(writes) == 21
    assert all(w['start']['sheetId'] == sid for w in writes)
    saved = [[c['userEnteredValue']['stringValue'] for c in w['rows'][0]['values']] for w in writes]
    assert saved[0] == HEADERS
    assert len(index(saved)) == 20
    assert saved[1][2] == '=literal title'
    assert saved[1][4] == '000012345678'
    assert saved[1][len(IDENTITY):] == [
        'REVIEW_REQUIRED' if k == 'match_status' else 'UNKNOWN' for k in RESEARCH]


def test_rerun_preserves_research_custom_columns_and_row_order():
    existing = [HEADERS + ['custom']] + [r + ['observed'] * len(RESEARCH) + ['keep'] for r in reversed(rows())]
    original = deepcopy(existing)
    requests = plan(rows(), metadata(True), existing)
    for request in requests:
        write = request['updateCells']
        values = [c['userEnteredValue']['stringValue'] for c in write['rows'][0]['values']]
        assert len(values) == len(IDENTITY)
        existing[write['start']['rowIndex']][:len(IDENTITY)] = values
    assert existing == original
    assert len(index(existing)) == 20


@pytest.mark.parametrize('bad', [[['wrong']], [HEADERS, rows()[0], rows()[0]], [HEADERS, ['1', 'bogus']]])
def test_destination_fail_closed(bad):
    with pytest.raises(ValueError): plan(rows(), metadata(True), bad)


def test_partial_queue_adds_only_missing_asins():
    requests = plan(rows(), metadata(True), [HEADERS, rows()[0] + ['research'] * len(RESEARCH)])
    assert len(requests) == 20
    assert len(requests[0]['updateCells']['rows'][0]['values']) == len(IDENTITY)
    assert all(len(r['updateCells']['rows'][0]['values']) == len(HEADERS) for r in requests[1:])


class Client:
    def __init__(self):
        self.book = None
        self.meta = metadata()
        self.saved = []
        self.writes = 0

    def select(self, book): self.book = book
    def metadata(self): return deepcopy(self.meta)
    def values(self, tab):
        if self.book == SOURCE: return [IDENTITY] + rows()
        return deepcopy(self.saved if tab == TAB else [['history', tab]])
    def request(self, suffix, payload):
        assert self.book == SPREADSHEET and suffix == ':batchUpdate'
        self.writes += 1
        for request in payload['requests']:
            if 'addSheet' in request:
                self.meta['sheets'].append({'properties': request['addSheet']['properties']})
            else:
                w = request['updateCells']
                n = w['start']['rowIndex']
                while len(self.saved) <= n: self.saved.append([])
                data = [c['userEnteredValue']['stringValue'] for c in w['rows'][0]['values']]
                self.saved[n][:len(data)] = data


def test_publish_readback_preview_and_repeat():
    client = Client()
    assert publish(client)['mode'] == 'preview'
    assert client.writes == 0
    assert publish(client, True)['history_unchanged']
    client.saved[1][-1] = 'Browser Use evidence'
    assert publish(client, True)['unique_asins'] == 20
    assert len(client.saved) == 21 and client.saved[1][-1] == 'Browser Use evidence'


def test_history_readback_detects_concurrent_change():
    client = Client()
    original = client.values
    client.values = lambda tab: ([['changed']] if client.writes and tab in HISTORY else original(tab))
    with pytest.raises(ValueError, match='History changed'): publish(client, True)


def test_existing_transport_targets_and_grid_bounds():
    from app.amazon_research_queue import QueueClient
    client = object.__new__(QueueClient)
    client.select(SPREADSHEET)
    assert client.base == 'https://sheets.googleapis.com/v4/spreadsheets/' + SPREADSHEET + '/'
    with pytest.raises(ValueError): client.select('other')
    calls = []
    def request(suffix):
        calls.append(suffix)
        if suffix.startswith('?'): return metadata(True)
        return {'values': [HEADERS]}
    client.request = request
    assert client.values(TAB) == [HEADERS]
    assert 'A1%3AZ1000' in calls[-1] and 'valueRenderOption=FORMULA' in calls[-1]
    client.select(SOURCE)
    assert SOURCE in client.base
