# M88 bounded Amazon evidence executor

`app.m88` is a separate manual read-only research CLI. The normal orchestrator,
legacy formulas and $5 profit / 50% acquisition ROI gates are unchanged. It reads
the authentic six-source M88 manifest and pins the saved conditional 31-attempt
proposal, source bytes and application code. It never collects Walmart pages.

The only enabled network operations are:

| Operation | Endpoint | Maximum calls |
| --- | --- | --- |
| LWA authentication | POST `api.amazon.com/auth/o2/token` | 1 |
| Keyword catalog discovery | GET `/catalog/2022-04-01/items` | 6 |
| Candidate detail verification | GET `/catalog/2022-04-01/items/{asin}` | 6 |
| New/Consumer offers | GET `/products/pricing/v0/items/{asin}/offers` | 6 |
| Base-price FBA and FBM fee estimates | POST `/products/fees/v0/items/{asin}/feesEstimate` | 12 |

All SP-API operations use `sellingpartnerapi-na.amazon.com` and US marketplace
ATVPDKIKX0DER. Maximum: **31 attempts**, within the existing **49 cumulative
attempts**, including authentication, failures and uncertain dispatches. There
are zero retries, refreshes, pagination, exploratory operations or automatic
restarts. Unused authorization does not enable additional operations. Search
uses the supplied title plus original package description, at most ten results
and the summaries/identifiers/relationships/attributes/salesRanks datasets.
The source must be <=24 hours old, with an aware timestamp.

