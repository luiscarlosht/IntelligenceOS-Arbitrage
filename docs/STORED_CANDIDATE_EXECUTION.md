# Variable-size stored-source Amazon candidate details

The existing `app.amazon_candidates` CLI now supports `prepare-details` and
`run-details` alongside its CSV `plan`/`run` modes. This is a generic execution
mode for 1–1,000 validated stored records, not a five-record/date-specific runner.
CSV request limits now derive from source size (5/10/20 rows -> 11/21/41 maximum
authentication/search/detail attempts); the existing twenty-record checkpoint
normalization and evidence-policy checks in the local milestone remain intact.

Stored mode reuses the existing Amazon transport, authentication exchange,
`detail_evidence` parser, `decide` matching gates, `persist`, ObservationStore,
history and workbook/report generation. It performs only the deduplicated missing
catalog details, with no searches, pagination, pricing, fees or restrictions.
Titles/selected candidate ASINs never create exact matches or purchase approval.

## Offline binding and preparation

`prepare-details` reads the intake SQLite database in read-only mode and validates
the selected acknowledged COMPLETE batch, exact record counts, source/row/batch
hashes and retained observation timestamps. Other valid batches may coexist.
The original reviewed preview and saved search/detail evidence are not rewritten.

The reviewed preview is revalidated against current source records and the exact
saved evidence bytes, historical queries, original source fingerprints, selected
ASINs and derived request budget. A separate owner-only, exclusive execution
manifest stores the original preview byte hash, source/batch lineage, every
original row/raw JSON, every complete saved search page, explicit reviewed
selection and exact request scopes. Its stable run key ignores output names and
plan evaluation timestamps; it binds source contents, record/ASIN choices and US
catalog scope. The live command must supply the prepared manifest byte SHA-256
and an independent explicit attempt cap. Any mutation rejects before credential
access or HTTP. An operator who intentionally changes the reviewed scope must
prepare and review a new manifest; this is not a replay bypass.

Offline preparation for the currently reviewed batch (already done; exclusive
manifest paths must not be overwritten):

```sh
.venv/bin/python -m app.amazon_candidates prepare-details --database var/sheets-intake.sqlite3 --reviewed-plan var/sheets-amazon-five-offline-20261029/reviewed-plan.json --manifest var/sheets-amazon-five-offline-20261029/detail-execution-manifest.json
```

The current reviewed plan has five reused historical search pages and five
missing distinct US catalog details. The prepared limits are authentication=1,
search=0, detail=5, total=6. No deferred enrichment requests are included.

## Durable execution and replay behavior

Execution uses the existing dedicated private Amazon directory. It creates a
separate owner-only `candidate-executions.sqlite3`, never mutating the intake
source database or historical reports. Each run has a `candidate-details-<run-key>`
JSON report, append-only JSONL checkpoints, and the existing separate per-run
SQLite evidence/history and XLSX workbook. Every original source outcome exists
in the committed SQL checkpoint before credentials are loaded.

A transaction claims every missing US catalog operation before authentication.
Operation keys bind ASIN, marketplace and included datasets independently of the
source batch/plan/output path. Overlapping future runs fail closed, even if a new
plan name/evaluation time changes the run key. An attempt is durably reserved
before I/O. SQLite uses FULL synchronous commits; its checkpoint JSON remains
authoritative if a JSON/JSONL write is interrupted. Files are private/exclusive,
never overwritten as a means to replay. No token, credential, request header,
raw provider response or arbitrary exception message enters these records.

On a request, parser, authentication, timeout or keyboard interruption, execution
stops without retry. All rows remain in the outcome/checkpoint; untouched rows
remain not_attempted and uncertain work remains reserved/failed. A hard crash
also leaves committed claims, so replay stops before credentials/HTTP. Successful
prior responses and their observation times remain retained. Presentation failure
after requests preserves SQL/checkpoint evidence and does not release claims.
There is deliberately no automatic resume or retry switch. Later recovery must
first inspect durable outcomes and create an explicitly reviewed missing-only
follow-up; do not delete ledger claims or use a different private directory to
bypass them. Nonattempted claims are conservatively retained after interruption.

Reused completed details are copied unchanged and cause no HTTP/authentication
when no missing work remains. Duplicate ASIN targets across records require only
one GET but retain all record outcomes. Incomplete/old search pages stay marked
historical; no automatic refresh/search is performed.

## Exact future live SSH command — not executed during preparation

```sh
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && .venv/bin/python -m app.amazon_candidates run-details --manifest var/sheets-amazon-five-offline-20261029/detail-execution-manifest.json --manifest-sha256 80a6f69ec6c65665c5f0d72515d91bb7fc64212364507c8e87d20d6c7100eb58 --max-attempts 6 --execute'
```

Only this future explicit execution reads the existing Amazon credentials. No
credential access, live Amazon requests, email, scheduling, sheet writes/clearing,
merge or deployment occurred during preparation. The source database and original
reviewed plan/saved evidence remain unchanged. Runtime manifests and evidence
stay ignored and are excluded from the PR.

Offline tests inject all transport/credential inputs. They cover stored and CSV
5/10/20-row compatibility; exact HTTP scopes/ceilings; hash/source/evidence and
endpoint tampering; partial/all detail reuse and ASIN deduplication; failures at
authentication and multiple detail positions; parser rejection; soft/hard
interruption; reservation-before-credentials/I/O; checkpoint/presentation failure;
replay and overlapping-run refusal; explicit CLI opt-in; multiple intake batches;
and source database immutability. Existing catalog/matching/reporting tests remain
applicable. No mocks invoke real credentials or remote endpoints.
