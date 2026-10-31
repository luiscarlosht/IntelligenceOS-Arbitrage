# Amazon-first sourcing pilot — offline preparation

Amazon targets → Walmart search at ZIP **76063** → independent exact-product
verification → existing economics and reports. New broad Walmart campaign
preparation is paused for this pilot. This is a planning constraint, not a change
to running processes. Existing retailer-first operations, unresolved work,
observations, databases, intake headers, schedules and browser sessions remain
intact. No live call, credential access, subscription, purchase, Sheets write,
email, scheduling, merge or deployment is part of these commands.

## Existing components inspected and reused

* `keepa_adapter`: fixed basic US ASIN contract, time/history validation,
  separate price/rank/lower-bound demand evidence, missing fees/eligibility,
  false live code gate. Its existing one-day request and historical pilot stay
  compatible; this module prepares a separate 90-day request manifest only.
* `keepa_http` and `keepa_pilot`: dormant HTTPS/gzip bounded transport,
  no redirects/proxies, private terminal `read_pilot_key`, sanitized summary,
  durable one-shot attempt marker. No credential loader is invoked here.
* `amazon_catalog` / `amazon_details`: normalized Catalog Items identifiers,
  model/variation relationships, pricing coverage, proposed-price fee estimates
  and seller-specific restrictions. Partial pricing is blocked independently.
  Existing SP-API authorization and manual entry points stay unchanged. Keepa
  does not establish seller eligibility or replace these SP-API contracts.
* `marketplace.match_listings`, `discovery.screen`, `profitability.analyze`:
  deterministic identity, package and variation checks, freshness and cost gates,
  $5 profit / 50% acquisition ROI defaults. Callers pass configured thresholds
  into `browser_jobs`; no implicit environment/credential loading occurs.
* `ObservationStore`, `History`, `UsageLedger`, `candidate_execution` and
  `stored_candidate_search`: established normalized evidence, execution lineage,
  durable reservations/claims and cooldowns. TargetStore extends ObservationStore
  with additive tables in an explicitly supplied offline database. It does not
  consume pending executions or reset their claims. No discovery executor has
  been registered; future live work must reserve every attempt in UsageLedger
  before transport, under `Policy(max_attempts=1)`.
* `sheets_intake`: immutable COMPLETE batches, source record links and consumer
  acknowledgment ownership. `verify_observation` returns the existing report-row
  contract plus target/job IDs and independent verification flags, suitable for
  `reporting.write_report(..., discovery=True)`. Historical demand does not get
  promoted into `MarketplaceListing.monthly_sales` or an executable sale quote.

## Official Keepa findings, checked 2026-10-31

