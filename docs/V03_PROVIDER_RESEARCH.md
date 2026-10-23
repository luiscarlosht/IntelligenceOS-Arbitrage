# V0.3 access, evidence and cost decision record

Research checked **2026-10-23 UTC**, US retail to Amazon.com assumed. Only official
vendor/network documentation supports the findings below. No accounts were opened,
credentials read, paid calls made or providers enabled. Public documentation is
not account approval or permission for this specific use. Unknown charges remain
unknown, not zero. Recheck pricing/terms before activation.

## Recommended route and viability

Start with a small **user-owned, authorized CSV** of actual retail observations or
an expressly licensed export, then the user's **private, self-authorized SP-API
application** for Amazon catalog, pricing, fees and seller restrictions. Keep
manual evidence entry as the first pilot. This avoids an unapproved affiliate
feed license and an additional demand subscription. It is a recommendation
conditional on the account, fee and permitted-use checks below, not live readiness.

For demand, accept recent, authorized, variation-specific sales evidence supplied
by the user; record its basis and observation time. Amazon catalog sales rank is
not monthly unit sales. Own-account sales history is not market-wide demand for
an unlisted product. Keep the existing missing-demand rejection if adequate
evidence is unavailable. There is **no verified fully automated, universally
covered <$50/month route** established by this research.

