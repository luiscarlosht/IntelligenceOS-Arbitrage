# Roadmap

## V0.1 — completed baseline

CSV screening, deterministic economics, openpyxl reports, SQLite run audit, sequential jobs, JSON logs, TLS SMTP, Docker and Ubuntu/Python CI. Baseline: 29 tests.

## V0.2 — implemented for review

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
