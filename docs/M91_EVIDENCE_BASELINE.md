# M91 reproducible evidence baseline

Scope check: “Is this essential for M91 or M93?” The implementation adds only
pinned research inventory, an offline adapter, reports and integration coverage.
M90.3b, dashboards, automatic sourcing/purchasing and additional infrastructure
are deferred to the post-M93 backlog. No deployment or live API work is included.

From the repository root, with Python 3.12 and the existing project dependencies:

```bash
python -B -m app.m91 --output var/m91-baseline
```

Use a fresh output directory for each run; existing outputs are never overwritten.
On the implementation host Python is `/tmp/arbitrage-ci-fix-py312/bin/python`.
Outputs are `comparison.xlsx`, `comparison.json`, and `m92-checklist.md` under that
directory. Reports remain ignored and are not committed. No environment secrets,
ledger, account lock, database, credentials or network access are needed.

## Cohort and provenance

`evidence/m91` contains byte-for-byte copies of the original November 5 Walmart
research export, its existing six-row intake manifest and six independently saved
Amazon Catalog search receipts (2–7). `pins.json` records original repository paths
and SHA-256 hashes. These are source evidence, not generated M91 reports. Original
observations and timestamps remain unchanged. Missing screenshot/raw page captures
are not reconstructed. Recorded provenance is an assertion, not cryptographic
proof of origin or independent review of the source facts.

The six Walmart items are 17011265 (Elmer's glue), 13952053139 (Duracell AA),
37481849 (Post-it notes), 47070933 (Scotch tape), 721324153 (Gorilla glue),
and 711088244 (Pen + Gear tape). Each uses the lexicographically first ASIN in its
own saved search receipt as a reproducible research lead. This deliberately simple
selection makes no relevance or match claim; all alternative ASINs remain in JSON
and the Excel Evidence sheet. Review priority follows the existing product-analysis
ordering (exact identity, gap count, source ID), never profitability.

The adapter reuses `walmart_evidence.normalize`, the existing Walmart intake path,
`m88_evidence.match` for saved parsed Catalog observations, and
`product_analysis.comparison/workbook` for matching, financial rules and Excel.
Receipts already contain normalized saved parser output; M91 does not fabricate
raw responses or reparse unavailable originals. The original Walmart export is
cross-checked against its existing intake manifest. The stricter human-attested
`walmart_intake.validate` is intentionally not invoked: these observations have no
human signoff and must not gain its verified status.

JSON records and the Excel Evidence sheet retain original Walmart observations,
ASINs, seller/listing, original source references, timestamps, artifact hashes,
alternatives, matching gaps and review priorities. Source Inventory shows file
provenance and integrity. Data Quality lists validation gaps. Only file integrity
and recorded timestamp presence are verified baseline facts; retailer facts remain
unresolved observations. Financial costs, shipping, fees and eligibility are not
inferred. Synthetic test products are excluded, with explicit real-evidence labels.

Evaluation is fixed at 2026-11-06T00:00:00Z, not the execution time. This is a
historical baseline and never a claim of current freshness. Existing freshness,
matching and $5 profit / 50% acquisition ROI rules remain unchanged. JSON bytes
and Excel cell contents reproduce; ZIP metadata/workbook creation times may differ.

## M92 and M93 handoff

No exact match or supported profitability is established. The generated prioritized
checklist starts with the existing research-priority lead, which may be discarded
in favor of a compatible alternative. It requires independent field-level identity
captures/signoff, GTIN/package/model/variation conflict resolution, fresh seller and
destination-specific landed acquisition costs, price-bound scenarios and fees,
all other costs, seller/fulfillment eligibility and supported market evidence.
Missing costs remain UNKNOWN, including zero costs without explicit evidence.

M93 remains blocked on at least one independently established exact pair and
complete, fresh profitability evidence through M92. Live account access is not a
prerequisite to reproducing M91; any later live collection needs separate authority.

Validation: integration tests compare repeat JSON bytes and workbook cells, verify
unchanged sources, reject hash drift and synthetic labels, prohibit socket creation,
and confirm unresolved matches/unknown economics. Existing regression and both
legacy/discovery sample modes are also run. No PR is opened or pushed.

Implementation validation results: full final suite **3,667 passed, 9 skipped**;
focused M91/product-analysis/Walmart intake suite **150 passed**; legacy and
discovery sample commands both succeeded with isolated `/tmp` outputs. The initial
baseline suite had **3,664 passed, 9 skipped, 1 failed** in the pre-existing
`test_m902b_verify::test_valid_history_no_persistent_changes` metadata check.
That test passed in isolation, and the final full suite passed it as well. No
verifier behavior or infrastructure was changed to accommodate the transient failure.
