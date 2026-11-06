# M90.2c — Protected authority cutover design

## Executive summary

M90.2c implements a **pure, in-memory Strategy B state-machine model**, approval
and evidence bindings, claim preservation/reconciliation checks, event-journal
replay validation, failure/recovery decisions and a pure successor-verifier
predicate. It has no filesystem/network API, production policy loader, operational
CLI, migration command, source reader or installed launcher. Tests are synthetic.

The operational designs below are proposals requiring independent review and
separate approvals. A digest naming an evidence receipt is not proof that the
underlying host check or fsync happened. Synthetic approvals are not production
approvals. No production paths were inspected, created, read or modified in this
milestone; no production verifier, lock acquisition, credential access or Amazon
request was performed.

The expected 13-attempt ledger SHA is
`c79e2a7788c3b99ee75a17dc3150b9e2a609818ad2de3cce82f082e36c9b79f1`:
13/49 used, 36 remaining, purchases unauthorized. This remains historical
expectation, not newly verified production state. Neither migration approval nor
post-cutover verification authorizes authentication or Catalog execution.

## Strategy B architecture and trust boundaries

Proposed protected root: `/var/lib/intelligenceos-arbitrage-protected`.

| Location | Proposed ownership/mode | Writers and retention |
| --- | --- | --- |
| Protected root and children | root:root, 0700; root-controlled nonwritable ancestry | Explicitly approved migration/verifier/broker boundaries only; never reporting service |
| `authority/manifest.json` | root:root, 0600, regular single-link | Migration coordinator publishes durable authority decision; live ledger writes never rewrite authority selection |
| `m89/ledger.json` | root:root, 0600, regular single-link | Migration installs exact bytes once while nonauthoritative; approved broker later reserves/completes attempts |
| `m89/ledger.lock` | root:root, 0600, regular single-link | Provision once under separate storage approval, pin identity; never replace/unlink during inspection or execution |
| `claims/` | root:root, 0700; records 0600 | Exclusive append-only consumption, origin-preserving historical inventory and migration approval nonce records; never delete/restore to replay |
| `evidence/` | root:root, 0700; records 0600 | Bounded snapshots, metadata, receipts and hash-chain journal retained through abort/rollback; no credentials or tokens |

The existing account lock remains at
`/root/.intelligenceos-arbitrage-amazon/candidate-execution.lock`, unchanged. No
second account lock is introduced. The proposed new file is a **ledger** lock,
not another account lock. The old source ledger and lock remain untouched by this
milestone and must remain available as historical evidence after a future cutover.

The reporting service/timer, their ownership and writable data, and `/current`
remain unchanged. `/current` remains the V0.2 release ending
`68230d3fdaef588bb7ba5c8340f49a473e8386b7`. Do not make the reporting service's
StateDirectory manage the new root; a later service start must not chown protected
state. Reporting restoration must never include protected authority or claims.

Allowed future roles are distinct:

- Requester: fixed IPC operation, no credentials, root imports, protected-state
  write access, network or authority selection.
- Root coordinator: explicitly approved storage transitions, reviewed evidence,
  no Amazon requests. It must not accept arbitrary commands or caller paths.
- Root verifier: metadata-safe existing-file inspection only; no repair/creation.
- Root execution worker: future independently approved two-request workflow,
  bound to the committed authority and budget; no authority migration behavior.
- Host operator: independent approvals and evidence retention. Host root and
  trusted kernel/storage are outside the adversarial requester boundary.

Current application-owned credentials are a **separate unresolved trust issue**.
This design does not read, copy, chown, rotate or otherwise touch them. An
application account retaining credential access can bypass a broker using another
network-capable process. Deployment needs a separately approved credential-access
solution or a genuinely isolated requester identity plus verified controls over
all former credential readers. Storage cutover does not silently authorize changing
the existing credential source or solve that problem by itself.

## Historical source audit — specified, not operationally implemented

M90.2b's strict root-only verifier remains unchanged. It cannot safely certify the
current application-owned source ancestry. No owner-check relaxation, arbitrary
`--ledger` flag or privilege workaround is added. The pure model validates bytes
using `m902_history.validate_snapshot`; it does not open the source or prove its
metadata/freeze conditions.

A future **separate fixed-source read-only adapter** requires independent review:

1. Hardcode source ledger, old ledger lock and the existing account lock. Root-only
   policy pins reviewed device/inode identities and the actual expected source
   owners, modes, directory identities and approved maintenance freeze. No paths
   or identities arrive in requester JSON or environment variables.
2. Independently attest actual host/root identity, code/runtime, writer inventory,
   stop/freeze receipts and expiry. Apparent sandbox UID 0 is not sufficient host
   attestation. No source snapshot is relied upon before this gate.
3. Open only existing locks without creating/replacing them. Acquire nonblocking
   exclusive flock in account → old ledger order. A missing/mismatched/contended
   lock stops, without retry or substitute creation.
