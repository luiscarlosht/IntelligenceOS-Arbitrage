# M92 real-product matching and profitability POC

Scope check: “Is this necessary for the M93 POC?” This change only completes the
offline evidence review, applies existing analysis, and reports the gaps preventing
one supported product. No new infrastructure or milestone is introduced. M90.3b,
dashboards, sourcing automation and service changes remain post-M93 backlog items.

## Reproduce the result

From the repository root with Python 3.12 and existing dependencies:

```bash
python -B -m app.m92 --output var/m92-poc
```

Use a fresh output directory. `--as-of` accepts an aware timestamp to reproduce
historical evaluation; default evaluation uses current UTC with unchanged freshness
checks. The implementation host uses `/tmp/arbitrage-ci-fix-py312/bin/python`.
Outputs: `comparison.xlsx`, `comparison.json`, `evidence-collection.md`. Reports are
ignored, not committed. Repeated runs with the same clock reproduce JSON bytes and
Excel cells (workbook ZIP metadata may differ). No credentials, database, ledger,
account lock or network are needed or accessed by this command.

## Evidence and review

All **60 pairs (56 distinct ASINs)** from the six M91 Catalog search receipts are reviewed, including
every alternative omitted from the primary M91 comparison. The six original
Walmart products remain unchanged. `evidence/m92/pins.json` pins M91's original
pins plus four byte-for-byte supplemental source copies: the existing six-product
Walmart identity enrichment and three previously collected Catalog detail receipts.
Only these explicit files are loaded; no archive directory crawl or ledger read
is used. No new external evidence is collected.

The existing `walmart_evidence.normalize`, `m88_reconcile.validate/classify`,
`m88_evidence.match` and `product_analysis.comparison/workbook` implement intake,
identity review, strict matching and financial/reporting behavior. Existing
[M88 reconciliation](M88_ENRICHED_RECONCILIATION.md) and
[targeted evidence rules](M88_TARGETED_VERIFICATION.md) govern review: barcode
alternatives, models and manufacturer part numbers stay separate; title similarity,
shared UPC, packageQuantity and agent review never imply exact identity. Source
conflicts and missing human signoff persist.

`offline-review.json` contains additional explicit research rejections derived
from retained titles/sizes and source descriptions. It is labeled
`DERIVED_OFFLINE_REVIEW`, not a new observation or independent human verification.
Each annotation is bound to its exact saved Amazon title/size, and all source
artifacts remain separately available with hashes/provenance. Contradictory
count/size/formulation offers are excluded; model differences with barcode overlap
remain unresolved where manufacturer alias evidence is missing. Research rejection
is per Walmart/ASIN pair, not a permanent ASIN exclusion.

Ranking uses identity only: non-rejected pairs, barcode overlap, fewer source
conflicts, more equal observed brand/model/MPN/variant labels, fewer identity gaps,
and source/ASIN tie-breaks. Prices, profit and popularity do not affect ranking.
Barcode overlap is a review clue, never verified package applicability. The saved
Walmart observations themselves remain unverified and offer condition stays UNKNOWN.

## Result

**57 research rejections, 3 pairs needing review, zero verified exact matches.**

| Priority | Walmart item | ASIN | Important unresolved evidence |
| --- | --- | --- | --- |
| 1 | 17011265 — Elmer's Liquid School Glue | B000Q3KHCM | UPC overlaps one of three Amazon alternatives; source model SAP_2089725 / MPN 2089725 versus Amazon model/MPN E304; outer-pack and variation applicability unresolved |
| 2 | 721324153 — Gorilla Clear Glue | B07GQ1CT47 | Barcode overlap, different model/MPN; source 5.75 oz / 0.5 oz conflict persists |
| 3 | 13952053139 — Duracell AA eight-pack | B003SI0TD4 | Source model/MPN/outer-pack barcode unknown; saved UPCs differ; eight cells versus one package is not verified equivalence |

Elmer's has the strongest existing identity lead, but **NEEDS_REVIEW**, not an
exact match. Walmart brand/UPC are independently recorded Walmart-page assertions,
not values copied from Amazon. The later Catalog detail provides independent
Amazon model E304 and MPN E304; it cannot resolve the Walmart labels. Source
screenshots are referenced but binary captures and independent human signoff were
never supplied. Amazon White color / Clear included-components wording also needs
review. Neither Catalog metadata nor the research title proves offer condition New.

## Economics and DFW gate

The first intended mode is **FBA**; **FBM is deferred**. No best verified exact
match exists, so calculation cannot proceed to supported financial results.
The existing engine produces insufficient-data diagnostics. Every pair's POC
decision is **INSUFFICIENT_EVIDENCE**; no evidence establishes unprofitability or
ineligibility either. Identity rejections remain a separate explicit verdict.

The historical Elmer's purchase observation is **$1.17**, recorded
2026-11-05T02:38:29Z, seller Walmart.com, in the **Sacramento CA 95829** context.
It remains in the original/acquisition evidence. It is never substituted for DFW
landed acquisition cost. The actual DFW destination ZIP has not been supplied,
and there is no DFW-specific seller/availability, shipping, tax or current price
confirmation. No applicable tax rate or shipping fee is inferred.

Actionable DFW purchase, retailer shipping, applicable tax, selling price,
price-bound referral/fulfillment fees, inbound, preparation, packaging, storage,
placement, returns allowance, transaction and other costs remain UNKNOWN.
Listing and FBA eligibility, supported demand/competition and history remain
missing. Explicit zero costs require evidence. Net profit, ROI and margins are
UNKNOWN; the existing **$5/unit net profit and 50% acquisition ROI** gates are
unchanged. The original M86 workbook includes both mode schemas, with FBM unknown;
this does not constitute an FBM analysis or change the FBA-first collection scope.

## Deliverables and next evidence

The original six-sheet product-analysis workbook is reused. Three additional
sheets expose all pair identity reviews/decisions, rejected alternatives with
reasons, and the prioritized evidence checklist. JSON retains the complete input
observations, timestamps, source hashes, comparisons, engine diagnostics, historical
acquisition evidence and explicit DFW/condition status.

The generated checklist specifies the exact source/ASIN, field captures, barcode
package applicability, model/MPN correspondence and signoff needed, followed by
DFW-specific landed cost, FBA price-bound fees, all other costs and seller-specific
eligibility. External collection is **not performed or authorized** here. Stop at
these missing inputs; do not invent an alias, quantity equivalence, fee or zero.

**M93 is not ready:** independent exact identity, DFW acquisition evidence and
complete fresh FBA economics/eligibility are missing. These business evidence gaps
are the blockers, not a requirement for M90.3b or new infrastructure. No purchases,
production changes, API/network calls, push, merge or deployment are performed.

## Validation results

- Baseline matching/reporting tests before implementation: **133 passed**.
- Focused M92/M91/product-analysis/reconciliation tests: **120 passed**.
- Full regression suite: **3,670 passed, 9 skipped**.
- Legacy and discovery offline sample modes: both succeeded with isolated `/tmp`
  workbook/database outputs.
- Integration coverage verifies all 60 pairs, research rejection reasons, the
  strongest lead, unresolved model/MPN and package evidence, DFW UNKNOWN gates,
  unchanged financial thresholds, no network/account state access, repeat JSON
  bytes and Excel cells, source integrity and rejection of pinned-source drift.

Final local reports are in `var/m92-final/`; no generated reports are committed.
