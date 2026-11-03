# M78 isolated preparation — current status

**FAIL / NOT READY.** The fresh fixed destination is
`/mnt/intelligenceos_data/arbitrage/m78-isolated`. The existing
`/mnt/intelligenceos_data/arbitrage/sandbox/m78` remains preserved and is never
an installation source. The [current isolated procedure](M78_DIGITALOCEAN_PROCEDURE.md)
supersedes all historical migration instructions below.

The new installer uses a separately approved offline bundle, exact manifest checks,
ACL-free root-controlled ancestors, exclusive copies, resumable matching partial
installs and fail-closed conflict handling. The wrapper uses this fresh installer;
no empty-layout shell bypass remains. Runtime paths consistently use the isolated
base. No DigitalOcean changes, trial, API calls, registry updates, service restarts
or reboot were performed.

Dependency recovery examined local all-ref requirements/lock/provenance history,
M78 tool history, repository search, prior PR provenance and CI artifact metadata.
No authenticated dependency record was recovered. The current procedure documents
verified-artifact offline reconstruction, independent review and the generated
bytecode limitation. Neither old sandbox hashes nor counts establish trust.
The mandatory 401-file dependency profile is unchanged; reconstruction that cannot
satisfy it needs a separate reviewed profile change.

Remaining blockers: independently authenticated dependency record and approved bundle;
direct-host identity/mount/ACL preflight; separately authorized installation and two
complete synthetic target verification passes. Production staging/execution requires
additional authorization and trial-specific design. Development tests do not clear
any target enforcement or production gate.

Exact read-only host preflight:

```sh
sudo /usr/bin/python3 -B /root/IntelligenceOS-Arbitrage-M61/ops/m78_sandbox/audit.py
```

This audit never traverses the old sandbox and intentionally reports readiness FAIL
with target isolation NOT_TESTED. See the current procedure for review criteria and
approval-scoped artifact preflight and installation commands.

## Isolated preparation validation

Python 3.12.3, final code/tests held fixed throughout the full run:

- Full repository suite: **2,310 passed in 740.98 seconds**.
- Focused M78 security suite: **77 passed in 2.23 seconds** (26 new tests).
- Both README sample modes passed with a clean environment and output/database
  files under /tmp; only bundled fictional inputs were used.
- Shell syntax and git diff --check passed.

Coverage includes fixed paths, ACL boundaries and inspection errors, exact dependency
bytes (including bytecode), fresh preflight without mutation, first installation,
matching partial resume, idempotence, protected evidence/output, original sandbox
preservation, symlinks/hardlinks, mounts, drift/extras and fail-closed wrapper gates.
The new UID/GID output creation and kernel/systemd enforcement still require the
separately approved host checks; synthetic local fixtures do not establish them.

## Historical final-readiness report (before isolated preparation)

The following observations and test counts describe main at 03d42c1, not this PR.
Its next-step migration instructions are superseded by the current procedure.

# M78 final readiness — 2026-11-03

**Overall: FAIL / NOT READY for an offline production trial.** Development
fixes are prepared and tested. Target deployment and trial readiness remain blocked. No server change,
production evidence staging, M78 production execution, Amazon request or M77
registry change was performed. SSH failed at socket creation, but the existing host data-volume view was
available read-only and was audited without modification. This session has a
root-only UID/GID map; observations below cannot replace direct host verification.

## Completed work and security assessment

Reviewed merged PR #70 (`aa549e23a84d46edc4817833d7c8cf16badc927b`), including
migration, launcher, verification wrapper and the DigitalOcean procedure.

- **Cache blocker confirmed and fixed:** the reported 125 extra `.pyc` files
  would fail the original exact-map comparison. Only canonical CPython 3.12
  app/ops caches with source counterparts are now recognized. Every node must still
  pass ownership, mode, ACL, hardlink and mount checks. Cache paths appear in
  the result; originals remain intact. Read-only classification recognized all
  125 actual app caches and left exactly 528 inventory paths. Cache bytes are never trusted, executed,
  copied into code/, or silently deleted. Extra source/dependency files,
  destination caches, orphan caches and noncanonical caches still fail closed.