4. Walk/pin directory descriptors with O_NOFOLLOW/O_DIRECTORY/O_CLOEXEC/O_NOATIME;
   open regular single-link bounded source with O_RDONLY/O_NONBLOCK plus the same
   safety flags. If metadata-safe access fails, stop. Verify named/open identities
   before and after read, owner/mode/link count and nanosecond timestamps.
5. Explicitly label the result **application-owned source under maintenance
   freeze**, not root-controlled storage. Pinned descriptors prevent pathname
   redirection; exact SHA protects byte authenticity; neither proves absence of
   a live process holding writable FDs or deletion of earlier claims. Account
   flock cannot freeze legacy unlocked writers. Independent freeze evidence is
   indispensable, and a hostile host root remains outside this model.
6. Read one bounded snapshot (8 MiB maximum), compare exact raw thirteen-attempt
   SHA, validate all attempts, ceiling 49, purchases false, successful attempt 13,
   and complete canonical twelve-attempt prefix SHA
   `b7502888a36b97594e5c79b3f8c47312c1226d80355a03621284660b45da2f1b`.
   Any extra attempt/reservation, chronology/history drift or read interruption
   blocks migration; never rewrite the ledger to the expected bytes.
7. Retain the descriptor and original bytes under the freeze for copying and source
   recheck through destination verification. Assert unchanged file metadata and
   source bytes at each boundary. Never update source atime or other metadata;
   do not restore timestamps after unsafe reads. Flock changes kernel state only
   temporarily and needs explicit operational approval.
8. Emit only fixed status/count/hash-match fields and protected evidence receipt
   digests, never raw ledger text, seller IDs, tokens or credential information.

**Blocker:** no independently attested maintenance freeze, complete claim
inventory or reviewed weaker-trust adapter exists yet. Implementing a runnable
reader that simply accepts application ownership would weaken established
assurances. It is intentionally left unimplemented; no production read was tried.

## Historical claim inventory and reconciliation

Inventory is an approved, fixed-scope host operation—not a recursive arbitrary
file-reader exposed to a requester. Define roots/expected artifact types in
root-controlled policy after host review. Capture raw evidence using bounded,
no-atime descriptor reads; never print contents. Absence is meaningful only for
reviewed scopes and cannot prove an application-owned claim was never deleted.

Required coverage:

| Scope | Required evidence |
| --- | --- |
| Embedded original ledger markers | Full-byte snapshot and JSON-pointer/operation mapping, including M88 historical markers and `m89_authentication_only=CLAIMED_NO_REPLAY` |
| M89 authentication-only | Attempt 13 timestamps/outcome/token_received marker and its embedded claim; any separate manual authentication receipts |
| M90/M90.1 | Attempt 14/15 reservations/outcomes, `m90_one_request`, `m901-no-replay.json`, token-pipe execution receipts and uncertain stops |
| M90.2 broker | Every configured Policy.claim origin and associated approval/ledger binding, including claims before reservation |
| Historical releases/checkouts | Retained reports, plans, private operation registries, status files and operator launch records; release-directory emptiness proves nothing about external state |
| Application-owned state | Existing m89 directory, historical private account directories and backups; note weaker integrity and missing/deleted-evidence risk |
| Separate protected locations | All previously approved root-controlled claim roots and independent retention copies; do not infer old claims from an empty new directory |

Each inventory record retains origin kind/reference, device/inode where available,
content/identity digest, operation, timestamps, consumed state, attempt mapping,
ledger/approval/evidence bindings and uncertainty. Embedded markers use a
ledger-digest/JSON-pointer identity instead of pretending to have their own inode.
Store raw original records as evidence; a reconciliation index never replaces or
edits them. Credential/token contents are excluded from evidence bundles.

Distinguish historically accounted consumption (e.g. original attempt 13, retained
and mapped to its validated record) from unconsumed, future-consumed or ambiguous
claims. Historical accounted claims do not disappear; future requests must not
reuse their IDs. An authentication-14 claim before reservation, reservation without
outcome, duplicate identity with conflicting fields, unmapped attempt, missing
approval, missing timestamp/binding or uncertain provenance blocks future live
execution. A consumed future claim is not cleared just because the ledger says 13.

Alias records from multiple origins must retain all origins and be reconciled by
explicit evidence, not deduplicated away. Compare source/destination inventory
content digests and membership; all source claims must remain binding. Missing
records, conflicting consumption, or incomplete scope certification stops the
cutover. If authority already committed, keep new authority and live launch disabled
while investigating; never revert or delete claims to obtain a passing check.

