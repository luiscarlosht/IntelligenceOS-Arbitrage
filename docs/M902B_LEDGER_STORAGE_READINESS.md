# M90.2b — Ledger verification and protected-storage readiness

## Executive summary

M90.2b delivers a network-free, read-only verifier and a migration design. It does
**not** verify production, provision policy, migrate storage, deploy code or enable
execution. The utility was run only with synthetic files in tests. No production
credentials or ledger contents were accessed and no production locks acquired.

Recommend **Strategy B: a dedicated root-controlled protected state location**,
conditional on a formally approved single-authority cutover and complete legacy
writer isolation. It avoids changing the offline service's reporting paths and
ownership. It is not safe merely to copy the ledger and start a new broker.
Strategy A is viable if preserving the old path is essential, but changes shared
reporting ancestry and service output configuration, increasing the blast radius.
Neither strategy is authorized for execution by this milestone.

The expected full ledger SHA is
`c79e2a7788c3b99ee75a17dc3150b9e2a609818ad2de3cce82f082e36c9b79f1`, with
13/49 used, 36 remaining and purchases unauthorized. These are expectations, not a
fresh verification or permission to restore those bytes. Attempts 14 and 15 are
future conditional operations, not existing reservations created by this work.

## Evidence provenance and current blockers

The following are **operator-provided follow-up observations in the M90.2b
request**, not measurements made during this milestone:

- `/var/lib/intelligenceos-arbitrage` and its `m89` directory are application owned;
  `ledger.json` is application owned, mode 0600.
- `/etc/intelligenceos-arbitrage/m89` is application owned, mode 0700; `live.env`
  is application owned, mode 0600. Credential contents must remain unread.
- The shared Amazon account lock is root owned, mode 0600.
- The application-owned offline reporting service has an enabled, active timer.
  Its protections include ProtectHome=yes, NoNewPrivileges=yes,
  RestrictAddressFamilies=AF_UNIX and IPv4/IPv6 deny-all configuration.
- nftables IPv4 and IPv6 NAT/filter tables exist. Their actual rules, hook
  priorities, chain policies and effective egress behavior are unverified.
- `/current` must remain on the V0.2 release ending
  `68230d3fdaef588bb7ba5c8340f49a473e8386b7`.

M90.2a's visible filesystem inventory additionally found group-writable installed
application source trees and could not traverse the ledger ancestry. Its sandbox
mapped non-root owners to overflow UID 65534, so the newer operator observations
supply information that that inspection could not establish. M90.2b performs no
new production inspection, privilege escalation or attempt to work around access.

## Verifier security model

`app/m902b_verify.py` imports only standard-library modules and the new pure
`app/m902_history.py`. The latter contains JSON/history validation and constants,
with no filesystem, credential or network operations. No legacy Amazon runner,
transport, broker writer helper or dynamically chosen module is imported. M90's
existing `history_bytes` delegates to this shared validator while preserving the
existing public API and test seam for the reviewed twelve-attempt prefix.

Only a trusted root-operated immutable runtime may invoke the verifier. Root is
trusted; a Python helper is not a sandbox against root code modification or hostile
kernel/filesystem behavior. Neither success nor the review policy authorizes any
Amazon request. The requester must never receive general root Python execution.

### Fixed invocation and paths

The sole accepted argument sequence is **`verify`**. No arguments, `--help`, path
flags, repair verbs, extra words and baseline/identity arguments are rejected
before any target path access. There are no environment path overrides, credential
paths, arbitrary file-reading commands, output-file options or resume/retry APIs.
Internal underscore helpers and monkeypatched constants are test implementation
seams, not requester interfaces; deployment must protect code and imports.

Fixed v1 production paths:

| Purpose | Fixed path |
| --- | --- |
| Existing account lock | `/root/.intelligenceos-arbitrage-amazon/candidate-execution.lock` |
| Existing authoritative ledger lock | `/var/lib/intelligenceos-arbitrage/m89/ledger.lock` |
| Authoritative ledger | `/var/lib/intelligenceos-arbitrage/m89/ledger.json` |
| Operator-reviewed identity policy | `/etc/intelligenceos-arbitrage/m902b/verification-policy.json` |
| Independent protected-state/claim scope | `/var/lib/intelligenceos-arbitrage-protected` |

