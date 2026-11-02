# M77 safety audit

## Scope and implementation identity

The implementation adds separate M77 modules; original M72–M76 application modules
and immutable reports are unchanged. The reviewed scope is 31 exact first-page
queries, q020–q050, with US marketplace, frozen includedData and page size 20.
The maximum consumed budget is 32 slots, including one LWA authentication, and
620 raw observations. [The request manifest](M77_REQUEST_MANIFEST.json) contains
all exact phrases, original intent labels and request parameters. The canonical
request-definition digest is
`6f07ab81c826d09055665029169aa4658ccf250c5870c43b32a695a44b6cea07`.

The current application-source and offline-wrapper hash map is committed in
[M77_IMPLEMENTATION_HASHES.json](M77_IMPLEMENTATION_HASHES.json).
Its canonical implementation digest is
`06cb6a95cdfd198483c57167c155dd223b7d21c9d980c84504b0af5bfdde8343`.
The canonical preflight SHA-256 also binds the entire exact budget dictionary;
authorization checks both the preflight hash and every budget value and integer type.

This binds all application Python files and the offline wrapper, including shared
transport, pacing, parsing and persistence dependencies. Tests and documentation
are reviewed through the Git commit; the implementation map does not claim a
self-hash or bind future edits.

## Real-evidence offline validation

Two actual guarded preflights produced byte-identical review files. Process audit
hooks prohibited network events and credential/owner-authorization artifact reads.
Original M73/M74/M75 validation and exact M76 report reconstruction passed; both
supplied M76 pins and the M75 checkpoint matched. All **157 protected evidence
entries** retained their inventory, sizes, modes, mtimes, inode/owner/link metadata.
Original file content hashes are checked by the historical validators and guard.

| Artifact | SHA-256 |
| --- | --- |
| Canonical preflight | `1f15e2c5921586a491d6f3bff3b7f208b16332bace6f42226c10b85903310e5b` |
| Preflight file | `4d1afd748831143a481d79e7c1f18c016b2f5ac218058722fdceaa18a693dfc9` |

Private ignored artifacts are `var/m77-dry-run.json`,
`var/m77-dry-run-repeat.json` and `var/m77-offline-validation.json`.
They are review evidence, not permission to execute. No M77 registry exists and
no live authorization was created or consumed. Actual authentication and Amazon
request counts are **zero**. Production credential values were not read.

## Control review

| Boundary | Enforcement and evidence |
| --- | --- |
| Historical evidence | Pinned M76 manifest/proposal, exact directory and output digests, original implementation hashes, reconstructed report, complete M73/M74/M75 chain and 21-slot M75 completion |
| Fixed scope | Original proposal equality plus exact ranks/IDs/phrases; fixed transport scope; query, endpoint, headers, marketplace, includedData and page size validated before send |
| Fresh owner permission | Separate M77 schema and operation; hidden seller confirmation; reviewed/current preflight equality; exact code, evidence, account, request and budget binding; at most ten-minute validity; explicit flag and file digest |
| Credential isolation | Dry-run prohibits values; execute verifies authorization under global lock before reading values, verifies original content digest and checks content before every dispatch |
| Durable accounting | Exclusive new registry, fsynced file/directory creation, SQLite FULL synchronous intent commits before dispatch, sequential slots, immutable triggers, event chain and strict completion checks |
| Permanent no replay | Any existing registry blocks execution, including empty, failed, corrupt or SIGKILL-interrupted claims; no reset/delete/resume path |
| Concurrency | Existing global account lock, exclusive nonblocking flock; all authorization and evidence rechecked under lock |
| Bounded network | Exact LWA/Catalog endpoints, verified TLS, no proxy/redirects/retries, socket/body bounds, conservative pacing, saved cooldowns/lower observed rates, 180-second hard deadline |
| Failure handling | Errors, throttles, malformed/oversized pages, expiry and interruption stop; uncertain slots remain consumed; already validated responses remain attributable |
| Private outputs | 0700/0600; exclusive new output paths outside historical evidence; cleaned observations, normalized source adapter, counts/checkpoint/digests; read-only recovery |
| Product claims | Original provenance/conflicts retained; no fabricated attributes or eligibility/economics; pricing/fees/retailer/purchase operations disabled |

## Validation coverage

Tests use synthetic credentials, temporary accounts, fabricated product replies,
synthetic authorization artifacts and injected transport only. Those artifacts are
not live owner permission and their products are not real discovery observations.
Network connections/DNS and production credential/owner-artifact reads are prohibited
by the offline regression audit hook, including in Python subprocesses.

Coverage includes exact definitions and first/last slots, all authorization/budget
bindings, missing live gates, hidden input/TTY failures, freshness/future/naive
expiry, credential-content drift with preserved metadata, mid-run revocation,
zero-request stops, before/after-accounting interruption, SIGKILL durability,
strict ordering/ceiling/no replay, immutable chain corruption, empty/corrupt
registries, global lock contention, deadline/rate-limit stops, token expiry without
refresh, partial and empty pages, oversized responses, scope violations, cursor
privacy, private normalized exports, output protection, and credential-free recovery.
The M77 evidence tests independently mutate original M76 outputs, code and all
candidate definition boundaries. Existing tests retain prior source/provenance and
M75 registry/accounting contracts.

Both documented orchestrator sample modes (legacy and discovery) and `app.demo`
passed with sockets blocked, using only fictional local fixtures. Baseline targeted
M75/M76 validation passed: **134 tests**.

Reproduce the guarded checks with:

```bash
.venv/bin/python -m ops.m77_test_offline -q tests/test_m77.py tests/test_m77_evidence.py
.venv/bin/python -m ops.m77_test_offline -q
```

The wrapper creates a temporary inherited Python audit hook; it blocks connection,
DNS and datagram-send events and production credential/live-owner-artifact reads.
It permits synthetic test-only artifacts in temporary directories. It supplies
`offline-test.invalid` as the synthetic local SMTP greeting name, so mocked SMTP
constructors do not attempt host DNS lookup. DNS and connection prohibitions remain
active. The SMTP diagnostic regression passed **70 tests** under this guard.

Final targeted M77 validation: **145 passed in 499.26 seconds**.
Full regression results are recorded below after completion.

## Operational limits

This PR provides implementation and offline evidence only. It does not merge,
deploy, schedule, authorize, execute or reserve ASINs. A separately reviewed fresh
owner authorization is required for any future live operation. Yield is unknown;
the baseline remains 777 real ASINs with 223 remaining.

A deadline or low observed rate can stop before all 31 pages. An incomplete/corrupt
journal blocks recovery as well as replay; preserve it for investigation. Recovery
validates current code/evidence/account/credential metadata against the claimed
preflight and requires that binding to remain unchanged. It reads no credential
values or owner artifacts. Lost/unanswered responses cannot be recovered, and a
partial output never proves completion. Restrictive file permissions, fsync and
SQLite protect normal operation; they do not claim protection against a malicious
host administrator rewriting the entire filesystem and code.