The model's Claim objects retain these logical fields. It requires the embedded
M89 consumed claim, rejects duplicate claim IDs and conflicting origin/operation records, requires
accounted claims to be consumed, and disallows dropping/changing records
between phases, and blocks reconciliation on unresolved/future/missing evidence or
wrong ledger bindings. It cannot discover real claims or certify completeness of
an operator-supplied inventory. Required root-reviewed receipt digests stand for
that external evidence; synthetic records do not fabricate confirmation of Amazon
account state.

## Pure single-authority state-machine implementation

`app/m902c_cutover.py` has no filesystem/network/credential imports or operational
entry point. All paths are fixed constants, included in the immutable Plan digest.
Tests use synthetic ledger bytes, prefix/baseline digests, lock identities,
approvals and receipts. A future production policy loader must pin the actual
historical constants; these synthetic Plan constructor values are not a path or
baseline override interface for production.

Every transition requires a fresh Approval bound to: complete plan (migration ID,
fixed source/destination/manifest/lock paths, three reviewed identities, immutable
release/runtime digests, baseline/prefix and requester identity), previous state
hash, exact target phase, exact evidence digest, reviewer, unique nonce and aware
approval/expiry timestamps (maximum one hour). The operation is
`M902C_OFFLINE_TRANSITION`, not a live execution identifier. Boolean UIDs and
unapproved operations fail. This is a pure contract, **not signature verification**
or kernel requester authentication.

The reducer retains an immutable event history, receipt hash chain and consumed
nonces. Before advancing or verifying, it replays all events and rejects a state
whose authority, claims, bytes or receipts disagree. Illegal jumps, duplicate
transitions, reverse transitions and restart of a blocked state are rejected.
Ledger bytes are retained exactly and never reconstructed from JSON. The source
can remain physically present while only one authority identity is active.

| Phase | Required evidence beyond approval | Authority / locks |
| --- | --- | --- |
| PRECHECK | Plan and separately provisioned inert destination/lock identity; scope, host, runtime and approval prerequisites reviewed | Old; no model operation performs I/O |
| WRITERS_FROZEN | Maintenance freeze, writer inventory, claim-scope inventory | Old; account → old ledger |
| SOURCE_VERIFIED | Weaker-trust descriptor audit and source metadata review, complete byte/history checks | Old; account → old ledger |
| DESTINATION_STAGED | Exact bytes, copy file fsync, copy directory fsync, new ledger-lock review | Old; account → old ledger → new ledger |
| DESTINATION_VERIFIED | Destination descriptor audit and source recheck | Old; all three locks |
| CLAIMS_RECONCILED | Inventory completeness, historical mapping and retained claims reconciliation | Old; all three locks |
| RUNTIME_ATTESTED | Immutable runtime, requester/legacy isolation, independent network-policy review | Old; all three locks |
| AUTHORITY_COMMITTED | Old-writer retirement, manifest file and directory durability receipts | New only; all three locks |
| POST_CUTOVER_VERIFIED | New authority descriptor audit and all prior bindings rechecked | New only; all three locks through final inspection |

Evidence cannot declare both old and new authority, omit/reorder locks, omit any
required receipt, substitute copy bytes, remove claims or change runtime identity.
There is no automatic execution/resume/recovery transition. Model receipt digests
are assertions requiring real verified durable records in a future adapter; they
do not implement fsync or prove lock acquisition.

### Replay and durable-journal limits

The pure model prevents reuse of consumed nonces in retained state and detects
internally altered/partial journals. It cannot defeat restoring **all** model
state, including its nonce history, to an older valid prefix. The future adapter
must consult an independently retained root-controlled nonce/claim registry and
latest checkpoint before accepting a transition. Approval consumption and the
intent record must be durably committed before any side effect; never restore
this registry with a ledger or staged-state rollback. The model deliberately has
no persistence loader, automatic intent replay or production approval issuer.
Do not treat a successful simulation as a signed authority manifest.

## Durable operational cutover procedure — proposal only

No executable cutover command is delivered. All provisioning, freeze, copying,
fsync, manifest publication and policy changes below require separate production
approval. The reporting service/timer and V0.2 `/current` are not migration tools.

1. **Approved PRECHECK provisioning:** create only the root-controlled destination
   layout and dedicated new ledger lock under a storage-provisioning approval.
   Mark destination INERT/NONAUTHORITATIVE. Independently inspect/pin its actual
   new inode before final Plan/approval issuance; never predict an inode. This is
   why the model Plan already has three identities. No source-audit operation
   creates locks, and the account lock is never replaced. No worker is enabled.
2. **Freeze:** approve and quiesce Amazon execution routes and account-capable
   processes without changing the offline reporting service/timer. Verify old
   unlocked/ledger-only paths are unavailable. Acquire account then existing old
   ledger lock; inspect known claims under these held locks. If frozen-writer
   absence cannot be established, stop before relying on the source snapshot.
3. **Audit source:** use the separately reviewed fixed-source adapter described
   above. Retain exact raw bytes, verified source identity, metadata and claim
   inventory under the approved freeze. Source remains the sole authority.
