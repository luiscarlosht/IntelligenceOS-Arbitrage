import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.amazon_diagnostics import ResponseDocument
from ops import m94_restrictions as m94


class FakeRequest:
    full_url = (
        "https://sellingpartnerapi-na.amazon.com/"
        "listings/2021-08-01/restrictions?asin=B000255NH8"
    )


@pytest.fixture
def isolated_manifest(tmp_path, monkeypatch):
    """Pre-execution evidence; production integrity logic is never mocked."""
    from app.m63_history import audit, sha256

    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    m69 = tmp_path / 'm69.json'
    m79 = tmp_path / 'm79.json'
    m69.write_text(json.dumps(dict(rows=[dict(asin=f'C{i:09d}') for i in range(40)],
        excluded_asins=[f'D{i:09d}' for i in range(97)])))
    m79.write_text(json.dumps(dict(catalog=[dict(asin=a, marketplace=m94.MARKETPLACE)
        for a in list(m94.ASINS)+[f'E{i:09d}' for i in range(1392)]])))
    value = json.loads((Path(__file__).parent/'fixtures/m94_reviewed_proposal.json').read_bytes())
    historical = audit(private)
    value['source_sha256'] = dict(M69=sha256(m69), M79=sha256(m79))
    value['historical_audit_sha256'] = m94.audit_digest(historical)
    value['historical_exclusion_union_count'] = len(
        set(json.loads(m69.read_bytes())['excluded_asins']) | set(historical['excluded_asins']))
    proposal = tmp_path / 'proposal.json'
    proposal.write_text(json.dumps(value))
    digest = sha256(proposal)
    # Only the synthetic fixture's reviewed digest and source locations change.
    # Real hashing, history auditing, cohort and exclusion checks remain enabled.
    monkeypatch.setattr(m94, 'M69', m69)
    monkeypatch.setattr(m94, 'M79', m79)
    monkeypatch.setattr(m94, 'EXPECTED_DIGEST', digest)
    return proposal, digest, private


def test_exact_manifest_validates_offline(isolated_manifest):
    proposal, digest, private = isolated_manifest
    reviewed = m94.validate(proposal, digest, private)
    assert reviewed['asins'] == list(m94.ASINS)
    assert reviewed['budget']['maximum_requests'] == 6
    assert reviewed['execution_authorized'] is False


def test_completed_pilot_rejects_stale_historical_audit(isolated_manifest):
    proposal, digest, private = isolated_manifest
    m94.validate(proposal, digest, private)
    (private/m94.AUTHORIZATION).write_text(json.dumps(dict(asins=list(m94.ASINS))))
    with pytest.raises(ValueError, match='Historical audit changed; re-review required'):
        m94.validate(proposal, digest, private)


def test_m95_reader_does_not_change_audit_without_m95_files(isolated_manifest, monkeypatch):
    from app import m63_history as history
    _, _, private = isolated_manifest
    (private/m94.AUTHORIZATION).write_text(json.dumps(dict(asins=list(m94.ASINS))))
    current = history.audit(private)
    monkeypatch.setattr(history, 'PATTERNS', tuple(
        p for p in history.PATTERNS if not p.startswith('m95-')))
    assert history.audit(private) == current


def test_m95_evidence_changes_audit_and_excludes_attempted_asin(isolated_manifest):
    from app.m63_history import audit
    _, _, private = isolated_manifest
    before = audit(private)
    (private/'m95-eligibility-synthetic.json').write_text(json.dumps(dict(
        attempts=[dict(stage='restrictions',asin='B00004OCNJ',status='reserved')])))
    after = audit(private)
    assert m94.audit_digest(before) != m94.audit_digest(after)
    assert 'B00004OCNJ' in after['excluded_asins']


def test_manifest_rejects_wrong_digest():
    with pytest.raises(ValueError):
        m94.validate(m94.MANIFEST, "0" * 64)


def test_sanitizer_removes_private_response_fields():
    raw = ResponseDocument({
        "restrictions": [{
            "marketplaceId": "ATVPDKIKX0DER",
            "conditionType": "new_new",
            "reasons": [{
                "reasonCode": "APPROVAL_REQUIRED",
                "message": "PRIVATE SELLER INFORMATION",
                "links": [{"resource": "PRIVATE URL"}],
            }],
        }]
    }, 200)

    with patch.object(m94.pilot, "_request_json", return_value=raw):
        cleaned = m94.safe_transport(FakeRequest())

    serialized = str(cleaned)
    assert "PRIVATE SELLER INFORMATION" not in serialized
    assert "PRIVATE URL" not in serialized
    assert cleaned["restrictions"][0]["reasons"] == [
        {"reasonCode": "APPROVAL_REQUIRED"}
    ]


def test_sanitizer_rejects_invalid_response():
    raw = ResponseDocument({"errors": [{"code": "INVALID"}]}, 400)
    with patch.object(m94.pilot, "_request_json", return_value=raw):
        with pytest.raises(ValueError):
            m94.safe_transport(FakeRequest())


def test_unknown_restriction_code_is_not_preserved():
    raw = ResponseDocument({
        "restrictions": [{
            "marketplaceId": "ATVPDKIKX0DER",
            "conditionType": "new_new",
            "reasons": [{"reasonCode": "UNRECOGNIZED_PRIVATE_CODE"}],
        }]
    }, 200)

    with patch.object(m94.pilot, "_request_json", return_value=raw):
        cleaned = m94.safe_transport(FakeRequest())

    assert cleaned["restrictions"][0]["reasons"] == [
        {"reasonCode": "OTHER"}
    ]


def test_unexpected_endpoint_never_reaches_network():
    class BadRequest:
        full_url = "https://example.com/listings/2021-08-01/restrictions"

    with patch.object(m94.pilot, "_request_json") as network:
        with pytest.raises(ValueError, match="Unexpected Amazon API endpoint"):
            m94.safe_transport(BadRequest())

        network.assert_not_called()


def test_replay_blocked_before_network_execution(tmp_path):
    from app.m63_history import audit

    private = tmp_path / "private"
    private.mkdir(mode=0o700)

    reservation = private / m94.AUTHORIZATION
    reservation.write_text(__import__("json").dumps({
        "manifest_sha256": m94.EXPECTED_DIGEST,
        "asins": list(m94.ASINS),
        "maximum_checks": 5,
        "state": "claimed_no_replay",
    }))

    history = audit(private)
    assert set(m94.ASINS).issubset(set(history["excluded_asins"]))

    with patch.object(m94, "validate", side_effect=ValueError(
        "Previously reserved ASINs"
    )), patch.object(m94.engine, "_execute") as execute:
        with pytest.raises(ValueError, match="Previously reserved"):
            m94.run(m94.MANIFEST, m94.EXPECTED_DIGEST)

        execute.assert_not_called()
