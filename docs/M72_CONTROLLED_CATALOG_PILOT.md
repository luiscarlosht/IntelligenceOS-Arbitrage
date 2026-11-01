# M72 — controlled one-shot Catalog pilot

M72 adds an explicitly authorized execution path for a single **maximum ten-request**
pilot. This PR implements and tests it offline; **no live pilot was executed** and
no live authorization artifact was created or consumed. M63–M71 modules, credentials,
authorizations, ledgers and immutable evidence are unchanged. Nothing is deployed,
merged or scheduled automatically.

## Exact scope and frozen inputs

Base: merged PR #60, commit `8e73b0cb5d1d3b49e19b89cdb13fe98464aeacec`.
Both original M71 digests are compiled into `m72_policy.py`, with no CLI override:

- Proposal SHA-256: `b09cbea8033caa994b8a79c2451851b1cc91171548e73cadf1c1ebef35731103`.
- Original manifest file SHA-256: `0161373a75c3a744c97bd20a0caefd7afb5527158794c15875ac1946963fa26c`.

| Slot | Phase | Frozen query | Category intent | Exact phrase |
|---:|---|---|---|---|
| 1 | Authentication | — | Existing account | One refresh-token grant exchange |
| 2 | Keyword | q001 | garden | plant support clips |
| 3 | Keyword | q002 | pet_accessories | pet grooming comb |
| 4 | Keyword | q003 | craft_supplies | embroidery hoop |
| 5 | Keyword | q004 | kitchen_accessories | silicone jar spatula |
| 6 | Keyword | q005 | home_storage | fabric drawer dividers |
| 7 | Keyword | q006 | office_accessories | cable management sleeve |
| 8 | Keyword | q007 | sports_accessories | yoga mat strap |
| 9 | Keyword | q008 | automotive_accessories | car seat gap organizer |
| 10 | Keyword | q009 | hand_tools | magnetic parts tray |

One authentication and at most nine Catalog keyword requests are permitted. Every
keyword request is the **first page only**, page size 20, in the frozen round-robin
order. A nextToken is saved privately as partial-result evidence and never followed.
The pilot has at most 180 raw product result slots and cannot satisfy the broader
1,000-product discovery target by itself. Distinct coverage and identity quality
are measured, not promised. No other M71 query, substitute, batch or phase is enabled.

US marketplace is `ATVPDKIKX0DER`. The existing account reference, seller binding,
credential-file digest and US/New context come from the original owner-only
`m67-account-context.json`. Catalog data itself remains condition-agnostic.
There is no seller ID in a Catalog request. The actual private seller ID is used
only to validate scope/owner confirmation and redact saved products.

Only two exact HTTPS endpoint/method contracts are allowed:

- POST `https://api.amazon.com/auth/o2/token` with the refresh-token grant and
  existing private `client_id`, `client_secret`, `refresh_token` values.
- GET `https://sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items` with
  US marketplace, `pageSize=20`, the exact frozen phrase, and M71's exact
  `includedData=summaries,identifiers,relationships,attributes,productTypes,classifications,dimensions`.

No identifier queries, detail endpoint, pageToken parameter, product-type search
filter, brand filter, additional pages, retries, token refreshes, restrictions,
pricing, fees, FBA, listings, purchases or approvals are permitted. The transport
validates each built request before accounting and again before sending. HTTPS
host/path/method/body/parameters/token checks reject redirects, alternate hosts,
ports, userinfo, fragments and altered queries. The reused `amazon_pilot._request_json`
uses verified TLS, no proxies/redirects/retries, a ten-second socket timeout and
bounded bodies; it bypasses the legacy convenience pacer and any SDK refresh layer.

## Preflight and authorization boundaries

`dry-run` performs no network activity or state allocation. It validates the exact
original manifest file/proposal digests, unchanged M71 implementation, complete
original history and all permanent exclusions, existing account scope, credential
file ownership/mode/link metadata, current pacing and saved search cooldowns.
It does **not** read credential values. The report explicitly marks credential
content verification as deferred until fresh authorization. No lock, registry,
authorization file, ASIN reservation or execution output is created by preflight.

The preflight binds a baseline M70 catalog CSV by file SHA-256 and ASIN count.
This permits honest reporting of newly encountered ASINs rather than calling every
returned unclaimed ASIN new. The baseline must have M70 export columns and distinct
valid ASINs. The original catalog/identity engine is reused, not reimplemented.

Fresh owner authorization has a distinct M72-only schema. It binds:

- The permanent operation ID, both M71 digests, first nine query IDs and exact
  integer 1/9/10 budget with all other operation counters zero.
- Existing account/US scope and original private account-binding digest.
- The complete current executable implementation map, including shared transport,
  pacing, policy, source parsing, normalization, identity and reporting dependencies.
- The exact reviewed current preflight fingerprint, which includes immutable history,
  credential metadata, baseline and pacing/cooldown bindings.
