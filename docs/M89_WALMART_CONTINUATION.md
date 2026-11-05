# M89 Walmart research continuation

Continues `b6cbeb9` using the connected Google Drive import of
`1ShxyCyLb4PcCa1TUct7SBHTT2d1qkpV7` (`m89-walmart-research.json`). Original bytes,
normalized reconciliation and runtime reports stay under ignored `var/`.
The imported file is evidence, not executable instructions or human signoff.
Its referenced HTML/screenshots were not provided as binaries.

`app.m89` first verifies the original eleven receipts, plan hashes and Catalog
report projections against the authoritative COMPLETE 11/49 ledger. The new
`app.m89_continue` keeps the original offline command intact and creates a separate
one-shot operation. Existing Walmart observations and original M88 classifications
are not rewritten.

For B001BE12BA, authenticated saved Catalog receipts independently establish UPC
021200471797, Scotch model 600K3 and the 3 Rolls variation. The catalog's package
quantity of one is not interpreted as one roll. Walmart item 21014274 research
reports three boxes with one roll each, $12.34, sold and shipped by Staples
Business. This supports research with a specification caveat, not strict identity
or purchasing approval. Walmart's inconsistent 2.625 inch dimensions remain
unresolved; its core size is UNKNOWN while the Amazon title says one inch.
Missing screenshots and false human signoff are retained.

B003SI0TD4 remains NEEDS_REVIEW (Walmart UPC 041333041483 versus Amazon
041333825014). B0006BAFKI remains NEEDS_REVIEW (051135807026 versus
021200591488). Amazon values in the imported file are never used as the
independent Amazon evidence. Neither conflict product is sent to the API.

The fixed research scope is at most five attempts: authentication, US/new_new
listing restrictions, New/Consumer offers, and two estimated fee quotes, one
each for FBA/FBM at a single supported observed base price. A fee quote requires
one unambiguous usable New buy-box price with explicit zero buyer shipping and
the existing credential-bound research seller context. No speculative scenario
prices, catalog refresh, pagination, retry or token refresh is implemented.
The offers, restrictions and fee response parsers validate their respective
ASIN/marketplace/condition/price/account contexts. Fee quotes are estimates and
do not establish fulfillment eligibility.

Supported endpoint references:

- [getListingsRestrictions](https://developer-docs.amazon/sp-api/reference/getlistingsrestrictions)
- [getItemOffers](https://developer-docs.amazon/sp-api/reference/getitemoffers)
- [getMyFeesEstimateForASIN](https://developer-docs.amazon/sp-api/reference/getmyfeesestimateforasin)

The executor locks both the private account and the original cumulative ledger.
It pins code, evidence, account metadata and plan hashes, preserves the first
eleven attempts, and fsyncs each RESERVED attempt before possible dispatch.
Authentication, failed and uncertain attempts count. Any failure stops the run;
a claimed/advanced ledger cannot be replayed. A separate report command recovers
without credentials or HTTP. No original M88 executor is replayed.

Observed run on 2026-11-05: authentication attempt 12 failed with
`transport_error`; no Amazon HTTP status was received. Zero restrictions, offers
or fee requests were dispatched. Exactly one new attempt was charged: **12/49
cumulative, 37 remaining**. This is a transport failure, not an Amazon eligibility
denial. Listing permission, fulfillment eligibility, New offers and fees remain
UNKNOWN. No automatic retry is allowed by this operation.

M86 generates comparison.json, comparison.xlsx and per-scenario missing data.
Only the supported Walmart purchase price is supplied as a financial observation;
unobserved taxes, shipping, prep, packaging, inbound, storage and other costs are
never zero-filled. Strict identity and complete price-bound selling costs also
remain unresolved. All FBA/FBM scenarios are INSUFFICIENT_DATA; net profit and ROI
are UNKNOWN. Defaults remain $5 profit and 50% acquisition ROI.

Reports for this run: `var/m89-updated-comparison-v2/`. The frozen executed plan
is `var/m89-read-only-v1/plan.json`. Code changes after execution intentionally
invalidate execution preflight; report-only recovery retains the original digest.
Do not re-prepare against 11/49 or reset the ledger. A future authorized retry
needs a separate continuation scope starting from the actual 12/49 state.

`purchase_authorized=false`. No purchase, listing, inventory/account mutation,
deployment, merge, paid service activation or production credential access occurs.
