# M75 — separately authorized controlled Catalog expansion

M75 implements and tests a new manual one-shot executor on main after merged
PR #63. **This PR performed zero live requests. No live owner authorization was
created or consumed, and the M75 operation was not claimed.** A merged PR is not
authorization to execute. Nothing is merged, deployed, scheduled or purchased by
this implementation task.

## Fixed evidence and implementation bindings

The verified catalog remains 377 real ASINs, with 623 remaining toward 1,000.
All 97 permanent exclusions, 40 previously checked seller-specific ASINs, 31
unresolved conflicts and 305 offline identity research candidates are preserved.
M72 remains permanently `COMPLETED_NO_REPLAY` with ten consumed requests.

Compiled pins have no command-line override:

| Evidence | SHA-256 |
|---|---|
| M74 canonical query manifest | `e9119972fd0257d9da5f1dbb1518567c859001d0a957946a0f846b9d26931105` |
| M74 query manifest file | `ae34d1d5df28f40f905bb80778fd3b5b4f6e61dd41ca1887607d18d585af283f` |
| M74 completion digest file | `0224671c5011e26182c7f117516149d83cb97c1a77b4f362e59b2627005a815a` |
| Exact M75 contract proposal file | `5170814e9f774df7dc20f148d20319cf2de2ea928df466219d3415110d3f90fe` |

M75 validates all eighteen M74 output files, its original implementation map and
original evidence chain through unchanged M74/M73 validators. It reconstructs the
plan in memory and requires exact equality with the saved planning report, separate
query manifest and contract. It does not regenerate historical reports. The
existing M70 temporary serialization checksum check remains part of the unchanged
read-only validator; original files are never overwritten.

The exact executable implementation digest, defined as SHA-256 of the canonical
complete implementation map, is:
`28325b9b140be24ce71834a70513012ccdb177a2aa9724d03f2203d28c357751`.

| New source module | File SHA-256 |
|---|---|
| `app/m75.py` | `41cf422579275fa8ded6fad43490fbda76743fa26bdc68b9aea7ceaca536acd6` |
| `app/m75_authorization.py` | `a52b1897ab1c25fe108dc89155d94f36c811a8e27514cbba9da568659fc984f2` |
| `app/m75_execution.py` | `a0426f7c6b060ea50350d8802ecbc5d218d701d12ab78e4fc1c86c32d4f644ef` |
| `app/m75_policy.py` | `f30cff7cb02e104555b1f2abca1025ad71f682dbfd903da7d63364526f24a21b` |
| `app/m75_registry.py` | `6dec36b062f6433a40b3f9ec0bbd2ec1881c0a0f5933a65299325c3930f4a0a5` |
| `app/m75_reporting.py` | `037001a248297a793db1afacf1749b5532e658782aa544287f19b0e38a7e08bf` |
| `app/m75_transport.py` | `5af085597d939a5a01c7a8d1aec9e676f1ebf2c290aa1c3672d1ce3425c5261b` |

The complete map includes unchanged shared M72 transport, authentication parsing,
TLS primitive, diagnostics, pacing, M63–M74 validation, normalization and source
import dependencies. It is retained in the private preflight report, not reduced
to only these seven new files. Current code must still match before every dispatch.

## Exact request scope

Only operation `M75-US-CATALOG-EXPLORE20-ONCE` is implemented. Its permanent registry
is fixed at `<private>/m75-catalog-discovery.sqlite3`, with no alternate operation,
registry, query, page count or request-budget selector.

Slot 1 permits one POST to `https://api.amazon.com/auth/o2/token` using the existing
private refresh-token grant. Successful completion requires all following twenty
GETs, in exact order; a failure stops early without replacements:

| Slot | Query ID | Exact keyword phrase |
|---:|---|---|
| 2 | q010 | soap saver pouch |
| 3 | m74-n001 | silicone baking brush |
| 4 | m74-n002 | luggage handle wrap |
| 5 | m74-n003 | mesh laundry wash bag |
| 6 | m74-n004 | shower curtain clips |
| 7 | m74-n005 | microfiber dusting mitt |
| 8 | m74-n006 | sewing seam gauge |
| 9 | m74-n007 | tent guyline adjusters |
| 10 | m74-n008 | bicycle valve adapter |
| 11 | m74-n009 | monitor memo board |
| 12 | m74-n010 | seedling transplant tool |
| 13 | q011 | seed starting trays |
| 14 | q012 | pet food scoop |
| 15 | q013 | crochet stitch markers |
| 16 | q014 | bamboo steamer liner |
| 17 | q015 | under shelf basket |
| 18 | q016 | desk document tray |
| 19 | q017 | bicycle tire lever |
| 20 | q018 | tire valve caps |
| 21 | q019 | precision screwdriver holder |

Every Catalog request has exact method GET, host
`sellingpartnerapi-na.amazon.com`, path `/catalog/2022-04-01/items` and only:
`marketplaceIds=ATVPDKIKX0DER`, `pageSize=20`, its reviewed `keywords`, and
`includedData=summaries,identifiers,relationships,attributes,productTypes,classifications,dimensions`.

The total hard ceiling is **21 consumed slots**, including at most one
authentication and twenty keywords. q001–q009 cannot be requested. No identifiers,
additional pages/pageToken, detail endpoint, retries, refreshes, resume, eligibility,
restrictions, pricing, fees, FBA, retailer, listings, purchases or approval submissions
are available. No service count, unique yield, demand or profitability is promised.
At most 400 raw product slots cannot fill the 623-ASIN gap by themselves.

## Owner authorization and account protection

`dry-run` reads credential ownership/mode/link/metadata only, not credential values.
It validates original account scope and the M74 account-binding hash. Credential
content verification is explicitly deferred until a fresh M75 owner artifact has
passed validation and the global account lock is held.

`authorize` is a separate, future local interactive action. It requires the exact
reviewed preflight file and file SHA-256, a new owner-only M75 artifact name in the
existing private directory, a real terminal, hidden confirmation of the existing
seller ID, and the exact acknowledgement:
`AUTHORIZE M75 21 REQUESTS NO REPLAY`.
If hidden input would fall back to echo, authorization fails. The preflight is
revalidated after human confirmation. No credential or seller value belongs in
chat, command arguments or shell history.

The new schema requires explicit approval, execution permission, no-retry/no-replay
acknowledgements, a bounded manual review reference and aware issue/expiry times
with **at most ten minutes** validity. It binds the exact operation, complete code
map, original evidence, account/US marketplace, canonical/file/completion/contract
hashes, every request definition, integer 1/20/21 budget and reviewed preflight.
M63/M67/M68/M72 artifacts and historical approvals cannot authorize M75.

Execution requires both the new artifact's exact file SHA-256 and `--execute-live`.
Under the account lock, the artifact is checked again before credential loading.
Existing private credential bytes must match the original account-context digest;
credential changes are never accepted merely because file metadata stayed equal.
Before every dispatch, including after pacing and durable slot consumption,
M75 rechecks current artifact contents/expiry, code, original file inventories,
account/credential binding, frozen pacing, saved cooldowns and registry integrity.
A changed or expired artifact never causes an automatic refresh or retry.

## One-shot accounting and failure behavior

The unchanged existing `candidate-execution.lock` must already exist and be secure.
M75 holds it exclusively for the operation. Initial full validation uses the old
read-only history readers. Under the exclusive lock, M75 rechecks the fully bound
immutable snapshot rather than nesting their shared-lock acquisition. Every
original source and M73/M74 completion file remains hash-checked under that lock.

The new registry is created exclusively, file and parent are fsynced, and the
permanent claim is committed before dispatch. It uses DELETE journaling and FULL
synchronization, immutable-table triggers, unique claim/start/terminal boundaries,
a hash chain and sequential intents tied to the fixed request definitions. Each
ATTEMPT commits before any transport call. A successful prior RESPONSE is necessary
for the next slot. Duplicate slots, out-of-order responses, a second start, slot 22
or successful completion without all 21 responses are rejected.