- **Trust inventory:** the offline builder produces exactly 127 code + 401
  dependency SHA-256 entries from a full reviewed Git commit and an independently
  authenticated dependency record. It ignores worktree edits, disables Git
  replacement objects and inherited Git environment/configuration, and checks
  Git object consistency. It refuses duplicate/invalid paths and incorrect record
  pins. A generated candidate requires independent provenance review; the tool
  does not manufacture trust from sandbox contents.
- **Probe acceptance:** the wrapper previously accepted any nonempty all-true
  JSON object. It now requires the entire exact named check set with true booleans.
  New probe checks cover expected primary GID, a distinct user namespace and
  read-only bind flags. `/proc/self/net` avoids a top-level proc compatibility
  dependency while retaining `ProcSubset=pid`.
- **Mounts:** migration and launcher now reject same-device bind mounts using
  mountinfo, in addition to cross-device rejection. Root-controlled ancestors,
  exclusive copies, empty evidence/output, private service-owned output and the
  fixed systemd sandbox remain mandatory. No ACL or permission relaxation was
  introduced. Root concurrency and the host runtime remain trusted assumptions.
- **Read-only diagnosis:** `audit.py` collects ACL locations and metadata without
  reading evidence/output contents, starting units or modifying files. It refuses
  symlink ancestors/source roots. Its FAIL/NOT_TESTED status is intentional.

## PASS/FAIL checklist

| Gate | Result | Evidence / remaining work |
|---|---|---|
| PR #70 and deployment review | PASS | Findings and fixes above |
| Cache preservation and integrity regression | PASS | Synthetic positive/negative tests |
| Independent inventory construction mechanism | PASS | Git/worktree/replacement-object and pin tests |
| Actual trusted 528-file inventory | FAIL | Manifest absence confirmed; 127 Git source matches verified; authenticated 401-entry dependency record needed |
| ACL migration safety design | PASS | Preserve existing tree; reviewed fresh layout proposed, no ACL removal automated |
| Read-only staged metadata/count audit | PASS | Existing read-only host-volume view inspected; findings below |
| Direct-host ACL identity/ownership/isolation audit | FAIL / NOT TESTED | Root-only namespace maps hide service identities; repeat direct-host audit |
| UID/GID, namespace, mounts, runtime and network enforcement | FAIL / NOT TESTED | Requires explicitly approved host synthetic probe |
| Repeated migration and verification | PASS locally / FAIL target | Synthetic inode-preservation/resume tests; two approved target passes required |
| Full repository tests | PASS | Frozen final code: 2,284 passed in 900.57 seconds |
| Final focused security tests | PASS | 51 tests (final focused run) |
| Both README sample modes | PASS | Clean environment; fictional legacy and discovery inputs only; outputs under /tmp |
| Shell syntax and whitespace | PASS | bash -n and git diff --check |
| Production evidence/trial authorization | FAIL / NOT AUTHORIZED | Separate review and explicit owner authorization required |
| Offline production readiness | FAIL | No production authorization inferred from development tests |

Validation used Python 3.12. The final full run included all final code and test
changes. An earlier post-change full run passed 2,277 tests; the final focused run
passed all 51 M78 security tests in 1.94 seconds. The initial long baseline overlapped
live edits: four old collected probe tests read the newer probe via runpy and failed
on obsolete arguments. That mixed run is not used as validation; the frozen 2,284-test
run above supersedes it. No code/tests changed during the frozen run.

The actual staged 126 application sources + one ops source + 401 dependency files
form the required 528 records. The additional 125 caches explain the reported 653
comparison entries. Matching counts and zero mismatches alone are not an independent
trust anchor. No candidate manifest or provenance attestation was fabricated.

## Observed read-only deployment blockers

- The data volume appears as `/dev/sda`, ext4, **ro,nosuid,nodev** in this session.
  It is not a writable installation context. No remount was attempted.
- Counts: app 251 files (126 `.py`, 125 `.pyc`); ops one `.py`; dependencies 401
  files (193 `.py`, **193 `.pyc`**, 15 other files). Dependency bytecode remains
  part of the exact independently authenticated 401-file inventory; the app-cache
  exception does not discard it. Wheel-only hashes cannot authenticate generated
  dependency bytecode without separate verified records or reproducible provenance.
