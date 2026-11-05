# M87 — Walmart evidence integration (offline)

Based on main `1dd89bd` / PR86. `app.walmart_evidence` imports six original
candidate IDs and observations, emits `walmart_product_analysis_input_v1`, and
calls `app.product_analysis.comparison` and `workbook`. No independent economics
engine, workbook publisher, production job or purchasing policy is introduced.
Default thresholds remain $5 profit, 50% acquisition ROI, 30 supported monthly
units and at most 10 supported New offers. Financial analysis is independent of
seller eligibility. Purchase authorization is always false.

## Recovery findings

M86's distinct populations were rechecked locally. The four source byte hashes
still match. See `M87_RECOVERY_INVENTORY.json` for paths, SHA256 and filesystem
mtime nanoseconds; originals retain their embedded timestamps and identifiers.
The zero-result browser observation explicitly records an access blocker. The
10-product comparison has 8 ambiguous / 2 unmatched pairs; the 8-product shortlist
has no verified six-member selection; the five-product audit has no sixth member.
The separate twenty-ASIN Amazon cohort establishes no Walmart batch membership.
Original six recovery remains INCOMPLETE, zero reliably recovered. No authentic
six-product report can currently establish a business winner. This is a bounded
local finding, not a claim about inaccessible external workspaces. No source file,
SQLite history or workbook was migrated or edited.

## Capability map and evidence flow

| Existing module | Reused capability / limitation |
| --- | --- |
| `sheets_intake.product`, `validate_raw` | Existing Walmart Agent text export consistency, item URL, timestamps, acquisition price. No Sheets read or write needed. Package identity is unverified. |
| `amazon_catalog.parse_catalog` | Catalog identity/relationships; title similarity alone is insufficient. |
| `amazon_details.parse_pricing`, `amazon_offer_coverage` | New offer scope, Featured Offer/lowest-price context, detail/summary coverage. Total mixed counts cannot become New-only competition. |
| `amazon_details.parse_fees` | Seller/ASIN/mode/price-bound referral and FBA aggregate estimates; missing components stay absent. FBM fulfillment remains merchant shipping/handling input. |
| `amazon_pilot`, `amazon_pacing` | Existing TLS/authentication and bounded pacing, audited without reading credentials. Prior authorization is not M87 permission. |
| `m80_contract` | Prior exact request-list pattern; its 20-ASIN authorization and state are not reusable for M87. |
| `product_analysis`, `analysis_engine`, `m66_opportunity` | Exact identifiers/pack/variant, 24-hour evidence quality, Decimal financial math, scenario order and provenance, six-sheet safe reports. |

Saved evidence is supplied in the explicit `walmart_pilot_batch_v1` format shown
in `sample_data/m87_synthetic_batch.json`. All six rows in that file are fictional
format examples, including identifiers, quotes and fees. Never use them as source
observations. `batch_kind` is NEW_PILOT or SYNTHETIC_DEMO, never historical recovery.
The full content SHA256 produces a deterministic unique batch ID. Identical
imports produce the same ID without inserting database rows. Changing content
produces a different batch; an explicit mismatching ID is rejected.

Each row retains `source_candidate_id`, `walmart_product`, `acquisition` and
optional `amazon`. Walmart identity includes item ID, URL, title, brand, GTIN/UPC,
model, size, pack quantity and variation, with original timestamp/reference.
Acquisition contains item price, retailer shipping, tax, inbound, preparation,
packaging and other acquisition costs. `other_cost_basis` must explicitly exclude
retailer shipping: M86 adds shipping once. Amazon supplies exact ASIN/product,
market/eligibility observations and FBA/FBM conservative/base/optimistic scenarios.
Every monetary observation uses M86 attribution metadata. Copying a quote across
scenarios is allowed only when that same price and cost basis is actually supported;
missing prices or price-specific fees are never extrapolated. UNKNOWNs remain
visible. Assumed values cannot support confident classification.

Repeated or contradictory acquisition values in Amazon scenarios and explicit
`conflicting_observations` block classification, rather than selecting a convenient
value. M86 checks cross-product identity, variant, pack, fee price basis and stale
prices. Original row hashes accompany normalized records; the immutable source
batch is pinned by byte SHA256 and retained in source inventory. Do not delete it.

For existing Walmart Agent exports, wrap six saved text rows matching
`sheets_intake.FIELDS` in `{"schema":"walmart_agent_saved_export_v1","rows":[...]}`.
The importer reuses existing raw/export validation and preserves `record_id`, raw
JSON, batch IDs and observed/exported timestamps. It never upgrades missing
GTIN/model/quantity or reviewer confidence. These records enter M86 incomplete;
attach independently verified identity/cost observations in a new reviewed batch.

