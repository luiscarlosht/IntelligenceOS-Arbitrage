# Analysis engine MVP

Workbook routing and preview schema are superseded by
[canonical workbook integration](CANONICAL_ANALYSIS_WORKBOOK.md). Use its current
read-only verification commands; historical acceptance below describes PR83.

## Existing functionality assessment (before implementation)

PR 82 is merged. Its `amazon_evaluation` already supports FBA/FBM, three price
scenarios, all required expense components, Decimal profit/margin/acquisition ROI,
conditional fixed-fee break-even, missing fields, freshness and identity checks,
approval precedence, documentation/demand/competition gates, and synthetic review.
`profitability.analyze` is the shared formula; do not copy it. Its $5/50 defaults
are currently hardcoded in the evaluation wrapper, so add optional configuration
without changing existing callers. Baseline focused evaluation/publisher/identity
suite: 172 passed. Full baseline suite also started before new implementation.

`amazon_evaluation_sheets` already reads the manual JSON column, preserves
researcher rows, checks visible eligibility conflicts and reuses QueueClient and
literal-cell index/update helpers. It seeds evidence, but does not publish computed
analysis. Add separate ASIN-keyed analysis output; never rewrite original tabs.
`observations` provides canonical JSON/fingerprints and private SQLite persistence;
`decision_history.database` provides a validated append-only hash chain and rejects
unrelated schemas without migration. Reuse that database/chain for optional new
analysis snapshots in a separate explicit file; never mutate historical ledgers.
`provider_contracts` already separates catalog, fee, eligibility and demand evidence.
Use a small normalized-input adapter protocol; do not add HTTP transports.

Gaps: configurable evaluation thresholds; attributed market summary including
manual historical stats and volatility; unified per-ASIN output/missing report;
manual Seller Central/Revenue Calculator/Keepa adapter seams; optional immutable
analysis snapshots; and preview-bound computed Sheets publication.

## Implemented contract

`app.analysis_engine.analyze_record(record, aware_time, EvaluationPolicy(...))`
reuses PR82 evaluation. The public purchase decision is BUY_CANDIDATE, REVIEW,
BLOCKED or REJECTED; detailed PR82 reasons remain in `detailed_decision`.
All non-ELIGIBLE statuses map to BLOCKED. Financials still run independently.
Defaults remain $5 net and 50% acquisition ROI. Both base and conservative must
pass; optimistic must be complete and prices must be ordered. FBA additionally
needs independent eligibility. Neither decision nor financial output authorizes
purchasing. Existing engine callers and discovery/sourcing remain unchanged.

Input is the existing PR82 JSON, optionally with `market` observations. Every
observation supports `value`, `source`, `observed_at` (aware ISO time), `confidence`
(HIGH/MEDIUM/LOW/UNKNOWN), `condition`, `basis`. Unknown confidence is never
inferred; original descriptive confidence labels remain in confidence_note.
Input evidence is retained and fingerprinted before gate normalization. `assumed:
true` labels hypothetical observations; any such assumption prevents BUY_CANDIDATE.
Assumptions still require source/time/currency and normal fee/price scope to run
math, and never substitute for observed eligibility or demand. Synthetic/mock
inputs retain their existing review restrictions.

Market keys: current_price, historical_30d, historical_90d, sales_rank, category,
monthly_sales, competing_offers, price_volatility. PR82 descriptive observations
are read without silently upgrading mixed Used/New offers or lowest displayed
price into New offer count or Buy Box price. Missing/stale values stay visible
with usable=false and diagnostics. A recent export of historical statistics is
required; a 90-day window does not make an old export current.

Demand gates accept New-condition attributed integer observations with basis
`authorized_sales`, `bought_past_month_lower_bound`, or `validated_estimate` plus a
nonempty model_validation_reference. Rank is never converted into sales. Offer
counts require New condition and basis `new_offer_count`. The inherited demand
and competition thresholds remain >=30 monthly units and <=10 New offers.
Confidence metadata is required for gate evidence; other unknown observation
confidence downgrades an otherwise passing report to REVIEW.

Historical statistics can hold `{min, max, mean}` with currency USD and a precise
price-series basis. If a fresh, attributed New 30-day range satisfies
0 < min <= mean <= max, range volatility is `(max-min)/mean * 100`. This is an
observed range, not a prediction or statistical standard deviation. There is no
automatic volatility risk cutoff and no sales-velocity inference.

