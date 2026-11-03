# M78 existing DigitalOcean sandbox: approval-gated migration and verification

Status on 2026-11-03: **NOT READY / target enforcement NOT TESTED**.
This is the single procedure for the existing sandbox; it supersedes the empty-layout
installation steps in M78_SANDBOX_READINESS.md. Do not run prepare.sh on this sandbox.
SSH was denied socket creation, but the existing read-only data-volume view was
inspected. This session maps only UID/GID 0; output ownership and named ACL IDs
require direct-host verification. No server change was made.
No production M78 analysis, production evidence staging, API use or production service
changes are part of this procedure.

## Approval boundary

Review this migration PR and the exact revision to install (the original launcher
was introduced in PR #69). Obtain explicit owner approval
**before installing/updating tools on DigitalOcean, applying migration, or starting
the transient verification unit**. Approval must cover only this migration and
synthetic security probe. It does not authorize production evidence or analysis.
Do not use `launch.py run`; the current probe deliberately requires empty evidence.

Before approval, development validation uses only pytest temporary synthetic trees.
The migration CLI defaults to a read-only preflight. The wrapper without --apply
also performs preflight only: it neither migrates nor starts a unit. Merely having
an --apply option is not approval to use it.

## Preconditions and trusted inventory

The existing volume must be mounted at `/mnt/intelligenceos_data`. The fixed sandbox
path is `/mnt/intelligenceos_data/arbitrage/sandbox/m78`; there is no CLI override.
The dedicated intelligenceos-m78 UID and primary GID must be nonzero, with a
nologin/false shell. No processes may be running under that UID; the migration
refuses an active account and never kills jobs. The operator must prevent concurrent
root administration and service-account jobs throughout the procedure.

Require root ownership and no group/world write on sandbox ancestors, original
app/, ops/, dependencies/, and all their contents. Require output/ to be service-owned
and private (0700); evidence/ must be root-owned and allow non-owner read/traverse for the empty probe. Both must be empty. The migration
rejects any nonempty evidence or output directory before reading their file contents,
and does not rename, delete, chmod, chown or copy anything in those directories.
If a check fails, stop for review; do not run recursive chown/chmod or remove ACLs.

All inspected nodes must be regular files or directories: no symlinks (even internal
ones), file hardlinks, special permission bits, device nodes, FIFOs, cross-device nested mounts,
or extended/default POSIX ACLs. ACL checks use listxattr on every node and ancestor;
inspection errors fail closed. This deliberately conservative policy rejects even
an apparently restrictive extended ACL; any remediation needs separate review.

Supply an independently reviewed **existing verification record** as a root-owned,
non-writable JSON manifest, for example `/root/m78-reviewed-sha256.json`. Its ancestors
must also pass the security checks. The object maps each original relative file path
to its lowercase SHA-256 digest, e.g. `app/m78.py`, `ops/m78_offline.py`,
`dependencies/openpyxl/__init__.py`. It must enumerate exactly 127 Python files in
app/ plus ops/, and 401 dependency files. Use the previously trusted SHA-256 records;
if they need conversion, review that conversion offline. Do not regenerate a trusted
manifest from the current staging tree, and do not include any evidence paths.
Missing records, missing/extra files, wrong counts or changed digests are stop conditions.
Exception: canonical app/ops `__pycache__/<source>.cpython-312[.opt-1|.opt-2].pyc`
files with an existing source counterpart are metadata-checked, listed explicitly in
`preserved_untrusted_caches`, preserved in place and excluded from all runtime copies.
Their contents are untrusted and never executed. Orphan, legacy, foreign-version or
noncanonical caches are refused. Dependencies still require an exact inventory.
The script does not assume reported counts prove integrity. Preflight also requires
space for all missing copies plus a fixed 256 MiB free-space reserve; lack of space
is a stop condition. The CLI uses umask 022 for new directories and mode 0444 for
copied files; existing permissions are never silently repaired.

Install the reviewed repository revision/tool files as root without exposing any
credentials or evidence. The reviewed probe must be root-owned, regular, not writable
by group/other, without ACLs or hardlinks. Stage no additional dependencies from the
network: the existing pinned dependency tree is preserved and verified.

## One approved deployment and verification sequence

Run from the reviewed repository checkout in a direct DigitalOcean host SSH shell
(not a container), only after approval.
The commands use the system Python 3.12 on Ubuntu 24.04; no packages are installed.

```sh
# Read-only preflight; no unit or directory creation:
sudo /usr/bin/python3 ops/m78_sandbox/deploy_verify.py \
  --manifest /root/m78-reviewed-sha256.json

# ONLY with explicit approval for server changes and the synthetic probe:
sudo /usr/bin/python3 ops/m78_sandbox/deploy_verify.py \
  --manifest /root/m78-reviewed-sha256.json --apply
```

Preflight must return zero and report PREFLIGHT_PASS. Review it before using --apply.
The wrapper prints a JSON readiness report; capture stdout and the command exit status
in the operator's approved audit location. Do not commit generated reports. A failed
step returns nonzero, reports FAIL, and does not proceed to the next step. No command
in the wrapper executes M78 or stages evidence. If the wrapper reports migration
refusal, run migrate.py with the same manifest **without --apply** to see the reason;
inspect permissions/ACLs and trusted records rather than bypassing the check.

Migration creates root/, code/app/, code/ops/, deps/ and probe.py. It copies originals
into the new layout with exclusive file creation, root ownership and mode 0444, then
checks original and destination hashes and security metadata again. Originals remain
unchanged in app/, ops/ and dependencies/. Existing destination files are reused only
when every hash matches; no existing file is overwritten. An existing different probe
is a stop condition, including after a tool upgrade. Agree on any replacement separately.

A repeated successful apply preserves all original and destination inodes. Matching
partial copies can resume; a truncated or differing file after interruption stops the
procedure rather than being replaced. This is recoverable, not an all-or-nothing
transaction. Files are fsynced, but the procedure does not claim crash-durable directory
publication. Keep partial artifacts for review. Empty mountpoint directories and an
empty probe.py mountpoint in root/ are allowed after systemd verification; payload
files, symlinks and unsafe metadata there are refused. root/ is never populated with
host configuration, databases or credentials by migration.

## Synthetic target checks and pass criteria

The wrapper starts only the fixed transient intelligenceos-m78-sandbox.service.
It uses the non-root account, empty capability sets, NoNewPrivileges, read-only
system mounts, a restricted root filesystem, dedicated writable output, PrivateNetwork,
and IPAddressDeny=any. No host networking or production service configuration changes.
It does not fall back to a host process if systemd or a namespace operation fails.

The probe must exit zero and report every boolean true:

- The payload runs as the expected non-root UID; no effective capabilities or privilege escalation.
- Its network namespace identity differs from the invoking host context. Socket-based
  interface discovery shows only loopback; IPv4 has no routes and IPv6 has no external routes.
- Bounded TCP attempts to fixed public IPv4 and IPv6 destinations are denied. No DNS,
  Amazon API, external listener or production endpoint is used. These connection attempts
  occur only inside the private namespace; namespace creation failure prevents probe startup.
- Verified code files can be read; pinned openpyxl 3.1.5 and et_xmlfile 2.0.0 import.
  Evidence can be enumerated but remains empty. A uniquely named synthetic output
  can be written/read/deleted. No report generation or M78 import/execution is required.
- Writes to application, dependencies, evidence, runtime, root and tmp fail; host home,
  mount, opt, credential-file, run and var paths are absent, inaccessible or empty placeholders.
  Runtime /usr and library paths are intentionally readable; review them for locally
  stored secrets before approval. Kernel proc/device pseudo-files are exceptions to
  the persistent-write rule. Same-UID concurrent processes and privileged root operators
  are outside the boundary, hence the idle-account requirement.

Never use /sys/class/net alone to verify isolation: it may retain the host sysfs view.
Namespace identity, live interface discovery, routes and denied connections must all
agree. Development unshare EPERM is not a passing test and does not prove how the
host service manager behaves.

After success, review the JSON report, tool revision, trusted manifest digest and
Ubuntu/kernel/systemd versions. The wrapper reports target_security PASS but leaves
production_readiness PENDING_OWNER_REVIEW. It never grants production authorization.
Repeat the approved sequence to demonstrate idempotence and a second passing probe.
If the probe or JSON parsing fails, production_readiness remains FAIL. Do not remove
security properties or relax assertions to obtain a pass.

## Rollback and stop conditions

If necessary under the same explicit approval, stop only the transient sandbox:

```sh
sudo sh ops/m78_sandbox/rollback.sh
```

An already collected unit may produce a nonzero stop result; verify its absence.
Do not stop unrelated services. No persistent unit is installed and no host firewall,
routes or interfaces change. Rollback leaves original artifacts, evidence, output
and any new copies in place. Do not automatically delete partial copies or replace a
conflicting probe. Further cleanup or ownership/ACL corrections need a reviewed,
explicitly approved action. No reboot is required.

## Readiness report

| Gate | Development result | DigitalOcean result |
|---|---|---|
| Migration/check-only/idempotence/partial resume | PASS: synthetic temporary layouts | NOT RUN |
| Hash drift, extras, conflicts, evidence/output refusal | PASS: synthetic negative tests | NOT RUN |
| Symlinks/hardlinks/permissions/UID/ACL refusal | PASS: synthetic tests; UID/ACL cases simulated | NOT RUN |
| Wrapper stops after migration/probe failure, no analysis | PASS: mocked subprocess tests | NOT RUN |
| Namespace/interfaces/routes/connectivity/UID/mount enforcement | NOT VERIFIED in development | NOT RUN |
| Actual staged metadata/ACL audit | Read-only namespace view; see final report | Direct-host identity verification required |
| Production readiness | FAIL pending target validation and review | FAIL / NOT READY |

Development validation: 2,252 full-suite tests passed in 778.55 seconds; the final
focused suite separately passed all 34 current security tests (including tests added
after full-suite collection). Both documented sample modes, shell syntax and diff
checks passed. See follow-up PR #70 and M78_SANDBOX_READINESS.md. No server changes or production execution are authorized
by this document. Stop here for explicit approval of the above concrete procedure.


## Final readiness follow-up (2026-11-03)

Final frozen validation: **2,284 full-suite tests passed in 900.57 seconds**,
51 focused security tests passed, both sample modes and syntax/diff checks passed.
This preparation supersedes the earlier validation totals above; see
[M78_FINAL_READINESS.md](M78_FINAL_READINESS.md). PR #70's exact-inventory policy
would reject the reported 125 extra application caches before copying anything.
The cache exception above preserves all originals and never copies bytecode into
code/. Python runs with `-B`, a clean environment and no user site packages.
A destination cache is still an unexpected file and is refused.

### First command on return: read-only diagnosis

From the reviewed updated checkout on the DigitalOcean host:

```sh
sudo /usr/bin/python3 -B /root/IntelligenceOS-Arbitrage-M61/ops/m78_sandbox/audit.py
```

This prints metadata/ACL locations, original file counts, account details, volume
mounts and systemd version. It does not enumerate evidence/output contents, hash
production evidence, stage files or start services. FAIL/NOT_TESTED is intentional:
an audit is not a synthetic enforcement test. Preserve stdout in an approved private
audit location. No dependency downloads, ACL repairs or execution are hidden in it.

### Establishing the 528-entry trust inventory

Do this offline on the development/review machine. `inventory.py` reads committed
Git blobs (replacement objects disabled, inherited Git settings cleared, object
consistency verified) for all 126 app Python sources and only ops/m78_offline.py at an explicitly
reviewed **full commit SHA**, not the current worktree. The source revision must be
the revision independently established by the original staging records; the newest
tool revision may differ. It combines these with exactly 401 `dependencies/...` to
SHA-256 mappings from a separately authenticated dependency verification record.
Its record digest must come from that authenticated record's original review,
not a digest newly calculated from the sandbox or a modified record. Duplicate
keys, traversal, wrong counts and mismatching record digests fail closed.

```sh
.venv/bin/python -B ops/m78_sandbox/inventory.py \
  --source-commit aa549e23a84d46edc4817833d7c8cf16badc927b \
  --dependency-record "$INDEPENDENT_DEPENDENCY_RECORD" \
  --dependency-record-sha256 "$AUTHENTICATED_RECORD_SHA256" \
  --output /tmp/m78-candidate-sha256.json
```

The two dependency variables are required provenance inputs, not values to guess.
The source commit above was independently confirmed against the merged PR and all
127 staged sources match its Git blobs. A different source revision requires review. The builder
never reads staging and creates its output exclusively. Its output is a candidate,
not self-authenticating proof: independently review the commit's origin, the record's
origin, all paths and the emitted manifest digest. Preserve the original records and
review attestation. Only after review and server-change approval install the exact
candidate as root-owned /root/m78-reviewed-sha256.json without ACLs/group/world write.
The manifest is absent today. The 127-source commit was independently verified, but
no independently authenticated dependency record was found in this development run. Therefore no trusted manifest
has been fabricated. If records are irrecoverable, separately approve a new, pinned,
offline reconstruction from authenticated source/wheel artifacts and compare all
528 files before adoption; file counts or the earlier 653-file comparison alone
cannot authenticate a new inventory. Never bootstrap trust from sandbox hashes.

### ACL migration decision: preserve the existing tree

The audit must first establish every access/default ACL on ancestors and originals.
No permissive ACL allowlist or automatic setfacl/chmod/chown operation is introduced.
Even restrictive extended ACLs remain rejected by migration and launcher. Read-only inspection found 703 ACL-bearing nodes, including the shared `sandbox`
ancestor. Sampled ACLs grant only named-user read/traverse and no group/other access;
named IDs are unmapped in this root-only namespace. Host identity verification is
required before choosing remediation. No sampled default ACL was present.

If ACLs are confined to disposable new directories, an approved operator may create
a fresh sibling layout under an already ACL-free, root-controlled parent, with
explicit 0755 root-owned code/deps/evidence directories and a 0700 service-owned
output directory. Copy **only** manifest-authenticated bytes using exclusive file
creation, without preserving ACLs/xattrs/ownership from the source; never copy
excluded app/ops bytecode or evidence/output. The 193 dependency caches remain
part of the exact independently authenticated dependency inventory. Review every inherited ACL and mount before use.
Keep the original sandbox intact for rollback. This is a proposed replacement
installation, not an option silently enabled by migrate.py: the launcher has a
fixed BASE, so changing that path or promoting a replacement requires a separate
reviewed deployment patch and explicit server-change authorization.

If any shared ancestor has an ACL, a sibling beneath it will not satisfy the current
policy. Choose a reviewed ACL-free parent on the dedicated volume and revise the
fixed BASE consistently, or approve a narrowly scoped ancestor ACL change after
reviewing every affected consumer. Do not move shared paths, strip ACLs recursively,
relax ancestor checks or mutate the existing tree to force a passing result.
The read-only view identifies `/mnt/intelligenceos_data/arbitrage` as ACL-free, so
a fresh `/mnt/intelligenceos_data/arbitrage/m78-isolated` is the smallest proposed
replacement path. Confirm it and UID/GID mappings directly on the host first. The
existing root-owned 0700 evidence directory also blocks nonroot enumeration;
preflight now refuses it before copying. No permissions are changed automatically.
The approved fresh empty evidence directory must support service read/traverse;
the current conservative preflight requires non-owner r+x. Never apply that policy
to existing production evidence without separately reviewing isolation and approval.

### Enforcement and repeated execution review

- Same-device bind mounts are now rejected using /proc/self/mountinfo in addition
  to device checks. Cross-device mounts, symlinks, hardlinks and ACLs remain refused.
- PrivateUsers=yes is retained. systemd maps root and the configured service UID/GID
  to themselves; do not substitute container UID mappings or chown data to nobody.
  The probe now checks expected GID and a user namespace distinct from the caller.
- RootDirectory and read-only binds remain fixed. The probe checks mount flags for
  /app, /deps, /evidence and /usr as well as denied writes. Host /usr and libraries
  remain part of the trusted computing base and need a local secret review.
- Route inspection uses /proc/self/net, compatible with ProcSubset=pid. PrivateNetwork,
  IPAddressDeny=any, empty capabilities and all namespace restrictions remain enabled.
  Unsupported kernel/systemd/cgroup features must fail target verification; never
  remove properties or use a host-process fallback.
- The wrapper requires the exact complete named probe check set, with actual JSON
  booleans true. A partial all-true response is now refused.
- Keep the service UID idle, prevent concurrent root changes, and serialize every
  audit/migration/probe. A fixed transient unit name refuses conflicting active
  executions; do not kill an existing job automatically. After a successful apply,
  repeat the same approved --apply command only after the unit is collected.
  Preserve original/destination inodes and verify a second complete probe PASS.
- Empty mountpoint placeholders created by systemd remain supported. Interrupted
  mismatching copies and probe upgrades still stop for review without overwrite.
- `launch.py run` is **not a ready trial procedure**: its mandatory probe requires
  empty evidence. A separately reviewed evidence inventory, bounded read-only
  mounts, trial-specific checks and explicit offline-trial authorization are still
  required. No production readiness PASS can be claimed from synthetic checks.

After the trust inventory and the ACL deployment decision are reviewed and approved,
the smallest existing mutation command remains the single `deploy_verify.py
--manifest /root/m78-reviewed-sha256.json --apply` invocation above. It combines
migration and synthetic verification, never the production trial. There is no safe
one-command bypass for the presently missing trust records or unreviewed ACLs.

Reference: [systemd execution environment, version 256](https://www.freedesktop.org/software/systemd/man/256/systemd.exec.html)
documents UID mappings, root-relative bind destinations and proc namespace options.
Target Ubuntu/systemd behavior still requires the approved synthetic host test.
