# M96 retail arbitrage discovery

M96 is exclusively retail arbitrage through Walmart or other authorized retail
channels. It implements no wholesale sourcing, approval applications, account
submissions, purchases, listings, inventory changes or live API transport.

## Historical evidence and separate states

M96 reads the 1,397-ASIN M79 catalog, M69 history, completed M94 report, all retained
M95 reports and the merged M95 historical attempt/reservation audit. Every previously
tested ASIN is excluded, including failed attempts and permanent reservations. M79's
checked/excluded flags and historical eligibility arrays also block selection.
Inputs are read only. Original reports and authorization records are never rewritten.

`M96_eligibility_history.json` derives each retained nonmock M95 row using the existing
`m95_decision` classifier. The ten current live results are all APPROVAL_REQUIRED.
Listing eligibility, FBA eligibility, identity and profitability remain separate
fields. Empty restriction responses remain NO_RESTRICTIONS_REPORTED, not verified
listing permission. M95 classifications and parser semantics are unchanged.

## Registry and discovery

`data/m96/brand_registry.json` records user-reported OXO, 3M and Wera brand approval
observations for the current user's account context, US marketplace and New
condition. These are dated seller-specific observations, not permanent universal
bans. Original screen dates and ASINs were not supplied; receipt date is explicitly
identified as a substitute. OXO's reported manufacturer/distributor invoice
requirement (200 units within 180 days) is retained only as restriction evidence.
M96 does not seek such invoices or implement an application workflow.

Brand-scoped adverse observations lower priority by 200 points. They do not ban a
brand universally or grant permission to any other brand. A new positive ASIN
observation cannot establish brand-wide permission. All observed ASINs are excluded
from new discovery queues, including positive observations. The registry preserves
conflicting observations rather than silently declaring a brand open.

Selection admits only the explicit simple-accessory category allowlist and excludes
risk terms in title/category/product type (including batteries, aerosols, chemicals,
ingestibles, medical/infant products, blades and magnets). Recorded identity conflicts
are excluded. This conservative text/category triage is not compliance clearance;
undisclosed hazards and inaccurate catalog descriptions remain possible.

Ranking gives 100 points for verified identity, 5 per available identity field
(maximum 50), and 25 for allowed simple categories. At most two ASINs per normalized
brand and five per category preserve diversity; neither diversity nor an open
category establishes eligibility. Ties sort by ASIN. Up to 30 ASINs are returned;
short queues are valid. Summary fields explicitly disclose candidate and verified
identity shortfalls. Unverified identities remain research leads, never fabricated
verified matches. Current output: 30 leads, zero verified identities.

## Offline CLI and Seller Central template

From the checkout root with Python 3.12:

```bash
.venv/bin/python -m app.m96 --output var/m96-retail-review-final
```

Use a new output directory. Exclusive creation prevents overwriting previous reports.
Outputs are `M96_candidate_queue.csv`, `M96_screening_template.csv`,
`M96_registry.json`, `M96_eligibility_history.json`, and `M96_summary.json` with input
SHA256 fingerprints and historical audit inventory. Runtime reports remain untracked.

The screening CSV contains ASIN, brand, marketplace, condition,
`seller_central_outcome`, `approval_scope`, `approval_reason`, `evidence_date`,
`reviewer_notes` and `evidence_source`. Supported outcomes are SELL_THIS_PRODUCT,
APPROVAL_REQUIRED, NOT_AVAILABLE and UNKNOWN. Scope is ASIN unless the observed
screen explicitly establishes BRAND scope. Completed rows require a timezone-aware
date and evidence source; blank outcome rows are skipped. Reviewer notes retain
uncertainty. Keep account identifiers, credentials and private screen URLs out of
all fields. No submissions or screening are performed by this CLI.

```bash
.venv/bin/python -m app.m96 --observations /path/to/completed.csv --output var/m96-retail-after-screening
```

This creates a new derived registry and queue without editing input evidence.
SELL_THIS_PRODUCT is a dated ASIN-specific observation, not execution authorization.
No permission is inferred solely from a brand, category, GTIN or empty API response.

## Offline FBA eligibility adapter

`app/m96_fba.py` exposes pure request specification, conservative response parsing,
and explicitly labeled mock fixtures. There is no transport or credential loader.
Amazon's official [operation reference](https://developer-docs.amazon/sp-api/reference/getitemeligibilitypreview)
and [API model](https://github.com/amzn/selling-partner-api-models/blob/main/models/fba-inbound-eligibility-api-model/fbaInbound.json)
define GET `/fba/inbound/v1/eligibility/itemPreview`, ASIN, a single US marketplace
in `marketplaceIds`, and `program=INBOUND`.

The parser binds response ASIN, marketplace and program. Errors, malformed types
and contradictory positive responses return UNKNOWN. Explicit boolean results
produce ELIGIBLE_PREVIEW or INELIGIBLE_PREVIEW. A mock wrapper always carries
`is_mock=true`; mock evidence cannot pass the retail profitability framework.
FBA previews have no New-condition field and never establish listing permission,
shipment acceptance, account capacity or profitability. Future transport needs
separate explicit approval and M95-style budgets, scope, interruption accounting,
provenance, freshness and response limits. No live adapter is enabled here.

## Retail profitability evaluation

`app/m96_profitability.evaluate(record, now)` reuses `app.profitability.analyze` and
its acquisition-cost ROI denominator, without modifying the legacy formula.
Input has ASIN, US marketplace, `new_new`, `channel=AUTHORIZED_RETAIL`, and an
`evidence` mapping. Each entry requires `value`, `status=VERIFIED`, `source`,
timezone-aware `observed_at`, matching ASIN/marketplace/condition and `is_mock=false`.
Evidence must be no older than 24 hours and cannot be future dated. Listing and
FBA entries also require the same nonempty opaque `seller_scope_reference`; this
reference must not contain the seller ID. The evaluator does not authenticate
asserted evidence: a human must independently verify provenance and retail authority.

Required values are `exact_product_variant_pack_match=true`,
`listing_permission=SELL_THIS_PRODUCT`, `fba_inbound=ELIGIBLE_PREVIEW`,
`retail_acquisition_cost`, `amazon_selling_price`, and every existing COST_FIELDS
entry: referral fee, fulfillment (FBA) fee, inbound shipping, preparation, packaging,
sales tax, other cost, storage and transaction cost. Explicit verified zero costs
are allowed; absent or uncertain costs never default to zero. Complete evidence
produces net profit and acquisition ROI using Decimal. At least $5 and 50% are
required for MANUAL_REVIEW_ONLY; otherwise BELOW_THRESHOLDS. Missing or uncertain
evidence yields BLOCKED_MISSING_EVIDENCE with no profit calculation. All outcomes
keep purchase and listing authorization false. No model result is a purchase
recommendation; availability, demand and current account/compliance conditions
still require manual review.

## Validation

See [M96 summary](M96_SUMMARY.md) for the exact queue, input fingerprints, test
results and remaining limitations. No live execution, merge or deployment is part
of this milestone.
