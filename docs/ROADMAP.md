# Roadmap

## Status register — 2026-10-26

Implemented means code and fixture tests, live-verified means evidence from an
actual external interaction, deployed means installed/activated on production.
These are independent states. Deployment history below comes from existing release
handoffs; this milestone has not inspected or changed the running host.

| Capability | Implemented | Live-verified | Deployed | Blocked / next gate |
| --- | --- | --- | --- | --- |
| V0.2 CSV/mock reports + run history | Yes, existing | Offline fixture validation only; no real sourcing verified | Recorded V0.2 offline VM deployment; not re-audited here | Authorized fresh source and marketplace evidence |
| Source/match/enrichment SQLite persistence | Implemented in real-data-pilot PR; version 1, dedup and run linkage | No real supplier/SP-API/Keepa records | No | Permission/retention review before live data |
| Ten-product pipeline | Implemented offline with existing CSV, matching, Keepa contracts, screening and reporting | No; explicitly fictional fixed-clock fixtures | No | Approved ten-product CSV, seller evidence and account entitlement |
| Keepa adapter, ledger and dormant HTTP seam | Existing, reused; live code gate remains false | No account/key/request verified | No | Owner subscription/quote/license/balance and later live-enablement review |
| SP-API | Repaired catalog details mapping and bounded pricing/fees/restrictions pilot; normal job unchanged | Live details report confirms catalog success; pricing failed without retained status/code; fees/restrictions unattempted | No deployment performed | Safe diagnostics tested offline; separately authorized pricing-only diagnostic proposed; preserve ambiguous identity and unknown economics |
| Supplier pilot | Permissioned EE Distribution evaluation CSV recommended conditionally | No account, permission or sample verified | No | Written ten-SKU internal-analysis/export/storage license and no-purchase sample quote |
| Gmail transport | Merged PR #12 | Owner confirmed attempt-3 Hotmail delivery with both attachments | Manual DEMO only; no scheduled email deployment | OAuth readiness, nonroot access and separate activation approval |
| Email scheduling | Separate inactive templates | No unattended execution verified | No | See Gmail scheduling preparation; explicitly excluded from this pilot |
| Backups / monitoring / notifications | Offline implementations and proposed units | No new live acceptance claimed | Deployment not established by preparation docs | Independent receiver, restore/deployment authorization |
| Scan Profit | No connector added | Official product source still unidentified | No | Owner-supplied official URL and documented export/API permission |

See [real-data pilot implementation](REAL_DATA_PILOT.md) and
[account/source owner checklist](PILOT_ACCOUNT_ACCESS.md). No account prerequisite
blocks independent fixture implementation. No paid calls, purchases, deployments,
production migrations or scheduled email activation are part of this PR.

Historical milestone notes below describe earlier scope; the register above is
the current status and avoids treating implemented code as live readiness.

## V0.1 — completed baseline

CSV screening, deterministic economics, openpyxl reports, SQLite run audit, sequential jobs, JSON logs, TLS SMTP, Docker and Ubuntu/Python CI. Baseline: 29 tests.

## V0.2 — implemented; offline deployment recorded

Normalized retailer connector contracts and CSV ingestion; mock Amazon exact matching and ambiguity gates; richer expense model; confidence/data-quality and ranking; six-sheet reports; persistent project documentation. Real discovery remains dependent on authorized external data; mocks are not real opportunities.

## V0.3 — preparation implemented; live access pending

Official-source research, conditional cost model, provider/evidence contracts,
mock contract tests, bounded retry/timeout policy, SQLite usage reservations and
backup/restore tooling are prepared. [Handoff](V03_PREPARATION.md) documents
scope and validation; [research](V03_PROVIDER_RESEARCH.md) identifies owner account,
pricing and license decisions. Backup scheduling remains proposed for review.
No live adapters or paid integrations are enabled; V0.2 deployment is preserved.

Research Amazon SP-API, Keepa and authorized retailer/licensed product feeds. For each integration document API availability, account permissions, credentials, current authoritative pricing, usage/redistribution restrictions and estimated monthly cost before implementation/enabling. Implement mock contract tests and rate-limit/retry/freshness policies first. Get approval before any paid service. Prioritize historical price stability, demand, offer competition and fees. Do not wait for credentials to write interfaces; do not claim live readiness without authorized requests.

## V0.4 — AgentOps AI supervisor

Observe failed jobs, source quality, match accuracy, anomalous economics, API usage/costs and performance. Generate tests and proposed PRs. Use event-driven AI, not an LLM per product. Humans approve production deployment, purchases, infrastructure and sensitive credentials. See AGENTOPS.md.

## V0.5 — lightweight dashboard

FastAPI + React unless constraints justify a simpler stack: authentication, opportunities/search/filtering, execution history, source health, profit visualization, configuration controls and authorized report downloads. Assess measured load before PostgreSQL. Avoid microservices and paid infrastructure without demonstrated requirements.

## Delivery process

Inspect main and run tests; implement on a milestone feature branch; update documentation; run tests and sample workflows; commit, push and prepare PR. Do not merge or deploy without authorization. CI status and remotely executed workflows must be reported separately from local results.

## Amazon registration readiness review

See [SECURITY_READINESS.md](SECURITY_READINESS.md) for verified file evidence,
unknown effective production controls and owner actions. Authorized CSV template,
strict offline preflight and local health monitor are prepared for review only;
no production settings or live provider have changed.

## Backup enforcement and watchdog review

Disk admission/progress checks, restore proofs and optional notification transport
are prepared with offline tests. External silence detection requires an off-VM
receiver and owner-selected notification integration; same-VM checks are not
VM-failure-independent. Production deployment and live receipt/restore acceptance
remain pending. See [operations plan](OPERATIONS_WATCHDOG.md).

## Keepa offline adapter review

Official rendered pricing/terms, bounded mock transport contracts, token reservations,
pacing, permitted optional memory caching and conservative timestamped evidence are
prepared in [KEEPA_PREPARATION.md](KEEPA_PREPARATION.md). Live code gate and job
selector stay disabled. Scan Profit identification/permissions remain unresolved.

## Credential-free demonstration milestone

Pending pilot work is preserved with every public live entry point disabled.
The existing discovery/reporting path now powers a fixed-clock, clearly labeled
DEMO with threshold sensitivity, missing-fee/package/freshness failures and
sample authorized-export diagnostics with repair actions. SMTP settings reuse and backup/monitor installation are consolidated as handoffs.
An owner-authorized DEMO email attempt using existing WeinsteinAgent settings
failed DNS before SMTP connection; no message was submitted.
See [DEMO](OFFLINE_DEMO_HANDOFF.md), [operations](OPERATIONS_HANDOFF.md) and
[pytest remediation/verification limits](PYTEST_ADVISORY.md). No deployment or live Keepa/Amazon call is included.

## Gmail delivery confirmation and scheduling proposal

The operator confirms Gmail API DEMO attempt 3 arrived in Hotmail with both
attachments. HTTPS transport hardening and private safe-reason diagnostics are
consolidated for review. Scheduled reports remain disabled in separate proposed
units; service-owned private rotating-token state and OAuth publishing/fresh
consent are activation prerequisites. See [confirmation](GMAIL_API_DEMO_THIRD.md)
and [schedule preparation](GMAIL_SCHEDULE_PREPARATION.md). Existing schedules
and all attempt reservations are preserved; no additional email was sent.
