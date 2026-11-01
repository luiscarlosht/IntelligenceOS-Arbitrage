# M66 verified eligibility and profitable product discovery

M66 prepares reviews offline. It does not call Amazon or retailers, inspect Seller
Central, access credentials, purchase inventory, create/copy offers, submit
applications, upload documents, or change private authorization records.

## Merged-main assessment and reuse

PR #52 was confirmed merged into main at `28f96865af85dd12617201cddd10244fd8ecf94d`.
The baseline passed 1,286 tests. Shell Git DNS was unavailable; the exact signed
main Git object was obtained through the connected GitHub API, its SHA verified,
and the requested feature branch created from that commit. The existing checkout
was clean; no original work or backup was reset or overwritten.

M65 already supplies the private append-only intelligence store, historical
importer/exclusions, Catalog parser/deduplication, deterministic scoring,
manifest hashing, human authorization validation, permanent ASIN claims,
one-use request counters and safe-stop primitives. These are reused, not replaced.
The shared ranker receives optional bounded integer priority adjustments and a
derived brand-diversification key. Existing M65 defaults and scores are unchanged.
CSV private context is now redacted like JSON context. Changed ranker code makes
older code-bound M65 proposals stale by design; prepare a new review rather than
changing an existing authorization or bypassing its digest.

M65's gaps were separate Seller Central/FBA observations, evidence conflict and
expiry handling, exact-ASIN manual blocks, multi-source diversification, a strict
downstream match/cost contract, and the nine opportunity decisions. M66 adds these
as modules beside M65. M60–M63 modules and private records are unchanged.

## Evidence model and review gate

API outcomes retain M65's five states: `NO_REPORTED_RESTRICTIONS`,
`APPROVAL_REQUIRED`, `NOT_ELIGIBLE`, `OTHER_RESTRICTED`, `UNKNOWN`. Successful
HTTP/operation completion is separate from the outcome. M63's 20 successful
restriction operations still mean 18 approval-required and two not-eligible;
the shared overall `partial` included intentionally unrequested pricing/fees.

Seller Central observations support:

- `OFFER_CREATION_AVAILABLE`: explicit existing-ASIN offer-creation check.
- `APPROVAL_APPLICATION_REQUIRED`: application requirements were observed.
- `LISTING_CREATION_ACCESSIBLE`: navigation/Copy listing access only.
- `BRAND_VALIDATION_BLOCKED`: brand validation/clarification issues.
- `NEW_LISTINGS_NOT_ACCEPTED`: the observed ASIN does not accept new listings.
- `UNVERIFIED`: no supported conclusion.

FBA is independently `FBA_ELIGIBLE`, `FBA_INELIGIBLE`, or `FBA_UNKNOWN`. A fee
estimate and Copy listing access cannot verify FBA. Only an independent
`MANUAL_FBA_ELIGIBILITY` observation can record an FBA conclusion. The schema
refuses an offer/FBA assertion made with `MANUAL_COPY_LISTING`.

Each observation records exact ASIN (or explicitly brand-only signal), brand,
US marketplace, New condition, nonsecret account alias, date, verification method,
states, invoice requirement/minimum units, restriction scope and source alias.
Optional typed `restriction_codes` record `PRODUCT_RESTRICTED`,
`CATEGORY_RESTRICTED`, `HAZMAT_REVIEW_REQUIRED`, `BRAND_CLARIFICATION_REQUIRED`,
or `OTHER_REVIEW_REQUIRED`. Arbitrary private messages, seller IDs, headers,
screenshots and documents are not accepted. M65 API evidence is projected with
method `SAVED_SP_API_LISTINGS_RESTRICTIONS`, source hash and original date.

Positive listing verification requires both a fresh empty API restriction result
and a fresh existing-ASIN offer-creation observation, with no conflicting or
invalid evidence. FBA requires separate fresh evidence. Positive evidence expires
24 hours after observation; aggregates retain the earliest applicable expiry so
reusing an aggregate cannot extend evidence validity. Historical negative facts
remain conservative review blockers; they are never erased by a newer positive.
Conflicting API/manual/FBA evidence requires review. No implicit conflict-resolution
or recheck workflow is supplied.

