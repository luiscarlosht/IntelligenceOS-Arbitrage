"""M95 proposal fixtures never require operator histories or credentials."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def m95_reviewed_manifest(tmp_path, monkeypatch):
    from ops import m95_manifest as manifest
    from ops import m95_restrictions as m95

    fixture = Path(__file__).parent / 'fixtures/m95_reviewed_proposal.json'
    assert manifest.sha256(fixture) == m95.EXPECTED_DIGEST
    proposal = tmp_path / 'reviewed-proposal.json'
    proposal.write_bytes(fixture.read_bytes())
    value = json.loads(proposal.read_bytes())
    monkeypatch.setattr(manifest, 'OUTPUT', proposal)
    # Isolate only evidence discovery. The fingerprint and complete expected
    # request/cohort/budget reconstruction remain real. Evidence discovery has
    # separate synthetic drift/exclusion tests.
    monkeypatch.setattr(manifest, 'evidence', lambda: {k: value[k] for k in (
        'source_sha256', 'historical_audit_sha256', 'historical_exclusion_union_count')})
    return value