4. **Stage copy:** acquire new ledger lock last. Copy raw bytes directly from the
   retained source snapshot into an exclusive staged file under pinned root
   directory descriptors. No JSON reserialization, counter change or source write.
   Fsync file, publish only to the inert destination via same-filesystem atomic
   rename, fsync destination directory; independently re-open/verify raw SHA and
   full history, plus unchanged source. Different-filesystem copies are not an
   atomic authority switch. Failed/uncertain durability stops; never retry blindly.
5. **Preserve claims/evidence:** retain raw records and origin/identity digests,
   write a reconciled root-controlled index, fsync each file and parent, compare
   all source members and bindings. Claims remain blocking through every phase.
   Do not install an empty claims registry in place of historical consumption.
6. **Attest runtime:** verify fixed executable, all code/imports/dependencies/CA
   roots, launch and network policy; prove old writers/requester cannot reach
   usable credentials or bypass accounting. No Amazon probes. Missing credential
   isolation is a blocker, not authority to alter existing credentials here.
7. **Prepare exact decision:** construct the canonical manifest containing schema,
   migration/generation ID, fixed authority/old-evidence identities, ledger full
   SHA and ceiling/purchase prohibition, three lock identities, claim-index digest,
   immutable runtime/release/policy digests, previous journal head and consumed
   transition-approval ID. Bind operator approval to the exact decision/evidence.
   Validate all fields and claim conservation before publication.
8. **Commit:** persist approval consumption/intent in the independent registry;
   fsync it and its directory. Write an exclusive manifest temporary file inside
   `authority/`, fsync it, atomically rename to `manifest.json`, fsync `authority/`.
   Only after these succeed and independent re-read validation may evidence say
   AUTHORITY_COMMITTED. No other file is a competing authority selector. Keep
   all writers frozen through commit and postcheck.
9. **Postcheck:** re-open committed manifest, new ledger/lock and claim index via
   pinned read-only/no-atime descriptors; prove bytes/claims/runtime/retirement
   bindings match. Retain journal and old source as nonexecutable evidence. Release
   new ledger, old ledger and account locks by safe descriptor closure. Keep live
   execution disabled until a separate execution approval and fresh preflight.

Old source is **permanently nonexecutable by policy**, not merely chmodded. Its
application-owned parent can replace an old path, so changing the old file's mode
alone is not isolation and is not proposed. New approved writers use a hardcoded
manifest location and require the sole fixed destination, exact generation and
approved inode/content identities. They never accept a caller-selected authority,
follow an old-path symlink or fall back to the old ledger. Future normal execution
locks account → new ledger; the old lock is required during migration only.

Precommit active-OLD with staged bytes is not dual authority: all live writers are
frozen, and no installed policy authorizes writing the staged file as a ledger.
Retained backups/source copies are evidence. A durable commit selects NEW; no
report restore, old release, missing manifest or launch error can select OLD again.
If required atomicity/durability cannot be established, do not commit.

## Failure and recovery matrix

All failures preserve raw evidence, approvals, consumed nonces and claims. No
automatic retries or request dispatch occur. The model's interrupt is terminal.

| Boundary/failure | Required conservative result |
| --- | --- |
| PRECHECK, missing provisioning/policy/identity | Original authority; no freeze assertion or destination eligibility |
| WRITERS_FROZEN, contention or active legacy writer | Abort inspection; preserve old authority; keep execution authorization frozen pending operator review |
| SOURCE_VERIFIED, interrupted read, SHA mismatch, extra attempt, metadata race | No verified source; no reliance/copy activation; never reset historical ledger |
| DESTINATION_STAGED, copy error or failed file/directory fsync | Old authority; staged bytes inert/uncertain; retain evidence; no automatic retry or cleanup of claims |
| DESTINATION_VERIFIED, copy/source mismatch | Old authority; staged data unusable; root review required |
| CLAIMS_RECONCILED, missing/conflicting/ambiguous claim or evidence | Block migration/live execution; preserve every origin and unresolved record |
| RUNTIME_ATTESTED, runtime/requester/network isolation failure | Old authority, live launch disabled; do not weaken checks or mutate credentials to pass |
| Before manifest publication attempt | Abort may preserve old authority, but re-enabling any writer needs separate review; staged state remains inert |
| Manifest rename/fsync failure where decision visibility is uncertain | UNKNOWN_NO_WRITERS; both launch paths blocked. Do not assume that failure means old authority. Inspect retained manifest/intents under locks manually |
| AUTHORITY_COMMITTED, crash before postcheck | New authority retained; live launch disabled; manual fix forward only |
| POST_CUTOVER_VERIFIED, later crash/failed verification/legacy activity | New authority retained; no fallback or old-ledger restoration; investigate before any execution |
| Crash with an incomplete journal/intent | No automatic replay of effects; operator compares independent nonce registry, journal, manifest and physical state |
| Storage lies about durability, ambiguous mount semantics, unavailable safe reads | Block deployment/cutover; no unreviewed weaker filesystem or atime fallback |

