"""Validate and persist exactly one supplied CSV row offline, without Amazon evidence."""
import argparse
import json
from pathlib import Path

from app.amazon_source_plan import prepare


def intake(source: Path, directory: Path) -> dict:
    # No fabricated seller alias, catalog, price, fee or eligibility evidence.
    return prepare(source, (), {}, {}, {}, directory, seller_reference='', expected_rows=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = intake(args.source, args.output_directory)
    except (OSError, ValueError):
        print(json.dumps(dict(status='invalid_input', notice='One source row and exact template headers required; no replacement data generated')))
        raise SystemExit(1) from None
    print(json.dumps(dict(status='persisted_offline', run_id=result['run_id'],
                          source_findings=result['source_findings'],
                          missing_information=result['rows'][0]['rejection_reasons'],
                          proposed_budget=result['budget'],
                          purchase_approved=False, requests_enabled=False)))


if __name__ == '__main__':
    main()
