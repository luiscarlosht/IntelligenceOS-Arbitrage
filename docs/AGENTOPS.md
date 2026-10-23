# AgentOps supervisor plan

## Existing observability

JSON events report job start/success/failure with UTC time, run ID and exception class. SQLite retains running/succeeded/failed records, candidate counts, report paths and failure classes. Six-sheet discovery reports expose rejection reasons, missing/stale evidence, estimation basis, provenance and evidence scores. No exception text or credentials are logged.

## Future event-driven supervisor (V0.4)

Consume failed jobs and aggregated source-health/quality events. Detect missing data, matching ambiguity/drift, profitability outliers, unusually high error/rejection rates, runtime/memory regressions and API spend. Measure source freshness, match accuracy against labeled examples, API counts and costs before making claims about quality.

Investigate autonomously, propose tests/patches, and prepare PRs for review. Do not auto-merge, deploy, purchase inventory, change infrastructure, subscribe to services, access production credentials or modify unrelated applications. Human authorization remains required for these operations.

AI should be triggered by failures or material anomalies with bounded/redacted context, rate limits and a cost ledger. Do not process every product through an LLM. Default V0.2 AI usage is zero; a ~$15/month AI target and <$50/month early-MVP incremental operating target require measurement, not assumptions. No AI supervisor, alert delivery or API spend tracking is claimed implemented in V0.2.
