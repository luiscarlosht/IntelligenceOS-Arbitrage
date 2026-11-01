# M68: local-only M67 human authorization preparation

M68 prepares the separate authorization schema that unchanged M67 already requires.
It supports only the original frozen M66 manifest with SHA-256
`8983bef70ce5cfd79d15b7611e4b5646784f37bfce1a88bd220286394303ee55`:
20 exact ordered ASINs, existing account alias, US `ATVPDKIKX0DER`, `new_new`,
one authentication slot, 20 restrictions slots, maximum 21 HTTP requests,
zero retries and zero other operations. It never authenticates, sends requests,
creates execution reservations, submits offers/applications, or purchases anything.
There is no execute, scheduler, retry, account-binding creation or automatic follow-on action.

## Workflow and human confirmation

`python -m app.m68 prepare` reads an existing owner-only M67 preflight and reconstructs
it using the original manifest, sources, current code, historical records, original
M63 reservation and legacy ledger, derived store and M67 global claims. The saved
and fresh reports must have identical canonical fingerprints and `ready=true`.
It also checks the private account-binding hash and hashes credential-file bytes
against that binding locally. Credential contents are never parsed or printed by M68.
A matching digest proves file continuity; it cannot prove the seller/token association
offline. The operator must have verified that association privately using existing
records. No new Amazon authentication or account probe is allowed for this milestone.

Before producing authorization, the command opens a private terminal and requires:

1. Re-entry of the privately verified seller ID using hidden input, compared with
   the existing binding without displaying either value.
2. Hidden entry of the exact phrase `I VERIFIED THE ACCOUNT; PREPARE ONLY`.

Missing terminal, echo fallback, rejection, empty input, incorrect seller or phrase
fails closed. No seller-ID argument, environment confirmation, `--yes` or confirmation
bypass exists. M68 revalidates evidence after confirmation before writing anything.
The validity window is exactly 15 minutes, beginning after confirmation; it cannot
be extended by a CLI option. Keep the local UTC clock accurate.

Ubuntu SSH PTYs are non-seekable character devices. Confirmation opens `/dev/tty`
once using `os.open` and unbuffered binary I/O beneath a text wrapper, avoiding the
buffered `r+` seek failure. Both inputs use this pinned descriptor with terminal
echo disabled and settings restored in `finally`. Missing TTY, echo-control errors,
EOF or interruption fail closed; stdin is never a fallback, even when it is a TTY.
The exact constant-time comparisons, schema, expiry and request limits are unchanged.
This code change invalidates old M68 code-bound receipts as intended. Preserve
existing private artifacts; any later authorized preparation must use a fresh name.

The artifact contains exactly the M67 schema, including `approved=true` and
`execution_permission=true`, which M67's policy requires. These fields make it a
sensitive execution-capable review artifact. **This M68 task authorizes preparation
only. Do not invoke M67 execution.** M67 still independently requires its explicit
execution flag, current evidence and permanent budget reservation. Validation calls
M67's pure policy validator with a simulated flag; it never calls its executor.

## Private storage and deterministic evidence

Outputs are restricted to the existing `/root/.intelligenceos-arbitrage-amazon`
directory, owned by the operator and mode 0700, outside the repository. The CLI
rejects another directory, path traversal, protected filenames and symlinks. Names
must match `m68-authorization-<nonsecret-label>.json`; no original file is overwritten.
Files are owner-only mode 0600, including during staging, regardless of the umask.

Preparation writes an accompanying `<name-without-json>.review.json` receipt with
artifact/account-binding/preflight hashes, M68 implementation hashes, timestamps
and the human-confirmation method. It contains no seller ID or credential values.
This keeps M68 code drift detectable without changing M67's exact artifact schema.
M67 code bindings remain in the artifact. Fixed inputs, clock, code and review
reference produce identical artifact/receipt bytes and digests.

Both files are fsynced and published with atomic no-replace hard links, receipt
first and authorization last, with directory fsync. The temporary hard link is
removed immediately; existing validators reject multiple links. A crash can leave
an orphan receipt or pending temporary file, or an authorization whose publication
was not acknowledged. Never assume such a file is validated. Preserve it privately,
use a fresh filename and require a new human confirmation if preparation must be
repeated. M68 never silently overwrites or cleans up existing review artifacts.

Stdout contains only status, SHA-256 digests, expiry and explicit zero-operation
counters. It never prints artifact contents, private paths, seller ID, tokens or
exception messages. Argument errors are fixed/redacted, including mistakenly
supplied private arguments. Do not `cat` the artifact, binding or credentials into
chat, logs or shell history; do not commit runtime files.

## Separate read-only validation

`python -m app.m68 validate` requires the artifact and receipt digests reported by
preparation. It verifies permissions, single links, exact digests/schema, ordered
scope, current ready preflight, credential/binding continuity, M67 and M68 hashes,
confirmation receipt and expiration. It calls the existing M67 authorization
validator with current read-only history. It never prompts or rewrites files,
renews validity, creates a database/lock/reservation, authenticates or sends requests.
Existing execution locks are acquired shared/nonblocking; no lock is created.

Successful validation means the artifact currently passes M67 policy checks.
It is not permission to execute during this milestone and is not evidence that any
ASIN is unrestricted, offer creation is available, FBA eligible or profitable.