`interrupt(commit_uncertain=True)` explicitly models an ambiguous manifest decision
at RUNTIME_ATTESTED as UNKNOWN_NO_WRITERS. Durable successful commit moves to NEW.
Once NEW is durably established, failures do not change authority back to OLD or
UNKNOWN based merely on an outdated checkpoint. Recovery requires a reviewed,
root-operated fix-forward procedure with new narrowly bound approval; it may not
remove claims, rewrite source history or restore old request counts.

## Successor fixed-path verifier design

The real successor filesystem verifier is **not implemented**. The pure
`verify_destination_model` checks completed journal replay, NEW authority,
byte/claim preservation, baseline/prefix, asserted runtime identity, requester and
operation; it returns MODEL_VERIFIED_NOT_AUTHORIZATION with live_enabled=false.
It accepts only already-supplied synthetic bytes/objects, not file paths, and
cannot touch production. Peer UID here is an assertion from a future trusted
adapter, not SO_PEERCRED proof.

The future operational verifier must hardcode new ledger and dedicated ledger-lock
paths, the unchanged account lock, `authority/manifest.json`, protected policy and
claim-index locations. No path/hash/import overrides or repairs. It must:

- Require separate read-only operational approval (including temporary flock),
  provisioned root policy and actual immutable runtime attestation before opening
  state. Never create a directory, lock, manifest or claim while verifying.
- Validate full root ownership/ancestry, modes, ACL mask implications, single-link
  regular-file types, mounts and reviewed device/inode identities; use read-only
  no-atime, no-follow, close-on-exec pinned descriptors and nonblocking locks.
- Match committed generation/decision, independent latest checkpoint/nonce registry
  and fixed new authority. A stale manifest or alternate active-authority record
  blocks; old archived bytes do not themselves make a second authority.
- Verify exact thirteen-attempt bytes or an **explicitly separately approved**
  future continuation with complete historical prefix and valid individually
  charged attempts. The current model supports only the original thirteen-attempt
  baseline and cannot approve a continuation by supplying another SHA.
- Verify complete historical claim index/raw evidence, account/ledger lock bindings,
  ledger ceiling 49 and purchase_authorized=false. Missing or ambiguous claims,
  unexplained reservations or competing writer authorization block.
- Verify source retirement/launch policy; source-file mode alone cannot prove no
  competing authority. Report sanitized status only, with no credentials/IDs.

Do not run M90.2b v1 against the new directory or relax its root checks. Its old-path
and empty-protected-root contract intentionally cannot certify a Strategy B
cutover. An operational successor requires its own reviewed implementation/tests.

## Legacy writer isolation matrix

Locations below are prior M90.2a/2b evidence, **not a new host inventory**. M89 and
M90 refer to installed releases ending `6a09b7a503906fa3fd96eae1ea9472d15859865f`
and `cb1125613fd7a18a991519ee251c577c578a855a`. Each module is under `<release>/app/`;
manual checkout copies also exist under `/root/IntelligenceOS-Arbitrage*`. Actual
running/manual processes and external schedules must be independently verified.

Evidence abbreviations: C = requester cannot read credentials/copies or retain
usable tokens; L = launch/sudo/service/cron/manual route review; E = effective
network denial for all unauthorized processes; A = same account lock and sole new
authoritative durable budget. No control below is installed in this milestone.

