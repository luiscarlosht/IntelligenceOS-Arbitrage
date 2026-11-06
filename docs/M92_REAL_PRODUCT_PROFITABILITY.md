# M92 real-product matching and profitability POC

## Current offline reassessment — ZIP 76063

**M92 is open.** User clarification fixes the DFW reference to **76063,
Mansfield, Texas** and supplies the final decision taxonomy. No new network
collection, credentials, account access or SP-API requests were executed for this
reassessment. No purchase, production change, deployment or M93 work is authorized.
Current HEAD is `ea703059c7f5523ba21e2a5736e06cf13bb4d0b0` on
`milestone/m92-real-product-profitability`; continuation changes are uncommitted.

All existing pinned artifacts were revalidated, including earlier public
renderings, manufacturer SDS, retailer mappings and the original Catalog receipts.
The original observations and timestamps remain unchanged. The user-supplied ZIP
is a required collection context, not a verified purchase quote. Sacramento,
Atlanta, San Antonio and Chicago observations are historical only. Tax, shipping,
availability, seller and price need actual 76063 evidence; no tax rate or exemption
is inferred from ZIP alone.

| Walmart / ASIN | Identity | Eligibility (listing / FBA) | Economics | Final decision |
| --- | --- | --- | --- | --- |
| 17011265 / B000Q3KHCM | NEEDS_REVIEW | UNKNOWN / UNKNOWN | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| 721324153 / B07GQ1CT47 | NEEDS_REVIEW | UNKNOWN / UNKNOWN | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| 13952053139 / B003SI0TD4 | NEEDS_REVIEW | UNKNOWN / UNKNOWN | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |

The 57 alternatives with supported identity contradictions now have final decision
**REJECTED_IDENTITY**, independently of their UNKNOWN eligibility and insufficient
economics. Both Excel and JSON retain all 60 separate identity, eligibility and
economics verdicts. The inherited engine's `decision`/`legacy_decision` fields retain
their original screening semantics; M92's `final_decision` and `poc_decision` use the
user's taxonomy.

| Final classification | Required evidence |
| --- | --- |
| VERIFIED_PROFITABLE | Independently verified exact identity, supported eligibility, complete applicable economics, net profit at least $5/unit and acquisition ROI at least 50% |
| VERIFIED_UNPROFITABLE | Independently verified exact identity and complete economics; at least one profitability threshold fails |
| INELIGIBLE | Seller-specific evidence confirms listing or selected fulfillment ineligibility |
| REJECTED_IDENTITY | Supported product identity contradiction |
| INSUFFICIENT_EVIDENCE | An essential verification or financial input is missing |

No retained evidence supports the first three classifications. All FBA scenario
profit, ROI and gross/net margins remain UNKNOWN through the existing engine;
neither negative profitability nor ineligibility is established. Missing costs
remain UNKNOWN. The $5 profit / 50% acquisition ROI thresholds are unchanged.

The precise sources, fields and authorization requirements are in
[M92 collection plan](M92_COLLECTION_PLAN.md) and pinned
`evidence/m92/completion-plan.json`. Investigate identities in the requested order,
then collect economics and seller evidence for the first exact match. Stop at the
external evidence gap; no additional infrastructure or milestone is needed.

Updated reports (fresh output directory):

```bash
python -B -m app.m92 --output var/m92-76063
```

Outputs are `comparison.xlsx`, `comparison.json` and `evidence-collection.md`.
The latter now includes precise sources and authorization for every collection
task. No automated network collector or account workflow was added.

Validation for this reassessment: focused M92 tests **5 passed**; legacy and
discovery sample modes succeeded with isolated `/tmp` outputs. Full regression
suite: **3,672 passed, 9 skipped** (Python 3.12). Generated workbook contains ten
sheets and no formula cells; `git diff --check` passed. Passing tests do not close
M92. The updated local PR description is `/tmp/m92-pr-description.md`; no remote
PR, push, merge or deployment was performed.

## Historical public research continuation — 2026-11-06

This section records the earlier investigation before the ZIP/taxonomy clarification.
The current context and authorization above supersede its collection instructions.

**M92 remains open: no independently supported exact package match and no
complete FBA economics.** No M93 work or M92 sub-milestone was started.
The sections below this continuation describe the original offline baseline.

