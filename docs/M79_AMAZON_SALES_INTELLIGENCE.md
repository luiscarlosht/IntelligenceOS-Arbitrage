# M79 — Amazon evidence coverage before Walmart sourcing

**Demand shortlist blocked: saved catalog discovery is not sales evidence.**
M79 performs only offline inspection, consolidation, coverage and research ordering.
It makes no requests, replays no M77 operation, opens no registry or credentials,
stages no evidence on DigitalOcean and changes no historical input.

## Actual evidence and scope

M76's original manifest is pinned to
`0e8c1840d7f9860c36422baa5d828bfc9d29493bac77d2c80af71daf0b67577b`.
Every manifest-listed M76 export is checked. The upstream M70 report, including
40 historical restrictions observations, is checked against the digest bound by
that manifest (`228c29245ab8898fb4647aa5016b0e86b49ac6546ebef546480a65c941370a56`).
Original M77 saved pages/source/summary must match their complete saved digest
inventory and agree on completed 31-page, 32-slot/no-uncertainty accounting.
The source reference must point only to the original saved-page filename.
No journal is opened or replayed: M77 origin is the owner's supplied original
export set; internal export digest consistency is not an independent re-audit of
the immutable journal. Exact input and current implementation hashes are retained
for independent review and checked again before publication.

The original curated M76 decisions plus M70's existing saved-page normalization
produce exactly 777 + 620 = 1,397 unique ASINs, zero overlap, 80 conflict ASINs and
41 catalog permanent exclusions. No annotation for an out-of-catalog ASIN creates
a new product. Exclusions and conflicts are preserved, never reset by M79.
No original M76/M77 implementation, historical report or registry is modified.

Coverage as of **2026-11-03T03:24:33Z**, using explicit planning freshness thresholds:

| Metric | Available fresh | Stale historical | Missing | Unverified |
|---|---:|---:|---:|---:|
| Current seller eligibility | 0 | 0 | 1,397 | 0 |
| BSR | 0 | 0 | 1,397 | 0 |
| Current Amazon offer price | 0 | 0 | 1,397 | 0 |
| Offer count | 0 | 0 | 1,397 | 0 |
| Buy Box | 0 | 0 | 1,397 | 0 |
| Category label | 1,396 | 0 | 1 | 0 |
| Historical eligibility annotation only | 0 | 40 | 1,357 | 0 |
| Catalog list price, not an offer | 576 | 0 | 800 | 21 |
| GTIN | 632 | 0 | 765 | 0 |
| Brand | 1,396 | 0 | 1 | 0 |
| Model | 1,079 | 0 | 318 | 0 |
| Title | 1,397 | 0 | 0 | 0 |
| Explicit package quantity | 870 | 0 | 527 | 0 |

The 40 historical seller checks are **36 APPROVAL_REQUIRED and four NOT_ELIGIBLE**.
There are no positive eligibility checks to promote. History remains history,
including its original timestamps and source references; it is never inferred
from catalog identity or brand. Manual application requirements are not approvals.
No current or FBA selling permission is claimed.

M77 retained 597 ASINs with a `list_price` attribute. Positive, US-scoped USD values
exist for 576 ASINs. Twenty-one have zero-only values; another CAD observation is
rejected without currency conversion (its ASIN also has a valid USD observation).
All 22 rejected observations and reasons are retained. A catalog/MSRP attribute is
**not** a verified current offer, Buy Box price, revenue estimate or margin input.
M76's normalized identity exports contain no offer/BSR fields; M77's requested
includedData omitted salesRanks, and its retained items have no sales-rank datasets.
New/unrecognized sales datasets in an export stop analysis for a reviewed adapter;
they are not silently discarded into UNKNOWN.

Freshness policy: 24 hours for BSR/eligibility, six hours for offer/Buy Box metrics,
and 30 days for catalog identity/list-price observations. These are conservative
review thresholds, not Amazon guarantees. Missing, stale, invalid/unscoped and
fresh are distinguished. Future/naive/malformed timestamps are unverified.
A missing price/count is never zero; unknown eligibility is never eligible.

## Demand, competition, stability and sales estimates

