# Kroger source integration decision — 2026-10-27 UTC

Status: **contractually blocked under standard public terms; no connector**.
No account registration, provider contact, credentials,
authenticated provider calls, purchases, deployment or email occurred. Public
documentation research is separate from a live Products/Locations request.

The conditional [one-product pilot and Amazon request plan](KROGER_ONE_PRODUCT_PLAN.md)
is prepared. Its executable request budget is zero. Suitability must include
permission for private Kroger-to-Amazon sourcing, normalization, SQLite evidence,
backups and private Excel/JSON reporting, not merely API authentication.

## Official sources and registration

Kroger's [official Public APIs collection](https://www.postman.com/kroger/the-kroger-co-s-public-workspace/collection/ki6utqb/kroger-public-apis)
documents account creation, email verification, then application registration to
generate OAuth2 client credentials. A Postman account is not established as a
requirement to use the API from our application. No Amazon credentials belong
in Kroger registration. Customer cart/profile authorization is a different flow.

Official API/terms entry points:

- [Acceptable use](https://developer.kroger.com/documentation/public/getting-started/acceptable-use)
- [API basics](https://developer.kroger.com/documentation/public/getting-started/apis)
- [Quick start](https://developer.kroger.com/documentation/public/getting-started/quick-start)
- [Products](https://developer.kroger.com/api-products/api/product-api-public)
- [Locations](https://developer.kroger.com/api-products/api/location-api-public)
- [Reference](https://developer.kroger.com/reference)

The direct text retrieval of these developer pages returned a JavaScript shell
or access error. Rendered official-page verification is recorded below; no
third-party summary is treated as a contractual grant.

## Verified contractual blocker and retention decision

The rendered official **Acceptable Use of Public APIs → Products API** prohibits
“Comparing products/prices among other retailers.” It also prohibits systematic
response gathering to build a database and tracking/sharing/storing data derived
from customer searches or frequently viewed products. Our private Kroger-to-Amazon
comparison and durable SQLite evidence workflow conflict with those stated
restrictions. Private use does not establish an exception. Normalizing and
reporting the responses would not resolve the purpose/storage restrictions.
Source: [Kroger acceptable use](https://developer.kroger.com/documentation/public/getting-started/acceptable-use).

There is no verified Product/Location retention allowance that permits our
database, report exports and backups. Do not invent a 24-hour cache license:
API quota reset timing is unrelated to storage permission. The Cart API's
session-limited cache/display rule is cart-specific and cannot authorize a
product-history database. No customer cart or search histories are needed.
Any exception must explicitly cover comparison, normalization, derived reports,
local storage, backup copies and deletion, including termination obligations.

Consequently the user's **if technically and contractually suitable** condition
is not satisfied. No disabled connector, mocked connector tests, credential
loader or production provider registration is added. This is the requested
blocked-source branch of the task, with Target assessed below. A future written
exception and verified access contract would justify implementation and its
mocked schema/missing-data/permission/disabled-gate tests in a subsequent PR.

## API capabilities, limits and verification gaps

| Requested check | Current official evidence and consequence |
| --- | --- |
| Products / Locations availability | Public API pages and Kroger's official collection advertise both; account/email verification and application registration produce OAuth2 credentials. Public availability does not override acceptable use. |
| OAuth | Kroger's collection documents client-credentials access separately from customer authorization-code/cart use. The requested authorization page redirected to sign-in with an error, so the exact token exchange and minimum scopes were **not verified** in accessible current official text. `client_credentials` / `product.compact` must not be marked verified or implemented from memory. No customer login or extra scopes are proposed. |
| Identifiers | Preserve distinct provider product/item IDs and actual barcode strings; no guaranteed equivalence to a valid UPC. The proposed candidate demonstrates why check-digit validation is necessary. Exact identifier field semantics remain an implementation prerequisite. |
| Package | Expanded Products example contains `size`; net size is not retail pack count. Missing size or count stays unknown. |
| Price / promotions | Products documents `price.regular`, `price.promo` and effective/expiration dates. Preserve both prices; no assumption that promo means unconditional or that loyalty/coupon eligibility is known. Exact date field nesting/meaning must be checked against the accepted schema before coding. |
| Stock / fulfillment | Products documents `inventory.stockLevel` and instore/shiptohome/delivery/curbside indicators. These are not a guaranteed numeric available quantity or a fulfillment quote; absent stock stays unknown. |
| Observation time | No general product record observation/update timestamp was visible. Price effective/expiration dates are not stock observation times. API Basics' error timestamp is error metadata. Store retrieval time separately without inventing upstream freshness. |
| ZIP selection | Locations documents `filter.zipCode.near` as a starting point; select and verify one location rather than assuming ZIP-wide prices. |
| Products quota | **10,000 calls/day** on the Public Products API; do not assume each product/store or client receives an independent quota. |
| Locations quota | **1,600 calls/day per endpoint**. API Basics says limits reset 24 hours after the first call to an endpoint, not necessarily midnight. Confirm actual account limits and honor 429 before any later use. |
| Charges | No public API charge stated on reviewed pages; this is **not a verified $0 price**, absence of overage fees, or account billing confirmation. No paid plan or budget is approved. |

Sources: rendered [Products](https://developer.kroger.com/api-products/api/product-api-public),
[Locations](https://developer.kroger.com/api-products/api/location-api-public),
[API basics](https://developer.kroger.com/documentation/public/getting-started/apis),
[authorization access gap](https://developer.kroger.com/documentation/public/getting-started/authorization)
and the official collection above. These are documentation/schema findings,
not successful account access or a real product response.

## Exact next owner action

**Do not register for either affiliate/developer program to bypass the blocker.**
Review this PR first. If Kroger remains desired, the next future action would be
requesting a written exception/partner agreement through Kroger's official
developer partnership/support route, after separately authorizing contact. Its
[official Partner APIs collection](https://www.postman.com/kroger/the-kroger-co-s-public-workspace/collection/nryx3kn/kroger-partner-apis)
says partner access requires a contractual agreement and is not self-service.
Partner status itself is not proof that arbitrage is permitted.

Use this exact scope in that later request (not sent): private Kroger-to-Amazon
sourcing for one US seller near ZIP 76063; cross-retailer comparison; normalized
product/price/stock evidence in SQLite; private Excel/JSON reports; backups;
permitted retention and deletion; regular/promo/loyalty conditions; current quota,
all charges and minimum read scopes. Ask for an existing licensed one-item sample,
not a new collection job. Require the grant before credentials or calls.
If no exception is available, stop Kroger and use Target's written-approval
route below; neither source is currently live-ready.

## Location and fulfillment

The [official Mansfield locator](https://www.kroger.com/stores/grocery/tx/mansfield)
lists Broad St, 3300 E Broad St, and Matlock, 3001 Matlock Rd, both ZIP 76063 and
pickup available. The [Broad St detail](https://www.kroger.com/stores/grocery/tx/mansfield/broad-st/035/00594)
and [Matlock detail](https://www.kroger.com/stores/grocery/tx/mansfield/matlock/035/00584)
provide division/store identifiers. Select a specific confirmed API location,
not whatever default store a public page header shows. No Locations API call was
made, no distance ordering verified and no product inventory verified.

Pickup capability does not guarantee a product is in stock or a slot is open.
Delivery eligibility requires actual address/service/fulfillment evidence; a ZIP
or nearby pickup store does not establish it. Public catalog prices do not
establish delivery fees, minimum basket, membership, tax or shipped resale costs.
All missing fields remain unknown. Treat any future pickup and delivery quotes
as separate observations, including location, fulfillment and applicable conditions.

## Target assessment as the next alternative

Target's [official Partners FAQ](https://partners.target.com/faqs) describes an
affiliate referral program via Impact for approved websites/creators with mainly
US audiences. Joining is free; accepted partners can use promotional links and
creative. This is not an established internal sourcing-data license. A private
analysis tool without the described promotional property should not misrepresent
itself as an affiliate publisher.

The rendered [Target Partners terms](https://partners.target.com/termsandconditions)
define a Merchandiser Datafeed with TCIN, price, description and other information.
Sections **5.5–5.6** provide feed content for the affiliate site and require
express permission for API-related use. Section **2.3** restricts use to the
approved site, prohibits feed redistribution to third-party shopping sites and
prohibits scraping without written consent. Sections **13.1 and 13.3** limit the
license to generating Target sales from the approved site and require prior
written approval for other purposes. This purpose limitation blocks treating
standard affiliate membership as permission for our internal sourcing workflow;
it is not a claim that the terms explicitly name arbitrage or cross-market use.

No public page reviewed establishes this account's Target catalog entitlement,
barcode/package completeness, store-specific stock/price for 76063, observation
time, feed fees, private cross-market use or retention/export/backup rights.
Impact platform catalog capability is not Target-specific approval. No permitted
general-purpose Target retail API has been verified here; do not use undocumented
website endpoints, scraping or a partner login as a workaround.

Future owner steps, only if subsequently authorized: obtain the actual Target
program/catalog agreement and a written grant for internal Target-to-Amazon
analysis, normalized storage, backups and derived private reports; ask whether
the feed supports one branded shelf-stable item at the chosen store/fulfillment
near 76063, original timestamps, regular versus loyalty/promo price and shipping
conditions. Require an existing permitted one-row sample and a quote covering
license/setup/minimum/overage/tax/cancellation. Free affiliate signup does not
prove free data access or authorize this use. No registration/contact is needed
now; Target is **unresolved**, not approved or implemented.

## Credential-entry procedure after rights and access approval

Do not register or enter credentials now. Once a suitable grant, current charges
and an explicit pilot authorization exist, the account owner should personally:

1. Review/save the applicable official terms and written use/storage exception
   privately, with version/date, permitted users, deletion deadlines and a
   nonsecret reference. Resolve retention across SQLite, reports and backups.
2. Create a Kroger developer account using a business-controlled email and
   truthful project identity, verify email, and register a server-side application
   for the exact approved private use. Select only the documented read scopes;
   no cart, identity or customer-data permissions. Do not invent redirect URLs
   or choose a customer authorization flow to obtain catalog credentials.
3. Save client ID/secret in the approved secret manager, outside this checkout,
   shell history, reports and backup data. On a private terminal use hidden input
   (for example Python `getpass`) directly into that store; never pass secrets as
   command-line arguments or paste them into chat, tickets, PRs or Postman cloud
   variables. Restrict any approved file to owner-only access, validate regular
   file/no symlink, keep token only in memory and rotate on exposure.
4. A future reviewed adapter must reject disabled operation before loading
   secrets, use verified HTTPS with bounded timeout/response size, redact auth
   and errors, prevent redirects/credential forwarding, honor 429 and reserve
   attempts. Environment variable names alone do not enable a connector. No
   Kroger credential loader or live transport currently exists.
5. Review the exact one-product location/price/evidence request manifest before
   separately authorizing any live request. Registration alone does not authorize
   calls, a subscription, purchases, deployment or sending reports.

## Local validation

The existing checkout passed **666 tests**, plus both documented legacy and
discovery sample modes with email recipients empty. The pilot candidate's
displayed retailer code was checked with existing GTIN normalization and rejected
as an invalid checksum; it is not silently repaired. This change is a research
and conditional pilot handoff, not a connector implementation or evidence import.