The policy is a new **proposed** root-only file, not an existing verified
production artifact. It is not created by the utility or this milestone. Its
absence blocks verification. Provisioning it later is a production configuration
change requiring separate approval, even though its contents are not secrets.

Exact policy schema, shown as an **invalid inert template**:

```json
{
  "version": 1,
  "account_lock": {"device": "OPERATOR_REVIEWED_INTEGER", "inode": "OPERATOR_REVIEWED_INTEGER"},
  "ledger_lock": {"device": "OPERATOR_REVIEWED_INTEGER", "inode": "OPERATOR_REVIEWED_INTEGER"}
}
```

Actual device/inode fields must be nonboolean unsigned 64-bit integers and inode
must be positive. Version is the integer 1. Extra/missing fields, duplicate keys,
nonfinite JSON, malformed nested objects and policy input over 4096 bytes fail.
Do not use placeholder identities or manufacture a production policy from these
examples. Independent operator review must establish identities; the utility does
not treat the inode it happens to open as its own authorization evidence.

### Filesystem and metadata contract

Every protected directory component must be root owned, non-symlink and not
writable by group/other. Immediate containing directories must be 0700; files must
be root-owned single-link regular files with mode 0600. Production validation
starts at `/`, not an application-writable anchor. The claim scope's parent may
be a normal root-controlled 0755 ancestor; an existing claim-scope directory must
be root-owned 0700. Synthetic tests use a private temporary anchor only.

**The currently described application-owned ledger layout intentionally fails
this contract.** Root's ability to bypass DAC is not evidence of safe ownership.
Do not chmod/chown to make this utility pass during a verification-only session.
A separately approved storage remedy and policy provisioning are prerequisites.
V1 also cannot follow a Strategy B ledger relocation: that needs a separately
reviewed version with the new fixed paths and updated claim-scope contract.

Directory components are opened descriptor-relative with O_DIRECTORY,
O_NOFOLLOW, O_CLOEXEC, O_NOATIME and O_NONBLOCK. Their identities are compared to
the named entries and retained throughout inspection. Files are opened O_RDONLY,
never O_RDWR, O_WRONLY, O_CREAT, O_TRUNC or O_APPEND, with the same safety flags.
Files' owners, modes, link counts, identities, sizes and nanosecond
atime/mtime/ctime are compared before/after inspection. Directory names/metadata
are rechecked. Symlink or directory replacement cannot redirect a read unnoticed.

O_NOATIME is mandatory even on systems where it is unsupported: missing flags,
permission denial or unsupported metadata-safe access cause a stop; there is no
fallback that permits an atime update. Directory listing also uses no-atime
opened descriptors. No lock, claim, ledger or directory is created, truncated,
replaced, unlinked, chmodded, chowned, restored or repaired. No fsync/write syscall
is needed. The utility does not read credential or claim contents.

Python code/interpreter imports are outside the explicit target-file open path.
A future runtime must be immutable and read-only/no-atime, use `-I -B`, have audited
site packages and suppress core dumps. `-B` prevents bytecode writes; it alone
does not prevent ordinary interpreter/code reads from updating code-file atimes.
The target-file metadata checks and synthetic tests prove the verifier's target
I/O behavior, not every possible host audit/logging/filesystem side effect.

### Temporary kernel lock state

Exclusive nonblocking `flock(LOCK_EX | LOCK_NB)` is acquired **account first,
ledger second**, on the two existing reviewed inode/device pairs. Linux supports
this local-filesystem flock use on O_RDONLY descriptors. If a filesystem/platform
requires writable access or provides different locking semantics, stop; do not
switch to O_RDWR or create a substitute lock. Remote/shared filesystem semantics
need separate review.