The original pinned inventory was verified before new public requests. All three
remaining pairs were investigated in the requested order. New retained artifacts
are public web tool renderings/search responses, not raw HTML/PDF binaries; cache
ages are preserved. Retrieval time does not refresh their observation dates.
`continuation-review.json` is explicitly derived review, pinned alongside those
artifacts. Original M91/M88 evidence is unchanged.

1. **Elmer's 17011265 / B000Q3KHCM — NEEDS_REVIEW.** The
   [manufacturer SDS](https://www.dick-blick.com/msds/DBH_SDS_238101105.pdf),
   revised June 30, 2025, includes E304 and 2089725 in the white school-glue
   family. Its multi-code coverage does not establish size, UPC or package aliases.
   Walmart's one 4oz bottle is consistent with the family; exact sellable-pack
   applicability, Amazon included-components wording and New condition remain open.
2. **Gorilla 721324153 / B07GQ1CT47 — NEEDS_REVIEW.**
   [Ace](https://www.acehardware.com/departments/paint-and-supplies/tape-glues-and-adhesives/glues-and-epoxy/1906833)
   maps retailer item 1906833 to manufacturer part 4572502.
   [Blick](https://www.dickblick.com/items/gorilla-clear-glue-575-oz/)
   independently ties that part, 5.75 oz, UPC 052427005519 and exact ASIN together.
   This supports a retailer-code explanation, not a verified Walmart package alias.
   Walmart's conflicting 0.5 oz phrase appears in AI-generated features; its selected
   variation is 5.75 oz Single. The
   [manufacturer page](https://gorillatough.com/product/clear-gorilla-glue/)
   currently lists 4560801 for 5.75 fl oz; continuity remains unverified. No rejection
   is inferred solely from those different codes.
3. **Duracell 13952053139 / B003SI0TD4 — NEEDS_REVIEW.** Walmart UPC
   041333051604 and Amazon UPC 041333825014 lack an independent package mapping.
   Walmart model, MPN, selected edition and outer barcode remain missing. Eight
   cells versus one retail package is not itself proof of incompatibility.

All three direct Amazon public-page requests failed (two HTTP 503 responses and
one fetch error); no current exact-ASIN New offers were established. Walmart's
cached displayed prices were $1.17 / $11.18 / $9.73, respectively, with Walmart.com
seller/fulfiller and Atlanta 30301 / San Antonio 78288 / Chicago 60602 contexts.
These are **not DFW landed costs**. Actual DFW ZIP remains requested. No seller
credentials or new SP-API requests were accessed.

Each investigated pair's final decision is **INSUFFICIENT_EVIDENCE**. Existing
57 incompatible alternatives and reasons remain in both reports. Referral/FBA
fees, inbound, placement, prep, packaging, tax, storage, returns, transaction and
other costs require ASIN-, price-, shipment- and time-specific evidence. The
[official Amazon pricing page](https://sell.amazon.com/pricing/) is a collection
starting point, not an applicable fee quote. Listing and FBA eligibility are
separate UNKNOWNs. Demand, competition and comparable price histories are missing.
The existing engine returns UNKNOWN profit, acquisition ROI and gross/net margins
for conservative/base/optimistic FBA scenarios, with unchanged $5 / 50% gates.

Reproduce the updated Excel/JSON reports in a fresh directory:

```bash
python -B -m app.m92 --output var/m92-continuation
```

Reports add an M92 Decision Report sheet with ordered findings and missing inputs;
JSON includes field comparisons, original timestamps, references, all cost inputs,
scenario diagnostics and an eight-step targeted collection plan for all three.
No missing cost is zeroed. The user's classification instruction ended at
“VERIFIED”; existing taxonomy is retained pending the remainder. Do not mark M92
complete until exact identity and complete supported economics exist.

Continuation validation: focused M92 tests **4 passed**; full regression suite
**3,671 passed, 9 skipped** (Python 3.12); legacy and discovery sample modes both
succeeded with isolated `/tmp` outputs. Generated workbook has ten sheets and no
formula cells. `git diff --check` passed. A local PR description is prepared at
`/tmp/m92-pr-description.md`; no remote PR, push, merge or deployment was performed.

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