| Module/command | Known copies | Credential requirement | Existing lock / ledger | Network capability | Proposed isolation / evidence |
| --- | --- | --- | --- | --- | --- |
| `amazon_pilot.run_pilot` | M89/M90, original and later checkouts | Private legacy LWA source | No account / no authoritative ledger | Auth + Catalog | Unavailable to requester; C/L/E; no generic privileged Python |
| `amazon_details.run_details` | M89/M90/checkouts | LWA + operator seller context | No account / no authoritative ledger | Auth, offers/fees/eligibility details | Retire live launch route; C/L/E; operations not broker allowlisted |
| `amazon_pricing_diagnostic.run_pricing_diagnostic` | M89/M90/checkouts | Legacy LWA source | No account / no authoritative ledger | Auth + pricing variants | Same; preserve reports as evidence only |
| `amazon_candidates.execute` | M89/M90/M61/current checkout | Legacy LWA loader | No lock by default; optional guard / private reports | Auth/search/details | Prohibit direct privileged calls, C/L/E; guard is not a universal boundary |
| `amazon_candidate_enrichment.execute` | M89/M90/M61/current | LWA + seller context | No account / private reports | Pricing/fees/restrictions | Retire; C/L/E; cannot inherit root broker transport |
| `candidate_execution.execute_details/execute_research` | M89/M90/M61/current | LWA + research context | No account / SQLite operation claims | Auth/details/pricing/restrictions | Private SQL is not cumulative authority; C/L/E |
| `candidate_recovery.run` | M89/M90/later checkouts | Delegated research credentials | Preparation lock only, not run / old SQL | Delegated live research | No automatic recovery executable; C/L/E and retained recovery evidence |
| `stored_candidate_search.run` | M89/M90/M61/current | LWA through underlying candidates runner | Account via Reservations guard / old SQL | Auth/search/detail | Retire requester launch; C/L/E; any retained admin path needs A and fixed existing lock |
| `sp_target_execution.run_prepared` | M89/M90/current | Legacy LWA | Account / old SQL, not authoritative JSON | Auth + fixed target reads | C/L/E; no alternate private root or lock creation; A if ever reauthorized |
| `m63_catalog.run` | M89/M90/current | Legacy LWA | Account / private SQLite | Auth/catalog discovery | Same; private budget cannot replace A |
| `m67_execution.execute` | M89/M90/current | Private reviewed credentials | Account (may create) / private registry | Auth/read transport phases | C/L/E; refuse creation/alternate roots; A if retained |
| `m72_execution.execute` | M89/M90/current | Private reviewed credentials | Account (may create) / private registry | Auth/Catalog | Same |
| `m75_execution.execute` | M89/M90/current | Private reviewed credentials | Existing account / private registry | Auth/Catalog expansion | Same; old plan approval not new execution approval |
| `m77_execution.execute` | M89/M90/current | Private reviewed credentials | Existing account / private registry | Auth/Catalog expansion | Same |
| `m80_execution.execute` | M89/M90/current | Private reviewed credentials | Existing account / private registry | Auth/Catalog/offers/restrictions | Same; outside exact two-request scope |
| `m88.execute` | M89/M90/current | Protected pilot credentials | Account → old JSON ledger | Multiple read phases | Freeze and retire old authority route; C/L/E/A |
| `m88_targeted.execute` | M89/M90/current | Protected pilot credentials | Account → old JSON ledger | Targeted Catalog continuation | Same |
| `m89_continue.execute` | M89/M90/current | Protected credentials | Account → old JSON ledger | Auth + bounded research | Same |
| `m89_deployment.authenticate` | M89/M90/current | Fixed live.env | Old JSON ledger only; no account | LWA auth | Must not remain callable by requester; C/L/E; missing account lock cannot be assumed safe |
| `m90.execute` | M90/current | Config validation + supplied token pipe | Account → old JSON ledger | One Catalog GET | Retire token-pipe/manual privileged route; C/L/E/A |
| `m901.execute` | Source checkout, not installed in prior inventory | live.env | Existing account → old JSON ledger | LWA + conditional Catalog | Approval string is not user authorization; C/L/E/A; do not bypass new gate |
| `m902.execute` | Source checkout, not installed | Protected policy credential source | Account → configured ledger; independent claim | Explicitly injected transports; prospective two calls | Only future attested fixed adapter, new authority/claim registry and independent approval may authorize it; C/L/E/A |
| Direct transport functions / old venvs / shell / generic sudo or systemd-run | All retained trees/runtimes, host mechanisms | Any available credentials or retained tokens | No universal coordination by themselves | Arbitrary possible network activity | No requester-accessible root interpreter, shell, module selector or arbitrary unit; C/L/E plus executable/dependency ownership audit |
| V0.2 `app.orchestrator` | `/current` V0.2 | Mock sample data, no Amazon credentials needed | No Amazon ledger writes | Offline AF_UNIX sandbox | Leave service/timer/code unchanged; verify continued network denial, no protected-state write grant |

File deletion is not the isolation mechanism. The requester may read harmless
source, but must lack credentials, generic privilege, network-capable escape
processes and writable root imports. Cgroup restrictions on the reporting service
alone do not constrain every process with the same UID. Existing credentials and
old source are untouched here; inability to establish C/L/E/A blocks live readiness.
Adversarial host root can bypass advisory locks and remains outside this boundary.

## Immutable runtime and authenticated one-shot launcher

Design only; no listener, service, socket unit, sudo rule or launcher is installed.
Use a manually started root-operated one-shot AF_UNIX SOCK_SEQPACKET endpoint,
with bounded accept/read time, one accepted fixed frame and no restart/socket
activation. Root-controlled `/run` ancestry and a narrowly accessible socket allow
connection but not pathname replacement or `/root` traversal. Check SO_PEERCRED
from the kernel before processing the operation; never trust JSON UID, argv,
SUDO_UID alone or the pure model's injected peer integer as authentication.

