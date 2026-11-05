# M88 enriched Walmart identity reconciliation

`app.m88_reconcile` compares the enriched six-row Browser Use JSON against the
original hashed M88 search receipts. This is an offline analysis command, separate
from the executor and normal jobs. It never reads credentials, dispatches HTTP,
replays the completed pilot or writes its cumulative ledger. Previous evidence
and reports remain unchanged. A new private directory holds all outputs.

The current imported evidence explicitly records agent review, no independent
human signoff and screenshot references without binary images. Preserve those
assertions and each reference exactly. Authenticated Drive retrieval proves which
file was imported; it does not turn agent review into human approval or verify
uninspected screenshots.

```bash
python -m app.m88_reconcile --plan <original-operation>/plan.json \
  --plan-sha256 <original-plan-sha256> \
  --enrichment <new-private-evidence.json> --enrichment-sha256 <evidence-sha256> \
  --output <fresh-report-directory>
```

The command validates the exact original source IDs/URLs, twelve-digit UPC check
digits, observation timestamps, explicit agent/human flags, original 7/49 COMPLETE
ledger binding and each receipt hash/number/phase/source ID. Read-only input hashes
are rechecked before publishing. Source candidate IDs are mapped through the
original manifest, never inferred from an ID suffix. Source and evidence drift,
invalid fields, symlinks and overwrites stop publication. Existing offline guards
forbid network/process access and writes outside the new output.

## Classification semantics

Every original source/ASIN pair receives REJECTED or NEEDS_REVIEW in this dataset.
EXACT_MATCH remains unavailable where independent Amazon package applicability,
model/MPN/variant evidence and consistent source identity are missing; the existing
strict M88 exact-match gate is not weakened. There is no acceptance from a matching
title, one shared barcode, or agent review alone.

- REJECTED is a research pairing with contradictory observations: unconflicted
  brands differ, explicit same-unit contents counts differ, or a different single
  canonical Amazon barcode accompanies different model labels without source
  outer-pack uncertainty. It is not a permanent global ASIN exclusion. Revised
  evidence may require a new assessment.
- NEEDS_REVIEW retains missing evidence, multiple barcode alternatives, source
  conflicts and differing model labels where a barcode overlaps. Barcode absence
  from a multi-identifier list is not proof of exclusion. When the source explicitly
  lacks outer-pack barcode basis, differing barcode/model labels alone cannot
  exclude the candidate.
- Saved Amazon model labels are not manufacturer part numbers. MPN was not
  retained by the original normalized receipts and remains UNKNOWN. No regional,
  retailer or manufacturer model alias is guessed.
- Contents counts are extracted only from explicit leading source descriptions and
  explicit typed units in Amazon size/variation strings. Eight cells and Amazon
  packageQuantity 1 are not treated as conflicting counts. Generic Count fields
  with no contents-unit basis remain unresolved. No roll-length conversion,
  liquid/weight equivalence or arbitrary free-text variant equivalence is inferred.

All source conflicts and unresolved fields are preserved, even for rejected
pairings. Mandatory exception retention includes Duracell missing model/outer
barcode, Gorilla's conflicting 0.5 oz description, Post-it lined/unlined,
Scotch core/dispenser and Pen + Gear brand/roll-dimension conflicts. A conflicting
brand string is never resolved by selecting the convenient brand. A shared UPC
cannot override different models or a multi-GTIN/package ambiguity.

## Authentic six-product result, 2026-11-05

The enriched JSON was imported through the authorized Google Drive connection.
Offline comparison used 60 previously observed source/candidate records, representing
56 distinct ASINs. Pair classifications:

| Walmart item | EXACT_MATCH | REJECTED | NEEDS_REVIEW |
| --- | --- | --- | --- |
| 17011265 — Elmer's | 0 | 1 | 9 |
| 13952053139 — Duracell | 0 | 1 | 9 |
| 721324153 — Gorilla | 0 | 6 | 4 |
| 37481849 — Post-it | 0 | 8 | 2 |
| 47070933 — Scotch | 0 | 10 | 0 |
| 711088244 — Pen + Gear | 0 | 8 | 2 |
| Total | 0 | 34 | 26 |

The distinct-ASIN aggregation has 30 rejected and 26 needing review; a shared
ASIN remains unresolved if any paired source needs review. These counts must not
be confused with the 60 pair classifications.

Only Elmer B000Q3KHCM and Gorilla B07GQ1CT47 have barcode overlap with their
respective enriched source UPCs. Elmer has Walmart model SAP_2089725 / MPN 2089725
versus Amazon model E304; Gorilla has Walmart model/MPN 1906833 versus Amazon
model 4572502. Both retained Amazon records have multiple barcode alternatives
and package/variation mapping issues. The two source/candidate pairs remain
NEEDS_REVIEW; neither is a verified match.

No additional requests were necessary now. Amazon offers or fees cannot resolve
Walmart packaging/description contradictions, missing screenshots or missing
source variant evidence. If those source gaps are resolved, a later specifically
reviewed Catalog clarification for the two barcode-overlap candidates could be
considered; do not replay or silently extend the original one-shot claim. This
phase reserves no new attempts. Cumulative accounting remains **7/49 COMPLETE**,
with zero authentication, retries, exploratory calls or other Amazon HTTP attempts.

## Reports and financial limits

Outputs include `candidate-reconciliation.json`, `reconciliation-summary.json`,
`enriched-batch.json`, `normalized.json`, `comparison.json`, `comparison.xlsx`,
`missing-data-report.json`, `additional-request-assessment.json` and
`executive-summary.md`. M87 normalization and M86 math/workbook generation are
reused, including private atomic publication and formula-safe cells.

Enriched identity observations retain their new timestamps, UPC/model/MPN/variant
text, source conflicts and screenshot references. Prior acquisition prices and
price timestamps are copied unchanged, never refreshed by identity collection.
Original contents-count/package-basis fields remain visible instead of being
silently reinterpreted. Agent-only source verified flags remain false; independent
human signoff is explicitly false. Source snapshots retain the complete imported
observations as evidence.

Zero products have supported profitability calculations. All six remain
INSUFFICIENT_DATA with unknown exact ASINs, selling prices, fees and missing costs.
No offers or fees were collected because no exact match was established. No paid
service, purchase, listing, inventory update, credential change, Sheets write,
merge or deployment occurs. purchase_authorized=false throughout.
