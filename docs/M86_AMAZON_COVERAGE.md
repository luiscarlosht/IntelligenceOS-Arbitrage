# M86 Amazon product-analysis coverage

Public documentation reviewed 2026-11-04 UTC; no authenticated request was made.
Documentation availability is **not** proof of account authorization. Existing
historical successful calls demonstrate only the operation/context/time recorded,
not present access, all products or a new endpoint. Credential permissions were
not inspected. Every product value still needs its own original observation time,
source/reference, ASIN, marketplace, condition, confidence and scope; this document's
review date is not a product timestamp.

Existing authentication: `amazon_pilot` LWA refresh flow, fixed US SP-API host,
verified TLS, no redirects/proxies, private credentials outside the repo, bounded
payload/deadline. Existing controlled tools use durable attempt accounting,
exclusive account locks, operation-specific pacing and separate owner authorization.
M86 calls none of them. Existing `OperationPacer` defaults are Catalog 2/s,
Pricing 0.5/s, Fees 1/s with 0.5 headroom (effective 1/s, 0.25/s, 0.5/s), sequential
operation, downward adjustment from response headers and Retry-After, and no
automatic retry. Do not replace these with the faster documentation defaults.
M80/other controlled pilots retain their own stricter pinned budgets and pacing.

The following notation identifies existing paths, not permission to execute:

- C: GET `/catalog/2022-04-01/items/{asin}`; search GET
  `/catalog/2022-04-01/items`. Default detail limit 2/s, burst 2.
  Required role: Product Listing. Dataset selection must be explicit.
- P: GET `/products/pricing/v0/items/{Asin}/offers`, US marketplace,
  `ItemCondition=New`, `CustomerType=Consumer`. Default 0.5/s, burst 1.
  Pricing **or** Product Listing role.
- F: POST `/products/fees/v0/items/{Asin}/feesEstimate`; default 1/s, burst 2.
  Pricing or Product Listing are sufficient role examples; the official mapping
  also lists other eligible roles. Supply seller/marketplace, price, shipping,
  currency and fulfillment choice. Existing tools estimate FBA; no general FBM
  carrier-cost endpoint is implemented.

Limits are documented defaults and may vary by application/seller pair. No new
request plan, reservation or live approval is created by this matrix.

