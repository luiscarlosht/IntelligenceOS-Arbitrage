"""Offline workbook routing, transport and fail-closed preview regressions."""
from copy import deepcopy
import json
from urllib.error import HTTPError

import pytest

from app.amazon_research_queue import QueueClient, ORIGINAL_ASINS, SOURCE as LEGACY
from app.sheets_intake import SPREADSHEET
from app.analysis_adapters import SheetsEvidence
from app.analysis_sheets import preview, publish
from app.analysis_engine import analyze_record
from tests.test_analysis_engine import Client
from tests.test_amazon_evaluation import NOW


def test_exact_metadata_endpoint(monkeypatch):
    client = object.__new__(QueueClient)
    client.access = 'offline-test-token'
    client.select(SPREADSHEET)
    seen = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return b'{"sheets":[]}'
    class Opener:
        def open(self, request, timeout):
            seen.append((request.full_url, request.method))
            return Response()
    monkeypatch.setattr('app.sheets_intake.build_opener', lambda *args: Opener())
    client.metadata()
    assert seen == [('https://sheets.googleapis.com/v4/spreadsheets/' + SPREADSHEET +
                     '?fields=spreadsheetId,sheets.properties', 'GET')]
    with pytest.raises(PermissionError): client.request(':batchUpdate', {'requests': []})
    assert len(seen) == 1


def test_missing_evaluation_and_analysis_preserve_all_twenty():
    client = Client()
    original = deepcopy(client.meta)
    records = SheetsEvidence(client).records()
    assert tuple(r['asin'] for r in records) == ORIGINAL_ASINS
    assert all(set(r) == {'asin'} for r in records)
    proposal = preview(client, [], NOW, from_sheets=True)
    assert proposal['workbook'] == SPREADSHEET != LEGACY
    assert len(proposal['reports']) == 20
    assert all(r['decision'] == 'BLOCKED' for r in proposal['reports'])
    assert proposal['requests'][0]['addSheet']['properties']['title'] == 'Amazon_Analysis'
    assert client.meta == original and client.writes == 0
    with pytest.raises(PermissionError): publish(client, proposal, NOW)
    assert client.writes == 0


def test_missing_queue_stops_without_writes():
    client = Client()
    client.meta['sheets'].pop()
    with pytest.raises(ValueError, match='Queue'): preview(client, [], NOW, from_sheets=True)
    assert client.writes == 0


def test_queue_research_edit_invalidates_saved_preview():
    client = Client()
    proposal = preview(client, [], NOW, from_sheets=True)
    original = client.values
    def changed(tab):
        rows = original(tab)
        rows[1].append('new manual research')
        return rows
    client.values = changed
    with pytest.raises(ValueError, match='changed'):
        publish(client, proposal, NOW, approved=True)
    assert client.writes == 0


@pytest.mark.parametrize('status', [401, 403])
def test_authorization_failure_never_falls_back_or_writes(status):
    client = Client()
    def denied(): raise HTTPError('https://sheets.googleapis.com', status, 'denied', {}, None)
    client.metadata = denied
    with pytest.raises(HTTPError): preview(client, [], NOW, from_sheets=True)
    assert client.writes == 0


def test_legacy_preview_cannot_be_published():
    client = Client()
    proposal = preview(client, [{'asin': ORIGINAL_ASINS[0]}], NOW)
    proposal['schema'] = 'analysis_publication_preview_v1'
    proposal['workbook'] = LEGACY
    with pytest.raises(ValueError, match='preview'):
        publish(client, proposal, NOW, approved=True)
    assert client.writes == 0


def test_existing_analysis_preview_only_plans_output_cells():
    from app.analysis_sheets import HEADERS, cells
    from tests.test_amazon_evaluation import fiskars
    client = Client()
    client.meta['sheets'].append(dict(properties=dict(title='Amazon_Analysis', sheetId=105,
        gridProperties=dict(rowCount=2002, columnCount=12))))
    client.saved = [HEADERS + ['research_note'], cells(analyze_record(fiskars(), NOW)) + ['keep']]
    original = deepcopy(client.saved)
    proposal = preview(client, [fiskars()], NOW)
    assert client.saved == original and client.writes == 0
    assert all(set(r) == {'updateCells'} and r['updateCells']['start']['sheetId'] == 105
               for r in proposal['requests'])
    assert len(proposal['requests'][0]['updateCells']['rows'][0]['values']) == len(HEADERS)
