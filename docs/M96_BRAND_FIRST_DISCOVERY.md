# M96 brand-first discovery

M96 creates an offline manual research queue from M79, M69, completed M94/M95
reports and the merged M95 historical attempt audit. Every checked ASIN is excluded,
including failed attempts and permanent reservations. M79's checked/excluded flags
and historical eligibility arrays also block selection. Historical files are read
only. No category, UPC match, empty restriction response or unobserved brand proves
seller permission. M95's conservative classification remains unchanged.

## Registry and manual screening

`data/m96/brand_registry.json` is versioned input evidence, not an authorization
record. OXO, 3M and Wera are brand-scoped approval-required observations supplied
by the user. No ASIN was supplied, so the ASIN field is empty. The date is the task
receipt date, explicitly distinguished from the unknown original observation date.
The OXO manufacturer/distributor invoice requirement is at least 200 units purchased
within 180 days. Requirements for 3M and Wera are unknown. These requirements are
account observations, not universal Amazon policy. Retail receipts are not assumed
to meet manufacturer/distributor invoice requirements.

Run from the checkout root with Python 3.12:

```bash
.venv/bin/python -m app.m96 --output var/m96-offline-review
```

Output directories must be new; reruns never overwrite evidence. Outputs include
`M96_candidate_queue.csv`, `M96_screening_template.csv`, `M96_registry.json` and
`M96_summary.json`. Runtime reports are deliberately untracked per repository policy.
The summary records input SHA256 fingerprints and the historical audit inventory.
No seller-account identifiers or credentials are needed.

For each template row, record the exact New-condition Seller Central screen:
`Sell this product`, `Apply to sell`, or `Not available` in `observation`.
Record `approval_requirements`, `invoice_requirements`, `evidence_source`, a timezone
aware `observed_at`, and `restriction_scope` (`ASIN` normally; `BRAND` only when the
screen explicitly names the brand). Keep credentials and account identifiers out
of evidence references. Blank observation rows are skipped; malformed completed
rows reject the import. Approval requirements remain independent text fields.

```bash
.venv/bin/python -m app.m96 --observations /path/to/completed.csv --output var/m96-after-screening
```

Imports produce a new derived registry; they do not edit the versioned seed or
historical evidence. Every observed ASIN is removed from subsequent new-candidate
queues, including positive observations. A positive observation must be ASIN scoped;
it never grants permission to the rest of its brand. Contradictory negative brand
observations conservatively continue to block that brand pending manual review.
No observation is a production authorization.

Ranking gives 100 points for verified identity, 5 per identity field (maximum 50),
and 25 for a small explicit set of simple accessory categories. Recorded identity
conflicts are excluded. Selection caps each normalized brand at two ASINs and sorts
ties by ASIN. Complexity is a research heuristic, not a regulatory determination;
uncategorized items remain UNASSESSED. There is no eligibility score based on category.
A shortage fails closed rather than relaxing the evidence gates.

## Separate FBA inbound adapter design

`app/m96_fba.py` exposes pure request specification and response parsing only.
Amazon's official [getItemEligibilityPreview reference](https://developer-docs.amazon/sp-api/reference/getitemeligibilitypreview)
and [API model](https://github.com/amzn/selling-partner-api-models/blob/main/models/fba-inbound-eligibility-api-model/fbaInbound.json)
define `GET /fba/inbound/v1/eligibility/itemPreview` with `asin`, `marketplaceIds`
and `program=INBOUND`. The spec supplies the US marketplace; future approved
transport must encode the marketplace list according to the official model.

The parser binds response ASIN, marketplace and program; errors, malformed types
and contradictory positive responses return UNKNOWN. Explicit boolean results
produce ELIGIBLE_PREVIEW or INELIGIBLE_PREVIEW. Unknown reason strings do not become
permission. This API preview has no condition field and does not establish New
listing permission, approval status, shipment acceptance, capacity or profitability.
No network client, credentials loader, retry loop or execution command is supplied.

A future live adapter needs separate explicit approval, reviewed account context,
freshness and provenance, request budgets, exact host/path allowlists, response
limits, interruption accounting and read-only evidence persistence under M95-style
controls. Its evidence must remain separate from Listings Restrictions and manual
Seller Central evidence. No live request is authorized by this milestone.

## Walmart and profitability gates

After a fresh seller-specific positive New-condition observation and independent
FBA inbound evidence, confirm Walmart's exact GTIN/model, pack, variation and current
local availability. Collect fresh landed acquisition costs, fees, inbound freight,
preparation, storage, tax, demand and competition evidence. Missing inputs block
selection; fees never default to zero. Preserve $5 net profit and 50% acquisition
ROI defaults. No M96 row establishes a Walmart opportunity or authorizes purchase,
listing, an approval application or shipment.
