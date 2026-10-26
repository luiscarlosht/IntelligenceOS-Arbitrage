# Real-data pilot milestone — offline implementation, live access pending

Current-main inspection used the connected GitHub API because shell Git DNS was
unavailable. Confirmed `main=da2b83d11f67406d449b323e30de6c9709efb5ea`, tree
`d14ea9c04c4f498eeccfa48d4d08cfe0dec8cd3b`. Existing implementation already provides
CSV normalization, deterministic matching, Decimal economics, screening/ranking,
formula-safe six-sheet reporting, History, UsageLedger, Keepa contracts/HTTP
preparation, and authorized-import validation. This milestone reuses those pieces.
Baseline: 357 tests. No production release, database, service, schedule or email
configuration was read/changed to implement this isolated workflow.

## Run the offline composition

```bash
.venv/bin/python -m app.offline_pilot
```

The default ten records in `sample_data/pilot_source_fixture.csv`, marketplace
JSON and Keepa JSON are **fictional**, not an EE/Walmart export or live Amazon
records. The explicit evaluation clock is `2026-10-24T12:00:00+00:00`. A fixed
fixture clock is never evidence of current freshness or live account access.
Use `--output-directory /tmp/pilot-review` for isolated review. Optional input
arguments select alternative local test fixtures only, not a live provider.

The entrypoint constructs Config directly, disregards inherited email/provider
settings, selects only MockAmazonProvider and FixtureKeepaTransport, never reads
credentials and never imports a network transport or invokes the mailer. Existing
Keepa live gates remain false. No new production provider selector is registered.
Input files are bounded to 1 MiB each; at most ten CSV rows are accepted.
Headers/field diagnostics are provided by the existing CsvConnector; missing
permission references add a row rejection. A populated fixture reference proves
no license. Real source permission remains an owner prerequisite.

Steps: normalize CSV → deterministic marketplace match → mock Keepa lookup and
existing fee/eligibility contract methods → screen with unchanged defaults →
record normalized evidence/decision → write labeled report/JSON → finalize run.
Only a matched candidate ASIN is enriched. Ambiguous/no-match rows remain visible
and receive no guessed-ASIN request. Multiple rows sharing an ASIN reuse its
response within the run. Duplicate normalized input rows share evidence and one
report row, while every original input ordinal retains its own lineage link.

The default fixtures exercise passing/boundary, insufficient profit/ROI,
over-budget, package mismatch, missing fees, stale evidence, no match and ambiguous
matches. Eight candidate ASINs result in eight **mock** Keepa requests. Default
outcome is two fixture REVIEW and eight REJECT; all purchase_ready flags are false
and confidence remains mock-capped. REVIEW never means purchase approval.

Keepa lookup supplies catalog metadata, historical Amazon price, rank and a
bought-past-month lower-bound bracket as independent observations. They do not
replace the fixture listing's sale quote, exact identity, pack/variation, seller
eligibility, fees, competition or monthly-sales input. Fee/eligibility contracts
still return unknown. The seven-sheet fixture workbook has the existing six DEMO
sheets plus DEMO Enrichment, including observation/fetch timestamps, provenance,
mock status and per-field freshness. JSON and SQLite retain structured rejection
arrays in addition to the original report text. No reason is lost by splitting
semicolon-delimited strings. Unknown enrichment has null observation time;
retrieval time alone is not a fabricated observation.

## Persistence and replay semantics

`app.observations.ObservationStore` creates a separate owner-only (0600), regular,
nonsymlink SQLite file `var/pilot-offline/pilot.sqlite3`. Existing History and
UsageLedger share this **pilot** file, not production history. Schema version 1
is additive; reopening is idempotent and an unknown version is rejected. No
production migration is installed or invoked.

| Table | Retained evidence and linkage |
| --- | --- |
| `runs` | Existing History lifecycle, counts, final report path and fixed exception class on failure |
| `pilot_runs` | Run FK, explicit evaluation clock, fixture label and SHA256 of each input file |
| `source_observations` | Exact-content fingerprint, normalized source/GTIN, original observation time, provenance, permission reference, exact purchase-price string and complete normalized product including issues |
| `marketplace_matches` | Source FK, provider label, candidate ASIN/null, exact flag, listing observation time/provenance and full match/listing payload including reasons and null unknowns |
| `enrichment_observations` | ASIN, kind, canonical normalized value, observed_at/null, provenance and mock flag; never vendor response bodies or credentials |
| `pilot_run_items` | Run + input ordinal primary key; source/match FKs and full decision including all rejection reasons |
| `pilot_run_enrichment` | Run/input FK to each enrichment and that run's fetched_at |
| `provider_usage` / `keepa_pacing` | Reused conservative mock request accounting and pacing reservations |

