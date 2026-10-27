# Amazon US read-only pilots

The owner confirmed a successful manual catalog call for B002XQ1R06. The sanitized
report inspected previously recorded success at 2026-10-26T23:42:42.119876+00:00,
US marketplace ATVPDKIKX0DER and `is_mock: false`. That original report lacks a
title because the parser discarded it; identifiers and relationships were not
requested. Do not interpret the original missing fields as Amazon confirming
an exact source match. This change preserves the original report and credentials.

The catalog mapping repair and expanded pilot have been tested with synthetic
responses only. No additional live calls, credential reads, purchases, listing
changes, email or deployment were performed during this work. Existing scheduled
jobs and provider selection remain unchanged.

## Credentials and terminal handling

For initial setup only, use direct interactive SSH:

```bash
cd /root/IntelligenceOS-Arbitrage
.venv/bin/python -m app.amazon_pilot credentials
```

Existing credentials must be retained; do not repeat entry after successful setup.
All three prompts are hidden, including client ID. A controlling terminal and
working echo suppression are mandatory; GetPassWarning aborts before visible
fallback. `/dev/tty` is opened in output-only text mode `w`; `getpass` opens the
controlling terminal separately for input. The original `r+` mode raised
`io.UnsupportedOperation` on a nonseekable terminal before any prompts.

Never pass credentials or seller ID as arguments, shell exports, chat messages
or shell startup changes. Credentials live under the invoking user's home in
`.intelligenceos-arbitrage-amazon/`, outside Git and application reports/backups.
Directory ownership must match the invoking user and mode must be 0700; files are
created exclusively with mode 0600. Symlink directories/files, permissive or
hard-linked credentials are rejected. No Gmail configuration is loaded.

Failures print only operation name, exception class and numeric errno (or `none`).
No exception message, credential value, raw response, traceback or request URL is
printed. Existing files are never overwritten, including failed-attempt reports.
A failed attempt needs deliberate operator review before any newly authorized
attempt; this preparation neither removes nor changes existing private files.

## Catalog request and demonstrated mapping gaps

The original `includedData=summaries` already returned a summary schema capable of
containing `itemName` and `packageQuantity`. Both were discarded by the old parser.
The repaired request uses `includedData=summaries,identifiers,relationships`:

| Dataset | Mapping | Conservative behavior |
| --- | --- | --- |
| US summary | `itemName` → title; manufacturer/model; positive integer `packageQuantity`; color/size/style; item classification | Missing values stay missing. Invalid quantities never default to one. `number_of_items`, dimensions and bundle text are not package-count substitutes. |
| US identifiers | Typed identifiers retained; UPC/EAN/GTIN checksum validation and canonical 14-digit GTIN | Equivalent UPC/EAN forms deduplicate. Distinct canonical IDs or invalid GTINs block adapter matching; no arbitrary first-ID selection. |
| US relationships | Type, parent/child ASINs, variation theme and theme attributes | Parent ASINs are not purchasable child verification. Missing relationships never mean “standard”; unsupported or incomplete theme values block matching. Package hierarchy requires source verification. |

Only the requested US marketplace is normalized. Duplicate US datasets are
rejected; other-market values never fill US gaps. Relationships preserve
PACKAGE_HIERARCHY separately from VARIATION. Summaries supply package quantity
and common variation values, so unbounded product-type attributes are not
requested; unsupported theme dimensions remain unresolved.

`AmazonCatalogListing` extends the existing `MarketplaceListing` contract with
title, identifiers, relationships, mapping issues and missing fields.
`AmazonCatalogAdapter` implements existing catalog/match seams and delegates basic
checks to `match_listings`, adding mapping-issue gates. It requires source identity,
package and explicit variation agreement; an ASIN hint alone is insufficient.
Use the adapter's `match` method to preserve those added gates. There is no live
production provider registration or automatic purchase decision.

The original two-request catalog-only command remains available as
`.venv/bin/python -m app.amazon_pilot pilot`, but refuses the existing
`catalog-pilot.json`. Do not remove the successful report just to rerun it.

## Expanded pilot: prepared, not executed

For a future separately authorized manual run, choose a proposed USD sale price
with at most two decimals. Example only: 25.00 is a scenario input, not a verified
market price or recommendation.

```bash
cd /root/IntelligenceOS-Arbitrage
.venv/bin/python -m app.amazon_pilot details --fee-price 25.00
```

The command prompts for the **authorized Amazon seller/merchant ID**, with hidden
input. This is not an LWA client ID, developer ID, marketplace ID or store name.
It is not added to the credential file; the report redacts it. The seller must be
the seller who authorized the existing refresh token. Fee response seller/context
validation rejects mismatches rather than assigning another seller's estimate.
No Sellers API call is added to discover the ID.

The fixed scope is ASIN B002XQ1R06, US ATVPDKIKX0DER, restrictions condition
`new_new`, Consumer/New pricing and an FBA fee scenario with explicitly zero
buyer-paid shipping. The seller's acquisition, inbound, prep and storage costs
are not assumed to be zero.

