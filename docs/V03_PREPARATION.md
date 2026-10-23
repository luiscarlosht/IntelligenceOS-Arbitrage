# V0.3 preparation handoff

PR #3 was confirmed merged at `d2e036c627418f67d31002fe3232fb2cf88f991d`
on 2026-10-23. Work began from that fetched origin/main on
`feature/v03-provider-preparation`. Initial checkout was clean; baseline 94 tests
passed. The deployed release remains
`68230d3fdaef588bb7ba5c8340f49a473e8386b7`, with the nonroot reporting timer
enabled/active at 06:00 UTC and most recent service result success/exit 0.
No deployed code, configuration, credentials, data or unit files were changed.

See [official-source research, costs and owner decisions](V03_PROVIDER_RESEARCH.md)
and [backup/restore operations proposal](SQLITE_BACKUPS.md).

## Prepared code boundaries

- `provider_contracts`: separate catalog candidates, fee quote, seller-specific
  eligibility and demand protocols. Evidence carries aware observation time,
  provenance and mock state; freshness rejects future/stale observations. Fee
  quotes include price, marketplace, seller, condition and fulfillment. Demand
  distinguishes lower-bound units from missing/unknown data. It has no rank-to-sales
  estimator. The existing deterministic matcher still checks ambiguity/packages/
  variation, and an exact catalog match cannot grant seller eligibility.
- `mock_evidence`: fictional in-memory contract double. Catalog candidates force
  mock labeling and unknown eligibility; eligibility/fee/demand responses require
  the correct request scope. No double is wired into live application selection.
- `provider_runtime`: injected read-only transport contract with timeout parameter
  (default 10 seconds), at most three attempts by default/five maximum, bounded
  exponential delays and Retry-After support. Only timeout/429/500/502/503/504 retry.
  Other exceptions and 4xx access/payment errors fail with redacted error text.
  Excessive Retry-After aborts rather than retrying early. No socket client exists;
  future adapters must actually enforce the timeout and verified TLS, restrict
  hosts, disable unsafe redirects, cap payload sizes and normalize headers/Keepa
  refill milliseconds before using the policy. This is tested policy preparation,
  not a claim that a network call can yet be made safely.
- SQLite `provider_usage` ledger: positive explicit worst-case units reserved before
  each attempt, including failures/retries, atomic per-provider UTC-month caps.
  Only enum provider/operation labels, units, timestamps and bounded outcome labels
  are stored. No URLs, API keys, seller IDs, product payloads or exception messages.
  Reserved/ambiguous attempts count permanently. Units are requests for SP-API or
  conservative token upper bounds for Keepa; not dollars or vendor invoices. Caller
  supplies an approved numeric cap; there is no hidden default paid budget.
  This is not vendor-wide quota enforcement; future adapters need per-operation
  pacing/token-bucket handling and actual vendor usage reconciliation. There is no
  production usage database or provider runtime configuration change.
- `backups`: online SQLite snapshots, manifest checksums/integrity, bounded retained
  snapshot count, and no-overwrite restore. Proposed daily units are uninstalled.

The application selector continues to accept only `AMAZON_PROVIDER=mock`. Existing
legacy/discovery orchestration, $5/50% gates, 24-hour freshness defaults and fixture
timestamps are unchanged. Reports never constitute purchase approval.

## Validation

Final local validation on 2026-10-23: **116 tests passed**, `pip check` clean,
and `git diff --check` clean. Both documented modes completed successfully with
development history run IDs 1 and 2. Legacy/discovery workbooks contain four/six
sheets and three candidates each; discovery rows are MOCK and never purchase-ready.
Future-clock screening rejects all three stale fixtures. A CLI backup/restore
drill reproduced both final history rows exactly with SQLite integrity `ok`.
Artifacts remain ignored under `var/v03-validation/`. Proposed backup units passed
`systemd-analyze verify`; neither is installed. Final read-only deployment check
confirmed the original release symlink, reporting timer active and service exit 0.
Remote CI status is reported separately in the PR/handoff message.

Checks include
contract scope/missing data/freshness/forced mock labels, retry and timeout policy,
authentication/payment failures, redaction, persistence/month rollover, concurrent
budget reservations, WAL backup/restore, corruption and conservative retention.
Both sample modes use development `var/`, never deployed state. No live network
adapter, paid request, real SMTP, Docker deployment or production restore was tested.
