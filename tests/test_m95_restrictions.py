"""M95 offline safety regression tests."""

import json

import pytest

from ops import m95_manifest as manifest
from ops import m95_restrictions as m95

pytestmark = pytest.mark.usefixtures("m95_reviewed_manifest")


def test_reviewed_manifest_validates():
    reviewed = m95.validate()
    assert len(reviewed["asins"]) == 10
    assert reviewed["budget"]["maximum_requests"] == 11


def test_unreviewed_digest_rejected():
    with pytest.raises(ValueError):
        m95.validate(digest="0" * 64)


def test_manifest_tampering_rejected(tmp_path):
    reviewed = m95.validate()
    reviewed["asins"][0] = "B000000000"

    changed = tmp_path / "manifest.json"
    changed.write_text(json.dumps(reviewed))

    with pytest.raises(ValueError):
        m95.validate(changed, m95.EXPECTED_DIGEST)


def test_manifest_rejects_symlink(tmp_path):
    link = tmp_path / "manifest.json"
    link.symlink_to(manifest.OUTPUT.resolve())

    with pytest.raises(ValueError):
        m95.validate(link)


def test_request_budget_is_fixed():
    reviewed = m95.validate()
    assert reviewed["budget"] == {
        "authentication": 1,
        "restrictions": 10,
        "maximum_requests": 11,
        "retries": 0,
        "pricing": 0,
        "fees": 0,
        "catalog": 0,
        "retailer": 0,
    }


def test_live_execution_disabled():
    with pytest.raises(RuntimeError, match="disabled"):
        m95.run()


def test_authorization_and_reports_distinct_from_m94():
    from ops import m94_restrictions as m94

    assert m95.AUTHORIZATION != m94.AUTHORIZATION
    assert m95.REPORT_STEM.startswith("m95-")
    assert m95.EXPECTED_DIGEST != m94.EXPECTED_DIGEST


def test_no_purchase_or_listing_authorization():
    reviewed = m95.validate()
    assert reviewed["purchase_authorized"] is False
    assert reviewed["execution_authorized"] is False
    assert reviewed["live_requests"] == 0