The existing fixed broker frame is `{version:1, operation:M902_AUTH14_CATALOG15}`,
maximum 256 bytes, exact fields, no duplicates. Reject truncation, extra frames,
malformed data, unexpected operation/identity and ancillary FDs (close received
FDs safely with close-on-exec). No path, URL, host, method, body, command, module,
executable, approval document or token may be supplied by the requester. Migration
transitions are root-operator-only and must never be available through this IPC.

A network-denied coordinator authenticates the peer and protected evidence. A
fixed trusted worker owns credential handling and both requests in the separately
reviewed egress namespace; secret values never cross back through requester IPC.
The worker holds account → new ledger locks across both phases and all durability
boundaries. Approval is independent root provisioned evidence bound to committed
authority generation, actual immutable release/runtime, exact baseline/seller/app/
marketplace, protected credential binding, lock identities, operation, expiry and
one-time claim. All historical claims and consumed migration approvals remain.

Runtime attestation must cover exact commit and source/content manifest, fixed
absolute interpreter, isolated imports/site packages, dependencies/native libraries,
CA roots, policy and executable ownership/modes/ACLs, read-only/no-atime code mount,
closed unrelated FDs and scrubbed environment/cwd. Use -I -B; disable core dumps.
No mutable checkout, user site, PYTHONPATH, SSL_CERT_FILE/DIR or arbitrary child
execution. Retain no unnecessary capabilities. Clearing Python references does not
guarantee zeroization; exit the dedicated process and never log traceback/local
values or raw Amazon responses.

An authenticated application peer can still cause denial of service or request
the approved fixed operation during an allowed window. It cannot create approval,
obtain root Python access, widen network destinations or retrieve tokens. Every
rejection occurs before consumption where possible. Success returns only static
allowlisted status/summary fields. Actual runtime attestation, kernel IPC tests,
one-time durable claims and failure handling remain future implementation work.

Accounting remains 13 → durable auth reservation 14 → durable successful auth
completion → conditional durable Catalog reservation 15. Failure/timeout/uncertain
dispatch stays charged; no retry, refresh, auto-resume, counter reset or purchases.
Root migration approvals and the model's operation identifier cannot authorize
these HTTP requests.

## Independent network isolation design

Known facts are prior/operator-provided: reporting is AF_UNIX-only with IPv4/IPv6
deny-all, and host nftables NAT/filter tables exist. Effective host rules, chain
policies/hooks, routing/NAT interactions and cloud firewall policy are unverified.
No new host inspection, rule change, DNS resolution or network probe occurs here.

Future worker boundary must be deny-by-default in a dedicated network namespace
or equivalently reviewed isolation, separate from the requester/reporting sandbox:

- Root-controlled provisioning resolves only `api.amazon.com` and
  `sellingpartnerapi-na.amazon.com` in an independently authorized preparation
  step; retain trusted resolver/address/TTL receipts. No requester resolver,
  endpoint selection or general DNS egress inside the worker.
- Short-lived reviewed destination sets allow TCP 443 only, with correct IPv4 and
  IPv6 coverage and established return traffic. Deny every other destination/
  port/protocol. Missing family support must block or explicitly disable that
  family in the reviewed namespace, not leave a bypass. Never auto-widen sets.
- Address churn/shared infrastructure means IP rules cannot prove HTTP hostname,
  path or tenant. Keep TLS certificate/hostname verification and original SNI,
  a trusted immutable CA configuration and fixed application-level requests.
- Permit exactly POST `https://api.amazon.com/auth/o2/token` and GET
  `https://sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items/B001BE12BA?marketplaceIds=ATVPDKIKX0DER&includedData=summaries`.
  No redirects, proxies, refresh, retries, offers, fees, inventory, purchases or
  listing changes. Ignore/scrub proxy environment and endpoint override variables.
- Bound request/response sizes, 10-second socket timeouts and a single 40-second
  workflow deadline. Deny untrusted subprocesses and drop CAP_NET_ADMIN/
  CAP_SYS_ADMIN; prevent setns/unshare/mount/cgroup escape in the worker.
- Verify actual namespace, nft rule handles/hooks/defaults, routes, address sets,
  cgroup and external/cloud policy before credential reads or any request
  reservation. Policy/TTL/TLS verification failure stops execution; no insecure
  TLS mode, broad fallback or automatic retry.
- Egress evidence logs only policy/generation ID, allowed operation label,
  timestamp and sanitized status. Never log LWA payload, headers, tokens,
  seller IDs, raw HTTP bodies, credentials or packet payload captures. Protect
  destination metadata and operator evidence with bounded retention/access.

Kernel network denial and fixed immutable HTTP code are complementary. Table names
or a passing mocked transport test prove neither. Network-policy verification
failure blocks RUNTIME_ATTESTED and any later live start. All DNS/TCP/TLS/live
validation needs separate explicit approval; no such operation is authorized now.

## Test evidence and exact offline commands

