# Prototype verification and authentication review (2026-10-28)

## Existing implementation preserved

The repository already uses pinned `openpyxl` for workbook reports, and has no indexed `artifact_tool` usage. The orchestrator supports one-shot or `JOB_INTERVAL_SECONDS` sequential execution, JSON logs and SQLite run history. Email delivery is opt-in by specifying recipients, and CI runs Python 3.12 tests and fixture workflows on Ubuntu 24.04. These are existing capabilities, not newly claimed features of this branch.

The legacy baseline gates remain a **minimum $5 net profit and 50% ROI on acquisition cost**. Exact-match and seller-eligibility checks remain mandatory. The extended discovery path uses `Decimal` accounting, evidence quality checks and mock-only provider selection. No worksheet constitutes authorization to buy inventory.

## Components and authentication flow

The ordinary `app.orchestrator` offline CSV/mock execution is not an authenticated HTTP service; it reads local inputs and emits Excel/SQLite artifacts. Config is read by `app.config.Config.from_env`; SMTP credentials are supplied by environment variables only when the SMTP transport is selected. `app.mailer.send_report` uses TLS (STARTTLS or SSL), logs in only when SMTP user/password are configured, and sends an XLSX attachment only if `EMAIL_TO` is populated.

The optional Gmail API path is disabled by default. An operator locally invokes `ops.gmail_authorize` after setting up an OAuth Desktop client and grants precisely `https://www.googleapis.com/auth/gmail.send`. The local helper uses loopback consent and writes a private token JSON file containing client ID, client secret and refresh token. The runtime reads `ARBITRAGE_GMAIL_TOKEN_FILE`, enforces owner-only file permissions, exchanges the refresh token at Google's fixed HTTPS endpoint, keeps the access token in process memory, and sends the MIME message using an Authorization Bearer header at Gmail's HTTPS API. Replacement refresh tokens are atomically stored with private permissions. OAuth errors are categorized without logging token payloads. Token authorization is separate from permission to send and no scheduled Gmail job is active by default.

Separately invoked Amazon SP-API pilot tooling in `app.amazon_pilot` accepts credentials via hidden operator entry into a private local directory, not the normal orchestrator. Live API authorization is not part of this branch; see `docs/AMAZON_PILOT.md`. Never reuse Gmail credentials for Amazon. No OAuth secrets, customer data, token files or host-specific deployment settings belong in Git.

## Operator verification

Run from an isolated Python 3.12 environment:

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python -m app.orchestrator
ARBITRAGE_MODE=discovery ARBITRAGE_REPORT=var/discovery.xlsx python -m app.orchestrator
python -m app.demo
python -m app.offline_pilot
```

Leave `EMAIL_TO` unset to run offline; **do not** invoke live integrations or scheduled delivery without separate authorization. The GitHub Actions `Tests` workflow is configured to execute these checks on push/PR. Execution outcomes must be verified from a completed Actions run; committing a test is not proof that it passed.

## Change scope

This branch adds offline regression tests for threshold boundaries, Decimal acquisition ROI, spreadsheet formula injection, no-recipient email behavior, JSON logging and persisted successes/failures. It does **not** replace existing supported integrations, request credentials, activate email, modify the server or merge changes.
