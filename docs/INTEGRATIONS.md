# Integration contracts and access

## Available now

| Integration | Runtime implementation | Network / credentials | Incremental service cost |
| --- | --- | --- | --- |
| Legacy candidate CSV | `pipeline.load_candidates` | Local user-owned file | $0 |
| Normalized retailer CSV | `connectors.CsvConnector.products` | Local user-owned file | $0 |
| Amazon matching fixtures | `marketplace.MockAmazonProvider.match` | Local JSON; forced mock labeling | $0 |
| SQLite history | `history.History` | Local filesystem | $0 |
| Excel | `reporting.write_report` | Local filesystem | $0 |
| Optional SMTP | `mailer.send_report` | User-configured provider with TLS; authentication optional | Provider-specific; not enabled by default |

V0.2 has no live Walmart, Walgreens, Target, Amazon or demand data integration. Retailer labels in sample fixtures are fictional. No scraping or product URL requests occur. There are no AI/API calls and no new paid service costs. Local CPU/storage and existing hosting still have operational costs. CI consumes the repository owner's available Actions quota; no paid allocation is authorized.

## Retailer contract

`RetailerConnector.products() -> Iterable[RetailProduct]` streams records. Implement authorized APIs/licensed feeds/permitted URL resolvers behind this interface only after reviewing authorization and usage terms. Record source identity, per-item retrieval time and meaningful provenance. A URL supplied by a user is not authorization to fetch it. Plan timeouts, pagination, rate limits, freshness, retry budgets and per-source errors before enabling remote adapters.

CSV headers required for parsing: `retailer,name,purchase_price`. Screening additionally requires URL, package quantity, in-stock status, timezone-aware `retrieved_at`, `provenance`, and either valid GTIN or manufacturer/model identity against a listing. Optional `asin_hint` narrows candidate lookup but never proves identity. `variation` must explicitly identify the variant; use `standard` for products with no variants. Missing variation evidence blocks exact matching even if both sides omit it. GTIN check digits are validated and valid identifiers normalized to GTIN-14 without losing leading zeroes. Bad row values are retained as quality issues instead of silently dropped. Missing headers/duplicate headers fail the job.

## Amazon contract

`AmazonProvider.match(product) -> Match` returns a listing, exact flag, confidence and reasons. ASIN hints, GTIN or exact manufacturer+model find candidates. Conflicting identifiers, ambiguous candidate sets, variant mismatch or unknown/mismatched package quantities block exact matches. Manufacturer/model normalization changes only case and whitespace; punctuation remains significant. No fuzzy AI matcher is enabled. Match confidence is 100 for deterministic verified identity/quantity/variation agreement, otherwise 0; it is not eligibility or a resale guarantee.

Mock JSON is an array of listing objects; see `sample_data/amazon_mock.json`. Every entry is forced `is_mock=True`, even if a fixture claims otherwise. Costs are USD amounts per unit, including explicit zeroes where applicable. Every cost in `profitability.COST_FIELDS` is required; `referral_rate` may replace fixed `referral_fee`. Rate is a fraction (0.15 = 15%), takes precedence, and must be less than 1. `verified_costs` names supplied verified fields, but mock results always retain an estimated basis. Costs such as inbound shipping and source sales tax are source-specific; providers must supply an appropriate quote for each source offer rather than blindly sharing those costs across retailers. `monthly_sales` and `offer_count` are supplied indicators, not estimates inferred by this application. Missing evidence is not zero.

Sample fixture timestamps are fixed at 2026-10-23 UTC. They intentionally become stale after the configured maximum age. Tests use a fixed clock for fixture screening. Refresh a user-owned snapshot only when new evidence was actually obtained; do not relabel stale data as fresh.

## V0.3 preparation — research and offline contracts

See [current official-source research and cost gates](V03_PROVIDER_RESEARCH.md)
and [implementation handoff](V03_PREPARATION.md). Typed evidence/provider boundaries,
fictional contract doubles, bounded retry/timeout policy and a SQLite usage
reservation ledger are prepared but not connected to live provider selection.
Current pricing/entitlement gaps are explicitly identified, not assumed free.

## Future providers — research gates

SP-API, Keepa, authorized retailer feeds and licensed data providers remain disabled. V0.3 research records available official requirements, unresolved price quotes and an explicit workload/cost model. Account-specific permissions, current API billing and licenses still require owner confirmation. Free access must not be assumed. Obtain approval before subscribing/enabling paid services. Configure credentials securely at runtime; never put keys in fixtures, logs, PRs or chat. Do not reuse or inspect another application's production credentials.

## No source available — access comparison

The owner has confirmed no authorized product source is available. Live collection
remains disabled. [Supplier access options](SUPPLIER_ACCESS_OPTIONS.md) compares
official access/permission/cost evidence and proposed small-sample requests;
no provider has been contacted, account created or feed downloaded.
