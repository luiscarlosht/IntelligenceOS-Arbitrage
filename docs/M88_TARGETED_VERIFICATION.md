# M88 targeted Catalog verification continuation

`app.m88_targeted` implements the next explicitly owner-authorized M88 scope.
It ranks the 26 NEEDS_REVIEW source/ASIN pairs from the pinned enriched-source
reconciliation. Barcode overlap and observed brand/model labels drive research
priority; the Duracell eight-count, pack-of-one size string is a labeled packaging
clue, never proof of count-basis equivalence. Scores are not identity confidence.
The highest-ranked Elmer/Gorilla candidates plus the strongest Duracell candidate
are selected under the owner's priority. No broad searches are enabled.

## Fixed endpoint budget

| Phase | Endpoint | Maximum new HTTP attempts |
| --- | --- | --- |
| Authentication | POST `api.amazon.com/auth/o2/token` | 1 |
| Targeted Catalog details | GET `/catalog/2022-04-01/items/{asin}` | 3 |
| Conditional New/Consumer offers | GET `/products/pricing/v0/items/{asin}/offers` | 3 |
| Conditional base FBA/FBM estimates | POST `/products/fees/v0/items/{asin}/feesEstimate` | 6 |

Marketplace is ATVPDKIKX0DER. The initial detail pass consumes at most 4 attempts;
the full conditional operation permits at most **13 new**, taking the original
7/49 ledger to at most **20/49**. Zero searches, pagination, retries or token
refreshes. Each outside-sandbox network command requires session permission.