- Explicit approval/execution permission, no retry/no replay acknowledgements,
  a nonsecret manual review reference, UTC issue time and expiry of at most 15 minutes.

`authorize` requires a local interactive TTY, hidden confirmation of the existing
seller ID, and the exact phrase `AUTHORIZE M72 10 REQUESTS NO REPLAY`. It accepts
only a new owner-only `m72-owner-authorization-*.json` file in the existing private
directory and revalidates preflight after confirmation. There is no authorization
creation during import, dry-run, tests against real files, or execution itself.
M63/M67/M68 artifacts, prior approvals, copied old schemas, changed budgets, stale
preflights, expired/future/naive timestamps and code/account/history drift fail closed.

Execution requires **both** `execute --execute-live` and the path plus exact file
SHA-256 of a fresh M72 artifact. Only after authorization validation and acquisition
of the existing global `candidate-execution.lock` does it read credential values,
check their original account-bound file digest, and construct the transport. It
rechecks authorization expiry/file contents, code, original history input inventory,
credential/account binding, manifest, baseline and pacing before each dispatch.

The unchanged M69 history reader normally acquires the global lock itself. To
avoid nested shared/exclusive flock conflicts, initial preflight validates its
result and binds every original audit input (including the audit filename patterns,
original ledgers/store and frozen M67 manifest/ranking). Under the exclusive lock,
M72 verifies that complete file inventory and hashes, including additions, against
the reviewed snapshot. It never releases the lock to run a nested history audit,
patches the old reader, or writes an original record. Any drift burns a started
pilot and stops before the next request.

## Permanent one-shot registry and bounded execution

The fixed operation ID is `M72-US-CATALOG-FIRST9-ONCE`. The registry path is fixed
at `<private>/m72-catalog-pilot.sqlite3`; neither ID nor path has a CLI override.
A new authorization, code revision, output path, expired token or interrupted run
cannot authorize a second execution of that ID. Any existing registry, including
an empty/corrupt/partially initialized file, blocks preflight. There is no reset,
resume, migration or replay command. Failures before the durable operation claim
send no requests and allocate no request slots.

Under the global account lock, execution creates the registry exclusively with
owner-only permissions, fsyncs its file and parent, and stores the permanent claim
before any dispatch. SQLite uses DELETE journaling and FULL synchronization.
Append-only operation/events tables have update/delete triggers and a hash chain.
Each sequential ATTEMPT is committed before the corresponding transport call,
including authentication. The next slot requires a successful prior RESPONSE;
the registry rejects duplicate/out-of-order slots and every slot above ten.
No ASIN claims or eligibility reservations are created.

A SIGALRM hard timer limits the whole dispatch phase to 120 seconds. Existing
signal timers are rejected; TERM/HUP/ALRM interruptions raise into the permanent
stop path. SIGINT, timeouts, token expiry, malformed responses, 429/Retry-After,
HTTP/transport errors, uncertain dispatch and budget/storage failures stop without
retry or refresh. If a process dies before recording STOP, its permanent claim and
consumed slots still prohibit replay. Core dumps are disabled during execution.

The unchanged operation pacer uses the frozen conservative cap/headroom (default
2 RPS × 0.5 = effective 1 RPS), with no burst. Existing original search cooldowns
and lower saved rates are loaded read-only; lower response rate headers reduce
subsequent pacing. No original cooldown table is written. An unexpired cooldown
or slower pacing can cause the deadline to stop the pilot with unused capacity;
remaining requests are not carried forward. Shared service/account limits and
previous documented default discrepancies remain as described in M71.

Authenticated successful/partial page responses are checkpointed privately after
each validated response. Authentication bodies, credentials, access tokens, seller
IDs, raw headers/errors and exception text are not persisted. Page records carry
query/slot, timestamp, original response hash, proposal hash and private cursor.
Only allowlisted Catalog product datasets survive; known account/credential/token
values and embedded private context are redacted. Permission remains UNKNOWN.

Normal exit writes owner-only files in the fixed new directory
`<private>/m72-catalog-pilot-output/`:

- `M72_catalog_pages.json`: successful pages, including partial cursors.
- `M72_M70_sources.json`: a hash-bound `amazon_catalog_pages` source manifest for
  unchanged M70 ingestion/deduplication/identity-quality reporting.
- `M72_summary.json`: redacted actual consumed authentication/keyword counts,
  uncertain slots, distinct returned/unclaimed/new ASINs, duplicate/exclusion counts,
  missing/conflicting identities, normalized import acceptance/rejection and source
  provenance/quality. ASINs rejected for missing identity still count as actual
  returned products; they never receive fabricated fields.

The report distinguishes raw product observations from normalized import records.
“New” means unclaimed and absent from the hash-bound M70 baseline. Full identity
completeness includes condition; Catalog alone cannot establish it. No selling
permission, listing access, FBA status or profitability is inferred.