## Exact DigitalOcean commands (operator-run, offline only)

The preparation command must be run by the owner in a private SSH terminal; an
agent must not simulate the account confirmation. No command below executes M67.
Do not modify the existing private account binding through this workflow. Missing
binding, source, saved evidence or a dirty checkout blocks progress.

Update the review branch and run offline tests without changing service settings:

```bash
cd /root/IntelligenceOS-Arbitrage-M61
git status --short
test -z "$(git status --porcelain)"
git fetch origin main
git fetch origin feature/m68-offline-authorization
git switch feature/m68-offline-authorization
git merge --ff-only origin/feature/m68-offline-authorization
.venv/bin/python -m pytest -q tests/test_m68.py
.venv/bin/python -m pytest -q
.venv/bin/python -m app.m68 --help
```

Use original source bytes at their verified locations. If paths differ, locate the
original files by hash; never reconstruct substitute sources or a manifest.
Generate a current saved M67 preflight under a new private name:

```bash
m68_review_tag=$(date -u +%Y%m%dT%H%M%SZ)
m68_preflight="/root/.intelligenceos-arbitrage-amazon/m68-preflight-${m68_review_tag}.json"
m68_authorization_name="m68-authorization-${m68_review_tag}.json"
m68_args=(
  --manifest var/m66-expanded-review/M66_review_manifest.json
  --manifest-sha256 8983bef70ce5cfd79d15b7611e4b5646784f37bfce1a88bd220286394303ee55
  --catalog /root/.intelligenceos-arbitrage-amazon/m63-catalog-discovery-01.json
  --catalog /root/IntelligenceOS-Arbitrage/var/m63-final-review-20261101/M63_amazon_candidates_100.csv
  --store var/m66-local/intelligence.sqlite3
  --private-dir /root/.intelligenceos-arbitrage-amazon
)
.venv/bin/python -m app.m67 preflight "${m68_args[@]}" --output "$m68_preflight"
```

Continue only if preflight reports `ready=true` and exits 0. Preparation requires
both hidden confirmations; never put a seller ID in any command or environment value:

```bash
.venv/bin/python -m app.m68 prepare "${m68_args[@]}" \
  --preflight "$m68_preflight" \
  --name "$m68_authorization_name" \
  --review-reference manual:M68-owner-review
```

Copy the two digests from that command's safe summary into the following prompts.
Do not replace reviewed digests by silently computing them from subsequently edited
files. Validate immediately within the 15-minute window:

```bash
read -r -p 'Preparation authorization SHA-256: ' m68_authorization_sha
read -r -p 'Preparation receipt SHA-256: ' m68_receipt_sha
.venv/bin/python -m app.m68 validate "${m68_args[@]}" \
  --preflight "$m68_preflight" \
  --name "$m68_authorization_name" \
  --authorization-sha256 "$m68_authorization_sha" \
  --receipt-sha256 "$m68_receipt_sha"
```

**Stop after validation.** Do not invoke `app.m67 execute`, merge the PR, install a
service or timer, or run any Amazon/retailer operation. Preparation itself consumes
zero auth/restriction slots and makes no account changes.

## Rollback and operational limits

Expiry never resets M63 or M67 reservations. Removing an authorization is not a
request refund or a revocation registry: copies may remain usable until expiry,
and unchanged M67 does not require the additional M68 receipt. Preserve the entire
private execution ledger and historical evidence against rollback/restoration.
Never delete, reset or replace original authorizations, claims, attempts or outcomes.
Multiple preparations do not create additional request budgets; M67's global claims
permit only the first separately authorized execution of any ASIN.

An operator can stop before preparation or let an unused artifact expire. Re-preparing
under a fresh name requires fresh evidence and human confirmation; there is no renewal
command. Clock rollback, root-level tampering and copied credentials cannot be prevented
by local hashes or file permissions. M68 does not attest Amazon permissions or token
validity, and no live integration is exercised here. M67 always revalidates at execution,
so successful offline validation cannot guarantee that later evidence remains unchanged.

## Validation performed for this milestone

Baseline: 1,488 tests passed. Final M68 targeted suite: 78 passed. Full regression:
1,566 passed. Both mock sample modes exited 0 with socket connections blocked and
isolated runtime state. Tests block network, Amazon token/transport entry points and
reservation primitives; approved test artifacts exist only in synthetic temporary
directories. They cover exact schema/scope, hidden confirmation, 15-minute expiry,
manifest/preflight/account/credential/code drift, global/historical claims, read-only
validation, redaction, atomic no-overwrite publication, failure cleanup, symlinks,
strict JSON and exact 0600 modes under permissive/restrictive umasks.

The original manifest validated through unchanged read-only M67 preflight with
`ready=true`, 20 ordered ASINs and 77 exclusions. Protected M63 reservation, legacy
ledger, M66 store and manifest bytes, and the private file inventory were unchanged.
No real M68 authorization was prepared: the owner must provide the hidden terminal
confirmation locally. Zero live Amazon/authentication/retailer calls, real execution
reservations, listing submissions, approval applications or purchases occurred.
M63/M65/M66/M67 safeguards and code-bound modules are unchanged. No merge or deployment
is performed by this milestone.