Flock acquisition temporarily changes kernel advisory-lock state and may cause
another cooperating writer to receive contention. Thus verification is not
observationally invisible and requires separate operator approval even though it
has no persistent writes. Both locks span the complete ledger/claim inspection
and release through descriptor closure on success or failure. A contention error
stops immediately, with no retry. Success is emitted only after all descriptors
close. Tests compare file/directory contents and nanosecond metadata before and
after success and failure, and verify lock order/cleanup.

Locks do not prevent an uncooperative process from writing directly. Root is
trusted, legacy writers must be isolated, and a successful result is a point-in-time
snapshot—not an execution authorization or a durable reservation for a later run.

## Exact ledger and claim verification contract

1. Validate the fixed root-protected policy and independently pinned identities.
2. Validate/open existing locks, acquire account then ledger nonblocking flock.
3. Require the ledger directory to contain exactly `ledger.json` and `ledger.lock`.
   Any extra entry, including an empty/linked `m901-no-replay.json`, is a blocker.
   Do not delete files to force compliance; unexplained artifacts need review.
4. Require the fixed independent protected-state root to be absent or empty.
   If absent, prove absence via its validated parent and recheck before returning.
   If present, validate its protected ancestry and require no entries, then recheck.
   The utility never opens claim contents or removes consumed claims.
5. Open the ledger once through the validated descriptor, bounded to 8 MiB; retain
   the descriptor through validation and final metadata checks. Partial reads are
   assembled into one snapshot; read errors/interruptions stop, not retry.
6. Match the **complete original thirteen-attempt raw SHA**. Reject duplicate keys,
   nonfinite values, wrong types, count/order drift, unresolved RESERVED entries,
   purchases not false, ceiling not integer 49 and authentication/retries coverage
   not true. Require attempt 13 to be successful LWA authentication, token_received
   true, no candidate ID and valid aware chronological timestamps.
7. Reconstruct the entire twelve-attempt prefix, preserving every historical
   field, and compare its canonical SHA with
   `b7502888a36b97594e5c79b3f8c47312c1226d80355a03621284660b45da2f1b`.
   Never normalize, reserialize or repair the production ledger itself.
8. Recheck retained ledger/lock/directory metadata and claim absence, close all
   descriptors, then return a fixed allowlisted result. Any inconsistency blocks.

Successful output contains only status, baseline_match=true, attempts_used=13,
ceiling=49, remaining=36, purchase_authorized=false,
claims=ABSENT_IN_FIXED_SCOPE and persistent_changes=false. Failure returns only
`VERIFICATION_BLOCKED` with exit code 1; unexpected invocation returns
`INVALID_INVOCATION` with exit code 2. No raw exception, protected path, seller ID,
credential data, token, credential digest or historical response is printed.

Claim absence is deliberately **scope-qualified**. It cannot prove that an old
trusted caller never configured a claim in another directory, or that an
application-owned historical claim was not deleted. Operator inventory and retained
independent evidence must identify all historical claim locations before runtime
readiness. The ledger's exact SHA detects extra embedded claims; expected historical
M88/M89 markers are retained. Future broker policy must use the reviewed claim
scope, and any newly introduced state there requires an explicit verifier-version
review. Never delete existing claims or interpret a restored 13-attempt ledger as
permission to repeat requests.

## Protected-storage migration alternatives

The following are designs only. All production ownership, service and storage
operations require an independently approved maintenance plan. The existing root
account lock remains exactly where it is in both strategies, with no replacement
or second independent account lock.

### Shared prerequisites

- Establish all host identities/ACLs/mounts and all live/manual/scheduled writers,
  including checkouts and retired releases. Freeze new execution authorization.
- Obtain explicit approvals for maintenance outage, writer isolation, metadata
  changes, state copying and authority cutover. Approval for a read-only verifier
  does not grant any of these permissions or any Amazon request.
- Quiesce and account for every relevant process, including ledger-only M89 and
  unlocked legacy runners. The future requester must lose direct access to
  credentials and arbitrary privileged execution; launcher permissions alone are
  insufficient while it owns credential files. Review any preexisting credentials
  or tokens retained in process memory/copies. Revocation/rotation, if required,
  needs its own approved procedure; no Amazon calls are authorized here.