Canonical fingerprints include normalized evidence values, original timestamps,
provenance and permission references. Decimal strings preserve precision and
canonicalize trailing fractional zeros; timestamps normalize to aware UTC. Nulls
remain null, including missing fees and false-vs-unknown eligibility. Repeated
identical evidence deduplicates across runs, but new price/time/provenance/license
or match content is a new snapshot, never an overwrite. A provider's changed
provenance (including embedded fetch metadata) also creates a distinct snapshot;
this is exact-content dedup, not inferred equivalence of vendor observations.
Run links retain every ingest, and source first_seen_at is not refreshed on reuse.
Original aware timezone offsets canonicalize to UTC, not new observation times.

A row, its match, decision and enrichment links are committed atomically with
foreign keys enabled. Provider lookup failures become fixed enrichment-unavailable
rejections while preserving all earlier screening reasons and continuing products.
Unexpected ingestion/report/storage errors mark the run failed; previously
committed rows remain attributable to that failed run. They are not deleted or
presented as a successful report. Reports/JSON are atomically published per file;
there is no transaction spanning SQLite and both output files. A crash can leave
a running History row or an older report beside a failed run; check run_id/final
status before interpreting artifacts.

A new import always creates a new run. Dedup is not send suppression or a reason
to delete history. The reused local mock ledger has a 30-token monthly cap, one
attempt per ASIN and initial balance 10. Repeated runs in the same directory can
exhaust that deliberately conservative mock allowance; inspect resulting rejection
and usage records or choose a fresh **fixture-only** review directory. This is not
permission to reset a future live budget. Adapter cache is disabled; it is closed
at the end of every run. The small per-run reuse map holds fixture records only.

## Outputs and inspection

Outputs are PILOT-FIXTURE.xlsx, PILOT-FIXTURE.json and pilot.sqlite3 under ignored
`var/pilot-offline/`. Do not replace or reuse prior DEMO files/attempt reservations.
Use a trusted directory; output paths cannot alias input paths or be symlinks.
Only normalized fixture evidence is persisted. Do not import actual Keepa/SP-API
responses into this workflow or call the store a licensed live data cache.
Before any live persistence, settle provider use/mixing policy, retention,
deletion and protected backup requirements. The fixture schema does not implement
provider-specific timed deletion or customer isolation; those are live-enablement
requirements. No raw-response export or credential store is added.

Useful read-only inspection after a fixture run:

```bash
sqlite3 -readonly var/pilot-offline/pilot.sqlite3 \
  'SELECT id,status,candidates,review_candidates FROM runs ORDER BY id;'
sqlite3 -readonly var/pilot-offline/pilot.sqlite3 \
  'SELECT run_id,ordinal,observation_id,match_id FROM pilot_run_items ORDER BY run_id,ordinal;'
```

## Validation and remaining work

Tests cover complete end-to-end reports, all fixture scenarios, unknown-value
nonpromotion, freshness, duplicate rows/reimports, changed observations, precise
Decimal storage, UTC equivalence, foreign-key rollback, failed runs, missing
permission references, private files, schema versions, path collisions, labeled
mock transport and inherited-mail/network isolation. Existing SMTP/Gmail and
Keepa contracts remain covered. CI adds this offline pilot and uploads only its
labeled XLSX/JSON, not its SQLite evidence database.

[Owner/account/source checklist](PILOT_ACCOUNT_ACCESS.md) specifies the remaining
SP-API and Keepa actions and a conditional permissioned supplier route. Scan Profit
remains unidentified; no guessed integration is added. Account blockers do not
prevent this persistence/offline workflow from being tested and reviewed.

Validation result for this PR: **369 tests passed** locally and in a clean staged
source export without credentials, reports, markers or a local helper dependency.
Legacy and discovery samples, the existing DEMO and the new ten-product fixture
pilot all passed in that export. Remote CI is a separate check for the published
PR head; no local test is presented as a live/provider/deployment acceptance.
