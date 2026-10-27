# Amazon live evidence and ten-product source preparation — 2026-10-27

The retained owner-run selected validation completed 12:58:49–12:59:29 UTC.
Authentication, pricing, fee estimate and seller restrictions each returned HTTP
200, one attempt each, four total, no retries. This establishes successful live
integration for these operations, not a profitable or purchasable product.
The private sanitized report was read without credential access and left unchanged:
`selected-validation-B0G1MJ24B4-01.json`, SHA-256
`5258e166a0b60aefb7b709b4a61816c5d6554d0c28975a84173d4e7ad0996201`.
No new live calls were made. No raw report or seller identifier is committed.

B0G1MJ24B4 is excluded from sourcing recommendations by the common discovery
screen and request planner: the authorized seller's US/new_new restriction was
`NOT_ELIGIBLE`, listing permission false. Keep the row and reason in all-candidate,
rejection and data-quality outputs. This is a retained seller-specific result,
not a universal restriction for every seller. The exclusion remains until an
explicitly reviewed policy update; a fixture claiming eligibility cannot remove it.
Overall seller/FBA eligibility remains unknown and purchase approval false.

Pricing reported New/FBA lowest and Buy Box observations of $8.97 plus $0 shipping.
The returned detail also contained $8.97 listing and $0 shipping; landed detail
price was absent and remains null. The fee scenario was independently selected
at hypothetical $37.25 FBA, $0 buyer shipping: $5.96 referral + $3.78 fulfillment
= $9.74 estimated total. Those fees must not be applied at $8.97 or promoted to
proof that $37.25 is achievable. No fee request is now appropriate for this ASIN.

## Condition-count finding

The newer retained report supplies NumberOfOffers: New/Amazon **1**, Used/Amazon
**4**, aggregate **5**, returned New details **1**. BuyBoxEligibleOffers contains
the same buckets. Thus the missing four are accounted for in the Used bucket;
a New-condition request plausibly explains why only one detail was returned.
This is an inference from the retained breakdown and the documented condition
filter, not a reconstructed raw response or a guarantee of all-seller coverage.
The earlier reports lacked this breakdown and cannot independently establish it.

