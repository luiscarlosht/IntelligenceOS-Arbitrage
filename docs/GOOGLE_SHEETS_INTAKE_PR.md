# Manual Sheets intake with original-browser compatibility

COMPLETE Walmart batches can be validated read-only or explicitly imported into
SQLite with immutable IDs, transactional storage, replay checks and a durable
acknowledgment outbox. The original browser JSON remains unchanged: source,
schema_version, batch_id, record_id and exported_at_utc belong to the spreadsheet
envelope. Price/timestamp/shipping aliases are checked for observation consistency.

Record IDs accept the existing colon-delimited producer format within the original
128-character bound. Literal shipping/delivery/pickup descriptions are retained
alongside independent conservative normalized values, without inferred charges.
Rejections expose only fixed codes and field names. Duplicate IDs, cross-batch
conflicts, changed stored batches, invalid money/timestamps/URLs and conflicting
raw values still fail.

The representative offline fixture uses all five supplied exact IDs and the
documented browser-object shape with no invented envelope fields inside raw JSON.
Other values are explicitly illustrative. The actual uploaded workbook was not
found locally, so compatibility with every actual source value remains unverified.
No credentials, live calls, sheet writes, production ingestion, Amazon calls,
email, merge or deployment are part of this preparation.

## Dependency and publication plan

Base the focused commit on current remote main. Main already contains
RetailProduct.source_context, ObservationStore and private transport helpers.
Isolate the pure keyword formatter into app/source_keywords.py; do not publish the
unrelated local Amazon candidate/checkpoint/enrichment milestones merely to obtain
that helper. Include only app/sheets_intake.py, app/source_keywords.py,
requirements-sheets.txt, tests/test_sheets_intake.py, the representative JSON fixture
and the two GOOGLE_SHEETS_INTAKE documents. Preserve all unrelated local changes
and runtime data. Validate both the existing VM checkout and the clean focused
commit archive before pushing the named branch and opening a draft PR.

Required checks: full pytest suite, both offline sample modes, workbook/SQLite
success checks, pip check and git diff --check. Report local validation separately
from GitHub CI. If Git transport fails, publish the reviewed tree through the
connected GitHub Git Data API, verify its file list/parent, then open a draft PR.
Never publish credentials or unrelated history to bypass a prerequisite failure.


Nullable observation comparisons use an explicit shared allowlist rather than a
shipping-only exception. The five-record fixture includes the owner-confirmed
null variants for 17617453 and 14906288, with blank exported cells, plus null
shipping charges. Missing observations stay missing; populated conflicts and
required fields remain strict. Raw values are retained and titles never supply
selected variants.

## ZIP normalization follow-up

A browser location `Mansfield, 76063` previously rejected against the exported
ZIP `76063`. Accept the explicit city-comma-space-ZIP shape while preserving raw
JSON and requiring agreement with the five-digit export. Reject conflicting,
ambiguous and malformed locations. Add a separate representative five-product
regression fixture with pack evidence, nullable variants and mixed shipping
charges; retain replay and changed-payload rejection coverage.

Local database inspection used SQLite mode=ro: original batch
`walmart-76063-20261029T010727Z-five-v1`, five records and five observations.
SHA-256 before/after: `589a5ebbdf77753b538300b3e95aa245f3ea16fa08982aa1eeaa21c2381d863c`.
No live operations were performed. Check ignores --database today; documentation
explicitly avoids claiming it can recognize already-stored batches.

Follow-up review scope: ZIP comparison in app/sheets_intake.py, the ZIP regression
tests in tests/test_sheets_intake.py, tests/fixtures/sheets_browser_five_zip_regression.json,
and these two intake documents. The checkout already contains earlier unpublished
Sheets work and unrelated changes; do not stage the entire working tree.

ZIP follow-up validation: baseline 1,137 tests passed; final full suite 1,149
tests passed; targeted intake suite 183 passed. Both documented offline sample
modes succeeded with readable workbooks and successful isolated SQLite histories.
`pip check` and `git diff --check` passed. Focused local patch and PR draft are
prepared under `/root/zip-normalization-pr/`; publication was not attempted because
this task forbids live calls.
