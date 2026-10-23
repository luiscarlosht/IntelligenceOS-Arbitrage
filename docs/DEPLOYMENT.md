# Development and deployment guide

The original development milestone did not authorize deployment. A subsequent
explicitly authorized dedicated VM deployment is documented in
[VM V0.2 release](VM_V02_RELEASE.md), including installed paths, daily systemd
execution, validation and rollback. Preserve other applications; do not inspect
their credentials or change their configuration.

## Ubuntu 24.04 / Python 3.12

From the existing checkout, create/activate a venv, install requirements, and run tests:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m app.orchestrator
ARBITRAGE_MODE=discovery ARBITRAGE_REPORT=var/discovery.xlsx python -m app.orchestrator
```

The legacy mode remains default and keeps its original CSV/report shape. Discovery uses `sample_data/discovery.csv` and `sample_data/amazon_mock.json` by default, contains no live opportunities, and emits six worksheets. The static snapshots intentionally fail freshness checks after 24 hours; a successful job with rejected stale products is expected, not an ingestion failure. Use fresh authorized user-owned inputs for actual evaluation.

## V0.2 environment variables

All V0.1 path, thresholds, scheduling and SMTP settings remain supported; see README.md. `.env` is not loaded automatically.

| Name | Default | Meaning |
| --- | --- | --- |
| `ARBITRAGE_MODE` | `legacy` | `legacy` or `discovery` |
| `AMAZON_PROVIDER` | `mock` | Only enabled provider |
| `AMAZON_MOCK_FILE` | `sample_data/amazon_mock.json` under repository | Local illustrative listing snapshots |
| `ARBITRAGE_INPUT` | mode-specific sample CSV | User-owned source input |
| `INVENTORY_BUDGET` | `500` | USD per-unit affordability cap, not a purchase allocation |
| `MINIMUM_MONTHLY_SALES` | `30` | Minimum supplied demand indicator |
| `MAXIMUM_OFFERS` | `15` | Maximum supplied competing offers |
| `MAXIMUM_DATA_AGE_HOURS` | `24` | Maximum source and marketplace data age; future timestamps rejected |
| `TOP_OPPORTUNITIES` | `20` | Maximum rows on ranked sheet |
| `MAXIMUM_CANDIDATES` | `10000` | Reject larger jobs; partition input rather than exhausting shared RAM |

`MINIMUM_ROI=50`, `MINIMUM_PROFIT=5` continue to apply. Avoid lowering freshness or evidence gates to manufacture passing opportunities. `ARBITRAGE_REPORT` and `ARBITRAGE_DB` must be writable and separate from source inputs. The maximum-candidate limit applies to discovery; legacy remains unchanged. Memory scales with candidate/workbook size; the default is a guardrail, not a measured 2 GB capacity guarantee. Large JSON catalogs need indexed/paginated providers before enabling them on the small VM.

## Scheduling and persistence

A positive `JOB_INTERVAL_SECONDS` waits after each completed job, so 86400 approximates daily reporting rather than a fixed local wall-clock time. Default is one shot. Run one process per output path. No distributed lock or concurrent-worker support is implemented. Graceful SIGTERM stops future jobs; a forced termination may leave a running history row. Reports replace the latest file atomically; retain separate paths if archives are desired. SQLite is the authoritative final execution/delivery status; workbook job summary describes report generation before optional email and finalization.

Persist/backup `var/` using SQLite backup APIs or a stopped process. A future reviewed systemd unit/container restart policy can supervise unattended operation; do not enable it on production without approval. Optional SMTP remains TLS-only; test with an explicitly authorized recipient before scheduled mail. Email is not deduplicated across separate runs and delivery failures are not retried immediately.

## Docker

```bash
docker build -t intelligenceos-arbitrage .
docker volume create arbitrage-data
docker run --rm -e ARBITRAGE_MODE=discovery \
  -v arbitrage-data:/app/var intelligenceos-arbitrage
```

For supplied data mount a dedicated input directory read-only and set `ARBITRAGE_INPUT`/`AMAZON_MOCK_FILE`. The image uses Python 3.12 and a nonroot user. Ensure bind-mount ownership supports writes; use separate paths for input and output. No new network ports or infrastructure are needed. Network-restricted build environments must provide trusted package access or a local verified wheelhouse; never disable TLS checks.

## Release checks

Run all tests, both sample modes, inspect workbook sheets/data and SQLite final statuses, run `pip check` and `git diff --check`, and review CI. Docker build/run is a separate validation claim. Commit and push a feature branch, prepare a PR, then wait for authorization to merge/deploy. Project service cost is $0 incremental for offline CSV/mock mode excluding existing compute/storage/CI quotas; SMTP/live providers are external dependencies with unverified pricing.