Any existing registry, including an empty/corrupt/partially initialized file,
blocks a new preflight. Once claimed, zero-request stops, interruptions and hard
kills burn the operation permanently. There is no reset or resume command. Before
claim, failed validation/authorization sends nothing and creates no registry.
Retain the registry and its backups; privileged deletion or rollback cannot be
prevented by local SQL/hash controls.

The transport reuses M72's tested TLS primitive and authentication handling, with
M75-only slot scope. It rejects alternate hosts, ports, paths, extra parameters,
headers, cookies, proxies, redirects and malformed tokens. TLS verification stays
enabled. No SDK, retry wrapper or refresh layer is used. Requests have a ten-second
socket timeout and a 120-second hard dispatch timer. TERM/HUP/ALRM and ordinary
interruptions enter the permanent stop path; core dumps are disabled during
execution. At most one effective search request/second, no burst, frozen headroom,
existing cooldowns and lower saved/response rates are respected read-only. A slow
rate/cooldown can stop the operation with unused capacity.

Timeout, HTTP error, throttle/Retry-After, malformed response, uncertain dispatch,
authorization/token expiry, drift, interruption or storage failure stops without
replay. Consumed slots are conservative: an intent committed before a last-moment
stop still counts, even if the transport was not reached. Reports identify slots
without a committed successful response as uncertain; they are never reused.

## Private observations and read-only recovery

Successful/partial pages are checkpointed after each response with source hash,
query ID, request definition/slot, M74 manifest, US scope and aware observation
time. A continuation cursor is evidence only and is never followed. Product data
uses the existing allowlist/scrubber. Known credentials, access tokens, seller IDs
and embedded private context are redacted; cursor strings are also scrubbed if
they contain a known secret. Authentication bodies are not persisted; only a
response hash is retained. Errors, raw headers and exception text are not logged.

Normal exit writes new owner-only files under fixed
`<private>/m75-catalog-expansion-output/`:

- `M75_catalog_pages.json` and hash-bound `M75_M70_sources.json`, compatible with
  unchanged M70 import, including successful pages from a stopped operation.
- `M75_summary.json`, reporting consumed authentication/keyword slots, uncertainty,
  successful pages, raw/normalized/distinct/new ASINs, duplicates, exclusions,
  completeness/conflicts/missing fields and source quality.
- `M75_output_digests.json`, binding the exported files.

“New” means unclaimed and absent from the original 377-ASIN M73 catalog. The separate
union count includes all real observed ASINs, including exclusions. Rejected
normalization does not erase observed ASINs or fabricate missing fields. Eligibility
and economics stay UNKNOWN. The original catalog and its 31 unresolved conflicts
are not silently replaced by this export.

A stopped execute returns exit code 2 after reporting. If export is interrupted,
the registry still contains all committed pages. `report` exports to a fresh review
directory without reading owner artifacts/credential values or dispatching. It
requires the reviewed M74 files and the original hash-bound M73 catalog. Reporting
never permits replay or authorizes any follow-up operation.

## Offline validation command — safe to review

Use the exact reviewed checkout. Shared Bash arguments contain no secret values:

```bash
m75_inputs=(
  --m74-dir var/m74-final
  --m73-dir var/m73-final
  --m73-digests-sha256 07be04f0c8e96dd6999841beef75a45e5afa3177d931cb0d3323e47df497b773
  --baseline-dir var/m70-offline-final
  --baseline-report-sha256 228c29245ab8898fb4647aa5016b0e86b49ac6546ebef546480a65c941370a56
  --proposal var/m71-preparation/M71_manifest.json
  --private /root/.intelligenceos-arbitrage-amazon
  --checkpoint 260e03e15b79c77b96430d3416a57fefc65c374421489fe34937d92e41077dd4
  --sources /root/.intelligenceos-arbitrage-amazon/m72-catalog-pilot-output/M72_M70_sources.json
  --summary /root/.intelligenceos-arbitrage-amazon/m72-catalog-pilot-output/M72_summary.json
  --store var/m66-local/intelligence.sqlite3
  --m67-manifest var/m66-expanded-review/M66_review_manifest.json
  --m67-sha256 8983bef70ce5cfd79d15b7611e4b5646784f37bfce1a88bd220286394303ee55
)
.venv/bin/python -m app.m75 dry-run "${m75_inputs[@]}" \
  --output var/m75-owner-reviewed-preflight.json
```

