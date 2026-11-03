# Original Amazon cohort in Walmart Intake

`app.amazon_research_queue` extends the existing intake integration. It reuses
`app.sheets_intake.SheetsClient`: the same explicit service-account file,
owner-only credential reader, Sheets scopes, local JWT signing, bounded verified
HTTPS transport, and existing destination `SPREADSHEET` constant. No authentication
setup, new workbook, Amazon request, scheduler, or paid dependency is added.
The optional dependencies remain `requirements-sheets.txt`.

The existing research publisher uses `ARBITRAGE_SHEETS_ID` and
`ARBITRAGE_SHEETS_CREDENTIALS` and manages several research tabs. This extension
imports its literal `updateCells` helper directly, and reuses the intake client
and credential configuration to keep a single new tab as its write scope.

## Execution on DigitalOcean, after separate code deployment approval

The documented existing VM checkout is `/root/IntelligenceOS-Arbitrage`, host
`137.184.180.155`. The existing intake credential setting/path is reused unchanged.
These commands assume this PR's code has been installed through an approved
release process. Neither command deploys code or installs dependencies.

Read-only preview (authenticates and reads both existing workbooks):

```bash
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && ARBITRAGE_SHEETS_CREDENTIAL_FILE=/root/.config/intelligenceos-sheets/service-account.json .venv/bin/python -m app.amazon_research_queue'
```

Explicit publication:

```bash
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && ARBITRAGE_SHEETS_CREDENTIAL_FILE=/root/.config/intelligenceos-sheets/service-account.json .venv/bin/python -m app.amazon_research_queue --live'
```

Success prints `{"mode": "published", "unique_asins": 20, "history_unchanged": true}`.
The service account must already have source read and destination edit access.
If access fails, stop and inspect the existing sharing/configuration; do not rotate
credentials or create another authentication scheme. No VM command was executed
for this delivery; service-account effective access was not independently tested.

## Data and safe repeat publication

Source: `1FcbY7OLu5Vz50IehxuA23E6obwuxt6_SYtFgRUac0ps`, `Amazon_Candidates`.
Destination: `1q9TPwNTka_wzSo_T283LBP7iFpfAorR3_QYB19LKDHA`,
`Amazon_Research_Queue!A1:V21`.

The original 20 ASINs are frozen in `ORIGINAL_ASINS`. Source headers, ASIN uniqueness,
exact cohort/count and ASIN-specific Amazon URLs are validated before any write.
Priority, title, brand, UPC, GTIN, model, pack count, size, variant and URL are copied
as observed; missing source values become `UNKNOWN`. Pack-count/title discrepancies
are preserved for manual identity review rather than inferred away.

Research columns are `walmart_url`, `walmart_price`, `shipping_cost`, `seller`,
`fulfillment`, `displayed_zip`, `stock`, `match_status`, `evidence_url`,
`research_timestamp`, `notes`. New rows use `UNKNOWN`, except `match_status` uses
`REVIEW_REQUIRED`. Researchers own columns L:V and any custom columns. Existing
research cells, including blanks and formulas, are never initialized again.

ASIN (column B) is the row key. Existing rows receive identity-only updates A:K;
missing ASINs append after existing rows. Invalid/duplicate destination keys or
headers stop publication. A single atomic batch creates only the new queue tab
when needed and writes literal strings, preserving leading zeros and avoiding
formula execution. No clear/delete/sort requests or writes to historical tabs occur.
Readback verifies 20 keys, identity fields, existing research and all historical
values/formulas. Readback failures stop without automatic replay or rollback.

Only one publisher may operate across hosts, and Browser Use should pause sorting,
row insertion/deletion and ASIN changes during publication. A local lock prevents
overlapping invocations of this command on one host; it cannot lock other clients.
Immediate revalidation detects intervening edits before the batch, but the Sheets
API offers no compare-and-swap for arbitrary row edits. Research-only edits remain
safe because reruns never write L:V for an existing ASIN. Concurrent history changes
are reported rather than overwritten. Snapshots are bounded to 20,002 rows/26 columns
per tab and the existing client's 4 MiB response limit; larger grids fail closed.

## Verified publication, 2026-11-03

Initial publication used the already connected Google Sheets account, without VM
access or credentials changes. It exercised the same pure `candidates` and `plan`
functions used by the CLI, then sent their exact atomic batch through the existing
connector. The VM service-account execution remains pending deployment approval.
Readback found 21 rows including the header, exactly 20 original unique ASINs,
and the requested defaults. The new tab has sheet ID `100`.

Before/after full-grid values/formula snapshots matched for `Walmart_Intake`
(79 populated rows), `Walmart_Batches` (16) and `Walmart_Benchmark` (8), including
headers. No existing tabs, credentials, VM files, timers or services were modified.

Tests cover malformed/duplicate/missing/extra/substituted source keys, headers and
URLs; literal strings; research defaults; partial queues; row ordering; duplicate
keys; custom research fields; repeat publication; readback and historical changes.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m app.orchestrator
ARBITRAGE_MODE=discovery ARBITRAGE_REPORT=var/discovery.xlsx .venv/bin/python -m app.orchestrator
```
