# Walmart-to-Amazon: the next access action — 2026-10-27

Walmart is now the owner's priority, superseding the earlier conditional EE
Distribution recommendation. Existing research established no granted Walmart
retail data license. No permission, account, real observation or sample is now
claimed. This is one concrete inquiry, not another provider comparison.

## Owner action: request a written-use exception and one existing sample

Use [Traject Data / BlueCart's contact form](https://trajectdata.com/contact-us/)
(or its published `support@trajectdata.com`, asking for commercial licensing).
Ask for a **provider-supplied, already available, licensed one-product CSV** for
Walmart.com, ZIP **76063**, for private Walmart-to-Amazon sourcing analysis.
Do not start with a free-trial registration or API key. Contact is for the owner
to perform later; the agent has not sent anything or submitted a form.

The [current vendor terms](https://trajectdata.com/traject-data-terms-of-service/)
limit the standard service license to personal use, trial accounts to temporary
non-commercial evaluation, and require written consent for interacting apps.
An applicable enterprise agreement can control conflicting terms. Our commercial
internal use therefore needs an explicit signed commercial/enterprise agreement
or written amendment, not an assumption that a trial or subscription grants it.

Required account type, if approved: a BlueCart business/commercial customer
covered by that written agreement (an enterprise/custom arrangement if necessary).
The public terms do not identify a self-service plan that grants our exact use;
ask the vendor to name it. A Walmart Marketplace seller account or Walmart
marketing affiliate account is not the provider account being requested. Their
credentials do not establish this sample license. No signup is required merely
to ask the published contact route about a sample; whether an account is required
to receive the file is a vendor question.

The owner should give truthful name, business/project identity, reply email and
this use statement. Do not submit payment details, seller tokens or unnecessary
business documents. If onboarding needs documents, ask for the current secure
process and exact requirements rather than guessing an EIN/website requirement.

Copyable inquiry, **not sent**:

> We need one existing Walmart.com retail product-data observation for private
> commercial analysis of potential Walmart-to-Amazon sourcing, delivered to ZIP
> 76063. We will not publish the source feed, advertise affiliate links or resell
> your data. Can you grant written permission for this exact use, local SQLite
> persistence, backups and derived private Excel/JSON reports? Please identify
> your right to supply/license the Walmart data for these uses, any Walmart or
> other third-party conditions, permitted users, retention/deletion and geographic
> restrictions. Your public personal-use/non-commercial-trial terms do not cover
> our intended use; please specify the applicable commercial agreement/amendment.
>
> Can you supply one already-held authorized CSV sample without an account,
> payment, subscription, inventory purchase, customer-run API request or new
> scraping job? We are not authorizing collection. We need product URL/item ID,
> UPC or manufacturer/model, exact variant and package quantity, seller, USD
> package price, actual stock, ZIP 76063, fulfillment method and shipping charge/
> conditions including basket, membership, promotion and delivery dependencies,
> original observation timestamp/timezone and provenance. Mark unavailable fields
> unknown. Does current product/Buy Box output support all these for that ZIP?
> We are not requesting an all-seller Offers endpoint. Please quote sample,
> license/setup, monthly/annual minimum, ZIP support, overage and cancellation
> charges separately, and say which commercial account type is required.

Proceed only after the actual written grant covers the sample and this use.
Save the agreement privately and use a nonsecret `authorization_reference` in
CSV. A vendor reply without the rights/use grant is not permission. If the vendor
cannot supply a permitted sample or adequate terms, access remains unresolved;
no trial, scraping workaround or alternative mock product is substituted.

## Costs and feasibility to confirm

The [official pricing page](https://trajectdata.com/ecommerce/blue-cart-api/pricing/)
currently displays Hobbyist **$18/month billed annually** (about **$216/year**
before tax), 500 requests/month and one custom ZIP. It also advertises a
100-request trial without a credit card. This is reference pricing, **not** our
commercial license quote; trial restrictions above still apply. Monthly billing,
one-sample price, commercial/custom agreement, setup, taxes and actual ZIP 76063
coverage need written confirmation. Do not subscribe or prepay an annual plan
on this evidence. The project's recurring operating target remains under $50.

The same page states BlueCart is not Walmart-affiliated or endorsed, uses no
Walmart-provided API and supplies web-scraped data. This is an unapproved vendor
inquiry, not an official Walmart feed or established Walmart permission. Obtain
the rights/third-party clarification before accepting the sample. The
[product updates](https://docs.trajectdata.com/bluecartapi/product-updates)
report that the Walmart Offers feature was deprecated March 29, 2024; later
updates describe Buy Box shipping policies when present. Confirm current
seller/stock/ZIP coverage in the sample; neither all sellers nor complete fields
are guaranteed.

The [Walmart affiliate agreement](https://affiliates.walmart.com/terms) is for
marketing participation, restricts feed redistribution and disallows resale
purchases through qualifying links. Applying to that program is not our next
step. [Marketplace item search](https://developer.walmart.com/us-marketplace/reference/getsearchresult)
supports catalog discovery/item setup for sellers; it does not establish a
license for a ZIP-specific consumer buy-price/stock sourcing feed. No Walmart
seller registration is proposed to unlock this retail use.

## Accepting the observation offline

Use [the Walmart CSV extension](../templates/walmart_observation.csv), based on
all existing authorized-source columns plus:

| Added field | Meaning |
| --- | --- |
| `source_item_id` | Supplied Walmart item identifier as text, not UPC/ASIN. |
| `source_seller` | Actual seller for the observed price; never infer Walmart from the site. |
| `destination_zip` | Explicit observed location `76063`; no default or ZIP relabeling. |
| `fulfillment_method` | `shipping`, `delivery` or `pickup`, as actually observed. |
| `source_shipping_cost` | USD charge if known; blank stays null. Zero only if explicitly evidenced. |
| `shipping_conditions` | Actual basket minimum, membership, coupon, delivery/pickup/store and eligibility conditions; explicit no-condition evidence if applicable. |

Base fields supply `url`, `gtin` (UPC normalized without losing identity),
`manufacturer`, `model`, `variation`, `package_quantity`, `purchase_price`,
`availability`, original `retrieved_at`, `provenance` and permission reference.
Do not invent a missing name, UPC, seller, price, stock, timestamp or permission.
ZIP alone does not identify a store: record any store scope in shipping conditions.

Run only after the owner provides the permitted row:

```bash
.venv/bin/python -m app.amazon_source_intake \
  --source var/private/walmart-observation.csv \
  --output-directory var/private/walmart-one-row
```

Existing CsvConnector/validator/intake/ObservationStore/reporting handle the
extension. Original input remains unchanged; structured source context participates
in fingerprints and persists in source JSON; Excel enrichment exposes it.
Missing/invalid seller, ZIP, item identity, shipping or source data remain findings.
The connector validates field shape, not license validity or actual Walmart stock.
Shipping context does not silently populate inbound shipping or other profit
costs: delivery economics, tax and possible conditions require explicit verified
cost mapping. Fees and seller/FBA eligibility remain unknown, not zero/true.
No actual product row has yet been supplied or persisted in this task.

## Exact Amazon request proposal after the row is supplied

The actual UPC/model/ASIN and selected fee price are unknown. No literal request
can responsibly be populated yet. Offline intake will report source findings and
prepare the following single-product plan, contingent on source identity and
permission review; it will not execute it:

1. One LWA refresh exchange for the existing authorized account; credentials stay
   private and are not read during intake. Failure stops dependent requests.
2. One US Catalog Items lookup: with valid UPC, `GET /catalog/2022-04-01/items`,
   `identifiers=<supplied UPC>`, `identifiersType=UPC`,
   `marketplaceIds=ATVPDKIKX0DER`,
   `includedData=summaries,identifiers,relationships,attributes`, `pageSize=1`.
   Other valid GTIN lengths use their correct identifier type. Without a GTIN,
   use one bounded manufacturer/model keyword search (`pageSize=10`) and verify
   identity rather than assuming its first result matches. If an ASIN hint is
   selected instead, use one `GET /catalog/2022-04-01/items/{hint}` with the same
   marketplace/data sets; verify it against source identity. Choose one route,
   no fallback/pagination. Unresolved or ambiguous results stop enrichment.
3. Only after exact ASIN, package and variation verification: one
   `GET /products/pricing/v0/items/{asin}/offers` with
   `MarketplaceId=ATVPDKIKX0DER`, `ItemCondition=New`, `CustomerType=Consumer`.
   Retain count/coverage uncertainty; never infer the seller's sale quote.
4. One `GET /listings/2021-08-01/restrictions` with the verified `asin`, authorized
   `sellerId` supplied securely later, `marketplaceIds=ATVPDKIKX0DER`,
   `conditionType=new_new`. Retain reason codes; no restrictions does not establish
   overall/FBA eligibility. B0G1MJ24B4 stays sourcing-excluded as NOT_ELIGIBLE.
5. **Zero fee requests initially.** Only after candidate suitability, independent
   seller/FBA evidence and explicit price selection: at most one
   `POST /products/fees/v0/items/{asin}/feesEstimate`, with
   `FeesEstimateRequest={MarketplaceId: ATVPDKIKX0DER, IsAmazonFulfilled: true,
   Identifier: <unique scenario ID>, PriceToEstimateFees: {ListingPrice:
   {CurrencyCode: USD, Amount: <explicit selected price>}, Shipping:
   {CurrencyCode: USD, Amount: 0}}}`. Mark the price hypothetical unless supported
   separately; validate response identity/price and preserve missing components.

Ceiling **4 attempts initially**, **5 only with the conditional fee**; zero retries,
no batch, pagination, reauthentication or second price. A pageSize=1 identifier
search with further matches stays unresolved; no cheapest-match assumption.
Independent FBA/demand/additional evidence is outside this ceiling and cannot be
assumed. Current executable request budget is **zero**. No source product data
calls, registration, provider contact, subscription, scraping, deployment, email
or purchases were performed.

## Validation

PR #22 publishes the exact tree of one-row commit 59c5476 as connector-created
commit d78279c (normal Git push failed DNS). Its Tests run 69
[passed](https://github.com/luiscarlosht/IntelligenceOS-Arbitrage/actions/runs/40513007026).
The subsequent local Walmart extension passes **666 tests** and both documented
offline sample modes. Tests exercise schema/lineage with explicitly incomplete
regression inputs, not replacement product observations. Actual source-data
validation/persistence remains pending receipt of one permitted real row.