This is offline and creates only a new private review report. Inspect every request,
all hashes, account binding, 21-request ceiling and current pacing. Existing output
files are rejected. A future dry-run must be reviewed again if any bound input or
implementation differs.

## Future owner procedure — not performed in this PR

After a separate explicit owner decision, use a local interactive terminal and the
newly printed review-file digest:

```bash
.venv/bin/python -m app.m75 authorize "${m75_inputs[@]}" \
  --reviewed-preflight var/m75-owner-reviewed-preflight.json \
  --preflight-sha256 REVIEWED_PREFLIGHT_FILE_SHA256 \
  --review-reference manual:m75-owner-reviewed-21-request-expansion \
  --output /root/.intelligenceos-arbitrage-amazon/m75-owner-authorization-pilot-01.json
```

Only the owner enters the seller ID privately and types the acknowledgement. The
command prints a fresh authorization file SHA-256 and expiry. Before that expiry,
the separately authorized execution command would be:

```bash
.venv/bin/python -m app.m75 execute "${m75_inputs[@]}" \
  --authorization /root/.intelligenceos-arbitrage-amazon/m75-owner-authorization-pilot-01.json \
  --authorization-sha256 FRESH_M75_AUTHORIZATION_FILE_SHA256 \
  --execute-live
```

Do not repeat execution after a claim or stop. There is no permission to continue
with unused slots. Read-only recovery, if later needed:

```bash
.venv/bin/python -m app.m75 report "${m75_inputs[@]}" \
  --output var/m75-recovered-private-report
```

No authorize/execute command above was run against real evidence during development.
No merged PR, plan hash, prior authorization or copied old artifact substitutes for
the new owner decision.

## Actual offline validation

Baseline regression: **1,931 passed**. Targeted M75: **111 passed**. Final full
regression: **2,042 passed in 382.61 seconds**. Both documented offline sample
modes passed with socket connections blocked. Tests use synthetic credentials,
accounts, temporary owner artifacts and injected replies only; their products are
not real discovery observations.

Coverage includes exact account/code/evidence/query/budget/freshness authorization,
TTY/hidden-input failures, no pre-claim state on invalid permission, locked synthetic
21-slot execution, durable before-send accounting, first/last-slot failures,
malformed/throttled responses, expiry/no refresh, conservative pacing/deadlines,
zero-request stops, hard SIGKILL recovery, immutable-chain tampering, partial-page
exports, credential drift with unchanged metadata, mid-run revocation, replay
blocking, privacy (including cursor redaction), fixed endpoint/header/parameter
scope and credential-free read-only recovery.

Two actual guarded dry-runs were identical. All 46 checked original evidence/report
files retained identical hashes, and all 68 private-directory entries retained
identical inventory/size/mode/mtime. Network and production credential/live-owner-
artifact reads were blocked. No M75 registry exists; no live authorization was
created or consumed; **actual authentication and Amazon requests: zero**.

Private ignored review artifact: `var/m75-dry-run.json`.
Canonical preflight SHA-256:
`45f29d2410a6f71505a4045721b79fe4f11d62c2523456920924d3e092c52777`.
Preflight file SHA-256:
`f150f138f3a0af2d96b8e01264f1f916088069f312e20a4b588965697efa8f91`.
`var/m75-offline-validation.json` records the guard/immutability checks. These are
review reports, not authorization. No generated report, raw source, runtime database
or credential is committed.