The [official Product Pricing model](https://github.com/amzn/selling-partner-api-models/blob/main/models/product-pricing-api-model/productPricingV0.json)
defines NumberOfOffers by condition and fulfillment channel, TotalOfferCount as
aggregate unique offers, and ItemCondition as a filter. It also defines the
Offers length against min(TotalOfferCount,20), without a condition exception.
Consequently the code now reports requested_condition_offer_count=1 and
condition_count_matches_returned=true separately from documented expectation=5,
documented_count_matches=false and partial/incomplete coverage. Missing condition
labels leave the condition comparison unknown. Conservative ranking exclusion
and no-lowest-price guarantee remain. No documented contract change justifies
silently treating the aggregate comparison as satisfied.

## Prepared workflow, execution disabled

`app.amazon_source_plan.prepare` is a local Python API, with no network executor,
credential loader, mailer or orchestrator registration. It accepts exactly ten
rows using `templates/authorized_products.csv`, normalized local catalog listings,
PricingSnapshot evidence, seller-scoped RestrictionCheck evidence and an explicit
mapping of 1-based CSV row to USD fee price. Missing evidence is allowed and
reported. Invalid prices or input row counts fail preflight before persistence.
This preparation does not manufacture ten authorized products from examples.
Actual source products and permission records have not been supplied.

1. Validate owner-authorized export and original evidence times offline. Record
   permission references; a populated field alone never proves authorization.
2. Reuse `match_listings`: GTIN or manufacturer/model, exact package quantity and
   variation; ASIN hints alone never establish identity. Preserve ambiguous,
   unmatched and mapping-issue candidates with reasons.
3. Retain separate pricing and seller/US/new_new restriction evidence, freshness,
   counts, scope and reasons. Missing, stale, partial, restricted or unknown overall
   seller/FBA eligibility blocks fee planning. No-restrictions alone is insufficient.
4. Require an explicit positive USD listing price per selected row, at most two
   decimal places, FBA and $0 buyer shipping. No automatic competitor-price choice.
   One scenario per row; deduplicate identical ASIN/price requests. Plans remain
   hypothetical and requests_enabled=false. No default fee price or missing fee=0.
5. Reuse ObservationStore, History, discovery.screen and write_report. Store every
   input ordinal, source hash, matching evidence, pricing/restrictions, scenario and
   decision; repeat runs deduplicate normalized observations, not lineage. Use
   provider `supplied-normalized-catalog` and an explicit offline-plan run label.
   Excel includes existing all-candidate/rejection/data-quality sheets and optional
   enrichment sheet for fee plans. Persist missing values as null.
6. Existing $5 profit / 50% acquisition ROI gates and all sourcing prerequisites
   still apply. Fee-request suitability is distinct from profitability readiness;
   missing demand/cost evidence stays visible even if a fee scenario is planned.

Example invocation from application code (all objects supplied locally):

```python
from app.amazon_source_plan import prepare
result = prepare(source_csv, tuple(normalized_catalog), pricing_by_asin,
                 restrictions_by_asin, {2: '19.99', 7: '24.50'},
                 development_output_directory, seller_reference='authorized-owner',
                 fba_eligibility=fresh_fba_evidence_by_asin)
```

The seller reference is a nonsecret alias consistently tied to the authorized
account, never an actual seller ID. Pricing and restrictions are normalized
objects, not raw responses. Supply trusted parsed evidence; do not use this API
to assert arbitrary JSON is verified provider evidence. Catalog mapping issues
remain blockers. No global production provider/configuration changes were made.

## Source-data requirements

Supply ten real rows: retailer, product name and permitted source URL; valid GTIN
(including check digit) or manufacturer plus model; per-package purchase price
in USD, positive package quantity, exact size/color/variation, confirmed stock,
original timezone-aware retrieval time, export/feed provenance and actual
permission/license reference. ASIN hint is optional. Use current evidence (24-hour
screening window); do not refresh timestamps without fresh observations.

After initial ingestion, separately collect inbound shipping, preparation, packaging, sales tax, storage
and other acquisition/transaction costs with verification basis; current demand
and competition evidence; verified catalog child/package/variation; authorized
seller scope and independent overall/FBA eligibility evidence. For selected fee
candidates provide listing price and its basis, distinguishing hypothetical from
an independently supported seller sale quote. These later fields are not required for initial CSV ingestion. Missing fields block sourcing
recommendations and remain visible. See the [CSV field guide](AUTHORIZED_IMPORTS.md)
for the source-only intake requirements and later Amazon enrichment stages. Source URLs are never fetched by this tool.

## Proposed request budget for later explicit authorization

Current execution budget: **zero**. Proposed single-product requests, sequential:

| Operation | Hard ceiling |
| --- | ---: |
| LWA authentication | 1 |
| Catalog lookup/search, one bounded result page per source product | 10 |
| New/Consumer pricing for exact matched unique ASINs | 10 |
| Authorized seller US/new_new restrictions for those ASINs | 10 |
| Fees, only passing unique ASIN/explicit-price scenarios | 0–10 |
| Total attempts including authentication | **31–41** |

The returned plan reports 31 + currently suitable unique fee scenarios as a
conservative ceiling; unmatched/restricted/deduplicated cases reduce actual
requests. No fees for B0G1MJ24B4. A fresh intake with unresolved evidence budgets
zero fee requests pending staged checks. No retries, pagination, token refresh,
fallback search, second price or automatic error recovery within this budget.
Stop on authentication failure or authorization/rate-limit error; preserve partial
results. Pace sequential calls according to the applicable operation limit;
reserve attempts in the existing UsageLedger before any future request. The
current planner does not reserve usage because it cannot execute requests.
A future executor needs its own bounded deadline and tests before authorization.
No batch endpoints or multi-identifier calls are enabled or needed.

Official references:
[Catalog search](https://developer-docs.amazon/sp-api/reference/searchcatalogitems),
[Product Pricing model](https://github.com/amzn/selling-partner-api-models/blob/main/models/product-pricing-api-model/productPricingV0.json),
[Listings Restrictions model](https://github.com/amzn/selling-partner-api-models/blob/main/models/listings-restrictions-api-model/listingsRestrictions_2021-08-01.json),
[ASIN fees](https://developer-docs.amazon/sp-api/reference/getmyfeesestimateforasin).
Catalog search supports identifier matching; keep pagination and unresolved
mapping outside the proposed budget. Amazon fees use the proposed price and may
differ from actual costs. Nothing here authorizes purchases, deployment or email.

## Local validation

The original local development suite passed 682 tests. The PR is based on current
main and excludes earlier unmerged selected-validation code. Both documented offline sample modes
were run with local development outputs; no provider calls, credential reads,
purchases, deployment or email occurred. Regression cases cover retained-ASIN
exclusion, condition counts, independent FBA eligibility, fee scope/freshness/
restriction/partial/missing gates, explicit prices and ten-row SQLite/Excel lineage.