| Analysis field | Source / endpoint | Permission / limit | Nature and existing support | Provenance / freshness and limitation |
| --- | --- | --- | --- | --- |
| Title, brand | C summaries/attributes | Product Listing; C | Direct Catalog observation; existing parser | Retain catalog ASIN, US dataset and time. Manufacturer is distinct from brand; missing attributes stay missing. |
| UPC / EAN / GTIN | C identifiers | Product Listing; C | Direct; normalized check-digit matching implemented | Retain literal identifier plus normalized GTIN; same identifier at different pack levels does not verify contents. |
| Model, size, pack, variation | C attributes + summaries + relationships | Product Listing; C | Direct when present; existing mapping with unresolved flags | Number of items, unit count, pieces and retail package count are distinct. Walmart counterpart requires independent evidence. |
| Current New selling prices | P New offers summary/details | Pricing or Product Listing; P | Observed listing/landed prices, not promised achievable proceeds; existing parser | Store price/currency/shipping, New/US/ASIN and original time. Select an explicit research price; no automatic conversion of observed competitor price to our sale quote. |
| Featured Offer / lowest New offers | P BuyBoxPrices / LowestPrices and returned offer context, where present | Same P authorization | Direct when supplied; current snapshot only | Suppression/absence means UNKNOWN. A returned offer subset does not establish all sellers or our Featured Offer probability. Not all normalized tools retain every raw summary field. |
| New competing offers | P condition-scoped NumberOfOffers / summary breakdown | Same P authorization | Direct New count when validated; aggregate/detail separation already implemented | Total mixed Used/New count and returned detail length are not New-only competition. Existing 5 total / 1 detail case remains partial coverage; do not bypass its historical ranking gate. |
| Referral fee estimate | F, exact proposed New price/mode | One supported F role; F | Estimate; existing FBA parser/price-binding checks | Retain request price basis, mode, ASIN, USD and estimate time; not an actual fee settlement or a guaranteed future rate. |
| FBA fulfillment estimate | F with Amazon-fulfilled choice | Same F role/limit | Estimate; existing implementation | Catalog dimensions may differ from measured inventory. Storage, inbound placement/shipping, prep, returns and tax must be separately supplied. No missing costs become zero. |
| FBM Amazon fees | F with merchant-fulfilled choice, if authorized and response supports it; otherwise saved Revenue Calculator | F entitlement; current FBM call path unverified | Potential referral/other Amazon fee estimate; not verified current account capability | Existing FBA success cannot establish FBM authorization/coverage. M86 accepts independently attributed manual mode/price-bound estimates offline. |
| FBM fulfillment cost | Merchant/carrier quote, saved cost evidence | No SP-API endpoint in inspected path; local input | Estimated shipping/pack/handling cost | F does not price the merchant's carrier service. Explicit labor/pack allocation and shipment assumptions needed. |
| Sales rank + category | C `salesRanks`, with classifications | Product Listing; C | Direct ordinal/category observation; M80 requests/maps ranks | Rank needs category, ASIN/variation and time; no rank-to-monthly-sales conversion. Older catalog-only requests lacking this dataset cannot fill it. |
| Monthly demand | No general competitor unit-sales field in C/P/F | Not available through inspected authorized operations | UNKNOWN unless independently supported evidence is supplied | Authorized sales evidence covers its stated population, not total marketplace demand. Bought-past-month brackets are lower bounds; estimates need independent validation. No Brand Analytics/Orders entitlement assumed. |
| Historical New prices / stability | No retrospective series in C/P/F | Unavailable through inspected operations | UNKNOWN; prior saved comparable observations could form a limited series | Snapshots are not continuous history. Preserve original dates and coverage; future scheduled collection needs separate approval. No backfill or migration in M86. |
| Competition history | No retrospective series in C/P/F | Unavailable through inspected operations | UNKNOWN absent existing authorized historical observations | Do not assume a current count describes prior months. Historical vendor data requires separate licensing/authorization. |
| Walmart acquisition / prep / packaging / tax / inbound / other costs | Original retailer quote + merchant evidence | Outside Amazon product APIs | Manual observed/estimated amounts | Specific sale-unit scope, source time, shipping ZIP/method, taxes and supported nonapplicable zero required. |
| Selling eligibility | Existing Listings Restrictions + seller review | Separate workflow, existing controls | Account-specific gate, not commercial-attractiveness evidence | No check is needed to start product analysis. An exact UPC match is not eligibility; restrictions persist until reviewed and cannot authorize buying. |

Historical authorization evidence: `docs/AMAZON_AUTHORIZED_SOURCE_WORKFLOW.md`
records owner-run authentication/pricing/fees/restrictions HTTP 200s on 2026-10-27
for B0G1MJ24B4, including restricted eligibility and New=1/Used=4. Catalog
pilot/discovery capabilities are documented in `AMAZON_PILOT.md` and M72–M80.
This does not create current six-product evidence or prove continuing authorization.

Official references:

- [Catalog operation and included datasets](https://developer-docs.amazon/sp-api/reference/getcatalogitem)
- [New-condition pricing operation and limits](https://developer-docs.amazon/sp-api/reference/getitemoffers)
- [Price-bound fee estimation and limits](https://developer-docs.amazon/sp-api/reference/getmyfeesestimateforasin)
- [Operation role mappings](https://developer-docs.amazon/sp-api/lang-de_DE/docs/role-mappings)

The matrix distinguishes documented potential, locally implemented parsers,
historical successful requests and presently missing evidence. New endpoints
(such as competitive summary/batch APIs), new dataset requests or an additional
seller/marketplace are not authorized merely by their documentation.
