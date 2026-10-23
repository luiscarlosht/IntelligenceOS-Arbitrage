# IntelligenceOS Arbitrage engineering instructions

- Read `docs/PRODUCT_REQUIREMENTS.md`, `docs/ARCHITECTURE.md` and `docs/ROADMAP.md` before changing behavior. Inspect current code and run baseline tests first.
- Use Python 3.12, small typed modules, environment configuration and SQLite until measured scale justifies more infrastructure. Target Ubuntu 24.04, Docker and a shared 2 GB VM.
- Preserve the legacy workflow, profitability formula and default $5 profit / 50% acquisition ROI gates. New behavior requires tests and documentation. Mock data is always illustrative; no output is purchase approval.
- Maintain explicit provenance, timezone-aware timestamps, package/variation checks, seller eligibility and conservative missing-data gates. Never infer eligibility from a UPC match. Do not replace missing fees with zero.
- Do routine implementation, testing, documentation and feature-branch/PR preparation autonomously. Run `python -m pytest -q` and both documented sample modes before submitting. Do not merge or deploy without authorization.
- Do not buy inventory, subscribe to paid services, enable paid integrations, access production credentials, access unrelated projects or modify WeinsteinAgent. No unauthorized scraping, CAPTCHA bypassing or access-control circumvention.
- Never commit secrets, `.env`, runtime databases or reports. Use verified TLS, formula-safe Excel strings and redacted operational logs. Do not ask for credential values in chat.
- Use the existing checkout; cloud tasks are already isolated. Do not create Git worktrees unless explicitly requested. Save work on a milestone branch and prepare a pull request with validation and remaining risks.
- Incremental budget targets: AI around $15/month or less; early MVP operating expenses below $50/month excluding inventory/existing hosting. Document actual vendor pricing and get approval before enabling paid services. No Kafka/Kubernetes/premature microservices.
