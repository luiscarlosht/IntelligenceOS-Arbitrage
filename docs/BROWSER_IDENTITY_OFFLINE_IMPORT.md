# Offline Browser Use identity import — B000I0TZO4

Reviewed against current main and the actual `ObservationStore` / `TargetStore`
APIs. This remains an identity-evidence import, not application matching or a
source-price/offer verification. No live provider/browser calls, credentials,
Sheets edits, email, runtime imports, merge or deployment were performed in review.

## Existing lineage is required

The selected existing owner-only database must already contain the original
`amazon:ATVPDKIKX0DER:B000I0TZO4` target revision and
`search:0920dcc561b655f5f94117745c58e286d97aa4ba0547ef34fcb60211c062a394`
job. These are the actual target/job tables introduced on main. Import does not
call `TargetStore.save_target`, `save_job` or initialize missing parent tables.
Missing databases, absent parents, mismatched target/job IDs, corrupted payloads
or an absent/mismatched pinned revision fail before any evidence insertion.

One `BEGIN IMMEDIATE` transaction validates the existing job's identity hash,
Walmart/76063 scope, target ID and pinned revision, checks that target payload's
fingerprint, then appends evidence and linkage. It does not complete a job/run,
update source observations, change intake columns, set an exact match, or write
profitability evidence. The target's package evidence is displayed as stored;
the importer no longer hardcodes an Amazon five-marker sale unit from the ASIN.
Browser run UUIDs remain external provenance, not invented application History runs.

## Raw preservation and replay

`import_file` preserves the supplied UTF-8 JSON text exactly, including whitespace,
key order, escapes, literal evidence and trailing newlines. The SHA256 identifies
those exact bytes. The fixture file is unchanged from the original PR. A mapping
passed directly to `import_record` has no original file bytes; its representation
is explicitly recorded as `canonical_object`, not claimed to be original text.
An optional `raw_json` must parse to the supplied record. Duplicate JSON keys,
nonfinite values, malformed or oversized inputs are rejected.

Exact duplicate imports add no rows and leave imported timestamps and payloads
unchanged. Different raw serializations are retained separately. A conflict means
different parsed content under the same verification ID; formatting differences
alone are not semantic conflicts. Conflicting models/statuses are preserved rather
than selecting a convenient observation. Comparison exposes every status
observation and reports `CONFLICTING_OBSERVATIONS` where there is no consensus.
SQLite triggers reject UPDATE/DELETE on the dedicated evidence/link tables.

## Observation schema aliases

Validation and comparison accept both the original schema and the actual supplied
Browser Use schema through these read-only aliases:

| Original field | Accepted alias |
| --- | --- |
| identity_browser_assessment | identity.browser_assessment |
| splitting_approved | identity.splitting_approved |
| result_delivery_status | delivery_status |

No normalized keys are inserted into the parsed observation or stored raw text.
If both representations exist they must agree in value **and type**, including
distinguishing boolean false from numeric zero. Conflicts fail explicitly before
database access. Explicit null is present, not a missing value or successful
default. Missing both identity-assessment or splitting fields fails closed;
missing both delivery fields reports `NOT_RECORDED`. Neither schema can grant
exact matching or splitting approval through this importer.

Different raw objects still remain separate observations under the existing
content-hash policy; alias support does not coalesce or rewrite their evidence.

## Prior LOCATION_FAILURE: reference only

The supplied identity JSON includes only the previous verification ID, run ID and
`LOCATION_FAILURE` status. Its complete raw failure record is **not supplied**.
The importer retains those three facts as a separate generated reference with
`raw_observation_available=false`, `record_scope=reference_only` and no invented
failure timestamp. It reports `full_location_failure_record_preserved=false`.
This is not reconstruction or full preservation of the failure observation.

The `kind=location_failure` label is retained for compatibility with the original
draft schema; the new scope metadata makes its reference-only nature explicit.
The complete raw prior failure, if recovered later, needs a separate reviewed
import path with its own unchanged payload and original timestamp. This module
does not fabricate that record or imply that a later identity response repaired
the failed location verification.

## Independent statuses and conservative interpretation