- 703 inspected nodes have extended access ACLs. `/mnt/intelligenceos_data/arbitrage`
  is ACL-free in this view; its child `sandbox` and existing m78 tree have access
  ACLs. Representative directory ACLs grant traversal/read only to an unmapped
  named UID with group/other denied. No sampled default ACL was present; all
  inspected ACL-bearing paths remain rejected by the current tools.
- `/proc/self/uid_map` and gid_map each show only `0 0 1`. The account database
  identifies intelligenceos-m78 as UID 997/GID 986 with nologin; output is seen as
  65534:65534, mode 0700, and ACL named IDs as 4294967295. These are namespace-limited
  observations, **not proof of wrong host ownership or corrupt host ACLs**. Do not
  chown to mapped/overflow IDs. `pgrep` saw no service-UID process in this view;
  the host must independently confirm idleness.
- Evidence is root-owned 0700 without ACLs. A nonroot service cannot enumerate it;
  migration now refuses that precondition before copying. An approved fresh empty
  layout must provide explicit service read/traverse access (the conservative
  current preflight requires non-owner read/traverse); no chmod is automated.
- The visible runtime reports systemd 255.4-1ubuntu8.18, kernel 6.8.0-71-generic,
  and a unified cgroup hierarchy. No systemd unit or synthetic probe was invoked.
- All 127 staged sources match SHA-256 digests of Git blobs at merged commit
  `aa549e23a84d46edc4817833d7c8cf16badc927b` (Git objects checked; replacements
  disabled). This establishes the code portion independently of staging.
- The trusted manifest is absent. PR #69/#70 metadata and discussion contain no
  recoverable independently authenticated dependency inventory.

The smallest isolation-preserving ACL proposal is a **new** root-controlled tree
such as `/mnt/intelligenceos_data/arbitrage/m78-isolated` under the observed ACL-free
parent, preserving `sandbox/m78` in full. Confirm that parent and identities directly
on the host before approving it. A separately reviewed fixed-BASE update and fresh
installation from independently verified artifacts are required; current migrate.py
intentionally refuses the existing ACL tree. A sibling under `sandbox` would retain
the incompatible ACL ancestor and does not solve the problem.

## Remaining work, in order

1. Review/merge the preparation PR and install the reviewed tools on the host only
   under explicit server-change approval. Merely fetching/merging this PR does not
   authorize deployment or transient-unit execution.
2. Repeat the read-only audit below from a direct host shell, outside this root-only
   namespace. Review ACL **contents** locally
   for the reported paths with getfacl, volume mounts, root ownership, service UID/GID,
   idle-account status and Ubuntu/systemd/kernel support. Audit output alone cannot
   approve ACL remediation.
3. Recover the independently authenticated 401-entry dependency hash record.
   Use the independently matched source revision recorded above. Build and independently review the candidate manifest offline using the
   single command in [the deployment procedure](M78_DIGITALOCEAN_PROCEDURE.md).
   Install the approved manifest as root only under deployment approval.
4. Select the minimal ACL-safe installation from the actual audit. If shared ancestors
   have ACLs, the current fixed-BASE migration cannot pass. A fresh ACL-free parent
   and consistent reviewed fixed-path change may be required. Preserve the original
   sandbox. No recursive ACL stripping, automatic chown/chmod or silent relocation.
5. After explicit approval of the concrete ACL/layout action, use read-only preflight
   and then the single `deploy_verify.py --apply` migration/probe command. Repeat the
   approved apply once the transient unit is collected; retain two complete PASS
   reports and manifest/tool/runtime provenance. Any failed check remains a stop.
6. Separately review and authorize the offline trial, its evidence inventory and
   trial-specific verification. The current mandatory probe requires empty evidence;
   `launch.py run` cannot be treated as a ready production command. Keep production
   analysis and evidence staging outside this migration authorization.

Exact next command on the DigitalOcean host, from the reviewed updated repository
checkout (read-only; intentionally reports readiness FAIL):

```sh
sudo /usr/bin/python3 -B /root/IntelligenceOS-Arbitrage-M61/ops/m78_sandbox/audit.py
```

There is no safe mutation command to run yet: trust provenance and host ACL identities and remediation
are unresolved. The [updated procedure](M78_DIGITALOCEAN_PROCEDURE.md) contains the
inventory command, approval-scoped one-command migration/verification, preservation
rules and stop conditions. Further server inspection/remediation and the trial must
respect the owner's separate authorization boundaries.