No defensible demand ranking or BSR-to-monthly-sales estimate can be computed from
these inputs. All such values, confidence and ranks remain **UNKNOWN**, rather
than assigning identity scores to demand or fabricating 0 sales. Category labels
alone do not supply browse-node sales rank, category market size or conversion.
No calibrated BSR-to-sales model or labeled category-level unit-sales dataset exists
in the declared evidence; there is no fitted coefficient or confidence interval.

If separately authorized evidence later supplies BSR, rank only within the same
marketplace, exact category/browse/display-group ID and rank type at comparable
timestamps. Do not compare a subcategory rank directly with a broad-category rank
or equate a better rank with a known number of units. An empirical conversion would
require representative ASIN-level units over matched time windows, category and
variation/seasonality assumptions, holdout validation, uncertainty intervals and
independently reviewed provenance. Seller-specific order units are not necessarily
total ASIN sales. A model would require a separately reviewed implementation; M79
contains no generic converter and no unsupported category constants.

Competition needs current new-condition offer counts, fulfillment segmentation,
Amazon retail presence where observed, and Buy Box/featured-offer evidence. Missing
or suppressed offers remain UNKNOWN, never zero competition. Price stability needs
repeated comparable landed offer prices, currency, condition, marketplace and
sampling windows. One catalog list price or one offer snapshot cannot establish
stability. Future time-series collection needs separate explicit authorization.

## Excel and machine handoff

Private outputs are ignored by Git and must not be committed:

- `M79_amazon_intelligence.xlsx`: All_ASINs, Coverage, Demand_Top100, Demand_Top20,
  Research_Top100, Research_Top20, Category_Coverage, Method and Provenance sheets.
- `M79_report.json`: full metrics, provenance, observations, rejections and summary.
- `M79_walmart_handoff.json`: all 1,397 ASINs and observed GTIN/UPC, brand, model,
  title, explicit package quantity (`quantity` alias), size/variation, field provenance,
  unknown current Amazon price, and explicit eligibility/sourcing/purchase gates.
- `M79_findings.md` and `M79_completion.json`: findings and exact input/code/output
  SHA-256 inventories. A directory without completion is an incomplete run.

Demand_Top100 and Demand_Top20 contain **no qualified products** and display the
blocker. There are 1,276 unblocked records for further Amazon metric acquisition.
Their research order uses only observed identity-field coverage descending, then
exact ASIN ascending for deterministic ties. The research Top 100 and Top 20 are
explicitly **not demand recommendations or a Walmart sourcing authorization**.
No numerical demand/competition/stability/eligibility scores are assigned.
The handoff has `ready_for_walmart_sourcing=false`, `approved_shortlist=[]` and
`sourcing_allowed=false` on every record. It is a schema-compatible preparation
artifact for the Walmart agent to inspect, not a supported sourcing shortlist.
Success at the requested demand-shortlist level remains blocked on Amazon metrics.

## Reproducible offline command

Run only in the authorized development workspace with existing original evidence:

```sh
.venv/bin/python -B -m app.m79 \
  --m76-dir var/m76-validated \
  --m77-dir /root/.intelligenceos-arbitrage-amazon/m77-catalog-expansion-output \
  --baseline-report var/m70-offline-final/M70_report.json \
  --as-of 2026-11-03T03:24:33Z \
  --output var/m79-amazon-intelligence-final-20261103
```

Use a new sibling output name for a second run. Identical inputs/code/as-of must
produce identical output bytes. No output may exist already, reside under an input
root, traverse symlinks, or resolve beneath /mnt. Output is 0700, files 0600, and
Excel values are formula-safe. Machine JSON preserves literal identity strings.
Only the new report directory may be written; failures preserve incomplete outputs
without publishing completion. The process audit guard denies Python socket,
subprocess, SQLite and sensitive credential/owner-artifact reads. It is defense in
depth, not an OS isolation claim or protection against native code/malicious owners.

## Fresh Amazon evidence — approval boundary, no executor

Fresh evidence is essential for the requested supported demand shortlist.
Nothing below is an approved request or execution command. Do not replay M77,
reuse its authorization, or alter its registry. A new reviewed milestone/request
manifest, explicit seller/marketplace binding, roles, request budget and owner
approval are required. No network execution code is added by M79.

A small **new Top-20 research-queue pilot** would require exactly:

1. At most one fresh LWA token POST to `https://api.amazon.com/auth/o2/token`, only
   after approval and through the existing protected credential mechanism. Never
   expose refresh tokens/client secrets in commands or reports.
2. Twenty `GET /catalog/2022-04-01/items/{asin}` calls on
   `https://sellingpartnerapi-na.amazon.com`, each with
   `marketplaceIds=ATVPDKIKX0DER` and
   `includedData=salesRanks,summaries,identifiers,productTypes,classifications,relationships,attributes`.
   Preserve original category IDs, rank type, variation relationships and timestamps.
3. One `POST /batches/products/pricing/v0/itemOffers` with twenty request objects:
   `uri=/products/pricing/v0/items/{asin}/offers`, `method=GET`,
   `MarketplaceId=ATVPDKIKX0DER`, `ItemCondition=New`, `CustomerType=Consumer`.
   Preserve all subresponse statuses, actual offer counts, listing+shipping amounts,
   currency, fulfillment and Buy Box flags when present. A batch HTTP 200 does not
   make each item successful; absent fields remain UNKNOWN.
4. Twenty `GET /listings/2021-08-01/restrictions` calls with exact `asin`,
   `sellerId=<approved-owner-bound-seller>`, `marketplaceIds=ATVPDKIKX0DER`,
   `conditionType=new_new`. Assess applicable restriction reasons; an empty successful
   list is evidence only of listing restrictions for that account/scope/time, not
   FBA, invoice, authenticity, profitability or purchase approval.

| Scope (one snapshot) | Catalog GET | Pricing batches (max 20) | Restrictions GET | LWA max | Total HTTP calls |
|---|---:|---:|---:|---:|---:|
| Research Top 20 | 20 | 1 | 20 | 1 | 42 |
| Research Top 100 | 100 | 5 | 100 | 1 | 206 |
| All 1,276 unblocked research records | 1,276 | 64 | 1,276 | 1 | 2,617 |
| Entire 1,397-ASIN universe (accounting comparison only) | 1,397 | 70 | 1,397 | 1 | 2,865 |

Permanent exclusions are never queried under this proposal; the last line is not
a recommended scope. Request plans must enumerate and hash exact selected ASINs,
freeze condition/marketplace/operation and define zero automatic retries, refreshes,
pagination or substitution. A partial failure remains consumed/uncertain; no replay.
Any rate, cooldown, credential-expiry or response issue stops for review. Repeated
snapshots for price stability and sales-model calibration are additional scope and
are not included in the table. Costs/billing and actual account usage-plan availability
must be reviewed before approval; no zero-cost claim or paid integration is implied.

Amazon's documented default ceilings are Catalog getCatalogItem 2 rps, pricing
getItemOffersBatch 0.1 rps (20 subrequests maximum), and Listings Restrictions 5 rps
per account/application, subject to other limits and returned headers. Sequential
service pacing alone is roughly 14 seconds for the 20 pilot (10 + 0 + 4), excluding
network latency, authentication, cooldowns and operational overhead; it is not a
completion guarantee. Use the lower approved/observed rates, not an assumed quota.

Required permissions: selling-partner authorization and Product Listing role for
Catalog/restrictions. The current role map permits either Product Listing or Pricing
for getItemOffersBatch; Product Listing therefore covers all three proposed operations
when granted for the owner-bound application. Verify actual granted access first. No PII or RDT
is needed for the proposed catalog/offer/restrictions fields. Approval must explicitly
cover the new operations, exact ASIN scope, seller/US marketplace, retention, request
caps and read-only/no-purchase purpose. Do not ask for credential values in chat.

Official references, checked during this development:
[Catalog operation](https://developer-docs.amazon/sp-api/lang-en_US/reference/getcatalogitem),
[Catalog roles](https://developer-docs.amazon/sp-api/docs/catalog-items-api),
[offer batch](https://developer-docs.amazon/sp-api/reference/getitemoffersbatch),
[restrictions prerequisites](https://developer-docs.amazon/sp-api/lang-en_en/docs/get-listings-restrictions),
[restrictions limits](https://developer-docs.amazon/sp-api/docs/listings-restrictions-api-rate-limits),
[role mappings](https://developer-docs.amazon/sp-api/docs/role-mappings).
