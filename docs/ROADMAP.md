# Roadmap

## V0.1 — completed baseline

CSV screening, deterministic economics, openpyxl reports, SQLite run audit, sequential jobs, JSON logs, TLS SMTP, Docker and Ubuntu/Python CI. Baseline: 29 tests.

## V0.2 — implemented for review

Normalized retailer connector contracts and CSV ingestion; mock Amazon exact matching and ambiguity gates; richer expense model; confidence/data-quality and ranking; six-sheet reports; persistent project documentation. Real discovery remains dependent on authorized external data; mocks are not real opportunities.

## V0.3 — recommended next milestone: permitted market intelligence

Research Amazon SP-API, Keepa and authorized retailer/licensed product feeds. For each integration document API availability, account permissions, credentials, current authoritative pricing, usage/redistribution restrictions and estimated monthly cost before implementation/enabling. Implement mock contract tests and rate-limit/retry/freshness policies first. Get approval before any paid service. Prioritize historical price stability, demand, offer competition and fees. Do not wait for credentials to write interfaces; do not claim live readiness without authorized requests.

## V0.4 — AgentOps AI supervisor

Observe failed jobs, source quality, match accuracy, anomalous economics, API usage/costs and performance. Generate tests and proposed PRs. Use event-driven AI, not an LLM per product. Humans approve production deployment, purchases, infrastructure and sensitive credentials. See AGENTOPS.md.

## V0.5 — lightweight dashboard

FastAPI + React unless constraints justify a simpler stack: authentication, opportunities/search/filtering, execution history, source health, profit visualization, configuration controls and authorized report downloads. Assess measured load before PostgreSQL. Avoid microservices and paid infrastructure without demonstrated requirements.

## Delivery process

Inspect main and run tests; implement on a milestone feature branch; update documentation; run tests and sample workflows; commit, push and prepare PR. Do not merge or deploy without authorization. CI status and remotely executed workflows must be reported separately from local results.
