"""M95.3 offline pilot manifest builder and validator. No network calls."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from app.amazon_catalog import MARKETPLACE
from app.amazon_pilot import DIRECTORY
from app.m63_history import audit
from ops import m94_restrictions as m94
from ops.m95_eligibility import M69, M79, M94

PROPOSAL = Path("var/m95-offline-review/M95_diversified_100.csv")
OUTPUT = Path("var/m95-offline-review/M95_pilot_manifest.json")

EXPECTED_PROPOSAL_SHA256 = (
    "b94268e5f23f20d95f01dea0e71edc61c13a86567e522932e528c2bd18cba3e5"
)

ASINS = (
    "B00004OCNJ",
    "B00004Z4CY",
    "B0002YTVJA",
    "B0009J4YAO",
    "B000YZ8N46",
    "B000YZASYO",
    "B002ACOEPS",
    "B0058PTK6M",
    "B005HVZ59I",
    "B007I6FS10",
)

BUDGET = {
    "authentication": 1,
    "restrictions": 10,
    "maximum_requests": 11,
    "retries": 0,
    "pricing": 0,
    "fees": 0,
    "catalog": 0,
    "retailer": 0,
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or unsafe source: {path.name}")
    return json.loads(path.read_bytes())


def evidence():
    if sha256(PROPOSAL) != EXPECTED_PROPOSAL_SHA256:
        raise ValueError("Proposal fingerprint changed")

    with PROPOSAL.open(newline="") as stream:
        proposal = list(csv.DictReader(stream))

    if len(proposal) != 100:
        raise ValueError("Unexpected proposal size")

    proposed_asins = [row["asin"] for row in proposal]

    if len(set(proposed_asins)) != 100:
        raise ValueError("Duplicate proposal ASINs")

    if tuple(proposed_asins[:10]) != ASINS:
        raise ValueError("Pilot cohort changed")

    m69 = load(M69)
    m79 = load(M79)
    m94_report = load(M94)

    historical = audit(DIRECTORY)

    excluded = (
        set(m69["excluded_asins"])
        | set(historical["excluded_asins"])
    )

    checked = (
        {event["asin"] for event in m69["events"]}
        | {row["asin"] for row in m94_report["rows"]}
    )

    if set(ASINS) & (excluded | checked):
        raise ValueError("Previously checked or excluded ASIN")

    catalog = {row["asin"]: row for row in m79["catalog"]}

    if len(catalog) != 1397:
        raise ValueError("Catalog shape changed")

    if any(
        asin not in catalog
        or catalog[asin].get("marketplace") != MARKETPLACE
        for asin in ASINS
    ):
        raise ValueError("Catalog marketplace mismatch")

    for row in proposal[:10]:
        if (
            row["eligibility_status"] != "UNKNOWN"
            or row["purchase_approved"].lower() != "false"
        ):
            raise ValueError("Unexpected proposal authorization state")

    return {
        "source_sha256": {
            "proposal": sha256(PROPOSAL),
            "M69": sha256(M69),
            "M79": sha256(M79),
            "M94": sha256(M94),
        },
        "historical_audit_sha256": m94.audit_digest(historical),
        "historical_exclusion_union_count": len(excluded),
    }


def build():
    source = evidence()

    return {
        "schema": 1,
        "mode": "M95_RESTRICTIONS_ONLY_PROPOSAL",
        "asins": list(ASINS),
        "marketplace_id": MARKETPLACE,
        "condition": "new_new",
        "source_sha256": source["source_sha256"],
        "historical_audit_sha256": source["historical_audit_sha256"],
        "historical_exclusion_union_count":
            source["historical_exclusion_union_count"],
        "budget": BUDGET,
        "requests": [
            {
                "method": "GET",
                "path": "/listings/2021-08-01/restrictions",
                "params": {
                    "asin": asin,
                    "marketplaceIds": MARKETPLACE,
                    "conditionType": "new_new",
                    "reasonLocale": "en_US",
                    "sellerId": "[private runtime value]",
                },
            }
            for asin in ASINS
        ],
        "execution_authorized": False,
        "purchase_authorized": False,
        "live_requests": 0,
    }


def validate(path, expected_digest):
    if (
        path.is_symlink()
        or not path.is_file()
        or sha256(path) != expected_digest
    ):
        raise ValueError("Manifest fingerprint mismatch")

    actual = load(path)
    expected = build()

    if actual != expected:
        raise ValueError("Manifest or historical evidence changed")

    return actual


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("create", "validate")
    )
    parser.add_argument("--sha256")
    args = parser.parse_args()

    if args.action == "create":
        if OUTPUT.exists() or OUTPUT.is_symlink():
            raise ValueError(
                "Manifest already exists; refusing to overwrite"
            )

        manifest = build()
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)

        with OUTPUT.open("x") as stream:
            json.dump(manifest, stream, indent=2, sort_keys=True)
            stream.write("\n")

        digest = sha256(OUTPUT)
        validate(OUTPUT, digest)

        print("PASS: M95 manifest created and validated")
        print("Manifest SHA256:", digest)

    else:
        if not args.sha256:
            parser.error("validate requires --sha256")

        validate(OUTPUT, args.sha256)
        print("PASS: M95 manifest validated")

    print("Pilot ASINs:", len(ASINS))
    print("Maximum proposed requests:", 11)
    print("Live requests:", 0)
    print("Execution authorized:", False)
    print("Purchase authorized:", False)


if __name__ == "__main__":
    main()