| Step | Method and path | Explicit seller ID in request? |
| --- | --- | --- |
| LWA exchange | POST `https://api.amazon.com/auth/o2/token` | No; uses seller-authorized refresh token |
| Catalog details | GET `/catalog/2022-04-01/items/B002XQ1R06` | No |
| Current observed pricing | GET `/products/pricing/v0/items/B002XQ1R06/offers?MarketplaceId=ATVPDKIKX0DER&ItemCondition=New&CustomerType=Consumer` | No; caller identity comes from token |
| Estimated fees | POST `/products/fees/v0/items/B002XQ1R06/feesEstimate` | No seller-ID request field; returned seller must match operator context |
| Listing restrictions | GET `/listings/2021-08-01/restrictions?asin=B002XQ1R06&sellerId=…&marketplaceIds=ATVPDKIKX0DER&conditionType=new_new&reasonLocale=en_US` | **Yes**, required |

All SP-API paths use `https://sellingpartnerapi-na.amazon.com`. The fee POST is
an estimation operation, not a listing update, order, purchase or fee payment.
No approval links are followed and no additional pages or ASINs are requested.

The report is exclusively reserved as `catalog-details-pilot.json` before hidden
seller entry or credential loading. Existing report refusal makes zero requests.
The cap is five HTTP attempts including token exchange; the first failure stops
all later steps. HTTP errors, throttling, malformed JSON and application-level
errors do not retry. Verified TLS, disabled inherited proxies, rejected redirects,
10-second socket timeout and 1 MiB response bounds reuse the original transport.
A Linux 60-second overall alarm bounds credential loading and network work after
interactive input. The original catalog-only pilot retains its 30-second alarm.
These are manual main-thread Linux/SSH commands, not background service jobs.

On failure, the private report records a fixed failed operation and request count;
completed normalized evidence is retained and unattempted stages stay null. Raw
payloads, access tokens, error messages, seller IDs and approval URLs are not saved.
Reports must remain in the private directory and outside Git/general report/email
pipelines. The report is an attempt reservation, not an automatic-retry mechanism.

## Evidence and purchase gates

Each evidence record has aware UTC retrieval time, operation provenance and an
explicit mock flag. Synthetic tests use `is_mock=True`; operator live execution
uses `False`. Retrieval timestamps do not establish guaranteed real-time accuracy.

Pricing records observed lowest/Buy Box summary prices with listing, shipping and
landed components separately. Absent components and counts remain null. USD,
ASIN, condition, marketplace and application status must match. Observed prices
are not guaranteed realizable sale prices and are not copied into listing economics.

Fees reuse `Evidence[FeeQuote]` and `SellerContext`. They validate seller, ASIN,
marketplace, FBA flag, scenario price/shipping and per-request correlation ID.
ReferralFee/FBAFees use explicit top-level FinalFee amounts; nested component fees
are not added to their aggregate. Missing or duplicate components stay unknown,
even when a total is returned. The estimate's timestamp and total remain separate.
Estimates can differ from actual measured-item fees and do not cover all costs.

A valid explicit `restrictions: []` records no listing restrictions returned for
this seller/ASIN/marketplace/condition at this time. Restrictions record a negative
listing-permission result; a missing/failed response remains unknown, never true.
Only allowlisted reason codes are retained. This evidence does **not** verify FBA
inbound/dangerous-goods eligibility, authenticity, invoices, brand/IP compliance,
source identity, demand, availability or profitability. Overall `seller_eligible`
remains null, and `purchase_approved` is always false. Listing permission alone
is never overall purchase approval.

## Official requirements verified 2026-10-26

| Operation | Required role for this pilot |
| --- | --- |
| getCatalogItem 2022-04-01 | Product Listing |
| getItemOffers v0 | Product Listing **or** Pricing |
| getMyFeesEstimateForASIN v0 | Product Listing is sufficient; Amazon lists additional alternatives |
| getListingsRestrictions 2021-08-01 | Product Listing |

These are operation-specific mappings; do not apply v2022 Pricing requirements
to the selected v0 getItemOffers endpoint. Profile approval alone does not prove
that the application and seller authorization include the roles. No IAM keys,
SigV4 or RDT are required for these non-PII operations.

Official sources:

