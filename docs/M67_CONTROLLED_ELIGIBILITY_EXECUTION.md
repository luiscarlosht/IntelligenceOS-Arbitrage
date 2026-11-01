# M67 controlled Listings Restrictions execution

M67 adds a manually invoked, authorization-gated executor to the unchanged M65/M66
architecture. Installing it, importing modules, CLI help, preflight and reporting
do not authenticate or send requests. It is never registered with a scheduler.
Implementation and review authorize **zero live calls and zero real reservations**.

## Architecture and boundaries

- `app/m67_policy.py`: read-only original M66 manifest validation, source/code/history
  reconstruction, private-storage checks, original M63 permanent reservation proof,
  legacy attempt-ledger inspection and separate authorization validation.
- `app/m67_state.py`: read-only M66 store view and private append-only global SQLite
  ledger. Every batch, ASIN, request attempt and sanitized outcome is permanent.
- `app/m67_transport.py`: allowlists the existing single LWA exchange and exact US/New
  Listings Restrictions GET. Reuses verified TLS, bounded responses, no proxies,
  no redirects and no retries from `amazon_pilot`; bypasses its default implicit pacer.
- `app/m67_execution.py`: Stage B only; existing cross-version execution lock,
  revalidation under lock, global reservation, existing M65 reservation/attempt mirror,
  bounded pacing and a 120-second main-thread execution deadline. No automatic refresh.
- `app/m67_reporting.py`: frozen M66 measurement, actual consumed budgets and idempotent
  allowlisted import into M66 results and M65 eligibility events. It never creates
  missing attempt proof. Reporting/import take a shared existing execution lock.
- `app/m67.py`: explicit `preflight`, `report`, `import-results`, `execute` actions.
  Only the last action can access credentials or transport, after separate review.

The M65/M66 code-bound files are unchanged, so the original manifest remains valid.
Catalog, Pricing, Fees, FBA APIs, retailers, offers, approvals and purchases are absent.
There is no approved-authorization generator or automatic follow-on operation.

## Stage A: offline preflight

Required inputs are the original manifest bytes/digest, its original catalog sources,
unchanged derived M66 intelligence store and original private historical directory.
Preflight reconstructs the M66 proposal, including exact ordered ASINs and ranking;
it rejects digest, source, code, store, scope or history drift. It requires the original
20-ASIN M63 `claimed_no_replay` reservation and reads the legacy SQLite attempt ledger.
It also rejects all global M67 claims, including claims absent from a restored derived DB.
The limit is at most 20 restrictions plus exactly one authentication slot, zero retries,
and zero other operations. Budgets must be integers; smaller reviewed cohorts are allowed.

Preflight opens SQLite read-only/query-only and never creates schemas, locks,
reservations, credentials or account bindings. It requires quiescent databases and
owner-only storage, verifies append-only triggers, checks writable storage and free
space, and checks credential-file **metadata only**. Credential contents and validity
are deliberately not checked offline. Storage checks cannot guarantee future disk
availability; any later persistence failure stops dispatch.

### Private account binding

Before a future execution can become ready, an operator must privately provision
`/root/.intelligenceos-arbitrage-amazon/m67-account-context.json`, mode 0600, in the
existing owner-only directory. Its exact keys are:

| Field | Value |
|---|---|
| `account_reference` | `existing-authorized-us-account` |
| `marketplace_id` | `ATVPDKIKX0DER` |
| `condition` | `new_new` |
| `seller_id` | Existing seller's private ID, entered locally only |
| `credentials_sha256` | SHA-256 of the existing credential file's exact bytes |

This is a private operator-reviewed binding, not API verification of the token's
seller association. Do not put its contents in chat, shell arguments, reports or Git.
Do not print credential files. Preflight exports only the binding file hash and alias;
Stage B pins this hash and checks the credential bytes against the private binding.
A missing binding produces a useful preflight report with `ready=false` and exit 2.
`ready=true` means offline prerequisites passed; it never means execution is authorized.
No such binding or approved authorization is created by this implementation task.

## Stage B: separate human review, never run during development

A new owner-only authorization JSON file and its exact file SHA-256 are required,
in addition to the original manifest and an explicit CLI `--execute` flag. The
original M66 manifest continues to say execution is unauthorized. An existing digest
or a ready preflight is insufficient. Do not edit the original manifest to enable it.

