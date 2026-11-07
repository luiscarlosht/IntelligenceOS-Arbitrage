"""M95 offline seller eligibility intelligence.

No network calls, purchases, listings, or credential access.
Unknown eligibility is never interpreted as permission.
"""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.amazon_pilot import DIRECTORY

ROOT = Path("/root/IntelligenceOS-Arbitrage-M61/var")
M79 = ROOT / "m79-amazon-intelligence-final-20261103/M79_report.json"
M69 = ROOT / "m69-offline-review/M69_history.json"
M94_DIGEST = (
    "8004c4bba07fa40b0636324424b0b5cf8b65498fb7305fe4b4945b443ddc9598"
)
M94 = DIRECTORY / f"m94-eligibility-{M94_DIGEST}-01.json"
OUTPUT = Path("var/m95-offline-review")

RESTRICTED = {
    "APPROVAL_REQUIRED",
    "NOT_ELIGIBLE",
    "OTHER_RESTRICTED",
}
STATUSES = RESTRICTED | {
    "UNRESTRICTED_VERIFIED",
    "NO_RESTRICTIONS_REPORTED",
    "UNKNOWN",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing or unsafe evidence: {path.name}")
    return json.loads(path.read_text())


def classify(value):
    """Only classify explicitly recognized historical status values."""
    if isinstance(value, dict):
        for key in ("value", "status", "eligibility", "classification"):
            if key in value:
                result = classify(value[key])
                if result != "UNKNOWN":
                    return result
        return "UNKNOWN"

    if not isinstance(value, str):
        return "UNKNOWN"

    normalized = value.strip().upper()
    aliases = {
        "NO_REPORTED_RESTRICTIONS": "UNKNOWN",
        "UNRESTRICTED": "UNKNOWN",
        "ELIGIBLE": "UNKNOWN",
        "APPROVAL_REQUIRED": "APPROVAL_REQUIRED",
        "NOT_ELIGIBLE": "NOT_ELIGIBLE",
        "OTHER_RESTRICTED": "OTHER_RESTRICTED",
    }
    return aliases.get(normalized, "UNKNOWN")


def m94_decision(row):
    restriction = row.get("restrictions") or {}
    if restriction.get("status") != "succeeded":
        return "UNKNOWN"

    data = restriction.get("data") or {}
    codes = set(data.get("reason_codes") or [])
    permission = data.get("listing_permission") or {}

    if "NOT_ELIGIBLE" in codes:
        return "NOT_ELIGIBLE"
    if "APPROVAL_REQUIRED" in codes:
        return "APPROVAL_REQUIRED"
    if codes:
        return "OTHER_RESTRICTED"

    # Do not infer permission from a successful API call or empty codes.
    if (
        isinstance(permission, dict)
        and permission.get("value") is True
        and permission.get("is_mock") is False
        and data.get("restriction_count") == 0
    ):
        return "UNRESTRICTED_VERIFIED"

    return "UNKNOWN"


def build(m79, m69, m94):
    catalog = m79["catalog"]
    if not isinstance(catalog, list):
        raise ValueError("Invalid M79 catalog")

    exclusions = set(m69["excluded_asins"])
    decisions = {}
    evidence = {}
    checked = set()

    for event in m69["events"]:
        asin = event.get("asin")
        if not asin:
            continue
        checked.add(asin)
        state = classify(event.get("eligibility"))
        if state in RESTRICTED:
            if asin in decisions and decisions[asin] != state:
                raise ValueError(f"Conflicting M69 evidence: {asin}")
            decisions[asin] = state
            evidence[asin] = "M69"

    for row in m94["rows"]:
        asin = row.get("asin")
        if not asin:
            continue
        checked.add(asin)
        state = m94_decision(row)
        if state != "UNKNOWN":
            if asin in decisions and decisions[asin] != state:
                raise ValueError(f"Conflicting M69/M94 evidence: {asin}")
            decisions[asin] = state
            evidence[asin] = "M94"

    history = []
    for asin in sorted(checked):
        history.append({
            "asin": asin,
            "status": decisions.get(asin, "UNKNOWN"),
            "source": evidence.get(asin, "CHECKED_NO_CLASSIFICATION"),
            "historically_excluded": asin in exclusions,
        })

    queue = []
    catalog_seen = set()

    for item in catalog:
        asin = item.get("asin")
        if not asin:
            continue
        if asin in catalog_seen:
            raise ValueError(f"Duplicate catalog ASIN: {asin}")
        catalog_seen.add(asin)

        if asin in exclusions or asin in checked:
            continue

        conflicts = item.get("identity_conflicts") or []
        verified = item.get("identity_verified") is True
        identity_count = item.get("identity_field_count") or 0

        # Priority is a research heuristic, not evidence of authorization.
        priority = (
            (100 if verified else 0)
            + min(int(identity_count), 10) * 5
            - (50 if conflicts else 0)
        )

        queue.append({
            "asin": asin,
            "brand": item.get("brand") or "",
            "category": item.get("category") or "",
            "identity_verified": verified,
            "identity_field_count": identity_count,
            "identity_conflicts_present": bool(conflicts),
            "eligibility_status": "UNKNOWN",
            "priority_score": priority,
            "research_only": True,
            "purchase_approved": False,
        })

    queue.sort(
        key=lambda x: (-x["priority_score"], x["asin"])
    )

    counts = Counter(row["status"] for row in history)

    summary = {
        "milestone": "M95",
        "mode": "offline",
        "catalog_asins": len(catalog_seen),
        "historical_exclusions": len(exclusions),
        "historically_checked_asins": len(checked),
        "status_counts": dict(sorted(counts.items())),
        "verified_unrestricted": counts["UNRESTRICTED_VERIFIED"],
        "discovery_queue_count": len(queue),
        "catalog_checked_count": len(catalog_seen & checked),
        "catalog_excluded_count": len(catalog_seen & exclusions),
        "purchase_authorized": False,
        "listing_authorized": False,
        "live_requests": 0,
        "limitations": [
            "M79 catalog eligibility fields do not establish current permission.",
            "Unchecked ASINs remain UNKNOWN.",
            "M69 classifications require reconciliation with original evidence.",
            "M94 approval-required results do not contain approval instructions.",
            "Eligibility can change and must be reverified before purchasing.",
        ],
    }

    return history, queue, summary


def write_csv(path, rows, fields):
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    m79 = read_json(M79)
    m69 = read_json(M69)
    m94 = read_json(M94)

    history, queue, summary = build(m79, m69, m94)

    summary["source_sha256"] = {
        "M79": digest(M79),
        "M69": digest(M69),
        "M94": digest(M94),
    }
    summary["generated_at"] = datetime.now(
        timezone.utc
    ).isoformat()

    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    write_csv(
        output / "M95_eligibility_history.csv",
        history,
        ["asin", "status", "source", "historically_excluded"],
    )
    write_csv(
        output / "M95_candidate_priority.csv",
        queue,
        [
            "asin", "brand", "category", "identity_verified",
            "identity_field_count", "identity_conflicts_present",
            "eligibility_status", "priority_score",
            "research_only", "purchase_approved",
        ],
    )

    (output / "M95_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )

    print("M95 OFFLINE ELIGIBILITY REPORT")
    print("=" * 45)
    print("Catalog:", summary["catalog_asins"])
    print("Historical exclusions:", summary["historical_exclusions"])
    print("Checked ASINs:", summary["historically_checked_asins"])
    print("Eligibility:", summary["status_counts"])
    print("Verified unrestricted:", summary["verified_unrestricted"])
    print("Untested discovery queue:", summary["discovery_queue_count"])
    print("Live requests:", summary["live_requests"])
    print("Reports:", output)


def m95_decision(row):
    """Current M95 evidence only; historical M94 results remain unchanged."""
    if not isinstance(row, dict):
        return 'UNKNOWN'
    restriction = row.get('restrictions')
    if not isinstance(restriction, dict):
        return 'UNKNOWN'
    data = restriction.get('data')
    if restriction.get('status') != 'succeeded' or not isinstance(data, dict):
        return 'UNKNOWN'
    codes = data.get('reason_codes')
    count = data.get('restriction_count')
    if (not isinstance(codes, list) or any(not isinstance(code, str) for code in codes)
            or type(count) is not int or count < 0):
        return 'UNKNOWN'
    if 'NOT_ELIGIBLE' in codes:
        return 'NOT_ELIGIBLE'
    if 'APPROVAL_REQUIRED' in codes:
        return 'APPROVAL_REQUIRED'
    if codes or count:
        return 'OTHER_RESTRICTED'
    # No production affirmative semantics are validated in conservative-v1.
    # Even a forged permission boolean cannot promote this result.
    return 'NO_RESTRICTIONS_REPORTED'


if __name__ == "__main__":
    main()