- [Connect to SP-API](https://developer-docs.amazon.com/sp-api/docs/connecting-to-the-selling-partner-api): LWA refresh-token exchange and access-token headers.
- [Role mappings](https://developer-docs.amazon.com/sp-api/docs/role-mappings): roles by exact operation.
- [Catalog model](https://github.com/amzn/selling-partner-api-models/blob/main/models/catalog-items-api-model/catalogItems_2022-04-01.json): summary packageQuantity/itemName, typed identifiers and relationship schema.
- [getItemOffers](https://developer-docs.amazon.com/sp-api/reference/getitemoffers): required marketplace/condition and current offer scope.
- [Product Pricing model](https://github.com/amzn/selling-partner-api-models/blob/main/models/product-pricing-api-model/productPricingV0.json): response casing, context and price components.
- [getMyFeesEstimateForASIN](https://developer-docs.amazon.com/sp-api/reference/getmyfeesestimateforasin) and [Product Fees model](https://github.com/amzn/selling-partner-api-models/blob/main/models/product-fees-api-model/productFeesV0.json): estimation request/response, seller echo, correlation and non-guaranteed fees.
- [getListingsRestrictions](https://developer-docs.amazon.com/sp-api/reference/getlistingsrestrictions): required sellerId and optional condition filter.
- [Listings Restrictions guide](https://developer-docs.amazon.com/sp-api/docs/listings-restrictions-api): listing checks and approval requirements.
- [AWS signing removal](https://developer-docs.amazon/sp-api/lang-fr_FR/changelog/sp-api-will-no-longer-require-aws-iam-or-aws-signature-version-4).

## Local validation

Baseline: 386 tests passed. After the mapping/details changes: 437 tests passed,
including 68 Amazon tests (17 credential/original-pilot tests and 51 catalog/details
tests). Legacy and discovery sample jobs, DEMO and the ten-product offline pilot
all completed successfully with a cleared environment and isolated output paths.
The tests cover request datasets/counts/methods, US filtering, title and quantity,
equivalent/invalid/ambiguous identifiers, parent/package relationships, incomplete
themes, price components, missing fees, nested-fee double-count prevention,
seller/scenario/correlation validation, restriction unknown/blocked/clear cases,
hidden-input refusal, no-overwrite, partial failure and timeout redaction.
Expanded live authorization, pricing, fee responses and restrictions are still
unverified. CI results are separate from these local checks.

## Pricing failure investigation and safe diagnostics — 2026-10-27

The operator's preserved details report records three attempts: LWA exchange and
catalog details completed, then `current_pricing` failed. Pricing, fees and
restrictions remain null; no fee or restriction request was reached. A second
invocation stopped at exclusive report creation before any requests. The original
report contains no HTTP status, Amazon error code or parser reason. Its cause
cannot be recovered or inferred from that report, and it must not be overwritten.
The catalog contains multiple distinct canonical GTINs; the adapter correctly
keeps the selected GTIN missing and marks identity ambiguous rather than choosing
one. Catalog evidence alone does not establish source matching or eligibility.

The request was rechecked against the official sources above on 2026-10-27:
`GET https://sellingpartnerapi-na.amazon.com/products/pricing/v0/items/B002XQ1R06/offers`
with `MarketplaceId=ATVPDKIKX0DER`, `ItemCondition=New`, `CustomerType=Consumer`.
The v0 endpoint, required parameter casing and allowed values match Amazon's
getItemOffers reference. That operation accepts Pricing OR Product Listing in
NA; v2022 competitive-summary requirements do not apply to this request. Effective
account/application role configuration was not inspected. No request change or
role-change recommendation follows from the available failure evidence.

Previously the HTTP handler closed errors without recording status/body codes,
and the details wrapper reduced all exceptions to a fixed failed operation. A
200 response rejected by the parser was also indistinguishable from an HTTP or
transport error. New diagnostics retain only numeric HTTP status and fixed
allowlisted Amazon/LWA error codes. Unknown string codes become `OTHER`; raw
code text, messages, details, URLs, headers, tokens and payloads are excluded.
Only up to 16 KiB of an error response is examined in memory, within the existing
socket/overall bounds. Invalid, oversized or unreadable error bodies retain only
the observed HTTP status. A transport failure before a response has no invented
status. Recognized status/code combinations describe the response, not a proven
root cause (for example, 403 alone does not establish a missing role).

Completed non-token stages record out-of-band `response_diagnostics` (status,
allowlisted codes and fixed application status). Failures record
`failure_diagnostics` with exception class, errno, HTTP status, codes and a fixed
failure category. HTTP 200 parser failures retain their observed status and are
labeled `response_validation_failed`; this is not reported as API success. CLI
output carries the same safe status/code/category fields for transport failures.
These changes apply only to future runs, not the preserved report. Existing
request caps, no-retry behavior, exclusive report files and unknown-data gates
are unchanged.

### Proposed next test — not executed or newly authorized

Use a separately reviewed pricing-only diagnostic: exactly one LWA exchange and
one getItemOffers call with the identical ASIN/US/New/Consumer request, no retries,
10-second sockets, 30-second overall deadline and bounded responses. Reserve a
new private owner-only report, such as `pricing-diagnostic-01.json`, exclusively
before credentials are read; do not rename, remove or overwrite either pilot
report. Preserve status/allowlisted codes or HTTP-200 parser-validation evidence,
then stop. Do not repeat catalog, fees or restrictions just to investigate pricing.
This is a proposed test scope, not an added runnable CLI command or authorization
to execute it. A fresh, explicit operator authorization is needed for any new
live attempt; the failed five-request run does not authorize an automatic retry.

Diagnostics validation: 456 tests passed locally, including 87 Amazon tests and
19 new diagnostics regressions. Both documented offline sample modes passed.
The sanitized details report's SHA-256 was unchanged before/after this work.
No credential file was opened, live Amazon request made, existing private file
written/deleted, deployment performed or email sent. New diagnostic fields cannot
supply the original report's unrecorded HTTP status or Amazon code.