Authorization has exactly the following keys (this is a schema, not an approved artifact):

| Keys | Required binding |
|---|---|
| `schema` | Integer 1 |
| `approved`, `execution_permission`, `no_retry` | Explicit boolean true, supplied only by a human after review |
| `manifest_sha256`, `asins` | Exact original file digest and exact ordered cohort |
| `account_reference`, `marketplace_id`, `condition` | Exact existing-account alias, US, `new_new` |
| `account_binding_sha256` | Private binding file SHA-256 |
| `budget` | Exact manifest budget, including authentication, total, retries and zero disabled operations |
| `implementation_sha256` | Current M67 and transport dependency hashes from preflight |
| `preflight_sha256` | `app.observations.fingerprint()` of the parsed preflight report |
| `review_reference` | Nonsecret `manual:` review reference |
| `reviewed_at`, `expires_at` | Aware ISO timestamps; reviewed <= now < expiry |

Review the code, ordered cohort, account binding, original evidence, budgets and
preflight before granting permission. The executor validates the authorization artifact's
file digest, then repeats validation while holding `candidate-execution.lock` exclusively.
Credentials load only after this validation. Review expiration is checked before every
request. The executor is Linux/main-thread only; it fails closed if its deadline cannot
be installed. Authentication or token-validation failure consumes its slot and stops;
401/403/429/5xx, timeouts, malformed replies or redirects never refresh or retry.

The Stage B CLI requires `execute --authorization <private-file>
--authorization-sha256 <reviewed-file-digest> --execute`, plus the same manifest,
source, store and private-directory arguments. This document intentionally supplies
no approved artifact or ready-to-run live command. **Do not invoke it for M67 review.**

## Durable accounting and crash recovery

New Stage B records live only in private `m67-executions.sqlite3`. Its batch claim and
all exact ASIN claims commit atomically before transport. Existing M65 batch and ASIN
claims are then mirrored in the derived M66 store. These two databases are not a
distributed transaction: a crash between commits permanently burns the cohort in the
global ledger without sending a request. This conservative gap is intentional.

For each call: check expiration/deadline, acquire pacing, validate request allowlist,
commit global request consumption, commit the M65 attempt mirror, then invoke exactly
one transport. Authentication is counted identically. SQLite uses `synchronous=FULL`,
DELETE journals, owner-only regular files and UPDATE/DELETE rejection triggers.
New ledger creation uses exclusive creation and directory fsync. Existing damaged
ledgers are rejected, not repaired. Root-level filesystem tampering/rollback cannot
be prevented by SQL triggers: preserve the original private directory and backups.
The atomic reservation also stores only hashes of the separate authorization,
account binding, preflight and executor bindings. Original authorization files are
never rewritten. Server cooldowns are restored read-only from the legacy ledger;
new cooldowns persist only in M67's private ledger, including on HTTP 429.

Any possibly sent request stays consumed, including a timeout or killed process.
A reserved batch cannot restart, even with zero attempts. No reset/release/resume,
replacement ASIN, retry or request-budget expansion is exposed. Missing outcome after
consumption is reported as `UNCERTAIN`/`UNKNOWN`; it never becomes unchecked permission
to retry. Unattempted members remain unchecked in reports but globally reserved.

After interruption, use offline `report` to inspect the frozen experiment. Optional
`import-results` copies sanitized results idempotently, requires existing local attempt
proof, reports unreconciled gaps and rejects conflicts. It never reserves missing proof.
An interruption between result import and eligibility-event import is recoverable by
repeating this offline import; repeating an HTTP request is never recovery.

## Response semantics and evidence

Only HTTP 200 with correctly scoped valid `restrictions: []` or exact `[{}]` yields
`NO_REPORTED_RESTRICTIONS`. Real restriction rows with missing reasons remain
`OTHER_RESTRICTED`; ambiguous/malformed/failed or wrong-scope responses stay `UNKNOWN`
and stop. Valid approval or ineligible outcomes are successful API operations.
There is no `SELLING_PERMISSION_CONFIRMED` state. Catalog access, Copy listing and
popularity provide no authorization. Existing-ASIN offer-only review and independent
Seller Central/FBA inbound verification remain necessary; no offer is submitted.