- Review source bytes, exact current ledger baseline, every independent claim and
  historical operator records. Current application-owned ancestry prevents this
  v1 verifier from certifying that source layout. A separately reviewed fixed-source,
  descriptor-based migration audit must establish source integrity under the
  approved freeze, without claiming that current ownership is safe. Do not add
  arbitrary path flags or relax v1 ancestry checks as a workaround.
- Capture a protected, immutable evidence package of original ledger bytes,
  SHA, all attempts, claim bytes, lock identities and metadata. Retained backups
  are evidence, not executable authoritative ledgers. Never print credentials.
- If the baseline differs, any pending/uncertain request exists or replay evidence
  is unresolved, stop. Never reset to the expected thirteen-attempt state.

### Strategy A — Preserve authoritative path

Keep `/var/lib/intelligenceos-arbitrage/m89/ledger.json` and `ledger.lock`.

| Area | Required change / risk |
| --- | --- |
| Ownership/ancestry | Make `/var/lib/intelligenceos-arbitrage` root controlled with no group/other write (for example 0755), `m89` root-owned 0700 and ledger/lock root-owned 0600. Keep existing lock files/inodes; ownership changes alter ctime and require new reviewed metadata. Root-owned files alone under an application-owned parent are insufficient. |
| Reporting compatibility | Introduce a separately application-owned reporting child, e.g. `/var/lib/intelligenceos-arbitrage/reports`, and explicitly move report/history outputs there. Review both ExecStart commands, environment/default DB paths and existing report retention. This requires separately approved offline service configuration changes; keep every network/sandbox restriction and `/current` target. The M90.2a inspected unit declares `StateDirectory=intelligenceos-arbitrage`: remove or retarget that application-owned StateDirectory assignment before protecting its old parent, or a future service start may undo ownership protection. Review automatic/recursive ownership handling, not just ExecStart paths. |
| Credential source | Make the fixed `/etc/intelligenceos-arbitrage/m89` directory and live.env root-only after host review; inspect ancestor ACLs without granting requester access. No credential values need be printed. |
| Existing ledger lock | Retain the exact existing ledger-lock inode/device; acquire it after the unchanged account lock for the entire cutover. Never unlink/recreate it. Verify ownership/mode transition while held and re-provision reviewed identity policy separately. |
| Durability/atomicity | Ledger contents need no rewrite. Ownership/output relocation is a multistep maintenance transaction, not globally atomic; keep all writers quiesced until metadata, reporting relocation and policy checks complete. Fsync any copied reporting data/manifests and directories as appropriate; record and validate all completed steps. |
| Writer dependencies | All code still points at the same ledger path, but old ownership assumptions, credential readers and alternate-root executors must be retired/coordinated. The unchanged path does not fix missing locks or direct network access. |
| Claims | Preserve every embedded and independent claim. Put future broker claims in a separately root-controlled retained location, never in reporting backups. Existing claims remain authoritative blocking evidence; relocation must not make the broker overlook them. |
| Duplicate authority | Low if the ledger is never copied for execution. Reporting or evidence backups must never be accepted as ledger paths. |
| Rollback | Restore reporting configuration/data only through a reviewed plan. Do not restore ledger bytes, remove claims, recreate locks or automatically revert protected ownership to application ownership. After any new attempt, accounting rollback is forbidden. |
| Approvals | Explicit shared-parent ownership, credential ownership, reporting relocation, service configuration/outage, claim-policy and operator-verification approval. No live requests implied. |

A requires careful reporting regression checks, including a controlled future
service start that confirms no automatic StateDirectory ownership reassignment
affects the protected parent or ledger, before re-enabling the timer in a future
maintenance window. Do not disable it during this milestone. A does not
require changing the authority's pathname, but is not a small permission-only fix.

### Strategy B — New dedicated root-controlled authority

Proposed destination: `/var/lib/intelligenceos-arbitrage-protected/m89/ledger.json`,
with a dedicated ledger.lock in that same root-only directory. Future independent
claims should occupy a separate root-only retained child, e.g. `claims/`, with a
registry that covers all historical claim locations. The account lock stays at
`/root/.intelligenceos-arbitrage-amazon/candidate-execution.lock`.

