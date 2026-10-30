# Stored-source catalog candidate execution

`app.stored_candidate_search` adapts a stored-row planning manifest to the existing
variable-batch candidate runner. The original `offline_missing_candidate_evidence_plan`
is not executable. Preparation creates a separate `stored_candidate_search` manifest;
run requires its exact SHA-256, an explicit cap no greater than 77 and `--execute`.
There is no scheduler integration. Intake-format compatibility from PR #36 is a
prerequisite for the actual multiline/observed-price source rows.

Preparation/check open intake SQLite with mode=ro and query_only, verify integrity,
all selected complete acknowledged batches, row/raw hashes, observation fingerprints
and timestamps, and rebuild every query and detail template. Exactly every row in
the selected batches must be covered once. One to 38 records are supported. Database
bytes, planning manifest, evidence inventory, reports and prior ledger bytes are
bound; changed inputs require offline review rather than automatic refresh.

The 38-row ceiling is one authentication + 38 first-page searches + at most 38
conditional catalog details = 77 total HTTP attempts. Pricing, fees, restrictions,
pagination and retries are absent. A 300-second deadline and 0.5-second minimum
interval apply. Only one returned candidate with the same whitespace/case-normalized title is
selected as a detail investigation lead; other or ambiguous titles skip details.
This conservative policy never establishes exact identity or purchase approval. Same-run ASIN details are
deduplicated, and compatible successful scoped historical details retain their
original observation times. Conflicting, incomplete and uncertain prior detail
evidence blocks a fresh call for that ASIN, including the historical Scotch case.

Execution reuses the existing private report, parser, diagnostics and persistence
boundaries. It claims every source-search key transactionally in the existing
candidate-executions.sqlite3 ledger before credential access, then durably reserves
each authentication/search/detail before HTTP. Search keys bind Walmart ID and US marketplace independently of URL, query,
price, record/batch ID, manifest time or output name; URLs remain separately
source-bound. Detail claims share the existing ASIN scope/key contract. Historical
CSV reports also block repeated searches and uncertain details. Crashes and transport
failures consume reservations; no clearing, retry or replay bypass is provided.
The existing CSV interface and stored-detail/research entrypoints retain their
behavior. A failed stage retains all source rows and sanitized diagnostics.

Offline preparation:

```sh
.venv/bin/python -m app.stored_candidate_search prepare --plan var/sheets-amazon-38-offline-20261030/bounded-manifest.json --manifest var/sheets-amazon-38-offline-20261030/execution-manifest.json
```

`check --manifest PATH --expected-sha256 HASH --max-attempts 77` revalidates source,
evidence, bounds and replay state with no credentials, ledger writes or HTTP.
`run` takes the same arguments plus `--execute`; it is a future owner action, not
part of preparation. Existing output manifests are never overwritten. Runtime
plans/reports/databases are private ignored artifacts, excluded from the PR.