[Amazon Catalog reference](https://developer-docs.amazon/sp-api/lang-en_us/reference/searchcatalogitems),
[New offers reference](https://developer-docs.amazon/sp-api/lang-de_DE/reference/getitemoffers),
and [Fees API roles](https://developer-docs.amazon/sp-api/lang-en_EN/docs/product-fees-api)
were checked for this milestone. Actual account entitlements are verified only
by authorized attempts; token possession is not an assertion of every role.

## Preparation and credential readiness

Use Python 3.12 with project requirements. Supply real paths and digests; never
put credential values, tokens or seller IDs in command arguments or chat.
`prepare` reads only credential metadata. Credentials must already exist in the
owner-only research directory outside Git, normally
`~/.intelligenceos-arbitrage-amazon/credentials.json`. No credential entry,
rotation, file rewrite or production configuration is performed.

```bash
python -m app.m88 prepare --source <six-product-manifest.json> \
  --source-sha256 <source-sha256> --preview <amazon-request-plan.json> \
  --ledger <existing-amazon-http-attempt-ledger.json> --output <new-operation-dir>
sha256sum <new-operation-dir>/plan.json
```

The existing ledger is mandatory and is not created, reset, migrated or modified
by preparation. An output already present is refused. Review the exact plan and
credential-readiness status before execution. Both source and saved proposal must
remain unchanged. Fees additionally need an explicitly supplied `--account-context`
private file with `seller_id` and `credentials_sha256` bound to the existing
research credentials. Without it, fees are skipped and remain unknown. A prior
milestone's authorization/ledger is never reused. No account context is invented.

## Matching and evidence gates

Every returned candidate is normalized with the existing catalog parser. Missing
or conflicting identifiers, mapping issues, differing brand/model/size/variant/
pack, unverified source identities and incomplete result coverage block selection.
Exactly one fully verified candidate on a complete first page is required before
detail retrieval. Detail evidence must pass the same gate again before offers.
Title similarity is never sufficient. Missing Walmart GTIN/brand/selected variant
cannot be filled from a plausible Amazon result. For the current supplied cohort,
source verification gaps are expected to limit a successful run to 1 auth + 6
searches, with all matches unresolved; this is useful candidate evidence, not
permission to relax the identity gates.

New competition uses only the response's explicit New-condition count. Mixed
aggregate counts, rank and search-result totals cannot supply demand or New
competition. New buy-box listing price with explicit zero buyer shipping may
support a **hypothetical base fee scenario**, only when offer coverage passes the
existing parser. It is not a confirmed achievable sale quote. Fees remain price/
mode/account-bound estimates; merchant fulfillment, storage, tax, source shipping
and other missing inputs remain unknown. Conservative/optimistic scenarios are
not extrapolated. Eligibility and monthly demand remain unknown.

## Execution, accounting and recovery

Each outside-sandbox network command needs the session's individual approval.
The owner-authorized exact plan is supplied by SHA256:

```bash
python -m app.m88 execute --plan <operation-dir>/plan.json --plan-sha256 <plan-sha256>
python -m app.m88 recover --plan <operation-dir>/plan.json \
  --plan-sha256 <plan-sha256> --output <fresh-report-dir>
```

`execute` holds the existing account execution lock plus a lock beside the original
M88 ledger. Before each possible dispatch it atomically replaces the original
ledger after file fsync, then fsyncs its directory. Attempt counts are monotonic;
COMPLETE/FAILED outcomes never refund them. Each phase/candidate can be attempted
once, with per-phase and global caps. A permanent operation claim in that ledger
prevents rerunning the cohort even with a renamed or regenerated plan. Do not
restore an old ledger or delete the claim to resume: this would defeat cumulative
accounting. Credential values are read only after scope/digest/lock checks.

Normalized evidence receipts are exclusive 0600 files with hashes in the ledger.
Raw vendor payloads, bearer tokens and credential values are not persisted. The
existing TLS transport disables inherited proxies, redirects and retries; body
sizes and 10-second socket timeouts are bounded. The run has a 600-second alarm
and token-expiry guard. Existing pacing limits are reduced conservatively and
stricter returned rates are honored. Any transport/HTTP/parser failure stops the
whole run without retry. Fixed allowlisted diagnostic metadata is retained.

An interruption after a reservation is conservatively charged even if dispatch
cannot be proven. `recover` never reads credentials, sends HTTP, refreshes a token,
changes the ledger or replays requests. It verifies completed receipt hashes,
excludes RESERVED evidence, lists unknown outcomes and writes fresh reports.
Missing or tampered completed receipts stop publication rather than reconstructing
evidence. A failed pre-dispatch run may have 0 attempts but is still not rerun
automatically. An operator must inspect the preserved operation status.

Reports: `comparison.json`, `comparison.xlsx`, `normalized.json`,
`enriched-batch.json`, `missing-data-report.json`, `execution-report.json` and
`executive-summary.md`, through existing M87/M86 math/reporting. Outputs are
exclusive private directories; old artifacts remain intact. Any result can be
INSUFFICIENT_DATA. `purchase_authorized=false` throughout. No purchases, listings,
inventory changes, paid services, Google Sheets writes or production deployment.

## Owner-authorized M88 execution, 2026-11-05

After the final plan/credential-readiness summary was shown, a separately approved
outside-sandbox command completed 1 LWA authentication plus 6 Catalog searches.
The original cumulative ledger advanced from 0/49 to **7/49**, all COMPLETE,
with no failed or uncertain attempts. Sixty candidate records represented 56
distinct ASINs. Each response was a partial first page (10 returned, estimated
result populations 77–247); no pagination was attempted. All six pairings remain
unresolved because source identity evidence and result coverage are insufficient.
No detail, pricing or fee requests were sent. Fee-account context was unbound.

Private versioned JSON/Excel/missing-data/executive reports were generated through
M87/M86 and all six financial assessments remain INSUFFICIENT_DATA. No candidate
was promoted from title similarity. The source observations and previous reports
were preserved. Credentials were not modified, token values were not persisted,
and purchase_authorized remains false. Remaining authorization is 42 cumulative
attempts, **not** authorization to replay this completed one-shot operation. Further
collection requires reviewed source identity evidence and a separately scoped
continuation that retains this ledger; this executor intentionally refuses replay.