Do not combine Keepa with SP-API by default. The current Amazon
[Acceptable Use Policy §4.3](https://sellercentral.amazon.com/solution-provider/policy?policyType=AUP&locale=en_US)
restricts use/offering/promotion of external services vending Amazon website data;
§4.4 limits aggregation across authorized users. Keepa integration needs explicit
policy compatibility clarification from Amazon and a suitable Keepa license.
This is a conservative implementation gate, not a claim that all uses have been
adjudicated. Do not evade it by routing the same data through another account.

## Amazon SP-API

The [registration overview](https://developer-docs.amazon.com/sp-api/lang-en_EN/docs/sp-api-registration-overview)
requires a Professional seller account and primary-user registration for a private
seller application. The [private developer guide](https://developer.amazonservices.com/start/getting-started-for-private-developers)
and [authorization guide](https://developer-docs.amazon.com/sp-api/docs/connecting-to-the-selling-partner-api)
cover developer approval, application registration and self-authorization.
Use LWA client credentials/refresh token through approved secret injection later;
no credential values belong in chat, fixtures, URLs in logs, or this repository.
Request only the roles needed for the operations, not orders/customer PII roles.

| Evidence | Proposed operation / role | Required interpretation |
| --- | --- | --- |
| ASIN candidates | Catalog Items 2022-04-01 `searchCatalogItems`, `getCatalogItem`; Product Listing | UPC can map to several ASINs; verify identifiers, package quantity and child variation. Preserve ambiguity. |
| Seller eligibility | Listings Restrictions 2021-08-01 `getListingsRestrictions`; Product Listing | Explicit seller, marketplace, ASIN and condition. A successful matching request says nothing about eligibility. A successful restriction evaluation still does not authorize purchase or replace authenticity/document checks. |
| Estimated referral/FBA fees | Product Fees v0 `getMyFeesEstimateForASIN` (Product Listing or Pricing among allowed roles); batch `getMyFeesEstimates` requires Pricing | Quote keyed by ASIN, marketplace, proposed sale price and fulfillment. Inbound, prep, packaging, tax, storage and other expenses still need separate evidence. Missing fees remain missing. |
| Price / competition | Product Pricing operations; request Pricing for the selected workflow | Preserve condition, fulfillment, shipping, offer scope and observation time. A price is not an assured sale. |
| Demand | Catalog `salesRanks` and separately authorized seller-supplied evidence | Rank is only rank; never invent a monthly-sales conversion. Account/brand analytics access must be checked separately. |

Official sources: [catalog workflow and non-unique identifiers](https://developer-docs.amazon/sp-api/docs/search-catalog-items),
[catalog reference](https://developer-docs.amazon/sp-api/reference/searchcatalogitems),
[restriction prerequisites](https://developer-docs.amazon/sp-api/lang-en_en/docs/get-listings-restrictions),
[fees roles and batches](https://developer-docs.amazon/sp-api/docs/product-fees-api),
[ASIN fee estimate limitations](https://developer-docs.amazon/sp-api/reference/getmyfeesestimateforasin),
[pricing guide](https://developer-docs.amazon/sp-api/docs/product-pricing-api).

Default reference rates observed: catalog search 2 requests/s, burst 2; ASIN fees
1 request/s, burst 2. Treat these as operation-specific defaults, not global
entitlements. Honor dynamic limits and 429 responses; batch/deduplicate only
within authorized use and allowed storage periods. See
[usage plans](https://developer-docs.amazon/sp-api/lang-en_en/docs/usage-plans-and-rate-limits).
The [policies index](https://developer-docs.amazon/sp-api/docs/policies-and-agreements)
links the current regional AUP, DPP and agreement. Review retention, deletion,
security and permitted use before storing live evidence; current offline backup
retention is not automatically a permissible retention period for future API data.

**Pricing verified:** US Professional selling plan **$39.99/month**, plus selling
fees, from [Amazon's official price page](https://sell.amazon.com/pricing).
This account charge is separate from API developer/usage charges.
**API fee schedule unresolved:** the indexed onboarding guide refers to an update
on SP-API fees, but the linked historical announcement
[`/spp-announcement`](https://developer.amazonservices.com/spp-announcement) returned
404 during this research. The current public onboarding page did not provide a
usable dollar schedule. Do not turn older third-party claims about $1,400/year,
rollout dates or private-app exemptions into a current verified quote. The owner
must confirm private-app billing classification and current charges in their
official portal or with Amazon support before activation. No API price of $0 is
assumed here.

## Keepa

[Official API overview](https://keepa.com/api-docs/) requires an API subscription
and private API key. The [product endpoint](https://keepa.com/api-docs/product.html)
supports batches up to 100 and codes that can map to multiple ASINs. Historical
prices, offers and rank may help assess stability, but Keepa cannot determine this
seller's eligibility. Its fee data cannot replace all acquisition/fulfillment costs.

The [product object](https://keepa.com/api-docs/product-object.html) documents
`monthlySold` as Amazon's bought-past-month lower-bound bracket, variation-specific,
often absent, with `lastSoldUpdate` separate from general product freshness.
It is not an exact monthly-sales count. Record the bracket and its own timestamp;
rank drops must not silently substitute for sales units.

[Plans and token rules](https://keepa.com/api-docs/plans-tokens.html): monthly
advance billing; unused tokens expire after 60 minutes. Basic product lookups
cost 1 token per requested ASIN, including ordinary misses. Optional parameters
change costs. The product endpoint's detailed offers rules supersede a simplistic
base-plus-offers formula: offers can cost 6 per found page (up to 10 offers), have
minimum/fallback cases, and replace the basic token charge in the documented
offers mode. Reserve a conservative upper bound for every requested option and
retry. Do not budget from batch count alone. [Request/error documentation](https://keepa.com/api-docs/request-basics.html)
describes 402 (access/payment) and 429 (token exhaustion), and response token state.

**Current subscription price not publicly verifiable through the tools used:**
the official [API dashboard](https://keepa.com/api) returned only the JavaScript
shell, not a price table or contractual API terms. The docs' €10/€25 proration
example is explicitly an example, not a plan quote. No browser-plan/API-plan
equivalence, trial, tax treatment, redistribution rights or entry euro price is
asserted. Obtain the current API checkout quote and API terms from Keepa through
the owner's account/support; require written permission for the intended use and
resolve Amazon compatibility before any subscription or data mixing.

## Authorized retailer feeds

| Retailer | Official access path and permissions | Price / restrictions / unresolved evidence |
| --- | --- | --- |
| Walmart | [Affiliate program](https://affiliates.walmart.com/) provides approved affiliates data feeds. [Membership page](https://affiliates.walmart.com/page/benefits) describes free membership. Apply with an eligible promotional property; the approved account determines actual feed access. | $0 membership is not a license quote for internal arbitrage. [Terms](https://affiliates.walmart.com/terms) limit licensed content to program purposes, restrict redistribution/syndication and require timely price updates. Obtain written permission for internal Amazon resale analysis and retention/export. Prices/stock are not guaranteed or necessarily store-specific. |
| Walgreens | The [official Walgreens program listing hosted by CJ](https://public.cj.com/signup/publisher?advertiserId=2568723) requires an active CJ account and advertises a product catalog. [CJ support](https://www.cj.com/support) states publisher signup is free. | $0 CJ signup; actual Walgreens catalog entitlement, current feed charge (if any), refresh frequency and internal analysis license must be confirmed after advertiser approval. No free data license inferred. [CJ Product Feed API](https://docs.cj.com/docs/productfeed-api-search) requires a personal token and company/advertiser IDs. Summary visibility is not sufficient permission to use product detail data. |
| Target | [Target Partners](https://partners.target.com/?q=2026-2027) advertises free application; [FAQ](https://partners.target.com/faqs) describes Impact approval and referral content. [Impact catalog download guide](https://help.impact.com/partner/what-would-you-like-to-learn-about/platform-features/marketing-content/product-marketplace-and-catalogs/download-product-catalogs-as-a-partner) requires joining a brand that has uploaded a catalog. | $0 application; Target-specific catalog availability, fields, feed charges and license for internal resale analysis are not verified by the public pages. Impact's generic catalog capability does not prove Target grants this account a feed. Confirm with the program before using it. |

Alternative Walmart APIs are not a blanket consumer-feed permission:
[Marketplace item search](https://developer.walmart.com/global-marketplace/reference/getsearchresult)
supports catalog listing workflows, while
[Scintilla feeds](https://developer.walmartdataventures.com/scintilla-media-data-feed/docs/getting-started)
are scoped to Charter Clients and GTIN ownership. No general-purpose licensed
retail-price feed or price quote for this business was verified there.
The [Walgreens developer portal](https://developer.walgreens.com/) is a separate API
program; its existence and older photo/pharmacy API materials do not establish
authorized general merchandise price/inventory access. Do not use health data.

All three need confirmation of GTIN completeness, unit/case quantity, variation,
USD price, store/ZIP/fulfillment applicability, public vs loyalty/coupon price,
stock, source observation time and permitted local storage. Feed download time
does not refresh an old observation. Prefer an authorized CSV export first;
never scrape or bypass access controls to fill missing fields.

## Projected monthly cost and workload

Assumptions: 100 source candidates/day, 30 days, one US seller/marketplace, up to
20 shortlisted products/day, existing VM; no AI, SMTP, purchases or new hosting.

| Route | Projected additional monthly amount | Gate |
| --- | --- | --- |
| Current offline preparation + local backup | $0 vendor charges; storage/hosting already owned | No live evidence; mock examples are not real opportunities. |
| User-owned authorized retail CSV + manual authorized Amazon evidence | $0 new data subscription; labor excluded | Availability and data rights required; missing evidence still blocks review. |
| Private SP-API pilot, Professional already paid | `A + F` | A = owner-confirmed API fees; F = authorized source license fee. Neither presumed zero. |
| Same pilot, new US Professional plan needed | `$39.99 + A + F` before taxes/selling fees | Less than $50 only if A + F < $10.01; subscription needs approval. |
| Add Keepa, only after compatible licensing | Previous route + `K_EUR × approved USD/EUR rate + tax/FX charges` | K = current API quote, currently unknown. Budget approval cannot be given from an unverified entry price. |

SP-API illustrative request volume: 3,000 individual catalog lookups/month
(or as few as 150 initial batches of 20 identifiers before pagination/details),
up to 600 restriction checks, 600 pricing reads and 600 fee estimates (or 30
batches of 20 with the required Pricing role). Extra detail pages, failures and
retries add usage. This is planning math, not a vendor quote or guaranteed limit.
Basic Keepa shortlist lookups would be about 600 tokens/month before options,
misses/retries/code multiplicity; token generation and short bucket lifetime
must also fit each run. Subscription price does not scale down to just those tokens.
No LLM call per product: planned AI API spend remains $0.

## Owner decisions before a live pilot

1. Confirm US marketplace, seller account ownership, existing Professional status
   and whether a private app for this organization is appropriate. Obtain developer
   role approval and official billing confirmation; provide no secret values in chat.
2. Choose the first retailer and supply an authorized sample export plus its usage
   terms, or obtain written feed permission for internal resale analysis and storage.
   Account creation and contacting providers are not performed in this milestone.
3. Choose an authorized demand evidence source. If coverage is missing, accept
   rejected rows; do not relax the monthly-demand or freshness gates.
4. If considering Keepa, obtain current API price/terms and Amazon policy
   compatibility confirmation. Approve a numeric monthly budget before subscribing.
5. Review backup retention/storage, data policy obligations and a later deployment
   PR. The backup timer proposed here is not enabled on this VM.
