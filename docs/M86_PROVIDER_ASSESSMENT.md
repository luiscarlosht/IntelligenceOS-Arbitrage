# M86 — External-data recommendation

Recommendation: use SP-API plus already authorized saved/manual evidence for this
POC. Do not subscribe yet. The demonstrated first gaps are six-product membership,
exact source identity and complete acquisition/fee evidence; Keepa cannot recover
that membership or validate the Walmart sale unit. Keepa would materially add
retrospective New-price/offer/rank history once exact ASINs are established, but
would not guarantee monthly sales or profitability. No external provider was
subscribed to, integrated or queried for products in M86.

Public source review: 2026-11-04 UTC. Costs below are incremental data-service
costs excluding existing seller fees, hosting, human research and development.
Amazon's current official notice cancels the previously announced SP-API usage
and annual fees at this time. Account-specific bills and existing entitlements
were not inspected; existing seller and fulfillment charges remain separate. A six-product workload is
small but does not waive a vendor subscription minimum.

| Option | History / demand / competition | API and usage | Provenance / reliability | Effort and ongoing cash cost |
| --- | --- | --- | --- | --- |
| Existing SP-API only | Current price/New offers and available category rank; no retrospective series or general competitor monthly units through inspected operations | Existing bounded Catalog/Pricing/Fees tools; exact authorization and rate limits in coverage matrix | First-party observations, incomplete/suppressed attributes and offer coverage possible; fee estimates vary | Existing parsers reused; offline mapping/review still needed. No new data subscription; current announced SP-API usage/annual fees canceled. Existing seller plan/operational charges excluded. |
| SP-API + free/existing authorized evidence | Existing saved comparable observations, manual Revenue Calculator/merchant cost quotes and any lawfully available bought-past-month bracket; historical coverage limited to actual saved points | M86 reads normalized JSON; no new API access or scraping. A browser-visible/free service is not automatically licensed for automation/export | Original evidence dates, exact variant, permitted usage and sampling limitations required. Merchant sales are not total-market sales | Lowest integration effort; $0 new subscription if evidence already available. Human collection time remains a cost. Recommended first stage. |
| SP-API + Keepa API | Historical New prices, rank and offer-count series where tracked; monthlySold may supply variation-specific Amazon bought-past-month lower-bound brackets, often absent; no validated exact unit-sales model assumed | Product API, base request typically 1 token/product; optional offers/buybox/refresh options cost extra. Monthly token bucket, unused tokens expire after 60 minutes | Third-party tracking can be stale/incomplete. Preserve field observation dates; distinguish New/Used and shipping series. Rank drops never equal units | Existing dormant adapter and manual market patch reduce effort; live activation, scoped normalization and licensed retention still required. Historical official 2026-10-23 quote: Starter €49/month + VAT, 20 tokens/min. Current checkout price NOT VERIFIED in this review. |
| Traject Rainforest (conditional alternative) | Vendor advertises live/historical Amazon prices and Buy Box monitoring; actual historical depth, New-only competition history and unit-sales accuracy not verified for these products | Product/offer APIs documented; current rate/plan entitlements need quote. No connector/credentials exist in this project | Third-party page-derived data; independent coverage, rights, timestamps and reliability review needed. Stock estimates are not sales | More work than existing Keepa seam; current monthly cost/limits UNKNOWN (official pricing URL redirects to marketing). No demonstrated material advantage for this six-product POC, so do not shortlist for integration now. |

Keepa's public documentation describes price/history arrays and bought-past-month
brackets; most products lack monthlySold. That field is a lower bound copied from
Amazon, not independently estimated actual monthly units. It cannot establish
low demand when the bracket's lower bound is below our threshold. Coverage and
original sample dates must be checked before using any vendor metric.
[Keepa product fields](https://keepa.com/api-docs/product-object.html).

Keepa bills API access monthly with a replenishing token bucket. Six base product
requests nominally require six tokens, but optional parameters can change that;
unused tokens expire after an hour. Subscription cash cost is not six prorated
tokens. Existing repository pricing evidence is documented in
[KEEPA_PREPARATION.md](KEEPA_PREPARATION.md); today's
[checkout page](https://keepa.com/api/pricing) returned only a JavaScript shell,
so €49 is a dated quote, not a verified current offer. Verify taxes, FX, licensing,
retention/deletion and API entitlement before an approved purchase; the old quote
can exceed the project's $50/month target after conversion and tax.
[Keepa token/billing documentation](https://keepa.com/api-docs/plans-tokens.html).

Rainforest's official page advertises historical/live pricing and Buy Box context,
but no reviewed product sample or current price proves an advantage here. Its
marketing claims are not a verified SLA or a validated demand estimate.
[Official Rainforest capabilities](https://trajectdata.com/ecommerce/rainforest-api/).
No trial, cart, stock-estimation operation or sales inquiry was initiated.

Decision sequence: recover six original records; analyze complete costs and current
New evidence regardless of selling status; enumerate remaining historical gaps.
If those gaps could change the economics/risk decision, request a separately
approved, fixed-cost Keepa sample with exact ASINs and licensed historical fields.
Compare coverage/freshness to existing observations before any ongoing commitment.
If supported demand remains unavailable, keep market assessment INSUFFICIENT_DATA;
a paid account never licenses an invented sales forecast.

Amazon's official fee-cancellation notice was checked on 2026-11-04; older
third-party articles describing upcoming annual/GET-call fees are not the current
basis for this recommendation. This does not waive seller or fulfillment fees.
[Amazon SP-API fee cancellation](https://developer.amazonservices.com/cancellation-of-sp-api-fees).
