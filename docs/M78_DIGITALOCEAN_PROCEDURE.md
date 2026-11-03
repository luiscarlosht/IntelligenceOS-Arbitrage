# M78 existing DigitalOcean sandbox: approval-gated migration and verification

Status on 2026-11-03: **NOT READY / target enforcement NOT TESTED**.
This is the single procedure for the existing sandbox; it supersedes the empty-layout
installation steps in M78_SANDBOX_READINESS.md. Do not run prepare.sh on this sandbox.
No DigitalOcean sandbox paths were inspected or changed while preparing this update.
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
and private (0700); evidence/ must be root-owned. Both must be empty. The migration
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
| Actual staged inventory, ownership and ACL audit | Not accessed | NOT RUN |
| Production readiness | FAIL pending target validation and review | FAIL / NOT READY |

Development validation: 2,252 full-suite tests passed in 778.55 seconds; the final
focused suite separately passed all 34 current security tests (including tests added
after full-suite collection). Both documented sample modes, shell syntax and diff
checks passed. See follow-up PR #70 and M78_SANDBOX_READINESS.md. No server changes or production execution are authorized
by this document. Stop here for explicit approval of the above concrete procedure.