`VerificationStore` subclasses M65's store in a **new derived database**. It adds
insert-only verification/result tables, content deduplication and revision hashes.
Updating manual evidence means appending another observation with a new date or
reference. Older facts remain; contradictory updates require review. SQL triggers
prevent ordinary updates/deletes, not privileged filesystem/schema tampering.
Keep the existing filesystem and backup controls. No original store, ledger,
M63 permanent reservation or authorization file is opened for writing.

## Manual facts included

Existing M64 facts are projected directly from M65: OXO `B00L9X2CWQ` requires
200 invoiced units; Avery `B001HA4JXQ`, Command `B07H54NZ3K`, and Whitmor
`B00AN8CTX0` each require 100. All observed applications had Brand scope,
at least one manufacturer/distributor purchase invoice, and no immediate approval.
No ASIN-wide brand rule is inferred.

The additional user-reported seed observations are:

- Stanley `B01MFHJUBA`: `NEW_LISTINGS_NOT_ACCEPTED` for that ASIN.
- Kozerite `B0FM84W641`: accessible listing navigation plus approval and brand
  validation blocks. API permission stays `UNKNOWN`, FBA stays `FBA_UNKNOWN`,
  and the opportunity needs seller verification. It is never called unrestricted.
- Joseph Joseph, iDesign, Duck, Post-it and BIC: brand-only approval-pattern
  signals, because exact additional ASINs were not supplied. They are ranking
  signals only, not verified restrictions on every product under those brands.

Review dates were not supplied and remain null. Insertion or evaluation time is
never substituted for a historical review date. Unknown-date observations cannot
establish fresh positive permission. No observations are invented for unspecified
"other ASINs".

## Discovery and proposed cohort

The original live M63 Catalog has 100 candidates, of which 20 completed M63
restriction checks are excluded permanently. The unchanged historical audit
preserves 77 total exclusions, including older failed/reserved/detail work.
Preparation requires the original permanent 20-ASIN M63 scope proof in that
history directory; a missing proof or empty replacement store cannot silently
make the completed cohort unchecked again.
Manual exact-ASIN restrictions are separate review blocks. Brand-only observations
and invoice-heavy pathways are soft priorities, not permanent brand exclusions.

M66 can combine multiple saved M63 JSON/CSV inputs using M65's parser. Identical
ASINs are deduplicated; contradictory identity observations are flagged rather
than choosing a convenient record. Source digests and selection are deterministic
regardless of input order. Returned brand labels are retained; PHILIPS/Philips LED
share a diversification cap. No current Catalog presence is claimed from an old
snapshot, and no browser/new API discovery occurs.

On top of M65's identity score, invoice-heavy penalty, historical concentration,
outside-seed bonus and greedy brand/category/type diversity, M66 adds +8 for a
brand absent from the imported restriction sample and -8 for an observed approval
pattern. Newly recorded invoice-heavy pathways receive the existing -35 weight
without double-counting existing M64 facts. These are explicit research heuristics,
not eligibility probabilities or claims about company size. Brand cap defaults
to two. Untested rows always remain `UNKNOWN`.
The inherited minimum-priority floor defaults to zero; `--minimum-score` can be
changed explicitly for a separately reviewed proposal. Invoice-heavy brands are
not written into permanent exclusions; changing priority never changes eligibility.

An older saved 98-ASIN Catalog CSV broadens the original pool to 197 unique
ASINs. The reviewed proposal contains up to 20 previously unchecked ASINs with
selection reasons and original provenance. This source broadens represented
brands without live discovery; it does not establish a small-brand population
or eliminate missing identity data. A genuinely new external Catalog discovery
would require separate authorization and new reviewed query inputs. The summary
reports the actual diversity and missing identity fields rather than padding or
inventing candidates.

## Offline CLI

Use Python 3.12 from the repository and a new M66 store. Never point it at an
original private authorization/ledger or another seller account's store.

