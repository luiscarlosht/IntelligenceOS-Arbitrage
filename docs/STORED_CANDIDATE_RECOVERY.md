# Stored candidate recovery

`app.candidate_recovery prepare` consumes a local missing-only proposal and produces
an immutable hash-bound execution manifest. `check` is read-only. Preparation never
loads credentials, calls providers, changes the ledger, writes Sheets, sends email,
or schedules work. Runtime manifests and source/evidence files stay private and
are excluded from git.

The proposal binds the original manifest/report, source database, shared ledger
location, saved evidence hashes and exact request scopes. Only original search
claims still in `claimed_not_attempted` may be delegated. A SQLite immediate
transaction creates the new execution and all delegation records together. Original
operation ownership remains unchanged; an append-only delegation history records
successive executions. Attempt state is updated on the original operation, using
its current delegate as the authority. Any conflict rolls back the entire transfer.
A shared nonblocking process lock serializes stored candidate execution. Run keys
and operation keys prevent manifest replay, duplicate searches and concurrent
execution. No reservations are deleted or released.

A consumed, failed, completed, parser-rejected or uncertain attempt is never
recovered. After interruption, inspect the durable ledger/checkpoint and prepare a
new separately reviewed missing-only proposal for the current delegate's unattempted
claims. An interrupted JSON rewrite falls back to the retained SQL checkpoint;
the proposal still binds the damaged report bytes. Replaying the previous manifest is forbidden. Preserve previous reports.
Conditional details reuse compatible scoped saved evidence with original observation
timestamps; uncertain/conflicting ASINs remain blocked by the shared ledger.

Operation pacing defaults to 50% of configured limits. `AMAZON_RATE_HEADROOM`
accepts a fraction strictly between zero and one. Existing `AMAZON_RATE_<OPERATION>`
settings set conservative upper bounds. Reported limits may lower those bounds;
they never raise them and do not establish available capacity. Stored live runs
persist UTC cooldowns and 429 pacing diagnostics in `amazon_cooldowns` in the same
private ledger. Successful responses do not erase the last 429 diagnostic. Missing
or invalid Retry-After on 429 imposes at least 60 seconds of cooldown. Every 429
checkpoints and stops the run without retry. Later sequential runs restore UTC
cooldowns; old monotonic values are never reused. Deadline deferral stops before
provider I/O. Recovery also imports the proposal's prior UTC cooldown.

Prepared 2026-10-30: 18 records; at most 37 attempts (1 authentication, 18 searches,
18 conditional details), no pagination, refresh, retries, pricing, fees or
restrictions. Completed searches and the failed Bentgo search are excluded. The
seven bound saved evidence reports remain reusable; B0000AQOAB and B0CFJM217C
remain uncertain/conflicting. This is research evidence, never purchase approval.

Manifest: `var/sheets-amazon-25-partial-verified-20261030/recovery-manifest.json`

SHA-256: `7fd26c08e38a0e76826c98fafe0e8d4065a1ba7f648f1587eda8f1c7ba4b9df5`

Future owner command, after code review, with the prepared private artifacts present:

```sh
ssh -t root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && .venv/bin/python -m app.candidate_recovery run --manifest var/sheets-amazon-25-partial-verified-20261030/recovery-manifest.json --expected-sha256 7fd26c08e38a0e76826c98fafe0e8d4065a1ba7f648f1587eda8f1c7ba4b9df5 --max-attempts 37 --execute'
```

Do not execute this command as part of preparation. Source, report, evidence or
claim changes invalidate verification and require review of a new proposal.
