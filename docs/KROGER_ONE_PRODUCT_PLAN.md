# Kroger one-product pilot specification — NOT executable

Prepared 2026-10-27 UTC. This is a future request specification, not a real
observation, import file, stock check or purchase recommendation. The execution
budget is **zero** until the [access decision](KROGER_ASSESSMENT.md) is resolved.
No Kroger connector, credential loader or production selector is registered.

## Candidate and location

Candidate: **Barilla regular Spaghetti dry pasta, 16 oz**, intended one retail
box, not thin/whole-grain/gluten-free spaghetti or a multipack. This shelf-stable
branded product has barcode identity on the official
[Kroger-family product page](https://www.frysfood.com/p/barilla-spaghetti/0007680828008):
displayed retailer code `0007680828008`. That string fails our GTIN checksum
validation and must remain a retailer identifier, not be zero-padded or silently
repaired into a UPC. Obtain and checksum-validate the actual package barcode
before matching; the Amazon UPC parameter remains unpopulated pending that check. The public page is candidate identity research only;
its price, availability and default store are not observations for Mansfield.
Package quantity remains unknown until confirmed; “16 oz” is net size, not proof
of pack count. No ASIN or sale price is selected.

Use **pickup** at Broad St, 3300 E Broad St, Mansfield TX 76063 as the proposed
first context. The official [store page](https://www.kroger.com/stores/grocery/tx/mansfield/broad-st/035/00594)
identifies division/store `035/00594` and pickup. Candidate API location ID
`03500594` must be confirmed by the Locations response, not assumed from the URL.
Alternative [Matlock](https://www.kroger.com/stores/grocery/tx/mansfield/matlock/035/00584),
3001 Matlock Rd, also lists pickup; it would be a separate observation. ZIP is
not a store ID. No nearest-store distance ranking has been verified.

## Source request proposal, only after permission and separate authorization

One client-credentials token exchange, one bounded Locations lookup centered on
ZIP `76063`, and one Products lookup for the candidate with the confirmed
`filter.locationId`. No retries, pagination, cart, checkout, identity endpoint,
customer authorization or delivery-service probe. Confirm current request
parameters/scopes against the official reference before implementing. Three
attempts is a proposed ceiling, not a currently approved execution budget.
Stop on auth, permission, 429, wrong location or ambiguous package/identifier.

Preserve these separate fields in a future normalized contract:

| Evidence | Required handling |
| --- | --- |
| Identity | Original productId, UPC, itemId, brand/name, exact variant and normalized GTIN; preserve original strings. |
| Package | Exact item size/unit and independently confirmed retail pack count. Missing count/size remains unknown. |
| Price | Separate regular and promotional values, USD package basis, selected price and selection basis. Never choose the lower price automatically. |
| Conditions | Loyalty requirement, digital coupon, quantity/basket threshold, start/end dates, membership and fulfillment scope when explicitly evidenced; absence means unknown, not unconditional. |
| Location | Confirmed location ID, division/store, address, ZIP, pickup context and source request parameters. Never relabel pickup evidence as delivery. |
| Stock | Explicit stock status and its scope/time if supplied. Pickup/delivery capability flags are not inventory or available units. Missing stock stays unknown. |
| Time | Aware client retrieval time separate from source observation/update time; a request time does not prove the price/stock was updated then. Missing source time stays null. |
| Costs | Shipping/pickup/delivery charge and conditions stay unknown unless separately evidenced. No free-shipping or zero inbound-cost inference. |
| Permission | Nonsecret agreement reference, permitted storage/reporting purposes and deletion deadline. No credentials in provenance. |

No live data should enter SQLite, backups or Excel until permission covers all
three. Afterwards, implement a fixture-tested mapping into `RetailProduct`,
`source_context`, `ObservationStore` and the existing report enrichment boundary;
missing critical evidence must reject screening. Existing ordinary CSV intake
does not preserve arbitrary new columns, so do not use it to silently discard
regular/promo/loyalty/location fields. Connector contract tests are intentionally
deferred with the connector while contractual suitability is blocked.

## Subsequent Amazon proposal

Only a permitted, verified source observation may trigger this later plan. Use
the existing private US account and least necessary approved Product Listing /
Pricing roles, no customer PII roles. No credentials are read now.

1. One LWA refresh exchange; stop on failure.
2. One [Catalog Items search](https://developer-docs.amazon/sp-api/reference/searchcatalogitems):
   `GET /catalog/2022-04-01/items`, `identifiers=<verified 12-digit package UPC>`,
   `identifiersType=UPC`, `marketplaceIds=ATVPDKIKX0DER`,
   `includedData=summaries,identifiers,relationships,attributes`, `pageSize=10`.
   Verify actual source barcode first. Any pagination, multiple plausible ASINs,
   missing pack/size or parent/child ambiguity stops downstream requests. Do not
   convert one box to a multipack on a UPC match.
3. After exact identity/package/variation verification, one
   [restriction request](https://developer-docs.amazon/sp-api/reference/getlistingsrestrictions):
   `GET /listings/2021-08-01/restrictions`, verified `asin`, authorized `sellerId`,
   `marketplaceIds=ATVPDKIKX0DER`, `conditionType=new_new`. Preserve reasons and
   approval requirements. No restrictions is not independent overall/FBA eligibility.
4. If suitable, one [offers request](https://developer-docs.amazon/sp-api/reference/getitemoffers):
   `GET /products/pricing/v0/items/{asin}/offers`,
   `MarketplaceId=ATVPDKIKX0DER`, `ItemCondition=New`, `CustomerType=Consumer`.
   Preserve condition, shipping, fulfillment, price time and offer-count coverage.
   Competitor prices are not our selected sale quote or proof of demand.
5. Initially **zero fee calls**. Only after independent seller/FBA suitability
   evidence and one explicit sale-price selection, propose one
   [ASIN fee estimate](https://developer-docs.amazon/sp-api/reference/getmyfeesestimateforasin):
   `POST /products/fees/v0/items/{asin}/feesEstimate` with
   `FeesEstimateRequest={MarketplaceId: ATVPDKIKX0DER, IsAmazonFulfilled: true,
   Identifier: <unique scenario>, PriceToEstimateFees: {ListingPrice:
   {CurrencyCode: USD, Amount: <selected price>}, Shipping:
   {CurrencyCode: USD, Amount: 0}}}`. Shipping zero here is an explicit hypothetical
   FBA sale scenario, never source shipping evidence. Verify response identity,
   scenario and fee components; absent fees stay unknown. Catalog dimensions may
   differ from the actual shipped package, so this remains an estimate.

Proposed ceiling: four attempts initially, five with that conditional fee;
zero retries, second prices, pagination or fallback searches. Actual execution
budget remains zero. Honor operation-specific dynamic limits, reserve attempts
before calls and stop on authorization/rate-limit errors. Independent FBA,
food/expiration, authenticity/invoice, demand and complete acquisition-cost evidence
remain required and outside this request budget. Existing $5 profit / 50% ROI
gates and the retained B0G1MJ24B4 exclusion remain in effect.

The existing one-row `app.amazon_source_intake` and planner can later reuse
normalization, persistence and reporting once a permitted source row exists;
they do not execute this proposal or supply missing evidence. No populated
“real” row or mock replacement observation has been created.
