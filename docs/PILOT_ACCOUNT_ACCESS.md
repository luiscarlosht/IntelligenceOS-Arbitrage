# Ten-product pilot: source recommendation and owner actions

Official sources checked 2026-10-26. No accounts, permission grants, product data,
keys, subscription entitlements or real seller evidence were verified. No provider
contact, registration, download of a live feed, purchase or paid API call occurred.
Keep credentials/business documents in the relevant official portals and protected
local storage; never send them in chat or commit them.

## Recommended source: permissioned EE Distribution evaluation CSV

Choose **one direct ten-SKU CSV supplied by EE Distribution with written internal
analysis/persistence/reporting permission**, before pursuing paid feeds. This is a
conditional recommendation, not a claim that a sample is already available or
that this project has a data license. If the supplier cannot grant that use without
a purchase or fee, leave real-data collection blocked and continue fixtures.

The [official site](https://www.eedistribution.com/) provides New Customer and
registration/contact routes. The current [client agreement](https://www.entertainmentearth.com/images/EED/Terms%20and%20Fees%20202506_V3.pdf)
requires a New Client Application and says submission does not guarantee approval.
The older application-PDF URL in the prior research returns 404; use the official
New Customer/sales route to obtain current account requirements.

The [official onboarding FAQ](https://www.eedistribution.com/help/kb/using-your-wholesale-account/what-is-the-onboarding-fee)
states that some new clients may owe **$250**. Its refund depends on $250 of shipped
merchandise and good standing; it is not zero upfront cost or a reason to buy.
No public sample/export license price was verified. Request a **$0, no-order
sample quote** and written permission before any signup/payment commitment; this
is our requested condition, not a supplier offer. If an onboarding payment or
minimum inventory order applies, obtain separate approval rather than proceeding.

Owner steps, not performed:

1. Use the official site's sales/New Customer route to ask whether a ten-product
   evaluation sample can be supplied before a paid account/order. Do not authorize
   payment or place an order to obtain it. Obtain current business/account document
   requirements through that supplier's secure process if an application is needed.
2. Obtain written permission covering local SQLite storage, analysis against Amazon
   evidence, derived internal XLSX/JSON, who may see them, allowed retention,
   deletion/backups and any ban on redistribution. Confirm Amazon resale/brand/channel
   restrictions separately. Save the agreement privately; use only its nonsecret
   reference in CSV. Website/account access alone is not export permission.
3. Obtain the account-priced sample and quote for sample, setup/onboarding, ongoing
   feed/subscription, MOQ and any shipping/pack charges separately. Require actual
   observed stock semantics (including preorder/backorder); do not assume stock.
4. Request product name/URL, valid UPC/GTIN or manufacturer+model, exact sellable
   package quantity/variation, USD price and its each/case basis, availability,
   original timezone-aware price/stock observation time, provenance and permission
   reference. Map to existing `templates/authorized_products.csv`; do not divide a
   case price or fill missing fields by inference. Record MOQ/other commercial
   restrictions privately and reject an incompatible package/economics context.
5. Validate the permitted CSV with existing `app.authorized_imports`; schema
   validation is not permission validation. Retain missing/stale fields and their
   rejection reasons. Ten real records may all be blocked, which is acceptable.

[Existing comparison](SUPPLIER_ACCESS_OPTIONS.md) still covers Inventory Source,
CJ and Target. Those do not need new connectors in this milestone. Free directory
or affiliate signup is not a data-license quote for internal resale analysis.

## Walmart distinction

The official [Marketplace item search](https://developer.walmart.com/global-marketplace/reference/getsearchresult)
describes catalog discovery to decide which items to sell and supports item-setup
specification responses. It does **not** establish our right to collect retail
buy prices/store stock for arbitrage. Supplier APIs likewise address a supplier's
own catalog and are not a general consumer sourcing feed. No Walmart seller key,
retail connector or catalog-sourcing permission is assumed here.

The [affiliate agreement](https://affiliates.walmart.com/terms) governs accepted
marketing affiliates and qualifying links. Its existence/free membership does not
authorize our internal resale data use. A separate affirmative license would be
needed; no repurposed affiliate feed, unauthorized scraping or live price fetch
is implemented. EE is recommended to request a small permissioned sample rather
than assuming Walmart APIs solve this access gap.

## Amazon SP-API — exact account-owner steps

1. Confirm the intended US seller account, primary owner and Professional status.
   Individual seller accounts cannot register private seller applications. Do not
   upgrade/buy a plan in this task. The current [Professional plan](https://sell.amazon.com/pricing)
   is **$39.99/month plus selling fees**; existing entitlement is unknown here.
2. Primary owner: Seller Central → Apps and Services → Develop Apps. If migrated
   to Solution Provider Portal, use Settings → Developer Profile. Follow
   [private registration](https://developer-docs.amazon/sp-api/docs/register-as-a-private-developer):
   contact details, Private Developer data-access type for the owner's organization,
   requested roles, truthful use case and actual security controls. Review the AUP,
   DPP and agreement. Do not assert controls that have not been deployed.
3. Request Product Listing for catalog/restrictions/selected individual fee
   operations and Pricing for the chosen price/offer/batch-fee workflow, subject to
   the operation's current role matrix. Request no orders/customer PII/restricted
   data roles for this pilot. Identify US marketplace `ATVPDKIKX0DER`, seller ID and
   condition `new_new`; never treat a UPC match as seller eligibility.
4. Submit the profile, retain the case ID and answer Amazon's requests; the current
   guide says to respond within five days to avoid case closure. Wait for approval,
   then register a **private seller app**, not a public multi-seller application.
5. As the primary owner, locate the private app and choose **Authorize app** for
   the intended account through Seller Central/SPP. Private draft apps can be
   self-authorized; public Appstore listing is not needed for private use. Securely
   store the app's LWA client ID/secret and account refresh token, separately from
   Gmail and Keepa credentials. Follow [self-authorization](https://developer-docs.amazon/sp-api/docs/self-authorization),
   including protected/encrypted storage, access, rotation and revocation. No
   secrets are requested or provisioned by this milestone.
6. Confirm current account billing. Amazon's official
   [fee cancellation announcement](https://developer.amazonservices.com/cancellation-of-sp-api-fees)
   says it is not proceeding with the planned usage and annual SP-API fees at this
   time. This corrects the earlier unresolved proposed-fee research, without
   implying that seller plans, app services, inventory or all future charges are free.
7. Approve a later read-only live-enablement scope: ten permissioned source rows,
   candidate catalog identification, package/child variation confirmation,
   seller/condition restrictions, price/competition and context-specific estimated
   fees. Other acquisition costs remain separately evidenced. Demand cannot be
   manufactured from sales rank or the owner's unrelated sales history.
8. Review actual retention/deletion/security obligations and Amazon's policy on
   external Amazon-data services **before combining SP-API and Keepa data**.
   This offline PR does not resolve that policy compatibility or implement a live
   SP-API HTTP client. A separate reviewed implementation and explicit bounded-call
   approval are still needed; account approval alone cannot enable a provider.

References: [registration overview](https://developer-docs.amazon/sp-api/docs/sp-api-registration-overview),
[private-developer guide](https://developer.amazonservices.com/start/getting-started-for-private-developers),
[role/evidence research](V03_PROVIDER_RESEARCH.md). No automated seller-account
registration or API request is performed here.

## Keepa — exact account-owner steps

1. Confirm the actual account and **API subscription** entitlement, not just a browser
   plan. Review [API pricing](https://keepa.com/api/pricing) in the owner's account.
   The prior 2026-10-23 rendered official check recorded Starter **€49/month at
   20 tokens/minute**. Today's public fetch returns only a JavaScript shell, so that
   price is historical, not a freshly verified checkout quote. Obtain current plan,
   VAT/FX/payment total and entitlement evidence before any budget approval.
2. Review [current terms](https://keepa.com/terms) for normalized local persistence,
   internal reports, permitted sharing, deletion and backups, and resolve the Amazon
   policy compatibility above. The prior terms reading recorded post-termination
   deletion within 60 days with qualified exceptions; current terms must be reviewed
   by the owner because today's fetch was unavailable. No live data-retention license
   is inferred from this fixture database. Record only the permission/retention
   reference, not account data, in a later manifest.
3. If already entitled, verify included available tokens and approve a strict pilot
   cap. If not entitled, obtain separate numeric budget/subscription authorization;
   no trial, prorated ten-product price or free API access is assumed. No payment
   is authorized by approval of this code or documentation.
4. Retrieve the API key through Keepa's official account interface into a protected
   secret store for a later approved runner. Do not paste it in chat, env dumps,
   source, command URLs or logs. Keep the existing dormant transport's fixed TLS/
   no-redirect/redaction policy and false live gate; do not add a second HTTP client.
5. Confirm ten explicit matched US **child ASINs** and the permitted data fields.
   Existing request contract fixes `domain=1`, `update=-1`, `history=1`, `days=1`;
   no code searches, offers, stock, forced refresh, buybox or other paid options.
   Reserve **10 tokens for one pass**; misses may cost less but reservations are not
   refunded. The current offline composition uses one attempt per ASIN. A future
   retry policy needs separately approved bounds. These are request units, not cash.
   [Product request cost/parameters](https://keepa.com/api-docs/product.html).
6. Confirm a real starting token balance; use one account-wide ledger and do not
   reset budgets to bypass caps. Plans bill monthly in advance; unused token bucket
   units expire after 60 minutes, which is not data-retention expiry.
   [Token model](https://keepa.com/api-docs/plans-tokens.html).
7. Approve a later live-enablement PR and storage/deletion rules. No environment
   setting enables the current code gate. Reuse existing adapter/ledger/pacing and
   preserve each observation's original timestamp, unknown costs/eligibility and
   monthlySold lower-bound semantics. No actual key or call is needed for the
   independently implemented offline pipeline.

## Ten-product cost decision

| Component | Cost evidence / gate |
| --- | --- |
| Fixture implementation/runs | $0 incremental vendor calls/subscriptions; existing host/storage excluded |
| EE evaluation CSV | Actual quote unknown; request no-order/$0 sample with written rights. Possible $250 onboarding, not authorized. No free export asserted. |
| SP-API developer usage/annual fees | Planned fees canceled per official announcement; owner checks current classification/billing |
| Professional seller plan | $39.99/month plus selling fees if not already held; no subscription authorized |
| Keepa API | Prior Starter record €49/month; current checkout/tax/FX and existing entitlement unverified. Full subscription cost, not 10-token fractional cash cost. |
| Other supplier/data services | None selected or subscribed; no automatic paid fallback |

With existing seller/API entitlements and a genuinely free permitted sample,
incremental vendor cash may be zero for ten approved reads, but no such entitlement
is verified. Without Keepa entitlement, adding a full API plan may exceed the
project's <$50/month target. Do not announce a universally covered <$50 live route.
No purchases, subscriptions or live paid calls occur while these gates are pending.

## Scan Profit and independent next steps

Existing research has not identified Scan Profit's official product domain or
vendor documentation. No guessed domain, feature/pricing assertion, scraped API
or export connector is added. Only once the owner identifies an official URL
should the project review documented API/CSV export fields, permission, account
requirements and cost. First map any documented export to the existing CSV importer,
match/evidence contracts and store; implement only a demonstrated missing capability.
This preserves the user's condition on investigation and avoids duplicating Keepa
or reporting functionality based on an ambiguous name.

Continue SQLite/fixture tests, field mapping and report inspection now. Wait for
actual source permission, ten records and account approvals before a separately
reviewed real-data run. Scheduled email/deployment remains out of scope even after
these account tasks are complete.
