# Manual Walmart Sheets intake

Prepared only: no credential access, Google requests, Amazon calls, deployment,
scheduling or email was performed. Dedicated spreadsheet:
`1q9TPwNTka_wzSo_T283LBP7iFpfAorR3_QYB19LKDHA`, tabs `Walmart_Intake`
and `Walmart_Batches`. No existing account, key or sharing is assumed.

## Owner setup

Enable Google Sheets API in an owner-controlled Google Cloud project. Create a
new service account exclusively for this integration, without domain-wide
delegation or unrelated project permissions. Share only this dedicated spreadsheet
with its service-account email as Editor (needed for acknowledgment). Keep general
access Restricted; do not publish it. Do not reuse Gmail, Amazon or WeinsteinAgent
credentials. Follow [Google service-account guidance](https://developers.google.com/identity/protocols/oauth2/service-account)
and [Sheets values API](https://developers.google.com/workspace/sheets/api/guides/values).

Privately install its JSON key outside the checkout and backups/reports, for
example `/root/.config/intelligenceos-sheets/service-account.json`, parent mode
0700, file mode 0600, owned by the operator. Never paste the key into chat or log
it. Set `ARBITRAGE_SHEETS_CREDENTIAL_FILE` to that absolute path. The loader
reuses the existing owner-only, no-symlink credential reader and verified HTTPS
transport. No application-default credential discovery is used. Install optional
dependencies with `.venv/bin/pip install -r requirements-sheets.txt` after review.
Use a persistent private SQLite path; losing it loses replay protection.

## Producer contract, version 1

Headers must match `FIELDS` / `BATCH_FIELDS` in `app/sheets_intake.py`, in the
specified order. All cells must be literal text, including numbers, timestamps,
ZIPs and IDs; format them as Plain text before exporting. No formulas are needed.
Availability cells preserve literal browser descriptions or the older
`AVAILABLE`, `UNAVAILABLE`, `UNKNOWN`/blank values. Descriptions must be single-line
text of at most 1,000 characters. `source_context` retains each literal value as
`<channel>_availability_description`; the existing `<channel>_availability` field
holds a separate normalized value. Explicit channel-specific arrival/time wording
normalizes to AVAILABLE; channel-specific unavailable wording to UNAVAILABLE.
Unrecognized wording stays unknown. Shipping, delivery and pickup never substitute
for one another. Contradictory availability wording rejects the row. Unknown shipping
charge is blank, never zero. Currency is USD, positive item prices and nonnegative
finite shipping charges. UTC ISO timestamps must be ordered observed <= exported
<= completed and must not be in the future. HTTPS Walmart `/ip/.../<item-id>` URLs
must agree with the text item ID. Batch/source ID characters are letters, digits, `_`, `-`; record IDs additionally
allow `:` for original producer batch:item keys. Both limits remain 1–128 characters.
Record IDs are opaque, exact literal strings; they are never split, renamed or
interpreted as code. Walmart IDs are digits. Record IDs are globally unique in this spreadsheet.

`raw_record_json` retains the original browser JSON object. Product fields must
agree with the exported text cells: `displayed_price` (for example `"$1.97"`)
maps to `item_price_usd` (`"1.97"`), `observation_timestamp` maps to
`observed_at_utc`, and `shipping_charge: null` requires a blank
`shipping_charge_usd` cell. Known monetary values compare numerically; timestamps
compare as validated UTC instants. Other product fields retain their exact text
names and values, including blanks. All product fields are required in the raw
object. Source/schema/batch/record/export metadata is outside the original JSON; if
present it must agree. Additional original browser evidence is retained, and
conflicting duplicate canonical aliases reject the batch. The older exact mirror
of all 20 exported text fields remains supported. No producer rewrite is required.
The raw object, original row, batch metadata and canonical content hashes are
retained privately. No sheet value is interpreted as code, shell, prompt or instruction.

Producer writes all records and counts first, then publishes `COMPLETE` last.
Completed batches and their records are immutable. New observations get new batch
and record IDs; `walmart:<item-id>` remains stable product identity. Missing brand,
seller, fulfiller and variant remain missing; package quantity, exact matching,
fees and eligibility are never inferred. Shipping, local delivery and pickup stay
separate, and overall availability stays unknown for conservative screening.

Maximum 1,000 rows per tab, 4 MiB Sheets responses, 15-second Sheets socket timeout,
120-second overall CLI deadline, one token exchange and no automatic retries.
Oversized snapshots fail closed. Blank rows are allowed. Malformed COMPLETE batches
are rejected without acknowledgment; unrelated valid batches can commit. Schema
failure prevents the entire run. Rejections include fixed code/field labels in `rejections`, never cell contents,
batch IDs, exception messages or provider error messages. Correct malformed uncommitted rows and manually rerun;
never edit already stored content under an existing ID.

## Storage, acknowledgment and recovery

`IntakeStore` extends the existing `ObservationStore`, storing source observations
and batch/record links in one SQLite transaction. Unique record IDs and batch
hashes prevent replay; changed content or reused IDs rejects the batch. A local
batch row with NULL acknowledgment is the durable pending outbox. After commit,
the consumer rereads the batch tab, checks identity/count/status/completion fields,
locates the current ID row and writes only F:G using RAW input. Producer status
and counts are never written. Failure or crash leaves safe manual replay, including
an ambiguous successful Google write followed by local failure.

**Operational concurrency requirement:** freeze sorting, row insertion/deletion
and producer edits while a consumer runs. Sheets values writes have no compare-
and-swap condition: a move between the final read and write cannot be prevented
by the API. Run one consumer at a time. The final reread handles moves before that
read; immutability and the short exclusive operator window cover the remaining
race. Do not run the first test until the producer follows this contract.

A pending batch must remain COMPLETE and present with its original intake rows
until acknowledged. If changed/deleted, pending state stays local and no write is
attempted. Restore the original producer data to recover. No rows are cleared,
no daily deletion or polling is installed. STORED means ingestion only, never
Amazon analysis completion.

`IntakeStore.products(batch_id)` is an offline retailer connector returning existing
`RetailProduct` objects for candidate planning. Existing
`app.source_keywords.search_keywords` formats these objects without requests or
imports from unpublished Amazon executor modules.
The existing ten/twenty-row Amazon executor is deliberately unchanged; a five-row
intake is not execution authorization and cannot be passed through that CLI.

## Operator commands (after reviewed installation)

Operator verification (2026-10-29): checkout `milestone/google-sheets-intake`,
commit `5a60d48`, contains the implementation and two-cell acknowledgment fix;
all 15 intake tests pass. A synthetic five-record text/raw-JSON snapshot passes
the actual `product` and read-only `process` validators (accepted=1 batch,
rejected=0). The previously uploaded intake workbook was not found locally;
compatibility of its actual five rows is **not verified** by this synthetic test.
Validate that workbook before treating the existing sheet as ready.

Only the Google Sheets API (`sheets.googleapis.com`) is required; the code does
not use Drive API. In Cloud Console, enable it, create a dedicated service account,
skip project role grants and domain-wide delegation, and create a JSON key.
Share just the dedicated spreadsheet with that account as Editor for ingestion.
The check requests `spreadsheets.readonly`; ingest requests `spreadsheets`.
No OAuth consent-screen user flow or service-account impersonation is used.

The spreadsheet ID above is the `SPREADSHEET` constant, not an environment setting.
Only the credential path is configured by environment. Changing the target ID
requires a reviewed code change. Counts and numeric fields must be strings;
the five-record batch requires text counts `5` and `5`, and `COMPLETE` status.
The raw JSON follows the original browser mappings above; the older exact text
mirror is also supported.
The accepted counter counts batches, so a valid five-row batch gives accepted=1.

Exact optional dependency installation from the checkout (not run here):

```sh
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && .venv/bin/python -m pip install -r requirements-sheets.txt'
```

Mac-to-VM setup, one command per line; replace only the local key path. These
commands are instructions, not executed preparation. The destination must be a
new dedicated path with no symlinks; do not overwrite an existing key blindly.
Directory: root:root 0700. Key: root:root 0600, regular file, no symlink. The
reader enforces file ownership and no group/world permissions; directory mode
is an operator setup requirement, not enforced by the read helper.

```sh
ssh root@137.184.180.155 'test ! -e /root/.config/intelligenceos-sheets && test ! -L /root/.config/intelligenceos-sheets && install -d -m 700 /root/.config/intelligenceos-sheets'
chmod 600 "$HOME/Downloads/intelligenceos-sheets-key.json" && ssh root@137.184.180.155 'umask 077; test -d /root/.config/intelligenceos-sheets && test ! -L /root/.config/intelligenceos-sheets && test ! -e /root/.config/intelligenceos-sheets/service-account.json && test ! -L /root/.config/intelligenceos-sheets/service-account.json && set -C && cat > /root/.config/intelligenceos-sheets/service-account.json' < "$HOME/Downloads/intelligenceos-sheets-key.json"
```

The transfer streams over SSH with restrictive creation permissions. If the
directory already exists, inspect its ownership/mode without reading credentials
before reusing it. Keep the directory outside checkout, reports and backup scope.

Read-only connection and validation (no SQLite or sheet writes):

```sh
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && ARBITRAGE_SHEETS_CREDENTIAL_FILE=/root/.config/intelligenceos-sheets/service-account.json .venv/bin/python -m app.sheets_intake check'
```

Explicit ingestion and acknowledgment:

```sh
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && ARBITRAGE_SHEETS_CREDENTIAL_FILE=/root/.config/intelligenceos-sheets/service-account.json .venv/bin/python -m app.sheets_intake ingest --database var/sheets-intake.sqlite3'
```

Each check/ingest emits a sanitized JSON summary: accepted, rejected,
already_stored, pending_acknowledgment, incomplete and a `rejections` list of
`{"code":"RAW_EXPORT_MISMATCH","field":"item_price_usd"}`-style diagnostics. Check's accepted count means
validation passed, not storage. Capture it privately if an audit is needed. For an
offline local inventory without credentials or network:
`.venv/bin/python -m app.sheets_intake summary --database var/sheets-intake.sqlite3`.
That summary reports durable stored/pending counts and the last completed import
summary, including accepted, rejected and already-stored counts.

Before the first five-record test: review/merge and separately install this change,
install optional dependency, provision/share the dedicated account, verify the
producer contract with five rows and a COMPLETE count of five, agree to the
exclusive editing window, run check, then explicitly run ingest. Verify five record
links and normalized observations, F:G acknowledgment, replay without duplicates,
and offline candidate keyword planning. Amazon execution needs separate planning
and authorization. No deployment or live test is included in preparation.

## Browser compatibility diagnosis (2026-10-29)

Inspection of checkout `5a60d48` confirmed that the original-browser compatibility
fix had not been implemented: `product()` compared the complete raw object to all
20 export columns and raised `Raw/export mismatch`. The counter-only exception
handler concealed that reason. An original browser object with the documented
aliases and no batch/export metadata necessarily failed that comparison. This is
an offline reproduction, not a claim that the live batch has no other validation
errors. The compatibility change and sanitized diagnostics are local changes;
the SSH check must use a checkout containing them. No live sheet check, credential
read, ingestion, sheet write, Amazon call or email was performed during diagnosis.

## Producer record ID compatibility

The original record `walmart-76063-20261029T010727Z-five-v1:17617453`
was rejected solely because the shared `[A-Za-z0-9_-]{1,128}` identifier
allowlist excluded `:`. A record-specific `[A-Za-z0-9_:-]{1,128}` validator
preserves this existing key. Batch/source identifiers retain the earlier rules.
Global duplicate/conflict checks, exact SQLite primary keys, batch foreign keys
and immutable content hashes are unchanged. No sheet edit or record rename is
needed. Validation here uses original-browser JSON fixtures, never live Sheets.


Offline regression fixtures now include all five exact owner-supplied record IDs,
ending in `17617453`, `14922696`, `14906288`, `10310568` and `12443828`.
Each is validated individually and together as one five-record COMPLETE batch,
using original-browser JSON aliases, null shipping and external source/batch/export
metadata. Other product values in these tests are illustrative, not copies of the
live rows. Tests verify exact ID/batch retention, local fixture storage/replay,
five distinct observations and duplicate rejection for every ID. This establishes
format compatibility, not live sheet validation.


## Full contract audit and current verification limit

The shipping rejection came from the former four-value enum in `product()`, not
from a raw JSON mismatch. Descriptive browser values are now retained verbatim,
compared verbatim against raw JSON, and normalized separately. Descriptions never
supply fees, shipping charges or overall purchase availability.

| Export field(s) | Consumer check / browser mapping |
| --- | --- |
| `schema_version` | Literal text `1`; external metadata, checked if present in raw JSON |
| `batch_id` | 1–128 letters/digits/underscore/hyphen; exact COMPLETE batch selection |
| `record_id` | 1–128 letters/digits/underscore/hyphen/colon; exact global uniqueness and immutable stored identity |
| `source` | Envelope only; same identifier rule as batch, validated independently; absent from original browser JSON |
| `walmart_item_id`, `product_url` | 1–30 digits; HTTPS walmart.com/www.walmart.com `/ip/` URL ending in that exact ID; no URL credentials |
| `title`, `displayed_zip` | Nonblank title; exactly five ZIP digits, retained as text |
| `brand`, `selected_variant`, `seller`, `fulfiller` | Exact raw text including blank cells; no inferred seller or package eligibility |
| `item_price_usd`, `currency` | Positive finite price, USD; raw `displayed_price` permits leading `$`, numeric equality required |
| Three availability fields | Exact raw literal descriptions retained; independent conservative channel normalization |
| `shipping_charge_usd` | Blank means unknown; raw `shipping_charge: null` requires blank; known values must be finite, nonnegative and numerically consistent |
| `observed_at_utc` | Raw `observation_timestamp`; timezone-aware UTC instant, not future |
| `exported_at_utc` | External metadata; observed <= exported, not future |
| `raw_record_json` | JSON object; every observation field required, the three explicit aliases supported, conflicting canonical aliases rejected; older exact text mirror also supported |
| Batch fields | Exact headers/text cells; unique batch ID, COMPLETE, nonzero actual selected count equal to both count cells; exported <= UTC completion <= now |
| Storage/replay | Original rows/raw JSON retained; exact IDs and batch association; transactional uniqueness, immutable content hashes; check performs no storage or acknowledgment |

Schema headers/order, all-text cells, 1,000-row tab limits, response bounds and
sanitized rejection reporting remain unchanged. Blank trailing cells are padded,
not converted to zero. The browser object excludes `source`, `schema_version`, `batch_id`, `record_id`
and `exported_at_utc`; those are validated in the envelope. Optional legacy copies
are checked for conflicts but are never required. Null is currently supported
for raw shipping charge only;
other product values require exact text, including explicit empty strings. These
rules are recorded to expose unresolved producer assumptions, not to require a
sheet rewrite without inspecting the source.

`tests/fixtures/sheets_browser_five_representative.json` contains all five exact
owner-supplied IDs and the supplied descriptive availability examples. It passes
read-only validation and isolated mock-client SQLite storage/replay end to end.
**It is representative, not a reproduction of the actual five source records.**
The original five-row export was not found in the checkout or local browser task
artifacts. Still needed: each complete original JSON object, all exact exported
product values/blanks/prices/timestamps, source value, exported timestamps and the
COMPLETE batch row including completion time. The examples do not identify which
shipping description belongs to each record. No timestamps, prices or raw objects
have been invented and presented as actual source evidence. Full live-row
compatibility is unverified until an offline source snapshot is provided.


## Envelope-source correction and focused publication

The latest `RAW_FIELD_MISSING/source` rejection came from wrongly treating the
spreadsheet's provenance label as a browser observation. `ENVELOPE_FIELDS` now
explicitly includes source, schema_version, batch_id, record_id and
exported_at_utc. Envelope values retain their own identifier/schema/timestamp,
batch association and uniqueness checks. Raw consistency compares only the
observation fields and their documented aliases; optional legacy embedded
metadata cannot contradict the envelope. The original browser-object fixture
contains none of the five envelope fields.

Offline inspection found no workbook with both intake tabs among 95 local
repository workbooks outside archived validation environments. The actual uploaded
workbook therefore remains unavailable. The fixture uses the five exact supplied
IDs and documented descriptions but illustrative prices/timestamps/other values;
it establishes shape compatibility only. No producer records or runtime files
were rewritten.

Current remote main already supplies RetailProduct.source_context, ObservationStore
and the private transport helpers. The pure keyword formatter is isolated in
`app/source_keywords.py` to remove the otherwise unpublished Amazon-module
prerequisite. Only the Sheets module, formatter, optional requirements, tests,
representative fixture and these two intake documents belong to the focused PR.
No unrelated milestone ancestry, runtime reports/databases or credentials belong
in its commit.