| Area | Required change / risk |
| --- | --- |
| Ownership/ancestry | Provision new root-owned protected root/children, mode 0700, and files/ledger lock 0600 under root-controlled ancestors. Protect credentials at their existing fixed source separately. Do not change the application-owned reporting parent. |
| Reporting compatibility | Existing reporting service, timer, output paths and ownership can remain as they are; `/current` remains V0.2 and offline restrictions remain intact. No broker state belongs in reporting backups. |
| Existing locks | Hold unchanged account lock, then old existing ledger lock. A new **ledger** lock may be provisioned only under migration approval; it is not a second account lock. During cutover acquire new ledger lock last: account → old ledger → new ledger. No reverse order, no creation by the verifier, no concurrent old/new writers. |
| Atomicity/durability | Destination starts as STAGED_NONAUTHORITATIVE. Copy exact source bytes without JSON rewriting, fsync copied file and parent, validate complete history/full SHA and preserved claims under the freeze. Keep staged state inaccessible to the requester. A reviewed durable authority manifest/release gate commits the switch; do not rely on two independent files being atomically renamed across directories/filesystems. Keep the namespace frozen through every policy/launch update. |
| Policy bindings | A new reviewed verifier/broker version must hardcode the new authority and ledger lock, pin the new lock identity, and bind approval to the actual immutable release, original ledger SHA, seller/application evidence, credential source and preserved claim registry. V1 cannot accept a `--ledger` override and must not silently follow a symlink. |
| Writer dependencies | Every still-authorized writer must use the new authority and reviewed shared account lock. Ledger-only and unlocked executors must become unavailable to the requester before commit. If any old writer remains launchable with usable credentials, do not cut over. |
| Duplicate authority | Critical risk. Old and new files can coexist only with exactly one declared write authority. Retain the old copy solely as blocked, nonexecutable evidence. Because its old parent is application-owned, chmod on the old file cannot prevent path replacement; enforcement must come from credentials isolation and trusted launch policy. Never accept either path opportunistically or fall back to the old one. |
| Claims | Copy/retain claims with origin, digests and bindings; preserve consumed state and independent retention. A new empty claims directory does not reset historical claims. Any historical claim blocks the planned 14/15 workflow pending explicit reconciliation, never deletion. |
| Rollback | Before authority commit and before any new dispatch, a separately approved abort can leave the old authority active while keeping staged data inert and preserving claims. After commit, disable live launch access and report-only investigate; never point a writer back to an older ledger. Fix forward to a reviewed release using the same current authority. Never restore ledger bytes or replay claims. |
| Approvals | Explicit writer retirement, credential protection, new state/ledger-lock provisioning, protected copy/claim retention, authority manifest and release/policy cutover, independent verifier review and deployment approval. Live execution is a later separate approval. |

**Recommendation: B**, because protected execution state and routine application
outputs should have independent ownership, retention and rollback domains. This
reduces changes to the enabled offline reporting service and prevents future
reporting restores from replacing protected accounting. Its additional authority
cutover risk must be resolved before migration, not accepted implicitly. If complete
writer isolation or a durable single-authority decision cannot be demonstrated,
keep migration blocked; do not operate both paths or automatically fall back to A.

## Legacy execution isolation plan

Retain all source/history; do not delete modules, modify installed releases or
change permissions in M90.2b. Use the detailed installed-writer matrix in
[M90.2a](M902A_SECURITY_READINESS.md) as the starting inventory, with host-side
confirmation before any future cutover.

The future broker requester must be unable to invoke privileged live execution
through original `amazon_pilot`, `amazon_details`, `amazon_pricing_diagnostic`,
`amazon_candidates`, `amazon_candidate_enrichment`, `candidate_execution`,
`candidate_recovery`, `stored_candidate_search`, `sp_target_execution`,
`m63_catalog`, `m67_execution`, `m72_execution`, `m75_execution`, `m77_execution`,
`m80_execution`, `m88`, `m88_targeted`, `m89_continue`,
`m89_deployment.authenticate`, `m90.execute` or `m901.execute`, including copies in
old releases and `/root/IntelligenceOS-Arbitrage*` checkouts. Transport primitives
and generic Python/shell entry points must not be an alternate privileged route.