All PR82 cost inputs remain per matched selling unit in USD. ROI denominator is
purchase + tax + inbound + prep + packaging + other acquisition (include retailer
shipping there). Referral, fulfillment, storage, placement, returns and transaction
costs are deducted once. Returns allowance is optional by explicit documented zero
when unconfigured; omission remains UNKNOWN, never an assumed zero. Break-even
holds supplied fees fixed, as in the existing engine; no fee rate is inferred.
Use fresh scenario-specific fee quotes for actual pricing decisions.

## Adapters and provider gaps

| Provider | MVP behavior | Missing metrics / future boundary |
| --- | --- | --- |
| Manual Seller Central / Revenue Calculator | ManualAmazon reads existing attributed PR82 JSON; no browser automation | Enter seller-specific eligibility, approval documents, New price, scoped FBA/FBM fee estimates and calculator assumptions. Unknown costs remain blocked. |
| Manual Keepa | ManualKeepa merges market-only patches by ASIN, rejects conflicting fields/unknown ASINs | Transcribe New-series 30/90-day stats, rank/category, offer counts and their observation dates. Does not edit fees, eligibility or sourcing. No subscription is required by this implementation. |
| Existing Sheets | SheetsEvidence uses the existing bounded Amazon_Evaluation reader/schema and detects visible eligibility/JSON conflicts | Existing records provide only what was entered. A publisher cannot supply missing market or seller facts. |
| Future authorized SP-API | Design only: implement AnalysisProvider.records, normalize into existing provider_contracts and PR82 fields | Product Pricing supplies price/offer information; Listings Restrictions supplies listing restrictions and approval next steps; Product Fees supplies estimates, not guaranteed actual fees. Authorization, seller/marketplace/condition scope and later enablement remain prerequisites. No HTTP adapter or selector is added. |
| Future Keepa API | Design only: normalize authorized product/statistics replies into the same market-only contract | Historical series/statistics, category/rank and offer data depend on available fields and rights. Do not treat an absent sales estimate as zero or turn rank drops into unit sales. Subscription/permission review is future work. |
| Retailer / merchant / seller | Manual evidence only; no sourcing changes | Current Walmart checkout price/tax/shipping, exact identity, prep/FBM costs, storage/placement planning and returns allowance require supplier/merchant/account evidence. Demand needs a supported signal or independently validated model; no service automatically verifies invoice acceptability. |

