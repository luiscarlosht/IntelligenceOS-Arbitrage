"""Offline diversified eligibility research proposal. No API calls."""
import csv
import json
from collections import Counter
from pathlib import Path

SOURCE = Path("var/m95-offline-review/M95_candidate_priority.csv")
OUTPUT = Path("var/m95-offline-review")
LIMIT = 100
MAX_BRAND = 2
MAX_CATEGORY = 5


def build(rows):
    selected = []
    brands = Counter()
    categories = Counter()
    seen = set()

    for row in rows:
        asin = row["asin"]
        brand = row["brand"].strip().casefold()
        category = row["category"].strip().casefold()

        if not asin or asin in seen:
            continue

        # Missing brands/categories must not bypass concentration limits.
        brand_key = brand or "__unknown_brand__"
        category_key = category or "__unknown_category__"

        if brands[brand_key] >= MAX_BRAND:
            continue
        if categories[category_key] >= MAX_CATEGORY:
            continue

        if row["eligibility_status"] != "UNKNOWN":
            continue
        if row["purchase_approved"].lower() != "false":
            continue

        selected.append(row)
        seen.add(asin)
        brands[brand_key] += 1
        categories[category_key] += 1

        if len(selected) == LIMIT:
            break

    return selected


def main():
    with SOURCE.open(newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)

    selected = build(rows)

    OUTPUT.mkdir(parents=True, exist_ok=True)

    csv_path = OUTPUT / "M95_diversified_100.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(selected)

    summary = {
        "mode": "offline_proposal",
        "proposed_asins": len(selected),
        "max_per_brand": MAX_BRAND,
        "max_per_category": MAX_CATEGORY,
        "distinct_brands": len({
            (r["brand"].strip().casefold() or "__unknown_brand__")
            for r in selected
        }),
        "distinct_categories": len({
            (r["category"].strip().casefold() or "__unknown_category__")
            for r in selected
        }),
        "identity_verified": sum(
            r["identity_verified"] == "True"
            for r in selected
        ),
        "eligibility_verified": 0,
        "live_requests": 0,
        "execution_authorized": False,
        "purchase_authorized": False,
    }

    (OUTPUT / "M95_diversified_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )

    print("M95.1 DIVERSIFIED ELIGIBILITY PROPOSAL")
    print("=" * 45)
    for key, value in summary.items():
        print(f"{key}: {value}")
    print("CSV:", csv_path)


if __name__ == "__main__":
    main()
