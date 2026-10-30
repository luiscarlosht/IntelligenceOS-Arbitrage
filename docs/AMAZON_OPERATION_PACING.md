# Amazon operation pacing and listing approval details

The manual SP-API transports use monotonic, operation-specific pacing without
burst consumption or automatic retries. Defaults verified against Amazon's
official documentation on 2026-10-30:

| Operation | Requests/second | Documented burst |
| --- | --- | --- |
| getCatalogItem | 2 | 2 |
| searchCatalogItems | 2 | 2 |
| getItemOffers | 0.5 | 1 |
| getMyFeesEstimateForASIN | 1 | 2 |
| getListingsRestrictions | 5 | 10 |

Sources: [catalog](https://developer-docs.amazon/sp-api/docs/catalog-items-api-rate-limits),
[item offers](https://developer-docs.amazon/sp-api/reference/getitemoffers),
[fees](https://developer-docs.amazon/sp-api/reference/getmyfeesestimateforasin),
[restrictions](https://developer-docs.amazon/sp-api/docs/listings-restrictions-api-rate-limits).
Catalog application limits also apply (250/s get, 500/s search, keyword search
50/s); restrictions have a 20/s application limit and count each marketplace
separately. Current adapters use one US marketplace. Header rates describe the
account/application pair and do not override other Amazon limits.

Configure each rate with `AMAZON_RATE_` plus the uppercase operation name,
for example `AMAZON_RATE_GETITEMOFFERS=0.25`. Values must be positive finite
requests per second. Programmatic `OperationPacer(rates=...)` and clock/sleep
injection support deterministic tests. A positive finite response
`x-amzn-RateLimit-Limit` updates only that operation. Existing reservations
are never shortened. `Retry-After` supports seconds and HTTP dates, translated
to monotonic time. Invalid headers are ignored. A 429 without Retry-After
reserves at least one operation interval. No failed request is replayed.

Enrichment durably reserves each attempt before transport, checkpoints sanitized
HTTP status/error codes and pacing metadata including a UTC not-before time,
and continues independent stages. A wait beyond the execution deadline records
`pacing_deferred` without sending that request. Attempt reservations are never
reset. Pacing state is process-local, intended for the sequential manual runner;
independent processes do not coordinate quotas. UTC diagnostics allow operators
to honor cooldowns before a later authorized execution; restarting a process
does not automatically load prior cooldowns or authorize another execution.

Restriction evidence retains returned reason codes, messages and links. The
report includes literal instructions and one row per link with its associated
reason. Only HTTP(S) GET links without credentials/control characters become
clickable; other supplied links remain literal text. Missing instructions stay
UNKNOWN. Listing permission, approval required, purchase approval and overall
seller/FBA eligibility remain separate. A hypothetical FBA fee estimate is not
FBA eligibility evidence.

Validation uses synthetic responses only. No live Amazon calls, credential
access, email, scheduling or Sheet changes are part of this work.

## Candidate run-research wiring and concurrency boundary

`python -m app.candidate_execution run-research` selects `execute_research`.
After validating the manifest and durably reserving an operation in
`ExecutionJournal`, its call wrapper invokes `OperationPacer.call` with the
execution deadline. The production path shares `amazon_pilot.default_pacer()`
and calls the raw verified transport exactly once. Injected transports use the
same pacing logic with injected clocks. The old common research interval is no
longer used for dispatch. Mocked tests exercise the production transport-selection
branch, verify a response header changes the next pricing start to four seconds,
and verify a pricing 429 leaves restrictions runnable and claims consumed.
Research is limited to requested pricing and restrictions; it does not estimate
fees, verify source identity, grant approval or establish FBA eligibility.

**Pacing is process-local. Concurrent runs/processes are not quota-coordinated.**
The shared in-process pacer supports sequential calls, not concurrent threads.
The durable execution journal prevents replay of claimed work; it is not a
shared Amazon quota limiter. Restarted processes do not automatically restore
cooldowns. Use a single sequential executor and honor saved UTC not-before times
before separately authorized executions. Coordinated concurrent execution needs
a separate shared limiter before it can safely be enabled.