```bash
.venv/bin/python -m app.m66 init --store var/m66-review/intelligence.sqlite3
.venv/bin/python -m app.m66 export-verification --store var/m66-review/intelligence.sqlite3 --output var/m66-review/manual-observations.json
```

Edit/add observations in a new JSON file with the same schema and import it:

```bash
.venv/bin/python -m app.m66 import-verification --store var/m66-review/intelligence.sqlite3 --input var/m66-review/manual-observations.json
```

Use a nonsecret `manual:review-alias`; no private free text or screenshots. Repeat
imports are idempotent. Existing M64 invoice documentation remains available via
M65's manual export workflow. Import the existing restriction report with
`app.m66 import-history --input <exact existing report.json>`; this reuses M65's
allowlisted importer, never the completed execution command.

Prepare a cohort using both saved inputs:

```bash
.venv/bin/python -m app.m66 prepare --store var/m66-review/intelligence.sqlite3 --catalog /root/.intelligenceos-arbitrage-amazon/m63-catalog-discovery-01.json --catalog var/m63-final-review-20261101/M63_amazon_candidates_100.csv --history-dir /root/.intelligenceos-arbitrage-amazon --output var/m66-next-review --max-checks 20 --max-per-brand 2
```

Use the literal printed manifest SHA-256 for offline validation, together with
the same sources/store/history. Validation reconstructs the complete proposal;
code/source/history/manual/score changes fail closed. Output directories/files
must be new; historical reports are never overwritten. The private final handoff
contains the exact evaluated digest and full commands for this host.

Output files include all evaluated candidates, selected-cohort CSV, ranking JSON,
historical exclusions, manual evidence, diversification/missing-data summary,
downstream templates, `M66_review_manifest.json`, `M66_manifest.sha256`, and
`M66_AUTHORIZATION_REVIEW.md` with exact ASINs and request budget.

## Authorization/accounting boundary

There is **no CLI execute/run action or network adapter**. The M66 review envelope
contains an unchanged M65 bounded restriction-proposal contract plus M66 code,
source and verification hashes. Both are non-executable proposals. Do not run
them with M63 or reuse M63's completed authorization.

Future accounting requires a separate fresh human authorization containing the
exact outer file digest, ordered ASINs, US/New scope, exact budget, review date,
expiry and reference, plus an explicit execution flag. Full source/history/code
validation precedes reuse of M65's transactional permanent ASIN/batch reservations.
Each request is consumed once before future transport; there is no reset, retry,
automatic budget expansion, refresh, release, or follow-on pricing/fees/retailer
stage. Immutable scoped result metadata requires a consumed request; an UNKNOWN
or failed result stops the batch. These primitives are tested only with synthetic
temporary records. Real preparation creates zero claims or attempts. A live
adapter remains a separately reviewed implementation task.

## Downstream identity and economics

Create a blank contract with `app.m66 template --asin ASIN --output new.json`.
The contract has Amazon and retailer product observations with ASIN/brand/title,
GTIN, model, size, pack quantity, variation, URL, date and provenance; per-unit
selling price, retailer price/shipping/tax, fees, inbound and other costs; and a
positive inventory-unit count. No values are fetched or invented. Evaluate
supplied inputs with `app.m66 evaluate --input new.json --output decision.json`.
It first recomputes eligibility from the store, before identity or cost analysis.

Exact matching reuses the existing matcher and additionally requires matching
valid GTIN, brand, model, size, positive pack quantity and variation, with two
fresh sourced observations. Missing identifiers cannot fall back to similar
titles/model-only matches. Explicit mismatches are rejected. Parent packs,
different variations/quantities and substitute brands do not qualify.

Every monetary field must be independently supplied, finite/nonnegative, USD,
fresh within 24 hours, and sourced. Explicit zero is allowed; absence is never
zero. Amazon price needs the exact ASIN/New scope. Referral/FBA quotes additionally
need FBA fulfillment and a `sale_price_basis` equal to the supplied selling price;
hypothetical fees for another price cannot be silently reused.

Per complete selling unit:

