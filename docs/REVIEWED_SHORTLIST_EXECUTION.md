# Reviewed shortlist detail execution

`python -m app.candidate_execution prepare-shortlist --reviewed-plan PATH --manifest OUTPUT`
creates a separate executable manifest from the offline reviewed shortlist. The
existing `run-details` action accepts both legacy single-candidate manifests and
the new nested candidate outcomes. Execution requires `--execute`, the exact byte
SHA-256 and an explicit attempt cap. Preparation never loads credentials.

Every original source row remains one product, with original intake JSON, source
fingerprint, observation timestamps and saved search unchanged. Reviewed candidate
outcomes are nested under their source; no winner is imposed. Detail HTTP requests
are deduplicated by US ASIN and linked to all relevant source/candidate pairs.
JSON, durable SQL/checkpoints and a separate workbook tab retain candidate evidence,
review reasons, alternatives and independent completed/failed/unattempted outcomes.
Successful historical evidence keeps its original observation time.

Preparation rebuilds the reviewed plan from its protected input hashes and mtimes,
checks the complete current report inventory and validates source batches read-only.
Execution repeats validation, requires the original shared private directory, and
claims all requested ASIN operations in one transaction before credentials. Prior
claims block regardless of run key or operation key; uncertain claims are never
cleared. HTTP attempts are durably consumed before I/O. Authentication/detail or
parser failure stops the run without retries and preserves all outcomes.

For the 2026-10-30 review, all 38 saved searches and Energizer AA B004U429ME detail
are reused. Eight missing details include both Energizer AAA B004U42A28 and
B0D51H9LQP. Maximum: one authentication plus eight details, nine HTTP attempts.
Searches, retries, pagination, pricing, fees and restrictions are absent. There
is no purchase approval, automatic execution, deployment or scheduler change.

The actual private executable manifest was rebuilt byte-for-byte offline at
`var/sheets-amazon-38-review-20261030/shortlist-execution-manifest.json`.
SHA-256: `7e05214dec0c0932c26e8f307d5cbc08f51561df254d5b09b6f43bfe5bf4ecfc`.
Runtime artifacts remain ignored and excluded from the PR. Changed source,
evidence or reservations require fresh review; the command must fail closed.

Future owner action only (not executed during preparation):

```sh
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && .venv/bin/python -m app.candidate_execution run-details --manifest var/sheets-amazon-38-review-20261030/shortlist-execution-manifest.json --manifest-sha256 7e05214dec0c0932c26e8f307d5cbc08f51561df254d5b09b6f43bfe5bf4ecfc --max-attempts 9 --execute'
```
