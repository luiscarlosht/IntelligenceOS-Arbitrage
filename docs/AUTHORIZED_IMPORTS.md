# Authorized-source CSV field guide

Start with [the header-only CSV template](../templates/authorized_products.csv).
For the Amazon source plan, supply ten product rows. Use UTF-8 CSV with the exact
header order; quote commas/newlines and preserve GTINs as text, including leading
zeroes. Keep the populated file in a private ignored directory such as
`var/private/products.csv`. No Amazon fees or seller eligibility are required to
import products. The template deliberately has no columns for those fields.

| CSV field | Initial source ingestion |
| --- | --- |
| `retailer` | Retailer or supplier name. |
| `name` | Source product name. |
| `url` | Permitted HTTP(S) source product URL, without credentials or signed access tokens. It is not fetched. |
| `gtin` | Valid check-digit GTIN; required unless both manufacturer and model are supplied. Keep as text. |
| `manufacturer` | Required with `model` if GTIN is absent; otherwise optional, useful for cross-checking. |
| `model` | Exact manufacturer model; required with manufacturer if GTIN is absent. |
| `package_quantity` | Positive integer number of items in the package being purchased. |
| `purchase_price` | Positive USD price for that source package, decimal amount without `$` or commas. |
| `availability` | Use `in_stock` only when confirmed. Unknown/out-of-stock remains flagged. |
| `retrieved_at` | Original timezone-aware ISO-8601 source observation time, e.g. `2026-10-27T12:00:00+00:00`. |
| `provenance` | Actual authorized export/feed and collection method. |
| `asin_hint` | Optional; leave blank if unknown. A hint proves neither identity nor eligibility. |
| `variation` | Exact source size/color/style; a documented standard designation only if it actually applies. |
| `authorization_reference` | Nonsecret locator for the owner's private permission/export record. |

All columns must be present, even optional ones. Missing or uncertain source
values stay blank or explicitly unknown and receive findings; never invent
values to pass validation. Valid source evidence above is required for a clean
source preflight and later fee planning. The offline ten-row planner retains
incomplete source rows with reasons. Malformed headers or a row count other than
ten are structural errors, rather than reportable ten-product plans.

The owner must verify permission for internal analysis and retain the agreement
privately. Software cannot verify rights from a populated reference field. Do
not include credentials, personal customer data or agreement text in the CSV.

Run the source-only preflight:

```bash
.venv/bin/python -m app.authorized_imports var/private/products.csv
```

Exit zero means the supplied source fields passed checks; it says nothing about
Amazon matching, fees, eligibility, profitability or purchase approval. Nonzero
reports source issues, including missing/invalid evidence, unknown stock, future
or stale timestamps (24 hours), malformed headers or empty input. Its JSON omits
input values and supplies corrective actions. Do not relabel old timestamps as
fresh. The general validator supports up to 10,000 rows; this source plan uses ten.

## Evidence collected after ingestion

| Later stage | Evidence and responsibility |
| --- | --- |
| Amazon catalog matching | Obtain catalog identity/ASIN and compare source GTIN or manufacturer/model, package quantity and exact child variation. Unmatched/ambiguous stays visible. |
| Amazon pricing | Obtain New/Consumer observations, currency, timestamp, counts and coverage. Partial or missing pricing remains flagged; competitor prices are not the seller's sale quote. |
| Amazon seller restrictions | Obtain the authorized seller's US/new_new restrictions and reasons. Unknown remains unknown; a catalog match never establishes eligibility. |
| Overall/FBA eligibility | Obtain independent seller/FBA evidence. No listing restrictions alone is insufficient; unknown remains a blocker for fee planning and sourcing. |
| Fee scenario selection | Operator explicitly selects a positive USD listing price per candidate, with price basis; the prepared scenario is FBA with $0 buyer shipping. This is not an ingestion requirement. |
| Amazon estimated fees | Only suitable candidates at selected prices qualify for a later estimate. Retain referral/fulfillment fees, total, scenario and timestamp; missing fees stay null, never zero. |
| Other costs and demand | Obtain source tax, inbound shipping, preparation, packaging, storage and other costs from the responsible source/operator; obtain supported demand/competition evidence separately. Amazon fee estimates do not fill every cost. |

Source rows can be imported and persisted before any of these later values are
known. Supply empty local catalog/pricing/restriction/price mappings to
`amazon_source_plan.prepare` for an initial intake; it preserves all ten rows,
with missing enrichment reasons and no fee requests planned. Its seller reference
is a nonsecret local account alias, not a requirement to supply eligibility.

Live requests remain disabled. The prepared API reuses SQLite evidence/history
and Excel reporting. Rejected, restricted, unmatched, partial and missing-data
rows remain visible; unknown costs and eligibility continue to block sourcing
recommendations. B0G1MJ24B4 retains its NOT_ELIGIBLE exclusion. Nothing here
approves a purchase. See the [workflow and request budget](AMAZON_AUTHORIZED_SOURCE_WORKFLOW.md).

The populated `sample_data/authorized_source_sample.csv` is fictional, not an
authorized supplier dataset. Do not edit mock fixtures to make an import pass.

## One real source row: offline intake

Use the same header-only template with exactly one supplied product row. Leave
missing fields blank. No Amazon data, seller alias or fee price is required:

```bash
.venv/bin/python -m app.amazon_source_intake \
  --source var/private/one-source.csv \
  --output-directory var/private/one-source-intake
```

This explicit one-row mode reuses the existing planner, SQLite observations/run
history and Excel report. It preserves the input file and persists the normalized
supplied values and missing-field reasons. It never pads to ten rows, substitutes
a sample product, invents stock/timestamps or replaces unknown money with zero.
A structurally valid incomplete row is persisted as rejected/pending evidence;
the CLI reports source findings and later missing information. Invalid headers
or a row count other than one stop before persistence. The ten-row API default
is unchanged. Avoid reusing the ten-row report directory for this intake.

Proposed later ceiling for one product is 1 authentication + 1 catalog lookup +
1 pricing + 1 seller-restriction request, with at most 1 additional fee estimate
only after all suitability gates and an explicit price selection. No fee estimate
is currently planned from source-only intake. Actual Amazon requests remain
zero; missing/invalid source identity or authorization must be resolved before
request authorization. Unmatched products skip downstream pricing/restrictions/
fees. Unknown eligibility, other costs and FBA evidence remain visible blockers.
FBA eligibility may need additional independent evidence outside this five-attempt
ceiling; the restriction response does not establish it.

For the prioritized Walmart pilot, use [the header-only Walmart extension](../templates/walmart_observation.csv)
and [specific access/observation instructions](WALMART_ACCESS_NEXT_STEP.md). It adds seller,
item ID, explicit ZIP 76063 and fulfillment/shipping context to the original columns.
The same offline intake command accepts either exact header format.
