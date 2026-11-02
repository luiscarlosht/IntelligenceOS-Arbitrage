# M78 offline consolidated catalog and identity quality

Issue #67 authorizes implementation, synthetic tests and a review PR only.
No production evidence has been inspected or processed for this implementation.
Running against production evidence needs separate explicit owner authorization.
M77 replay, Amazon/API calls, credentials, listings, purchases, merging and deployment
are outside this authorization.

The Linux/Python 3.12 entry point is `python -m ops.m78_offline`. It requires
`--catalog` (curated M76_catalog.csv), `--annotations` (M76 historical annotation
JSON list), `--sources` (M77_M70_sources.json pointing to saved pages), and
`--output` (fresh directory with an existing parent, outside all input directories).
There is no CLI bypass for the expected M76/M77 invariants. Do not execute this
command on production inputs under the current authorization. The Python API's
`verify_expected=False` is solely for small synthetic tests.

M76 CSV values and conflict decisions remain authoritative. The CSV's single
spreadsheet-safety escape is decoded; records are never reconstructed as raw
independent observations. Available provenance is retained; absent provenance
remains unknown, including conflict alternatives absent from the CSV. Historical
annotations remain separate: the 56 excluded ASINs outside the catalog do not add
rows. Historical seller checks never become current eligibility. Explicit curated
incomplete decisions cannot be promoted by recalculating field coverage.

Only completed, unique first-page saved M77 keyword pages are accepted. M70's
source adapter and identity merge normalize those records and retain field
provenance, alternatives and conflicts. Any rejected observation blocks completion.
Exact duplicate observations reconcile by ASIN; overlaps retain the M76 decision
and the M77 evidence separately, with a mandatory review block. The expected
production profile requires zero overlap and verifies both individual cohorts and
combined metrics from the actual inputs; no expected count supplies report data.

Classification precedence is Blocked (permanent exclusion, conflict or explicit
review block), then Needs review (any of the ten M70 identity fields missing),
then Identity ready. Catalog completeness excludes condition and remains a separate
structural measure. Eligibility and economics remain UNKNOWN; purchase-ready and
purchase authorization remain false even for Identity ready records.

JSON preserves normalized data; CSV and Excel use formula-safe cells. SQLite stores
the same canonical row payloads, with separate catalog, identity quality, conflicts,
annotations and summary tables. All formats have deterministic row/key order;
Excel creation/modified times and ZIP metadata are fixed. Long Excel cells fail
rather than truncate evidence. The SHA-256 completion manifest covers every input,
all application Python code and the entry point, and every report output (excluding
the manifest itself). Its own digest can be computed independently.

Generated directories are 0700 and files 0600. Symlink paths and output paths under
protected input directories are rejected, including normalized `..` paths. Reports
are written in a private sibling staging directory, source/code drift is checked,
and Linux `renameat2(RENAME_NOREPLACE)` publishes the entire directory on the same
filesystem. Existing destinations, including a racing empty directory, are never
overwritten. Exceptions and KeyboardInterrupt remove only the invocation's staging
directory using Python's symlink-resistant rmtree; no completed manifest is
published on failure. A process kill or host crash can leave a private staging
directory, which is not a completed run. This is atomic publication, not a claim of
host-crash durability or protection from a malicious process running as the owner.

The process audit guard denies Python sockets, process launch/dynamic library
loading, credential/authorization paths and undeclared input reads. It permits
explicit source paths, application/library code and files created by the run.
No transport module is imported by M78. Audit hooks do **not** provide a complete
OS network sandbox: native code, inherited descriptors and other same-user
processes are outside that guarantee. Use an OS-enforced network-disabled,
credential-free environment for any separately authorized production execution.
No credential or authorization artifact is required as an M78 input.

Validation uses only temporary synthetic evidence in `tests/test_m78.py`, including
a full expected-scale fixture. Commands and final results are recorded in the PR.
Run the M78 tests with `python -m pytest -q tests/test_m78.py`; relevant regressions
are `tests/test_m70.py`, `tests/test_m76.py`, `tests/test_m77.py`, and
`tests/test_m77_evidence.py`. The full suite and both README sample modes are also
required before review.