Starting tree verified clean on `milestone/m90-2b-ledger-storage-readiness` at
`12769879ff19b3801a1ddabde305d7912b5db5ad`. New branch:
`milestone/m90-2c-authority-cutover-design`. All prior history is preserved.

```bash
/tmp/arbitrage-ci-fix-py312/bin/python -m pytest -q tests/test_m89_deployment.py tests/test_m90.py tests/test_m901.py tests/test_m902.py tests/test_m902a.py tests/test_m902b_verify.py tests/test_m902c.py
/tmp/arbitrage-ci-fix-py312/bin/python -m pytest -q
/tmp/arbitrage-ci-fix-py312/bin/python -m pip check
ARBITRAGE_MODE=legacy ARBITRAGE_REPORT=var/m902c-legacy.xlsx ARBITRAGE_DB=var/m902c-legacy.sqlite3 /tmp/arbitrage-ci-fix-py312/bin/python -m app.orchestrator
ARBITRAGE_MODE=discovery ARBITRAGE_REPORT=var/m902c-discovery.xlsx ARBITRAGE_DB=var/m902c-discovery.sqlite3 /tmp/arbitrage-ci-fix-py312/bin/python -m app.orchestrator
git diff --check
```

Baseline milestone tests: 518 passed. New model tests: 70 passed. Tests cover all
legal transitions, illegal jumps, duplicate authorities, every phase interruption,
uncertain manifest decision, evidence/fsync absence, exact bytes, claim
preservation/conflicts/missing evidence/future consumption, approval replay and
bindings, lock ordering, runtime/peer/operation mismatch, altered journal and no
filesystem/network activity. A guard denies file/network operations while the
entire synthetic model runs. This proves model purity, not kernel IPC or actual
disk/fsync behavior. Both sample workflows: job_succeeded. Dependency check
passed. The full regression run started before the final conservative claim-guard
refinement; the final focused run rechecks all model cases, including duplicate
origins and false consumption. Final focused result: **588 passed in 18.24
seconds**, including all 70 model tests. Full regression result: **3559 passed,
9 skipped in 694.13 seconds** (3568 collected). The final model guards were
validated in the focused run after the full run had collected its modules; no
other implementation files changed. Dependency and whitespace checks passed.

## Remaining blockers, approvals and proposed M90.3 scope

Required separate approvals and evidence, in order:

1. Independent security/design review of this model, manifest/approval schemas,
   ambiguity handling and all remaining trust assumptions.
2. Host-side read-only evidence collection with real identities, existing lock
   metadata, filesystem/mount/ACL semantics, actual ledger, all claim origins,
   running/manual/scheduled writers and effective network/cloud rules. Current
   budget and completeness remain unverified. No bypass of denied access.
3. Explicit protected-storage provisioning approval (including new **ledger**
   lock), immutable runtime packaging and fixed protected policy provisioning.
   No account-lock migration, reporting change or `/current` switch is needed.
4. Maintenance freeze/writer-isolation approval and reviewed weaker-trust source
   auditor implementation. If credential access or writer absence cannot be
   resolved while credentials remain untouched, keep deployment/live readiness
   blocked pending a separate specifically approved credential-access solution.
5. Implement/test an actual durable journal, independently retained nonce/checkpoint
   registry, source descriptor adapter, raw-copy/fsync backend, exact manifest
   schema/commit reader and fixed-new-path verifier. Prove crash windows and
   competing-writer prevention with synthetic subprocess/storage fault tests.
   The pure receipts here do not replace those components.
6. Per-transition root approval bound to exact decision/previous head/evidence;
   independent claim reconciliation and explicit authority-cutover approval.
   Any ambiguous or missing claim blocks future execution; no deletion/reset.
7. Independently review/test the immutable one-shot SO_PEERCRED coordinator/worker
   and network namespace without activating them; obtain separate deployment
   approval only when all filesystem/runtime/credential/network blockers close.
8. After separately approved deployment/cutover, run a separately approved
   no-request verifier. Enable no live request until an additional explicit
   two-request approval, genuine seller/application evidence and fresh locked
   budget/replay validation. Migration itself authorizes zero Amazon requests.

M90.3 should implement these missing **offline adapters and fault tests first**,
not execute a production migration merely because model tests pass. A runnable
source auditor, durable cutover backend, successor filesystem verifier, runtime
attestor, nonce registry and launcher are intentionally not delivered in M90.2c.

## Production invariant confirmation

Zero production modifications and zero live Amazon requests. No production
migration/deployment/staging, credentials access, ledger verification/read/write,
lock creation/acquisition, ownership/mode/ACL change, service/timer operation,
firewall alteration, symlink change, DNS/TCP/TLS probe, package installation, push
or merge was performed. The source ledger and credential files remain untouched
by this work. Reporting retains its restrictions and its V0.2 `/current` target
is not changed. No request or purchase is authorized. Historical claims are never
removed/reset by the model. There is no automatic rollback to an older ledger.