Catalog requests use summaries, identifiers, relationships, attributes and
dimensions. The supported datasets are documented in
[Amazon getCatalogItem](https://developer-docs.amazon/sp-api/lang-en_US/reference/getcatalogitem)
and the [Catalog API reference](https://developer-docs.amazon/sp-api/lang-en_US/docs/catalog-items-api-v2022-04-01-reference).
The prior search normalization did not retain part numbers, formulation attributes
or dimensions; targeted reads retain those allowlisted fields with units/scope.

## Scope, accounting and recovery

Preparation requires the original reconciliation and its SHA256, a private fresh
output, the existing research credential directory and the unmodified 7/49 ledger.
It validates original input hashes and pins source batch, reconciliation, targets,
code and credential metadata. Credential values remain unread. The prepared plan
and ranking expose minimum Amazon fields and unresolved source evidence per target.
Targets are rederived from the pinned ranking before dispatch, preventing a plan
edit from expanding scope even when its digest is recomputed.

```bash
python -m app.m88_targeted prepare --reconciliation <candidate-reconciliation.json> \
  --sha256 <reconciliation-sha256> --output <fresh-operation-directory>
sha256sum <fresh-operation-directory>/plan.json
# Review exact endpoints, scope, budget and credential readiness first.
python -m app.m88_targeted execute --plan <operation-directory>/plan.json \
  --plan-sha256 <reviewed-targeted-plan-sha256>
python -m app.m88_targeted recover --plan <operation-directory>/plan.json \
  --plan-sha256 <reviewed-targeted-plan-sha256> --output <fresh-report-directory>
```

Optional `--account-context` uses an existing private seller-context file with
seller_id and credentials_sha256, bound to the existing research credentials. No
account entry/change or credential value is requested in chat. Without that
context, fees stay unknown. Offers and fees are conditional on the unchanged
strict exact-identity gate; a competing sale price is only a hypothetical scenario.

`TargetedJournal` appends to the **original authoritative JSON ledger**. The first
seven attempts and original `m88_operation` claim remain immutable, checked by a
prefix hash. A separate permanent `m88_targeted_verification` claim is saved with
the first reservation. No ledger is reset or replaced with a lower-count copy.
The original account lock and ledger lock serialize operations. File and directory
fsync precede every possible dispatch; every outcome, including failure or an
interrupted uncertain request, remains charged. Phase counts, source scope,
dependencies, repeat prevention and the absolute 49 ceiling are enforced.
The targeted claim prevents replay under a renamed/regenerated plan.

The existing verified TLS transport ignores inherited proxies, disallows redirects
and retries, bounds bodies to 1 MiB and uses 10-second socket timeouts. Existing
conservative pacing and stricter returned rates apply under a 600-second overall
alarm/token-expiry guard. Credentials/tokens/seller IDs are scrubbed from receipts
and logs; token material remains memory-only. Any HTTP/transport/parser failure
stops the operation. Credential values are read only after scope/locks/history
checks. Original pilot code and its no-replay policy are not relaxed.

`recover` makes no requests or credential reads and never changes counts. It
verifies receipt hashes/bindings and writes new private M87/M86 reports, excluding
RESERVED evidence and listing uncertain outcomes. Missing/tampered receipts stop
publication. Historical ledger hashes are explicitly labeled historical; a
separate current ledger hash is included in new provenance.

## Identity evidence rules

Manufacturer/model and independently scoped `part_number` are retained separately.
Unknown or foreign-market part numbers are never filled from source data or model
labels. UPC/EAN/GTIN alternatives are retained without choosing one by convenience.
Allowlisted item_form, included_components, size/color/style, unit_count,
number_of_items, item_package_quantity, dimensions and package relationships keep
their original units and marketplace scope. No model alias, contents/package count
equivalence, liquid/weight conversion or source correction is inferred.

Field comparisons expose source and Amazon evidence for GTIN, model, MPN, brand,
formulation, size, quantity and packaging. Source verified flags, human-signoff
status and all supplied source conflicts remain unchanged. Independent Amazon
data cannot erase Walmart's Gorilla 0.5 oz conflict or provide missing source
packaging evidence. No identity is accepted from title or barcode overlap alone.

## Actual authorized execution, 2026-11-05

The final reviewed plan selected:

| Walmart item | Amazon candidate | Rank among 26 | Minimum clarification |
| --- | --- | --- | --- |
| 17011265 — Elmer | B000Q3KHCM | 1 | Model/MPN correspondence, barcode package applicability, formulation/pack |
| 721324153 — Gorilla | B07GQ1CT47 | 2 | Model/MPN correspondence, barcode package applicability, source size conflict |
| 13952053139 — Duracell | B003SI0TD4 | 10 | Model/MPN, UPC/retail-pack correspondence, eight cells versus one package |

After the endpoint/budget/readiness summary and an approved outside-sandbox
command, **4 new attempts** completed: 1 authentication + 3 Catalog details.
The authoritative ledger advanced from **7/49 to 11/49 COMPLETE**; 38 remain.
No failures or uncertain outcomes. No offer/fee calls, retries or broad searches.

- Elmer: independently returned model and MPN E304 versus Walmart model
  SAP_2089725 / MPN 2089725. Three canonical barcode alternatives remain.
  Amazon White color and Clear included-components wording require review.
- Gorilla: Amazon model/MPN 4572502 versus Walmart 1906833. Four barcode
  alternatives remain. Amazon 5.75 Fl Oz, Liquid/Clear and one bottle evidence
  do not resolve the source's conflicting 0.5 oz text.
- Duracell: Amazon model field 1 is distinct from part number MN1500B8Z. Amazon
  UPC 041333825014 differs from Walmart 041333051604. The 8 Count unit_count
  and one package observations are retained without equating cells and packages.

**Zero verified matches**; all six products remain INSUFFICIENT_DATA and zero have
supported profitability calculations. No source identifiers or prices were
replaced, and no aliases were forced. Normalized evidence and dimensions are
retained in private receipts. Source conflicts, screenshot references and lack of
independent human signoff persist. A cryptographically verified projection of the
original seven-attempt ledger is saved as an audit-only snapshot, never an active
ledger or a restoration source; its bytes match the pinned pre-execution SHA256.

New private outputs: ranking/plan, receipts, targeted-evidence.json,
comparison.json, comparison.xlsx, missing-data-report.json, executive-summary.md,
execution-report.json and targeted-findings.md. Previous artifacts remain intact.
No purchases, listings, inventory/account/credential changes, paid services,
Sheets writes, merge or deployment. purchase_authorized=false throughout.