Persisted outcomes contain only fixed classifications/reason codes, sanitized HTTP
status/failure category, aware observation timestamp and a response-content hash.
Local immutable request IDs bind digest and operation/ASIN. Amazon headers/request-ID
strings and complete private responses are intentionally not exported. Exception text,
URLs containing seller IDs, tokens and credential values never enter results or logs.
Raw response evidence is hashed in memory and discarded; no private body archive is made.

Frozen reporting uses the original manifest and ranking snapshot, never a new selection.
It includes per-ASIN/brand/category results, all five eligibility counts, unchecked,
failed/uncertain, conflicts, immutable hash references and auth/restriction/total budget
consumption. Zero observations gives a null unrestricted fraction. Consumed slots are
an upper bound on actual HTTP dispatch after a crash. Counts describe this experiment;
they never imply brand-wide permission or statistical representativeness.

## DigitalOcean update and offline verification commands

These commands are instructions for a later operator session; they do not deploy a
service, authorize or execute the experiment. Preserve the private directory and `var/`.
If the working tree is dirty, stop and preserve that work before switching branches.

```bash
cd /root/IntelligenceOS-Arbitrage-M61
git status --short
test -z "$(git status --porcelain)"
git fetch origin main
git fetch origin feature/m67-controlled-eligibility-execution
git switch feature/m67-controlled-eligibility-execution
git merge --ff-only origin/feature/m67-controlled-eligibility-execution
.venv/bin/python -m pytest -q tests/test_m67.py
.venv/bin/python -m pytest -q
.venv/bin/python -m app.m67 --help
sha256sum var/m66-expanded-review/M66_review_manifest.json
.venv/bin/python -m app.m67 preflight \
  --manifest var/m66-expanded-review/M66_review_manifest.json \
  --manifest-sha256 8983bef70ce5cfd79d15b7611e4b5646784f37bfce1a88bd220286394303ee55 \
  --catalog /root/.intelligenceos-arbitrage-amazon/m63-catalog-discovery-01.json \
  --catalog /root/IntelligenceOS-Arbitrage/var/m63-final-review-20261101/M63_amazon_candidates_100.csv \
  --store var/m66-local/intelligence.sqlite3 \
  --private-dir /root/.intelligenceos-arbitrage-amazon
```

The absolute source paths above were verified against this runtime's original source
hashes. If paths differ elsewhere, locate the unchanged original files by hash; never
regenerate substitutes. A missing manifest/source/history/database blocks validation.
To save preflight, add `--output <new-ignored-private-report.json>`; existing files
are never overwritten. Do not commit generated reports or private runtime databases.

Offline frozen report, including CSV export (no requests, no reservations):

```bash
mkdir -m 700 var/m67-review-results
.venv/bin/python -m app.m67 report \
  --manifest var/m66-expanded-review/M66_review_manifest.json \
  --manifest-sha256 8983bef70ce5cfd79d15b7611e4b5646784f37bfce1a88bd220286394303ee55 \
  --store var/m66-local/intelligence.sqlite3 \
  --csv-dir var/m67-review-results
```

Exports retain existing `M66_experiment_*` filenames and include M67 accounting in
JSON. They are immutable owner-only files with formula-safe CSV cells. Real result
imports are not needed for implementation review. Synthetic tests exercise temporary
claims and in-memory review inputs only; they never create approved authorization files.

## Implementation validation

Baseline: 1,374 tests passed. M67: 114 targeted tests passed; final regression:
1,488 passed. Both legacy and discovery mock sample jobs exited 0 with isolated
runtime state, no email configuration and socket connections blocked. Tests cover
tampering, historical/global exclusions, authorization drift/expiration, budgets,
HTTP and authentication failures, process exit before transport, interruptions,
no replay/retry, unknown responses, manual conflicts, importer idempotency, immutable
storage, private-value rejection and frozen reports/CSV.

The original `8983bef7…3ee55` manifest was validated read-only against both original
sources and the current store: 20 ordered candidates, 77 historical exclusions,
20+1 requests and zero retries. Protected M63 reservation, legacy ledger, M66 store
and manifest bytes were identical before and after validation. Execution readiness
is blocked by the absent private account binding. No credential contents were read;
no live calls, approved authorization files or real execution reservations were made.

The live adapter remains unexecuted. Readiness depends on locally provisioning and
reviewing the private account binding, quiescent rollback-journal databases, unchanged
original evidence and a fresh explicit authorization. No permission or FBA eligibility
is asserted for any proposed product. This PR must not be merged or deployed automatically.