Unprivileged access to source text is not the principal issue: usable credentials,
privileged launch authority and unconstrained egress are. In the separately
approved design, remove requester access to credentials and their copies, forbid
arbitrary sudo/systemd-run/interpreter/module commands, use immutable code and a
fixed one-shot kernel-authenticated launcher, and keep request fields fixed. Only
the broker owns credentials, the unchanged account lock and the sole active
ledger/ledger lock. Apply appropriate requester egress restrictions outside the
offline service as well; that service's cgroup protections do not automatically
constrain every process running with the same UID.

Any retained administrative writer needs explicit operation approval, the same
account lock, the active authoritative ledger and per-request durable reservation.
Account-only private SQLite accounting or M89's ledger-only locking is insufficient.
Root remains a trusted administrative principal; no Python utility can prevent
an adversarial host root from bypassing advisory locks.

## Network boundary evidence still required

IPv4/IPv6 NAT/filter **table existence proves neither deny-all nor allowlisting**.
Before enabling a separate live execution environment, obtain reviewed evidence of:

- Complete relevant rules, base chains, hook priorities, default policies,
  interfaces, address families, conntrack/established exemptions, routing and NAT
  transformations. Identify competing iptables/nft management and rule persistence.
- The actual runtime reporting unit's sandbox and cgroup enforcement. Keep its
  IPv4/IPv6 deny-all, AF_UNIX and NoNewPrivileges/ProtectHome protections unchanged.
- A separately reviewed broker namespace/cgroup boundary, independent
  deny-by-default egress and protection against namespace/cgroup escape. It must
  cover IPv4 and IPv6, not merely install named tables in each family.
- Controlled DNS provisioning, TTL/address churn, trusted CA paths, exact hostname
  verification/SNI and immutable code. IP sets can include shared infrastructure
  and cannot enforce HTTP paths/methods or distinguish every tenant.
- Exact fixed LWA POST and conditional Catalog Items GET only, no redirects,
  proxies, retries, refreshes or arbitrary destinations. Socket/workflow/response
  bounds and fail-closed policy on stale/missing address evidence.
- DigitalOcean cloud firewall policy and its relationship to host rules. No
  assumption that host or service rules certify cloud policy, or vice versa.
- Offline synthetic enforcement tests, followed only by separately approved
  no-request host checks. DNS/TCP/TLS probes and live requests need their own
  explicit authorization; none are authorized or performed here.

The verifier needs no network access at all; its runtime should be network denied.
It is not a network readiness test and must not resolve Amazon hosts.

## Proposed operator verification procedure — NOT AUTHORIZED NOW

1. Obtain separate approval for read-only production verification, explicitly
   including temporary exclusive kernel lock acquisition. Confirm the exact
   immutable code/dependency release, host identity, filesystem semantics and
   maintenance/coordination window. Do not execute from a mutable checkout or
   group-writable old release.
2. Confirm root-owned protected ancestry, existing reviewed lock identities and
   fixed claim scope. With the currently described ownership this prerequisite
   fails: stop and resolve it only through separately approved storage work.
   Strategy B additionally needs a reviewed fixed-path verifier revision; do not
   use v1 against a relocated ledger or add a path argument.
3. A separately approved deployment may provision the root-only policy with actual
   independently reviewed device/inode integers. No production policy exists by
   virtue of this document. Missing policy or missing locks is a blocker, not a
   reason to create files during a verification session.
4. Confirm all historical claim roots/retention evidence have been inventoried and
   legacy writer launch routes are controlled. Do not remove claims, artifacts or
   reservations to obtain a successful result.
5. In a trusted host-root session, after the approved verifier package has been
   installed into the named immutable runtime, use the following exact contract.
   Replace `APPROVED_VERIFIER_COMMIT` **once during approved release selection**
   with its independently attested commit, not with a caller parameter:

```bash
# INERT PROPOSAL ONLY: prerequisites and separate approval are mandatory.
ulimit -c 0
/usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  /usr/bin/timeout --signal=TERM --kill-after=5s 30s \
  /opt/intelligenceos-arbitrage/releases/APPROVED_VERIFIER_COMMIT/.venv/bin/python \
  -I -B -m app.m902b_verify verify
```

This does not install anything, start services, change `/current` or create
state. The package must be available in that audited isolated interpreter's site
packages; do not compensate for a missing module with PYTHONPATH, cwd imports,
generic sudo permission or the existing offline runtime. The source/dependency
mount must provide read-only/no-atime behavior if requiring unchanged code-file
metadata as well. Core limit is process/session state, not a persistent OS setting.
Timeout terminates inspection rather than retrying; kernel lock release follows
process descriptor cleanup. An uninterruptible storage fault may delay release;
operator investigation is mandatory, not another invocation.

6. Accept only exit 0 plus the fixed VERIFIED result as snapshot evidence. Exit 1,
   exit 2, timeout, signal or any unexpected output is blocked/uncertain. Do not
   automatically invoke it again, reset state or fall back to legacy preflight
   commands that can create locks. Even VERIFIED is not approval for attempts
   14/15; eventual execution must revalidate under its own held locks and gate.

## Offline verification and recorded results

Starting branch/commit verified clean:
`milestone/m90-2a-security-hardening`,
`f451143030821e07ea075a0637b66279afce9c9e`.
Work uses `milestone/m90-2b-ledger-storage-readiness`; history is preserved.

Commands actually permitted/run in this milestone use only synthetic tests and
local illustrative workflows:

```bash
/tmp/arbitrage-ci-fix-py312/bin/python -m pytest -q tests/test_m89_deployment.py tests/test_m90.py tests/test_m901.py tests/test_m902.py tests/test_m902a.py tests/test_m902b_verify.py
/tmp/arbitrage-ci-fix-py312/bin/python -m pytest -q
ARBITRAGE_MODE=legacy ARBITRAGE_REPORT=var/m902b-legacy.xlsx ARBITRAGE_DB=var/m902b-legacy.sqlite3 /tmp/arbitrage-ci-fix-py312/bin/python -m app.orchestrator
ARBITRAGE_MODE=discovery ARBITRAGE_REPORT=var/m902b-discovery.xlsx ARBITRAGE_DB=var/m902b-discovery.sqlite3 /tmp/arbitrage-ci-fix-py312/bin/python -m app.orchestrator
git diff --check
```

Baseline milestone tests: 447 passed. New verifier tests: 71 passed, covering
correct synthetic history, full/prefix SHA, count/history/reservation drift,
claims, malformed policy, ownership/modes, missing/contended/replaced locks,
symlinks/hardlinks, inaccessible/replaced ancestry, read errors, unavailable
O_NOATIME, read-only flags/order, file replacement during open/read/validation,
metadata/content preservation, isolated network-free imports and sanitized CLI.
Both offline sample workflows: job_succeeded. Final focused suite: **518 passed**
in 16.50 seconds. Final collection: 3498 tests. Dependency check passed. The full
regression session was interrupted by server recovery; it was restarted with a
local log. The restarted complete run passed: **3489 passed, 9 skipped in
717.71 seconds** (3498 collected), including all new verifier tests. No result
is inferred from the interrupted run. Final `git diff --check` passed.

Internal review covered the static import boundary, read-only open flags,
nonblocking lock order, descriptor cleanup, snapshot consistency and fixed CLI.
An independent deployment/security review of the actual immutable runtime and
host remains required; these offline results do not establish production readiness.

## Zero-production-change confirmation

No production verifier invocation, ledger/credential read, production lock
acquisition/creation, claim/policy provisioning, permission/ownership/ACL change,
service/timer operation, firewall change, source installation, migration, staging,
deployment, symlink change, Amazon request, DNS/TCP/TLS probe, push or merge was
performed. All new fixtures and outputs are local/synthetic. Production changes:
**zero**. Live requests: **zero**. Request consumption by this milestone: **zero**.
Current production ledger integrity/budget is **not verified**; 13/49 remains the
supplied expectation, not a claimed fresh observation.