* Identity remains `PENDING_APPLICATION_REVIEW` even when a model appears to match.
* Location defaults to `NOT_VERIFIED_FOR_OFFER`; an explicit `LOCATION_FAILURE`
  stays independent. Displayed ZIP 95829 is contextual, not a Mansfield offer.
  Even ZIP 76063 text cannot confer offer verification in this identity-only path.
* Result delivery uses an explicit `result_delivery_status` or `delivery_status`
  (`COMPLETE`, `PARTIAL`, `FAILED`). The original fixture has neither, so it reports
  **`NOT_RECORDED`**, not an inferred COMPLETE based on successful ingestion.

The Walmart page claims **two packs × five markers = ten markers**. Individually
packaged five-marker sets, manufacturer confirmation and UPC/GTIN are unknown.
Historical prices cannot be divided by two to produce an acquisition cost. No
barcode, exact match, splitting approval, verified local offer, profitability,
purchase or listing approval is inferred. The raw claim is preserved as a claim.

## Additive storage and migration compatibility

The original nine-column `browser_verification_evidence` table and its raw rows
are not rebuilt or rewritten. `browser_evidence_links` is added alongside it,
pinning each imported evidence ID to a validated existing target revision and
recording scope/representation. Its evidence-ID foreign key references the
existing evidence table's primary key, compatible with both the original draft
and a new database. Existing core `evidence_schema` remains version 1.

No foreign key is added to `amazon_target_versions.target_id`: it is not unique
across revisions, and retrofitting core tables or invalidating legacy evidence
would require a separate migration. Target/job/revision consistency is enforced
transactionally using the same parent tables as the current storage API. Legacy
evidence remains visibly unvalidated until an explicit reimport validates its
parents and appends link metadata; the original bytes/timestamps stay unchanged.
No parent is invented to satisfy a reference or foreign key.

## Offline validation and operator usage

Integration tests create an actual owner-only temporary SQLite database, use
`TargetStore.save_target` / `save_job`, and seed an unrelated observation using
`ObservationStore.start_run` / `record_item`. They verify that all original core
rows, target/job data and unresolved run state remain unchanged. They cover exact
raw bytes, duplicate import, conflicting observations, immutable tables, invalid
linkage, independent statuses, missing costs, original-draft compatibility,
transaction rollback, foreign-key integrity and owner-only permissions.

```bash
.venv/bin/python -m pytest -q tests/test_browser_identity_import.py
```

To exercise the actual saved observation, while importing only into pytest's
temporary database:

```bash
BROWSER_IDENTITY_ALIAS_INPUT=/root/IntelligenceOS-Arbitrage/var/browser-identity/verify-v2-B000I0TZO4-02-identity.json .venv/bin/python -m pytest -q tests/test_browser_identity_import.py
```

That test checks exact raw bytes/hash, one identity observation, reference-only
prior failure, existing-parent linkage and duplicate-import idempotency using the
real ObservationStore/TargetStore. CI constructs a synthetic alias-schema variant
from the existing fixture when this explicit input path is absent; actual runtime
observation JSON is not committed. The supplied file's SHA256 is
`986c073939cb44a6e3f8ddcafdaf2ae0381ec0ec0f0f05558a8045a0cedcf243`.

For a later deliberate offline import, select a database that already has the
real matching target/job (not a legacy history-only database). For example:

```bash
.venv/bin/python -m app.browser_identity_import --database /path/to/existing/targets.sqlite3 --input sample_data/browser_identity_B000I0TZO4.json
```

This review runs imports only against temporary test databases. Remaining limits:
one focused verification/target/job contract, no complete prior raw failure record,
no independent proof of browser claims or package splitting, no local offer or
acquisition cost, and no generalized full failure-record ingestion/migration.

The exact command for the actual saved observation and existing runtime parents,
prepared but **not executed** by the alias change, is:

```bash
cd /root/IntelligenceOS-Arbitrage && .venv/bin/python -m app.browser_identity_import --database /root/IntelligenceOS-Arbitrage/var/sp-api-amazon-first-20261031-final/targets.sqlite3 --input /root/IntelligenceOS-Arbitrage/var/browser-identity/verify-v2-B000I0TZO4-02-identity.json
```