Official capability references checked 2026-11-03 (public documentation only):
[Amazon Product Pricing](https://developer-docs.amazon/sp-api/docs/product-pricing-api),
[Listings Restrictions](https://developer-docs.amazon/sp-api/docs/listings-restrictions-api),
[Product Fees](https://developer-docs.amazon/sp-api/lang-en_EN/docs/product-fees-api),
[Keepa product object](https://keepa.com/api-docs/product-object.html).
No Amazon/Keepa API request, key access, paid subscription or purchase occurred.
These are capability boundaries, not a promise that every metric exists for every
ASIN or that commercial use is authorized. No general monthly-sales estimation
model is installed. Missing data can be entered manually; buying a service is not
necessary to run analysis.

## Fiskars acceptance report

Input: existing `sample_data/amazon_evaluation_fiskars.json`.
Read-only connected Sheets evidence also matched this observation.

| Evidence | Evaluation |
| --- | --- |
| ASIN / brand | B000YZASYO / FISKARS |
| Lowest displayed Amazon price | $59.84; condition/New Buy Box not verified |
| Sales rank / category | 435 / UNKNOWN; no monthly sales inferred |
| Offers | 9 Used/New combined; New competing-offer count UNKNOWN |
| Eligibility / purchase decision | APPROVAL_REQUIRED / BLOCKED |
| Documentation | Manufacturer/distributor invoice, >=300 combined units; invoice dated May 7, 2026 or later; retail confirmations/invoices not accepted |
| FBA and FBM conservative/base/optimistic | Supported; all six incomplete until attributed acquisition, New selling-price scenarios and fee/cost inputs are supplied |
| Walmart price / Amazon fees / sales velocity | UNKNOWN; no invented inputs or hypothetical purchase candidate |

The report includes every financial missing field, market evidence summary,
approval requirements and purchase_authorized=false. Tests separately exercise
explicitly labeled fictional assumptions with the approval block still in force;
those numbers are not represented as Fiskars evidence. Reports are runtime files,
not committed historical records.

## Preview, history and publication commands

Offline read-only report (fresh output path required):

```bash
.venv/bin/python -m app.analysis --input sample_data/amazon_evaluation_fiskars.json --output /tmp/fiskars-analysis.json
```

Override thresholds with `--minimum-profit 7 --minimum-roi 60`. For manual Keepa
patches, add `--keepa-manual /path/to/manual-keepa.json` to local-input analysis.
Patch format: `[{"asin":"B000YZASYO","market":{"historical_30d":{"value":{"min":"UNKNOWN","max":"UNKNOWN","mean":"UNKNOWN"},"source":"UNKNOWN","observed_at":"UNKNOWN","confidence":"UNKNOWN","condition":"New","currency":"USD","basis":"New price 30d"}}}]`.
Unknown values remain unknown; replace them only with actual observations.
The adapter rejects conflicting existing market fields instead of silently
choosing a source. The JSON file must contain normalized manual observations,
not raw vendor responses or credentials.

Optional new analysis history, only when explicitly requested by the operator:

```bash
install -d -m 700 var/analysis-history
.venv/bin/python -m app.analysis --input sample_data/amazon_evaluation_fiskars.json --history var/analysis-history/analysis.sqlite3
```

This reuses the existing private SQLite hash-chain boundary, deduplicates exact
snapshots and only inserts new records. Existing updates/deletes are prohibited
by SQLite triggers. A legacy/acquisition database or a history containing another
payload type is rejected without migration. Default previews open no database.
Never point this option at production or preexisting acquisition ledgers.

The following exact DigitalOcean commands assume this PR's reviewed code has
already been installed through a separately authorized release. They deploy
nothing. Existing host, checkout and dedicated credential path are reused from
PR81/82; VM execution/effective service-account access is not tested here.

Read existing manual evidence and preview the complete proposed output batch:

```bash
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && ARBITRAGE_SHEETS_CREDENTIAL_FILE=/root/.config/intelligenceos-sheets/service-account.json .venv/bin/python -m app.analysis --sheets --sheets-preview --output var/analysis-preview-20261103-1.json'
```

After the owner approves that preview, publish it within fifteen minutes:

```bash
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && ARBITRAGE_SHEETS_CREDENTIAL_FILE=/root/.config/intelligenceos-sheets/service-account.json .venv/bin/python -m app.analysis --publish-preview var/analysis-preview-20261103-1.json --approved'
```

`--approved` is an operator assertion of prior approval, not a permission grant.
If approval takes longer or evidence/destination changes, regenerate a fresh
read-only preview under a new filename and review it again. The publisher
recomputes the preview, checks evidence freshness at publication time, checks
source/destination snapshots, writes one atomic batch and verifies readback.
Tampered/stale previews stop before writes. Only computed `Amazon_Analysis!A:K`
is upserted by ASIN. Custom columns, unrelated ASINs, Amazon_Evaluation and all
historical/research tabs are preserved. No clear/delete/sort requests exist.
Pause concurrent sorts/inserts/deletes and use one writer across hosts; the local
lock cannot lock other editors, and Sheets provides no arbitrary-cell CAS.
Ambiguous failures stop without retries/rollback; inspect and preview again.
Snapshots are bounded to 20,002 rows/4 MiB, batches to 1.8 MB, cells to 49,000
characters. Large inputs must use smaller explicit partitions. No automatic
purchase-ready opportunity list is written.

Local acceptance used the connected account to read `Amazon_Evaluation!A1:X2`
and current metadata, then generated the same pure analysis preview without
credential access or write calls. It proposed three requests (new output tab,
header, Fiskars row); no publication was performed. Existing Sheets and historical
records were left unchanged. Reports live under /tmp and are not committed.

Validation commands:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m app.orchestrator
ARBITRAGE_MODE=discovery ARBITRAGE_REPORT=var/discovery.xlsx .venv/bin/python -m app.orchestrator
```