Fresh collection follows the **same saved-export interface** after separate owner
approval of six exact Walmart URLs and the Agent's permitted access method. The
Agent remains externally operated; M87 does not invoke it or bypass its access
blocker. Save the resulting six-row export privately and run the offline importer.
This supports old and newly saved observations without silently replacing originals.

## Amazon preview and approval boundary

`execution-preview.json` identifies every candidate and ASIN, US marketplace
ATVPDKIKX0DER, condition New, exact endpoint, request body, price-bound fee scenario,
permissions, private destination, conservative pacing, zero retries/refreshes/
pagination, timeout, cost uncertainty and stop conditions. Six fully populated
candidates require at most 49 HTTP attempts: 1 LWA + 6 Catalog + 6 offers + 36 fees.
Missing ASINs are unresolved and missing fee-price bases produce no fee request.
The preview is a proposal; an unresolved variant blocks execution even if an ASIN
is supplied. Fees assume zero buyer shipping, explicitly present in every request;
nonzero buyer shipping requires a new reviewed preview and fee basis.

Before live execution the owner must approve the **exact preview SHA256**, account,
resolved variants, current permissions/rates/costs, expiration and concrete private
storage path. No approval flag in an input file can enable M87: `execute_live`
unconditionally refuses, and no transport/credential lookup is registered. A
separately reviewed executor must bind that approval, reserve a durable no-replay
budget before each attempt, pin raw receipts/hashes and stop on scope drift or
errors. This milestone delivers collection planning and offline ingestion, not a
live executor. Prior M80 and credential possession grant no permission.

Official endpoint references checked during implementation:
[Catalog](https://developer-docs.amazon/sp-api/lang-en_US/reference/getcatalogitem),
[New offers](https://developer-docs.amazon/sp-api/lang-de_DE/reference/getitemoffers),
[Fees roles and estimates](https://developer-docs.amazon/sp-api/lang-en_EN/docs/product-fees-api).
Actual role entitlements remain unverified. Fees API requires an applicable role
such as Amazon Fulfillment; the owner must verify all operation roles before approval.
[Amazon's developer fee cancellation announcement](https://developer.amazonservices.com/cancellation-of-sp-api-fees)
means earlier third-party fee announcements must not be assumed current; estimated
account-specific costs remain UNKNOWN pending review. No subscription is enabled.

## Provider gaps

Catalog ranks and current New offers/Featured Offer context are snapshots, not
monthly unit sales. Seller-authorized sales describe that seller's history, not
competitor demand. Mixed offer totals and rank-derived units are unusable market
threshold evidence. Historical prices, volatility, historical New competition and
rank trends remain UNKNOWN unless independently attributed saved evidence exists.
Repeated approved snapshots could establish forward history, not reconstruct past
history. Keepa could materially improve price/rank/offer-history risk assessment,
subject to exact variant, New-condition series semantics, coverage and a separately
approved plan. Its demand indicators/estimates would still need basis and validation;
no guaranteed competitor monthly unit sales are assumed. Existing dormant Keepa
code is not activated. No paid pricing/coverage guarantee or subscription is made.

## Local and DigitalOcean verification

After a separately approved installation, run these commands from the reviewed
checkout on Ubuntu 24.04 with its existing venv. They require no provider credentials
and make no live calls. Do not deploy as part of verification.

```bash
PY=/root/IntelligenceOS-Arbitrage/.venv/bin/python
$PY -m pytest -q tests/test_walmart_evidence.py tests/test_product_analysis.py
sha256sum sample_data/m87_synthetic_batch.json
# Use that exact digest below; choose a fresh output outside the source directory.
$PY -m app.walmart_evidence --input sample_data/m87_synthetic_batch.json \
  --sha256 <digest> --output /tmp/m87-synthetic-review \
  --as-of 2026-11-03T16:00:00+00:00
$PY -m pytest -q
```

The fixed clock is only for synthetic reproducibility. Real observations must be
evaluated at current UTC; do not rewind the clock to hide stale evidence. Outputs
are exclusive directories 0700 and files 0600: normalized JSON, execution preview,
M86 comparison JSON and six-sheet Excel. Input drift/duplicate JSON keys, unsafe
paths and overwrites fail. Excel cells retain formula safety and size limits;
oversize evidence aborts publication, never truncates source data. Inspect six
ILLUSTRATIVE results, UNKNOWN eligibility and `purchase_authorized: false`.
No reports/private source artifacts are committed. No VM verification is claimed.

The infrastructure can compare six products financially when exact fresh evidence
and complete scoped costs exist. The synthetic demonstration proves the pipeline,
not a real arbitrage opportunity. The remaining operational work is approved source
collection, exact-match review, complete acquisition/fee receipts and supported
market/history evidence.