[Request basics](https://keepa.com/api-docs/request-basics.html) specifies HTTPS,
the private `key` query parameter and compressed responses. Its usage envelope
reports `tokensConsumed`, `tokensLeft`, `refillIn` and `refillRate`; a positive
starting balance can become negative. Error bodies may contain partial failures.
Never log request URLs, keys, raw responses or provider error messages.

[Plans and tokens](https://keepa.com/api-docs/plans-tokens.html) describes separate
monthly API plans and dashboard API access/key management. Refill depends on the
API plan; unused tokens expire after 60 minutes and bucket capacity is rate × 60.
**Account API entitlement, key validity, refill rate, retention rights and actual
monthly price remain unknown.** A website/Data Access subscription is not evidence
of API entitlement. The owner must privately verify their dashboard and API plan;
no purchase, upgrade or account check has occurred. No vendor dollar cost is
assumed and no plan is selected.

[Product Request](https://keepa.com/api-docs/product.html) supports cached history,
time-window statistics and optional offer retrieval. Base lookup is one token
per product; `update=-1` prevents refresh, including a zero-token/no-data case for
an unknown ASIN. `history`, `days` and product `stats` add no token cost. Offer
pages cost six tokens each (minimum five on successful empty retrieval); Buy Box,
stock, ratings and historical variations can add charges. Those optional features
are excluded. Cached evidence is not a fresh achievable resale price.

[Product Finder](https://keepa.com/api-docs/product-finder.html) uses `/query`,
GET selection JSON or POST JSON body. Cost is 10 plus one per 100 returned ASINs;
its minimum/default page is 50, first-page maximum 10,000, with paging constrained
to 10,000 results. Finder `stats=1` incurs a separate, potentially query-wide
charge and is omitted. A local ten-target limit cannot make the vendor return
only ten; this pilot selects ten from one minimum-size page and stops.

[Product Object](https://keepa.com/api-docs/product-object.html) provides typed
price/rank histories, product/update timestamps, manufacturer/model, brand,
UPC/EAN/GTIN lists, size/color, package quantity, unit count and optional variation,
fee and offer fields. [Statistics Object](https://keepa.com/api-docs/statistics-object.html)
provides cached current and weighted historical values, rank-drop counts and
offer counts; some fields require optional offers/Buy Box requests. Missing or
negative unavailable values must not become prices. Rank changes and provider
monthly-sold lower bounds are **demand signals, not verified sales**.

These are documentation findings, not observed account behavior. Filter efficacy,
retailer availability, identifier accuracy and unit economics remain pilot
hypotheses. The current offline fixture is fictional, including its ASIN.

## Exact proposed requests and budget

Authentication is injected privately later, never placed in a command argument.
All requests would advertise `Accept-Encoding: gzip`; no retries, polling,
refill waits or pagination are allowed. Execution remains unavailable.

| Stage | Endpoint/options, excluding key | Maximum HTTP requests | Documented token reservation |
| --- | --- | ---: | ---: |
| Connectivity/history | `GET https://api.keepa.com/product?domain=1&asin=B002XQ1R06&update=-1&history=1&days=90&stats=90` | 1 | 1 |
| Discovery | `POST https://api.keepa.com/query?domain=1`, JSON selection below; omit Finder stats | 1 | 11 |
| Hydrate | `/product`, same cached 90-day options; one explicit ASIN per call, first ten distinct results excluding connectivity ASIN | 10 | 10 |
| Total | Stop on any error, billing discrepancy or incomplete response | **12** | **22** |

```json
{"page":0,"perPage":50,"productType":0,"title":"kitchen","current_NEW_gte":2000,"current_NEW_lte":6000,"avg90_SALES_gte":1,"avg90_SALES_lte":100000,"sort":[["current_SALES","asc"]]}
```

Proposed filters are assumptions: familiar kitchen products offer plausible
Walmart overlap; $20–$60 marketplace-new pricing leaves room for fixed fees;
90-day rank ≤100,000 favors sustained catalog activity. Rank is category-relative,
so this is a research queue rather than a cross-category sales threshold. No
category-ID discovery request is hidden in the budget. Product type 0 limits
unsupported records. No forced single-variation dedup removes variant evidence.
After hydration, prioritize identifiable models and explicit retail packs; retain
missing/ambiguous evidence as unresolved rather than inventing identifiers.

**A hard vendor billing ceiling is not guaranteed.** The 22-token reservation
assumes current documented pricing, one chargeable Finder block for 50 results,
and exact listed options. Confirm rounding/tariff before authorizing execution.
A client can enforce attempt limits but cannot prevent a provider billing
discrepancy already charged. No live execution is exposed by the new CLI.
Discovery proceeds only after the separately authorized connectivity stage has
acceptable entitlement/usage evidence. `select_discovery_asins` validates at most
50 returned ASINs and deterministically retains at most ten without any requests.

## Target, job and observation contracts

`AmazonTarget` v1 persists stable `amazon:<marketplace>:<ASIN>` identity, ASIN,
marketplace, brand/title/manufacturer/model, every identifier with field-level
provenance, timestamp and uncertain/verified/conflicting status, package/size/color
evidence, history and cached statistics, current-price context, seller restrictions,
fee assumptions, missing fields and created/observed/fetched timestamps. Product
observation time is distinct from retrieval time. Canonical Decimal strings,
explicit nulls and timezone-aware timestamps reuse existing evidence serialization.
Immutable content hashes preserve all target revisions.

No identifier list is collapsed to a convenient UPC. Keepa-reported package/variant
fields remain uncertain until independently checked. An acquisition ceiling
requires USD proposed resale price, provenance/time and every existing COST_FIELDS
entry, including explicitly justified zeros. Unknown shipping/tax/prep/packaging,
fees, storage or transaction costs keep the ceiling null. The existing economics
formula calculates the maximum **item purchase price** after acquisition extras,
rounded down to cents, under explicit fixed-cost assumptions. This is a scenario
ceiling, not verified profitability or purchase approval. Missing seller eligibility
still blocks verified profitability even when an illustrative ceiling is available.

`AmazonSearchJob` v1 hashes target ID + Walmart + ZIP 76063 + query version. It pins
the target revision and includes Amazon URL, identifiers/status/model, brand,
size/variant/retail pack, supported price ceiling and exact missing fields.
Queries run each identifier first, then brand/model, then brand/product wording.
Verify Walmart seller, fulfillment, location, stock, condition, pack, variant,
price, shipping and tax separately; pickup/delivery/shipping are distinct.
Brand/size/variant changes are never an acceptable substitute.

Save each attempted query outcome: `no_result`, `mismatch`, `unavailable`,
`unresolved` or `matched`, with evidence reference, observation time, elapsed
seconds and known cost or null. Use multiple outcome rows for multiple queries.
Browser matched means a claim only. Source observations link to target/job through
append-only events and independent evaluations. Save observations using the
existing intake/ObservationStore writer, then `TargetStore.evaluate` checks the
persisted product content before matching and screening supplied marketplace
evidence. It never treats the browser claim as proof. Target brand and source ZIP
must agree with normalized source_context evidence. Target model/pack/variant
constraints supplement the existing matcher. Verified-profitability flags require
exact matching, passing existing gates, verified costs and non-mock evidence.
All evaluation rows remain reportable, including rejections.

Re-exporting an unchanged job is idempotent and **does not authorize another
search**. Changed payload under the same ID is rejected. Any refresh requires a
new query version, prior-job ID and written reason, e.g. new manufacturer evidence,
known stock change or operator-requested dated recheck. There is no automatic TTL
retry of unsuccessful queries. Prior jobs, evidence and failures stay immutable.

## Offline Sheets handoff schema

No existing intake column or ownership rule changes. `sheets_export` proposes
three separate tabs, implemented as an offline values artifact only:

| Tab | Fields | Ownership |
| --- | --- | --- |
| Amazon_Targets | target_id, revision, schema_version, target_json | application produces immutable revisions; browser reads |
| Amazon_Search_Jobs | job_id, target_id, target_revision, retailer, location, query_version, schema_version, job_json | application produces; browser reads |
| Amazon_Search_Outcomes | event_id, job_id, target_id, outcome, query, observed_at, evidence_reference, elapsed_seconds, cost_usd, intake_record_id, browser_claim_json | browser appends; application consumes |

All cells are literal text; any future import must use RAW and preserve complete
JSON evidence. `intake_record_id` links to the unchanged Walmart intake producer
record; application resolution adds the local `source_observation_id`. Outcomes
including no-result need no invented product row. Existing COMPLETE publication,
immutability and consumer-only acknowledgment rules still apply to intake.
New-tab live creation, publishing, consumption and acknowledgment require a later
integration; this preparation implements no Google calls.

## One-line offline operator commands

Run from `/root/IntelligenceOS-Arbitrage`; output paths are illustrative private
offline artifacts, never production DBs. No command reads a key or starts a browser.

```bash
.venv/bin/python -m app.amazon_targets --asin B002XQ1R06
.venv/bin/python -m app.amazon_targets --fixture sample_data/amazon_first_fixture.json --database /tmp/amazon-first-pilot.sqlite3 > /tmp/amazon-first-handoff.json
.venv/bin/python -m pytest tests/test_amazon_targets.py -q
.venv/bin/python -m app.amazon_targets --metrics --database /tmp/amazon-first-pilot.sqlite3
```

There is deliberately no live command to run yet. A future authorized runner must
reuse private terminal entry, disable core dumps, reserve attempts before key
access, and persist only allowlisted normalized evidence and numeric usage. No
credentials in chat, reports, shell arguments, exception messages or Sheets.
The export honors only the existing `MINIMUM_PROFIT` and `MINIMUM_ROI` environment
thresholds, with optional `--minimum-profit` / `--minimum-roi` overrides. It does
not load production configuration or credential files. Both defaults remain 5/50.

Sample target: fictional `amazon:ATVPDKIKX0DER:B000000001`, brand Fictional Kitchen,
model DEMO-1, blue/10 inch/single pack, two uncertain UPCs (`012345678905`,
`036000291452`), cached price $29.99 and rank 25,000; seller eligibility, fees,
current sale price and acquisition ceiling all null. The command emits its full
target revision and job, beginning with both UPC queries, model and wording
fallback. `sample_data/amazon_first_expected.json` is the reproducible sanitized
output, including proposed tab rows; it contains no real browser findings.

## Measurement

`TargetStore.metrics()` reports query attempts (each actual retailer query is one
search), distinct independently exact/profitable job counts divided by query
attempts, all five outcome counts, summed active search seconds, known cost and
total cost only when complete. Multiple observations/reevaluations do not inflate
the distinct match numerators. Refreshes are separately retained and queries
under them contribute to the denominator. Browser elapsed time is operator/browser
reported, not an application timing assertion; measure end-to-end wall time from
first target preparation to final adjudication separately. Keep provider tokens,
monthly API subscription allocation and browser/AI expenditure as separate run
costs until measured; never infer dollars from tokens without an approved tariff.

Preparation: **0 live requests, 0 tokens, 0 retailer searches; match rates and live
elapsed time unmeasured.** Costs for a future API subscription are unknown. The
fixture demonstrates persistence/contracts only, not sourcing yield. Compare
exact matches/search, profitable matches/search, search seconds/match and total
incremental dollars/profitable match against the preserved retailer-first flow.
