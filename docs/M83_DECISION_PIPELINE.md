# M83 offline integrated sales and opportunity reporting

This pipeline processes saved, explicitly authorized evidence. It acquires nothing, reads no credentials, and never authorizes sourcing or purchases. A successful synthetic demonstration is software validation, not production readiness.

## Offline demonstration

```sh
python -B -m app.decision_demo --output /tmp/intelligence-fictional-demo
```

Use a fresh directory. The demonstration creates a new fictional 42-slot M80 journal, three fictional source artifacts/receipts and a private history database. Its workbook has twenty synthetic ASINs: one complete fictional economics review proposal, nineteen excluded for missing receipts. It does not modify original M80 evidence. It sends zero network requests. Fictional hashes authenticate only those fictional bytes, never live inventory.

## Owner-supplied input manifest

Create a private input directory outside original evidence and a separate owner-only state directory (`0700`). Do not place credentials, authorization files or account context there. An owner must independently review the original completed M80 ledger and receipt artifacts before recording their SHA-256 pins. Do not turn arbitrary sandbox hashes into trust anchors.

Manifest schema (`schema` must be integer 1):

```json
{
  "schema": 1,
  "ledger": {"path": "/reviewed-original/m80-us-top20-once.sqlite3", "sha256": "OWNER_REVIEWED_ORIGINAL_LEDGER_SHA256"},
  "receipts": [
    {"path": "walmart-quote.json", "sha256": "OWNER_REVIEWED_RECEIPT_SHA256"},
    {"path": "fee-estimate.json", "sha256": "OWNER_REVIEWED_RECEIPT_SHA256"},
    {"path": "risk-review.json", "sha256": "OWNER_REVIEWED_RECEIPT_SHA256"}
  ]
}
```

`receipts: []` is valid and excludes every economic opportunity. Optionally add `handoff: {"path": "/original/M79_walmart_handoff.json", "sha256": "REVIEWED_ORIGINAL_SHA256"}`. Its pin must match the original acquisition plan, and the original M80 source validator must accept it. The workbook then includes all 1,397 original ASINs: observed pilot rows plus the historical unobserved remainder. Historical identity and list prices never become current offers or permission.

Each receipt is a JSON object with `kind` (`WALMART_QUOTE`, `AMAZON_FBA_FEE_ESTIMATE`, `OWNER_RISK_REVIEW`), `asin`, `marketplace`, `account_binding_sha256`, `condition: "new_new"`, `currency: "USD"`, `evidence_class: "CURRENT_LIVE"` (or exclusively `SYNTHETIC` for fixtures), aware `observed_at`, `source_reference`, `owner_reviewed: true`, and `artifact_path` / `artifact_sha256`. The artifact must be a distinct original independently obtained saved file; both receipt and artifact are pinned. Paths may be absolute or relative to their containing manifest/receipt. Source-reference URLs are labels, never fetched.

Quote-specific fields: `identity` (`gtin`, `brand`, `model`, integer `quantity`, `size`, `variation`), `identity_verified: true`, `variation_verified: true`, positive `purchase_price`, and explicit `walmart_shipping`, `sales_tax`, `preparation`, `inbound_shipping`, `packaging`, `other_cost`. The source reference must be HTTPS walmart.com. No requests, scraping, subscriptions, shopping-cart actions or purchases are implemented.

Fee-specific fields: `sale_price`, `fulfillment: "FBA"`, integer package `quantity`, `referral_fee`, `fulfillment_fee`, `storage`, `transaction_cost`. Each cost is explicit USD, including supported zero. This release does not call the fee API; supplying actual fee estimates requires separately approved acquisition or independently reviewed owner-supplied records.

Risk-specific fields: `verified_amazon_identity` and `brand_resale`, `authenticity`, `invoice_acceptability`, `fba_eligibility`, each `VERIFIED_FOR_EXACT_ACCOUNT_AND_PRODUCT`. The reviewed identity can supply previously UNKNOWN size/variation, but cannot contradict any known frozen identity or the current catalog brand/model/quantity/GTIN. Human review must cite the original artifact; a flag is not a provider-issued invoice acceptance guarantee. Retail receipts are not assumed acceptable invoices.

Use `app.opportunity_fixtures.case()` only to inspect a complete fictional schema; it is never a live source. [M82](M82_PROFITABILITY.md) defines exact gates and formulas.

## Reporting saved evidence

```sh
python -B -m app.decision_pipeline \
  --manifest /local/private-inputs/manifest.json \
  --manifest-sha256 OWNER_REVIEWED_MANIFEST_SHA256 \
  --history /local/private-own-state/observations.sqlite3 \
  --output /local/new-report-directory \
  --as-of 2026-11-03T12:00:00+00:00
```

Choose the actual aware review time, not a date that makes stale data appear current. The ledger is inspected read-only with original hash-chain, trigger, scope, response and code-provenance checks. Partial M80 runs remain partial and cannot qualify. Manifest/artifact/code hashes are rechecked before publication. Output must be fresh, private, outside all original input directories, history, deployment volumes and credential paths. Existing reports are never overwritten. A Python audit guard rejects sockets, subprocesses, links, rename escapes and writes outside new output/owned state. This guard assumes trusted Python/native libraries and the same OS user; deployment needs separate kernel isolation.

Outputs:

- `decision-report.xlsx`: executive dashboard; Top 20 research queue; category-relative demand and competition; economics with auditable formulas; historical unobserved ASINs; data quality; history; weekly observed coverage; inventory proposals; input provenance and method.
- `decision-report.json`: authoritative unrounded Decimal economics, explicit gate results and row-level evidence classes. Excel calculation/cache behavior never determines qualification.
- `research-shortlist.json`: exact ASIN/identity, observed prices, timestamps and permission evidence for owner research review. It explicitly denies sourcing/purchase authorization and is not an instruction to a Walmart agent.

Demand ranks are comparable only within exact US category ID/rank type. The selected twenty are not a representative market sample. Offer details can be partial, and Buy Box observations are not win-rate forecasts. Research queue sorts review-ready rows first with deterministic ASIN ties; category sheets carry rank-relative priorities. Profitability ranks complete review proposals by acquisition ROI, then ASIN; excluded candidates remain visible. No global BSR score, monthly-unit estimate, velocity, inventory quantity or realized revenue is invented.

## History and weekly operations

The separate history uses SQLite FULL durability, exact schema, immutable-row triggers and a validated hash chain. Reimporting the same original observations is idempotent even when they are now stale. Original observation content is stored separately from today's freshness-filtered analysis. Synthetic and authorized-live series never pool; historical M79 identities are a separate evidence class.

Price history requires at least seven distinct timestamps spanning at least seven days within thirty days, matching ASIN, account, marketplace, condition, lowest-observed price basis and Amazon fulfillment. It reports an observed price range only, not continuous stability or sales velocity. Conflicting same-time prices fail to UNKNOWN. One pilot snapshot produces UNKNOWN stability. Weekly reporting counts observed ASINs/snapshots by evidence class and ISO Monday week; realized sales, revenue and profit remain UNKNOWN because no realized-sale feed is authorized or implemented.

History is derived local state, not independent provider authentication. A malicious same-user writer could replace an entire chain; preserve owner-reviewed input pins and separately reviewed backups. History append can commit before a final publication race fails; retry offline into a new output is idempotent and never repeats API calls. Do not point history at any acquisition ledger, M77 registry or other existing database.

Remaining live blockers: first Amazon pilot approval/current data; independently acquired matching Walmart quotes, fee estimates, account/product FBA eligibility and risk evidence. Future paid acquisition or sourcing needs separate authorization. No server changes or deployment are performed here.
