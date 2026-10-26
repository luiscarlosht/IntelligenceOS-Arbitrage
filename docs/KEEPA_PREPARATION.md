# Keepa adapter preparation — live disabled

## 2026-10-26 offline composition follow-up

The new [fixture pilot](REAL_DATA_PILOT.md) reuses this adapter and persists only
normalized **fictional fixture** enrichment in a separate pilot SQLite database.
It does not enable live caching/storage rights, load keys or change the false
code gate. Its request policy has one attempt per ASIN; historical three-attempt
math below describes the adapter's earlier default, not the new offline runner.
The prior rendered plan-price check below is dated 2026-10-23; today's public
pricing fetch returned only a JavaScript shell. The owner must confirm current
checkout/terms, retention/deletion and policy compatibility using the
[pilot account checklist](PILOT_ACCOUNT_ACCESS.md) before any live use.


Official public sources checked 2026-10-23 UTC, including rendered Keepa pages
through the public browser when text retrieval returned only a JavaScript shell.
No login, account, API product request, credential access, subscription or purchase
was performed. This supersedes the older unverified Keepa pricing paragraph in
V03_PROVIDER_RESEARCH.md; it does not refresh any product observation or fixture.

## Official pricing and small-run cost

The [official API pricing page](https://keepa.com/api/pricing) publicly displays:

| API plan | EUR/month | Tokens/minute |
| --- | --- | --- |
| Starter | 49 | 20 |
| Developer | 459 | 250 |
| Business | 2,499 | 2,000 |
| Enterprise | 11,099 | 10,000 |

[API terms](https://keepa.com/terms) state net prices with applicable VAT added
before ordering. The browser-oriented [Keepa Pro page](https://keepa.com/data)
is a separate €29/month subscription; do not buy it expecting API tokens.
Recheck checkout, account eligibility and tax before an approved purchase.

A proposed validation run uses **5–10 explicitly authorized US ASINs**, one basic
request each, update=-1, history=1, days=1. This asks for existing vendor records,
not forced refresh. The [product endpoint](https://keepa.com/api-docs/product.html)
charges at most one basic token per requested ASIN in this mode (missing records
with update=-1 may cost zero). Reserve 5–10 tokens for one pass, or **15–30 tokens**
for the maximum three attempts per ASIN, including ambiguous timeouts. All misses
and retries count against the conservative local reservation budget. No code or
UPC search, offers, rating, buybox, stock or historical-variation options are enabled.

Cash cost of starting without a subscription is **€49 for the initial Starter
monthly period + applicable VAT + FX/payment charges**, not a per-token fractional
payment for ten products. If already subscribed, no extra plan charge is expected
only if the owner's actual entitlement/balance covers the authorized run; no such
account is verified here. Small workload does not justify a claim of a free trial.
USD budget = 49 × actual approved USD/EUR conversion + taxes/charges; confirm
before buying because this may exceed the project's <$50 monthly target.

The [token model](https://keepa.com/api-docs/plans-tokens.html) bills monthly in
advance, replenishes each minute, and expires unused tokens after 60 minutes.
Starter's nominal bucket is 1,200 tokens; this is capacity, not this project's
verified balance. No rollover or pro-rata sample price is assumed.

Optional requests cost more and remain unsupported. The detailed product page
supersedes the overview's simplified offer formula: offers replace the base ASIN
charge and use six tokens per found page, with no-offer/failure special cases;
forced update, ratings, buybox, stock and variations also have conditional costs.
Do not add an option without updating tests and conservative reservation math.

## Licensing, cache and deletion

[API terms §18](https://keepa.com/terms) permit storing/caching/processing API data
and using derived results in the subscriber's products/services. Internal resale
analysis appears consistent with that permission; this is an interpretation, not
verification of an active license for this account. Supplying the underlying data
as a resold dataset, feed or programmatic retrieval service requires prior written
consent. Do not distribute API keys.

After termination the terms require ending retrieval/current-source use and
deleting stored data within 60 days, with qualified exceptions for derived works,
records and normally overwritten backup copies not restored to active use. Owner
must review the full conditions for their use and retention obligations. No
separate active-subscription cache TTL was found; token expiry is not data expiry.

Adapter caching is disabled by default. Optional normalized in-memory cache needs
an explicit permission reference and owner-approved retention duration; TTL cannot
exceed that duration. Capacity is 64 entries. Expiry is checked before reuse and
on subsequent lookups, not by a background eraser; `close()` clears and revokes
the adapter, and process exit clears memory. Do not claim timed secure erasure.
No vendor response payload, persistent database cache, CSV export or backup copy
is generated by this adapter. If future reports persist vendor data, document
retention, deletion and backup obligations before enabling them. Nothing here
asserts permission to merge Keepa data with future SP-API data: Amazon AUP review
and owner authorization remain separate gates.

## Implemented scope and disabled-live boundary

`app.keepa_adapter.KeepaAdapter` implements catalog, demand, eligibility and fee
contract methods. It is **opt-in** (`enabled=True`) and accepts explicit mock
transports only while the code-level LIVE_CALLS_ENABLED=False. Config still accepts
only AMAZON_PROVIDER=mock; jobs never select this adapter. No environment setting
or credentials can enable Keepa live calls in this release.

`app.keepa_http.KeepaHttpTransport` prepares a dormant fixed HTTPS endpoint with
verified TLS, no redirects/proxy inheritance, gzip support, socket timeout and
512 KiB wire/decoded bounds. The live gate is checked before even invoking the
credential loader. Future activation needs an explicitly authorized code review,
secure key injection and account/license/cost checks. Keepa requires keys in query
parameters, so transport exceptions are replaced with fixed errors; never enable
URL-level debug logging, proxy access logs, or HTTP tracing containing credentials.
No real credential or network transport is used by contract tests.

Only one explicit ASIN per request and US domain 1 are supported. A 30-token/month
local default cap reserves one unit **before every attempt** in the existing SQLite
UsageLedger and never refunds ambiguous failures. Reservation outcomes describe
transport success/failure, not proof that evidence is complete. One-second minimum
request spacing is shared through an atomic SQLite pacing record across processes
using that ledger. Waits beyond policy maximum are deferred by failure. Keep all
future users of an account on one ledger; this is not account-wide vendor billing.

An explicit initial available-token floor is required (default zero); successful
responses can only lower it. No optimistic refill or plan-rate assumption occurs.
A new authorized run would need a verified vendor balance; arbitrary resets or
separate ledgers can bypass local accounting and are not an approved workflow.
The adapter does not independently call the token endpoint. Unexpected reported
cost above one token stops the adapter; the reservation guarantee assumes the
vendor follows the documented fixed-request pricing, not an absolute billing cap.

Existing Policy bounds attempts (default 3), timeout (10 s), exponential backoff
and maximum delay (30 s). 400/402/405 fail without retry; timeouts and supported
transient errors retry within the cap. 429 refillIn milliseconds are converted to
seconds; long refills abort instead of shortening the vendor wait. Exhausted
known tokens never refill speculatively. Future multi-instance clients need a
shared authoritative token state before broader rollout. No tracking, search,
background refresh or unbounded pagination is implemented.

## Evidence interpretation and conservative gates

[Product field documentation](https://keepa.com/api-docs/product-object.html)
defines Keepa timestamps in minutes from 2011-01-01. The adapter separately
preserves product lastUpdate, each latest Amazon-price/rank point's timestamp,
lastSoldUpdate and actual response retrieval time. Negative/unavailable sentinel
values become missing, not zero. Malformed, future or unordered histories cannot
produce price evidence. Stale values retain their original timestamps;
Evidence.fresh() remains the consumer's freshness gate. Cache hits do not update
observation or retrieval times. Only STANDARD products are normalized; parent,
invalid, inaccessible and non-US responses do not become review candidates.

`monthlySold` is a variation-specific bought-past-month **lower-bound bracket**,
not exact sales or a future guarantee. It uses its own lastSoldUpdate. Sales rank
is a separate indicator; rank/drops are never converted into monthly sales.
The legacy listing.monthly_sales remains None, including when a bracket exists.

Amazon-price history is a separate observation, **not** an assured resale quote
or selected Buy Box. The listing's sale_price, costs, seller_eligible, offer_count,
GTIN, exact package quantity and variation remain missing. Explicit ASIN hints
only retrieve candidate metadata and never establish eligibility or exact match.
Fee and eligibility methods return Evidence(value=None) without a provider call;
the timestamp on absent Evidence denotes retrieval/unknown-result time, not a
fabricated seller/fee observation. Missing catalog/demand observation times never
produce corresponding value evidence. Existing discovery screening remains blocked
on absent identity/package/variation, price, costs, demand, competition and eligibility.

## Mock usage and validation

Use tests rather than a credential-bearing CLI:

```bash
.venv/bin/python -m pytest -q tests/test_keepa_adapter.py
.venv/bin/python -m pytest -q
```

Mock request/response builders in tests are explicitly fictional, with a fixed
clock and no production fixtures overwritten. Tests exercise disabled-live/key
loader isolation, contract values, independent timestamps, lower-bound demand,
sentinels, stale/future/malformed data, parent/identity mismatch, cache permission/
TTL/bounds/revocation, shared pacing and monthly budgets, charged retries, long
429 refill, 402 failure, gzip bounds, TLS/redirect policy and redacted exceptions.
Dormant HTTP branches are tested only after replacing the entire opener with a
fake; no real HTTP requests occur. No test is skipped to claim readiness.

## Remaining owner gates

1. No authorized ASIN/source sample currently exists. Obtain permitted product
   inputs and confirm business/marketplace identity before planning a live run.
2. Review current API terms and Amazon AUP compatibility, confirm the actual API
   account/price/VAT/FX and approve the cash budget; do not subscribe under this PR.
3. Choose retention/permission reference; leave cache disabled unless authorized.
   Add deletion inventory if reports or persistent cache are introduced later.
4. Only a later live-enablement PR may change the code gate/provider selector and
   provision credentials securely. Never send keys in chat or commit URL-bearing
   logs; no deployment or live request is authorized now.
5. **Scan Profit remains blocked:** official product URL and API/export permissions
   are unidentified. No guessed vendor, scraping connector, API endpoint or account
   integration is created.

## Validation result

152 baseline tests; **189 final tests passed** locally and from a clean source
export without a repository .venv, using Python 3.12 and CI-matching pinned runtime
and test dependencies. Both sample workflows succeeded in that clean export;
pip check and diff check passed. All provider responses and credentials in tests
are fictional. No live Keepa/Amazon request or credential lookup occurred, and no
production files/services were changed. Remote CI is separate and must pass for
the published PR. Close the adapter immediately when authorization is revoked;
the post-termination deletion deadline is not permission to keep making requests.