```text
amazon_fees = referral_fee + fba_fee
acquisition_cost = retailer_price + retailer_shipping + sales_tax
other_costs = prep + packaging + storage + other_acquisition + other_selling
net_profit = amazon_sale_price - amazon_fees - acquisition_cost - inbound_shipping - other_costs
total_invested_cost = acquisition_cost + inbound_shipping + prep + packaging + other_acquisition
ROI_percent = net_profit / total_invested_cost * 100
estimated_inventory_investment = inventory_units * total_invested_cost
```

The Decimal engine `profitability.analyze` performs the calculation. This matches
the repository's acquisition-ROI convention: Amazon fees/storage/other selling
charges are deducted once from proceeds, not added again to invested acquisition
capital. Retailer shipping and inbound shipping are different legs; tax is counted
once. Inputs must be allocated per matched selling unit; do not enter totals that
already contain separately listed charges. Budget is evaluated for this proposed
opportunity, not an automatic portfolio allocation. Estimates are not guaranteed
returns or purchase authorization.

## Opportunity decisions

`REJECTED_RESTRICTION`, `REQUIRES_APPROVAL`, `NEEDS_SELLER_VERIFICATION` and
`NEEDS_FBA_VERIFICATION` precede retailer/profit work. Conflicts/brand validation
require seller review; FBA conflicts require FBA review. After both positive
eligibility gates, explicit mismatch yields `REJECTED_IDENTITY_MISMATCH`; missing
identity yields `NEEDS_RETAILER_MATCH`; missing/invalid fees, price, costs, scope,
freshness or allocation yields `NEEDS_FEE_DATA` with exact missing-field names.
Complete but failing economics yields `REJECTED_PROFITABILITY`.

`READY_FOR_PURCHASE_REVIEW` requires fresh verified listing/FBA permission, no
conflicts, exact identity, all required sourced/scenario-matched costs, ROI >=50%,
net profit >=$5 and investment <=$500. It always returns
`purchase_authorized=false` and `listing_submission_authorized=false`. There is no
purchase/application/upload/listing action. Historical facts and operator-supplied
references support review; offline code cannot authenticate an invented source.

## Verification

```bash
.venv/bin/python -m pytest -q tests/test_m66.py tests/test_m65.py
.venv/bin/python -m pytest -q
```

Tests block sockets and real Amazon transport/credentials and cover all evidence
and decision states, expiry/conflicts, Kozerite, manual requirements, immutable
history/results, ASIN exclusions, deterministic diversity, manifest integrity,
budgets/reservations/no retries, exact UPC/pack matching, complete-cost math,
scenario-matched fees, missing data and privacy. Both documented offline sample
modes are checked with isolated outputs and email disabled. Real claims,
submissions, private authorization changes and live requests remain zero.

## Local acceptance result — 2026-11-01

The final suite passed **1,351 tests**, including 65 new M66 cases; both isolated
legacy and discovery sample modes passed. The original 100-product input alone
proposed 12 products across six brands. Combining the saved 98-row archive yields
197 unique products and a reviewed 20-ASIN proposal across 17 brands, five each
in kitchen, household, office and home improvement. Fourteen selections are
outside the original seed brands; this is representation, not company-size or
eligibility evidence.

All 20 completed M63 ASINs and all 77 historical exclusions remain protected.
There are 21 historically excluded ASINs within the combined input. Original
report/exclusion hashes match the M65 audit. The real M66 store contains zero
batch/ASIN claims, request attempts or result records. No live permissions were
used or changed.

Among selected candidates, 14 lack GTIN/model/size/pack data, 17 lack variation
data and all 20 lack product type. Prices, fees, retailer matches and positive
listing/FBA verification remain unavailable. No real product is ready for purchase
review. Across all 197 input products, current decisions are 177 needing seller
verification, 17 requiring approval and three rejected for restrictions. The API
history remains 18/2; Stanley's additional manual no-new-listings observation
accounts for the extra rejection at the decision layer. Kozerite remains
unverified and blocked from seller-readiness claims.

Private deliverables and literal verification/reproduction commands are under
`var/m66-review-delivery/`; the new derived store is
`var/m66-final/intelligence.sqlite3`. Runtime outputs are not committed.
