# IntelligenceOS Arbitrage

V0.3 preparation is available for review: [provider research and cost decisions](docs/V03_PROVIDER_RESEARCH.md),
[offline contracts and safeguards](docs/V03_PREPARATION.md), and
[proposed SQLite backups with restore procedure](docs/SQLITE_BACKUPS.md).
Live providers remain disabled; the deployed V0.2 service is unchanged.

An offline sourcing-analysis prototype for Python 3.12. It reads candidate CSV data, screens profitability and eligibility, creates formatted Excel reports, and records each execution in SQLite. Bundled products are fictional examples. The application does not scrape, buy products, or verify live seller eligibility.

## Quick start (Ubuntu 24.04)

Install Python 3.12 and its venv package using your system package manager, then:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m app.orchestrator
```

`python -m app.pipeline` remains a compatible entry point. Defaults create `var/opportunities.xlsx` and `var/history.sqlite3`. The sample produces three candidates, one for review and two rejected. No credentials or external services are needed. The old tracked report is an illustrative artifact; new runs write to `var/`.

## Profitability

`net_profit = sale_price - buy_cost - referral_fee - fulfillment_fee - inbound_shipping - other_cost`

`ROI = net_profit / (buy_cost + inbound_shipping + other_cost) × 100`

Default review thresholds are at least $5 net profit and 50% ROI, with both `eligible` and `exact_match` equal to `yes` (case insensitive). Thresholds use unrounded numbers; report profit is rounded to two decimals and ROI to one. Invalid, negative or nonfinite prices and nonpositive buy costs produce `ERROR` rows. Review always requires manual validation of live data before purchase.

The input CSV must contain all columns shown in `sample_data/candidates.csv`. Identifiers remain text in Excel. User strings are written as literal cells to prevent spreadsheet formula execution.

## Environment configuration

Export variables before starting; `.env` files are not loaded automatically. Never commit credentials.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ARBITRAGE_INPUT` | repository `sample_data/candidates.csv` | Input CSV |
| `ARBITRAGE_REPORT` | repository `var/opportunities.xlsx` | Latest report, atomically replaced |
| `ARBITRAGE_DB` | repository `var/history.sqlite3` | Persistent run history |
| `MINIMUM_ROI` | `50` | Minimum acquisition-cost ROI percentage |
| `MINIMUM_PROFIT` | `5` | Minimum net profit |
| `JOB_INTERVAL_SECONDS` | `0` | One shot; positive values wait this long after each execution |
| `SMTP_HOST` | empty | SMTP host for optional delivery |
| `SMTP_PORT` | `587` | SMTP port; typically use 465 with SSL |
| `SMTP_SECURITY` | `starttls` | `starttls` or `ssl`, verified TLS required |
| `SMTP_USER`, `SMTP_PASSWORD` | empty | Optional paired SMTP authentication |
| `EMAIL_FROM` | empty | Required sender when delivery enabled |
| `EMAIL_TO` | empty | Comma-separated recipients; empty disables delivery |

Reports contain an executive summary, ranked opportunities, all candidates, and rejected/error rows, with filters, frozen headers and currency/ROI formats. Email attaches the latest report. Supply SMTP credentials using your runtime's secret injection; local tests mock SMTP and do not send mail.

## Jobs and operations

The orchestrator runs sequentially without overlap within one process. Run only one process per output path; cross-process locking is not implemented. SIGINT/SIGTERM stop scheduling after the current job; waiting stops immediately. One-shot failures exit nonzero. Scheduled failures are recorded and the next interval proceeds. There are no automatic immediate email retries, avoiding duplicate sends on ambiguous SMTP outcomes.

Structured JSON events include timestamp, level, event, run ID and exception class. Exception messages and configuration credentials are not logged or stored in history. SQLite `runs` records UTC start/end, `running`/`succeeded`/`failed` status, candidate and review counts, report path and error class. A crash or forced termination can leave a `running` row for investigation. Row-level errors appear in the workbook and counts; they do not fail an otherwise completed execution. Report generation followed by email failure records a failed job and retains the report path.

```bash
sqlite3 var/history.sqlite3 'SELECT * FROM runs ORDER BY id DESC LIMIT 10;'
JOB_INTERVAL_SECONDS=3600 python -m app.orchestrator
```

Back up the SQLite file when the process is stopped (or use SQLite's backup API); retain the entire `var` directory on persistent storage. The latest workbook is replaced; execution metadata is retained indefinitely. Apply retention based on your needs. No database server, queue, or paid service is required.

## Docker

```bash
docker build -t intelligenceos-arbitrage .
docker volume create arbitrage-data
docker run --rm -v arbitrage-data:/app/var intelligenceos-arbitrage
docker run -d --name arbitrage --restart unless-stopped \
  -e JOB_INTERVAL_SECONDS=3600 -v arbitrage-data:/app/var intelligenceos-arbitrage
```

The container uses Python 3.12 and a nonroot user. For a bind mount, grant that user write permission on the output directory. Mount custom inputs read-only and set `ARBITRAGE_INPUT`. Pass email settings securely at runtime. These are deployment instructions only; no remote deployment is performed.

## Architecture and validation

`config` validates environment settings; `pipeline` handles CSV ingestion and deterministic screening; `reporting` owns Excel output; `mailer` handles optional TLS SMTP; `history` persists execution metadata; `orchestrator` coordinates jobs and scheduling. Extend integrations behind these boundaries.

GitHub Actions runs tests on Ubuntu 24.04 / Python 3.12, executes the offline sample job and uploads its workbook. Unit/integration tests cover profitability boundaries, invalid input, report contents and formula safety, history, repeat executions, scheduling failures, configuration and mocked SMTP delivery. Real SMTP delivery requires a configured provider and is not exercised by CI.

## V0.2 discovery preview

```bash
ARBITRAGE_MODE=discovery ARBITRAGE_REPORT=var/discovery.xlsx python -m app.orchestrator
```

This opt-in path uses a normalized CSV connector and a **fictional mock Amazon provider**, extended expense calculations, evidence screening/ranking and six-sheet reporting. It does not discover live products. Sample snapshots intentionally expire under freshness checks; stale data yields rejected rows, not real opportunities. No result is purchase-ready. Legacy mode and existing input files remain supported unchanged.

See [architecture](docs/ARCHITECTURE.md), [product requirements](docs/PRODUCT_REQUIREMENTS.md), [roadmap](docs/ROADMAP.md), [integration contracts](docs/INTEGRATIONS.md), [deployment/configuration](docs/DEPLOYMENT.md) and [AgentOps plan](docs/AGENTOPS.md). Runtime service cost for the CSV/mock workflow is $0 incremental excluding existing hosting, storage and CI quotas; no paid/API/AI integrations are enabled.