A stopped execution returns exit code 2 after its redacted report. If reporting
itself is interrupted, the registry holds all committed successful pages. The
read-only `report` action exports evidence to a new directory without dispatching,
reading credentials/authorization values or resuming requests. STOP/UNCERTAIN is
terminal even if zero requests were consumed after the operation claim. Privileged
filesystem deletion/rollback cannot be defeated by local SQL/hash controls; retain
the original registry and backups rather than restoring a pre-claim copy.

## Reviewable operator procedure — future only

**None of the authorization or execution steps below were run for this PR.**
Review/merge/deployment is a separate owner action. Use the exact reviewed commit,
existing private files and a local terminal. Commands deliberately contain no seller
ID or credential values. Do not use an old M63/M67/M68 authorization.

Set the fixed review inputs in Bash:

```bash
m72_inputs=(
  --proposal var/m71-preparation/M71_manifest.json
  --store var/m66-local/intelligence.sqlite3
  --private /root/.intelligenceos-arbitrage-amazon
  --m67-manifest var/m66-expanded-review/M66_review_manifest.json
  --m67-sha256 8983bef70ce5cfd79d15b7611e4b5646784f37bfce1a88bd220286394303ee55
  --baseline-catalog var/m70-offline-final/M70_catalog_1000.csv
)
.venv/bin/python -m app.m72 dry-run "${m72_inputs[@]}" \
  --output var/m72-owner-reviewed-preflight.json
```

Inspect that file, its printed file SHA-256, query order, budget, current code hashes,
account-binding hash, baseline, history and pacing. It is a review report, not an
execution authorization. New review paths are required; existing files are rejected.
After a fresh explicit owner decision, run this local interactive command, replacing
`REVIEWED_PREFLIGHT_FILE_SHA256` with the exact newly printed file digest:

```bash
.venv/bin/python -m app.m72 authorize "${m72_inputs[@]}" \
  --reviewed-preflight var/m72-owner-reviewed-preflight.json \
  --preflight-sha256 REVIEWED_PREFLIGHT_FILE_SHA256 \
  --review-reference manual:m72-owner-reviewed-ten-request-pilot \
  --output /root/.intelligenceos-arbitrage-amazon/m72-owner-authorization-pilot-01.json
```

The owner confirms the existing account privately and types the explicit ten-request
acknowledgement. The command prints the new authorization file digest and expiry.
Before expiry, the exact execution command is:

```bash
.venv/bin/python -m app.m72 execute "${m72_inputs[@]}" \
  --authorization /root/.intelligenceos-arbitrage-amazon/m72-owner-authorization-pilot-01.json \
  --authorization-sha256 FRESH_AUTHORIZATION_FILE_SHA256 \
  --execute-live
```

`FRESH_AUTHORIZATION_FILE_SHA256` must be the digest printed by the owner authorization
command. Never put credentials or the seller ID into shell arguments/history. The
command will not be run by this PR, import, dry-run, a scheduler or any test against
production. Do not repeat it after a claim, uncertain dispatch or stop.

Read-only recovery after a stopped/hard-killed operation:

```bash
.venv/bin/python -m app.m72 report "${m72_inputs[@]}" \
  --output var/m72-recovered-private-report
```

Retain the original proposal, baseline, registry and owner-only recovered output.
Pass its `M72_M70_sources.json` to the existing `app.m70 analyze` command with the
original M67/history arguments. No further Amazon operation is authorized by an
M70 report or by unused pilot capacity.

## Actual offline validation

Original M71 proposal/file digests matched; repeated actual dry-runs were identical.
The dry-run report is under ignored `var/m72-dry-run.json`:

- Canonical preflight SHA-256: `7290a12c1a4d4d6596693ec05abcdd91646b5aa69c6da33deef270a33e875b00`.
- Preflight file SHA-256: `f334b6411f6b30efcaffc8658b9819787f57b766621d144943f8b84c04626627`.
- Current baseline: 197 M70 ASINs; permanent exclusions: 97; checked eligibility ASINs: 40.
- Zero credential-content reads, authorization artifacts created/consumed, live
  requests, permanent operation claims or ASIN reservations.
- Nine protected evidence/proposal/baseline files retained identical hashes,
  sizes and modification times; all 62 private-directory entries retained identical
  inventory/size/mode/modification metadata. Production credential values were not read.

Baseline regression: **1,794 passed**. Targeted M72: **79 passed**. Final full
regression: **1,873 passed in 165.99 seconds**. Both documented legacy/discovery
sample modes passed with socket connections blocked. Tests use
synthetic credentials/accounts/temporary authorization files and injected transports
only; real socket/authentication/old execution/reservation primitives are blocked.
Coverage includes exact authorization scope and freshness, ten-slot budgets,
pre-dispatch accounting, lock contention, current/locked history drift, credential
binding, first-nine-only requests, endpoint/parameter rejection, TLS primitive wiring,
interruption and hard-kill no replay, phase deadlines/pacing, malformed/throttled
responses, privacy, M70 saved-page import and honest raw-versus-normalized quality.
