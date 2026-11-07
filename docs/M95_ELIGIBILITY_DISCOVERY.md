# M95 seller eligibility discovery

The reviewed ten-ASIN US/New pilot reuses `m94.engine._execute`. It has no
purchase, listing, inventory, pricing, fees, Catalog, or retailer operation.
Walmart profitability must be evaluated independently after eligibility research.
M94 evidence, authorization records, parser behavior, and reports are preserved.

## Execution controls

`ops.m95_restrictions` defaults to offline validation. The reviewed manifest
fingerprint is `618a5d38b01b622983e25d3e81acec8d19e5e78d8965bcd160b522e766bc6792`;
the proposal fingerprint is
`b94268e5f23f20d95f01dea0e71edc61c13a86567e522932e528c2bd18cba3e5`.
Validation reconstructs the complete proposal from source fingerprints, historical
audit, exact ordered cohort, request specifications, US marketplace, New condition,
and fixed budget. A second validation occurs under `candidate-execution.lock`.

A private owner-only exclusive file permanently reserves all ten ASINs before
credential access. Both file contents and directory are fsynced. The shared lock
is held until execution finishes. Reservation or report failures never permit
replay. Do not delete a claim to retry an interrupted run. New execution requires
separate review, scope, fingerprints, authorization and evidence names.

The transport separately enforces HTTPS hosts, exact endpoints/methods, exact
query fields, cohort membership, a single consistent seller, one authentication
and at most one restriction check per ASIN. Requests are accounted before I/O;
failed calls consume budget. The shared engine has an 11-attempt cap, 120-second
deadline, no retries, incremental fsynced checkpoints, and interruption reporting.
Sanitization removes messages, links, unknown codes, and arbitrary response fields.
M95 report and claim names start with `m95-eligibility-`; historical auditing now
recognizes those reports and permanent claims. No M94 file is overwritten.

## Interpretation and early stopping

M95 keeps APPROVAL_REQUIRED, NOT_ELIGIBLE, OTHER_RESTRICTED,
NO_RESTRICTIONS_REPORTED, and UNKNOWN distinct. `m95_decision` handles new evidence;
the historical M94 classifier remains unchanged. Malformed responses fail their
stage and remain UNKNOWN. Empty successful responses produce
NO_RESTRICTIONS_REPORTED, with listing permission unset.

The legacy parser infers permission from an empty array. The M95 parser deliberately
suppresses that inference. No affirmative permission signal has been independently
validated for this response shape. Consequently conservative-v1 cannot emit
UNRESTRICTED_VERIFIED. This is a known limitation, not proof the seller is barred.
The adapter passes `stop_after_no_restrictions=1`; the engine requires a successful
parsed result, zero restrictions, and affirmative permission before stopping.
A synthetic affirmative parser contract test verifies that path; the actual empty
response test verifies that execution continues. Supporting live verified permission
requires separately validated seller/ASIN/marketplace/condition-bound parser
semantics and regression evidence before changing conservative-v1. None of these
classifications authorizes a purchase or a listing.

## Offline validation

From the repository root, with Python 3.12:

```bash
.venv/bin/python -m ops.m95_restrictions validate --manifest var/m95-offline-review/M95_pilot_manifest.json --sha256 618a5d38b01b622983e25d3e81acec8d19e5e78d8965bcd160b522e766bc6792
.venv/bin/python -m pytest -q tests/test_m95_execution.py tests/test_m95_restrictions.py tests/test_m94_restrictions.py tests/test_amazon_candidate_enrichment.py
```

Tests use synthetic responses and isolated temporary claims. The original M94
exact-manifest test failed at baseline because its saved audit predates completed
execution evidence. The November 7 review replaces that environment-dependent happy
path with isolated evidence and adds an explicit stale-history rejection test.
The production validator and manifest remain unchanged. See
[M95 readiness review](M95_READINESS_REVIEW.md) for exact audit fingerprints and
current validation results.

## Proposed live command — not executed

Requires separate explicit user approval. This command would read production
credentials, prompt for the seller ID, create a permanent M95 claim, and issue at
most 11 requests. Review the conservative interpretation limitation first.

```bash
.venv/bin/python -m ops.m95_restrictions run --manifest var/m95-offline-review/M95_pilot_manifest.json --sha256 618a5d38b01b622983e25d3e81acec8d19e5e78d8965bcd160b522e766bc6792 --execute-reviewed
```

Do not execute this command during implementation, offline validation, or tests.

Amazon's [get listings restrictions guide](https://github.com/amzn/selling-partner-api-docs/blob/main/guides/en-US/use-case-guides/listings-restrictions-api-use-case-guide/listings-restrictions-api-use-case-guide_2021-08-01.md)
documents an empty array as no restrictions for the requested condition/store.
This implementation conservatively retains that narrower result rather than
promoting it to an affirmative permission guarantee. The
[operation reference](https://github.com/amzn/selling-partner-api-models/blob/main/models/listings-restrictions-api-model/listingsRestrictions_2021-08-01.json)
is the API contract to review before introducing different affirmative semantics.

## Implementation validation (2026-11-06)

Python 3.12.3. The full `python -m pytest -q` run finished with 3,750 passed,
9 skipped, and 1 failed in 730.28 seconds. The sole failure was
`tests/test_m94_restrictions.py::test_exact_manifest_validates_offline`, also
observed before implementation: `Historical audit changed; re-review required`.
No M94 manifest, historical result, evidence, authorization, or validator was changed
to hide this completed-pilot replay protection.

The final focused run of `tests/test_m95_execution.py`,
`tests/test_m95_restrictions.py`, and `tests/test_amazon_candidate_enrichment.py`
passed 67 tests. Two final M95 tests were added after the full run started and are
included in this focused result. The final combined M94/M95 run passed 48 tests
with the same one baseline M94 failure. Both documented offline orchestrator modes
passed with workbook/database outputs in `/tmp`. Compilation, `git diff --check`,
and exact reviewed M95 offline manifest validation passed.

Changed implementation files: `app/amazon_candidate_enrichment.py` (optional
restriction parser hook), `app/m63_history.py` (M95 audit recognition),
`ops/m95_restrictions.py` (adapter), `ops/m95_eligibility.py` (new conservative
classifier), `tests/test_m95_execution.py` (isolated regressions), this guide,
`docs/ARCHITECTURE.md`, and `docs/ROADMAP.md`.

Work is retained on `milestone/m95-eligibility-discovery`. Several M94/M95 files
were already untracked and history-reader changes already existed at the start;
those were preserved. Plain `git diff` consequently shows only four tracked files
(26 insertions, 4 deletions), including pre-existing M94 history-reader edits.
The four other relevant files appear as untracked files, not in that statistic.
No production claim, credentials access, live request, purchase, listing, inventory
change, deployment, or remote publication was performed.
