> Superseded for deployment by [the isolated installation procedure](M78_DIGITALOCEAN_PROCEDURE.md). Historical preparation instructions below must not be executed.

# M78 sandbox security readiness — 2026-11-02

Existing-sandbox migration procedure: [M78_DIGITALOCEAN_PROCEDURE.md](M78_DIGITALOCEAN_PROCEDURE.md).
Its approval-gated instructions supersede the empty-layout installation plan below.

Decision: **FAIL / NOT READY for production** until target verification and review.
No production M78 execution, evidence staging, credential access, API replay,
registry changes, deployment, service/network changes or reboot performed.

## Diagnosis

Observed here: `unshare --net -- sh -c 'readlink /proc/self/ns/net; ls /sys/class/net'`
exits 1: `unshare failed: Operation not permitted`. The execution environment
restricts namespace creation even though its effective UID is root. The process lacks effective CAP_SYS_ADMIN (required for this operation) and
has seccomp filtering enabled (mode 2). The seccomp policy itself was not read;
the missing capability is sufficient to explain this development refusal.

The previously reported host interface names alone do not prove that unshare
succeeded or failed. A network namespace does not automatically replace the
inherited sysfs mount; `/sys/class/net` can describe the host namespace. Other
possible causes include running the interface command outside unshare or ignoring
its failure. Original command, exit status and namespace identities are missing,
so the original cause remains **unresolved**, not diagnosed as a confirmed leak.

The probe compares host and child `/proc/self/ns/net` identities, enumerates live
interfaces via socket.if_nameindex (netlink), inspects IPv4/IPv6 routes and attempts
bounded IPv4/IPv6 TCP connections. Every check must pass. The systemd launcher
adds PrivateNetwork and IPAddressDeny=any; unsupported settings, namespace setup
failure, probe failure and invalid staging all prevent analysis. There is no
fallback to a host process. Probe connections occur only inside the proposed
sandbox; this work has not executed those connections.

## Boundary and limitations

`ops/m78_sandbox/launch.py` requires root to establish the sandbox, but fixes the
payload UID/GID to the dedicated non-login service account, clears supplementary
groups/capabilities and environment, and denies privilege escalation and namespace
creation. No arbitrary payload or host path arguments are accepted. Systemd
creates fresh namespaces with only stdio pipes inherited.

An empty RootDirectory exposes only read-only Ubuntu runtime trees `/usr`, `/lib`,
optional `/lib64`, staged code/dependencies/evidence, the synthetic probe, private
devices and filtered proc. `/output` is the sole persistent writable bind. Root
filesystem writes are denied by ProtectSystem=strict. Runtime files under `/usr`
are intentionally readable; the runtime must be reviewed for locally stored
secrets before approval. Device/proc pseudo-files are kernel-managed exceptions
to the persistent-write restriction. No host /etc, /home, /root, /mnt, /opt,
/run or /var tree is bound. Production evidence/DBs outside the staged tree are
unreachable. Root operators and other processes with the same service UID remain
outside this threat model: keep this UID dedicated with no concurrent jobs.

Staged trees and their ancestors must be root-owned, not group/world-writable,
and symlink-free. Output must be private and service-owned. Existing externally
verified SHA-256 counts supplied in the task have **not** been independently
reverified here. Before installation, review a signed/offline manifest covering
all staged files, reject unexpected files and verify dependency versions. This
launcher validates permissions, not artifact provenance. No production staging is
authorized by this PR.

## Deployment plan (requires separate explicit DigitalOcean approval)

1. Review this PR; confirm Ubuntu 24.04 systemd and Python 3.12, dedicated mounted
   volume, non-login intelligenceos-m78 account and absence of concurrent jobs.
2. Review existing sandbox layout without reading production evidence. Do not run
   prepare.sh over the existing m78 directory: it deliberately refuses overwrite.
   Approve migration/archival of that directory separately if necessary.
3. `sh ops/m78_sandbox/prepare.sh` creates an empty layout only. It does not install
   packages, change accounts or stage application/evidence. Stage reviewed code
   and pinned dependency artifacts as root with no symlinks and read-only modes.
   Copy only synthetic fixtures into evidence for validation. Install probe.py
   root-owned, mode 0444. Verify manifests and ancestors; code/deps/evidence must
   contain readable files. Keep root/ empty and output/ private, service-owned.
4. `sh ops/m78_sandbox/verify.sh` must exit zero and print every result true.
   Capture JSON, kernel/systemd versions and staged manifest hashes as review
   evidence. Failure is a stop condition; never relax sandbox properties to pass.
5. On a disposable synthetic staging layout, test refusal of writable code,
   symlinked evidence, missing stage, wrong output ownership, and invocation as
   the service user. Each must exit nonzero before payload execution. Restore
   root-owned verified staging after each case. Test a second successful probe.
6. Review effective systemd restrictions and UID, confirm no external interfaces,
   no routes, denied connections, denied writes and hidden host paths. Exercise
   full M78 only with separately reviewed synthetic inputs, under separate
   authorization; `launch.py run` uses fixed evidence names and /output/report.
   It first executes verify and refuses existing report destinations via M78.
7. Production execution/evidence staging require separate explicit authorization
   even after all security checks pass. No production command is part of this plan.

Rollback: `sh ops/m78_sandbox/rollback.sh` stops only the dedicated transient unit.
If already collected, systemctl may return nonzero: confirm unit absence. No host
network restoration is needed. Retain staging/output for review; do not recursively
remove evidence or reuse a partially written output. No production services change.

## Explicit results

| Check | Result |
|---|---|
| Development namespace creation | FAIL: EPERM; no isolation claim |
| Original host-interface incident root cause | UNRESOLVED: original execution evidence absent |
| Launcher configuration and staging negative tests | PASS: 7 tests |
| Full baseline suite, Python 3.12.3 | PASS: 2,233 tests in 730.36 seconds |
| Both README sample modes (synthetic/offline) | PASS |
| Target namespace/interface/route/connect checks | NOT RUN — required |
| Target UID, read-only mounts, hidden host paths, output checks | NOT RUN — required |
| Target malformed-stage refusal tests | NOT RUN — required |
| Staged artifact hashes and dependency inventory | NOT REVERIFIED — required |
| Production readiness | FAIL pending target evidence and review |

Validation completed 2026-11-03 UTC: `.venv/bin/python -m pytest -q`
passed 2,233 baseline tests (collected before the new test file existed).
`.venv/bin/python -m pytest -q tests/test_m78_sandbox.py` separately passed
all seven new tests. Both README sample modes, shell syntax checks and
`git diff --check` passed. Development unit tests validate construction and
refusal logic; they do not verify kernel enforcement.

Review PR: https://github.com/luiscarlosht/IntelligenceOS-Arbitrage/pull/69.
No merge or deployment was performed. The branch was published through the
connected GitHub integration because local Git push could not resolve github.com;
local and remote commit histories differ but the proposed file contents match.


## Existing-sandbox deployment preparation — 2026-11-03

Added read-only preflight and an explicit --apply migration preserving the original
app/, ops/ and dependencies/ trees. It requires the independently trusted original
SHA-256 inventory, checks ownership/modes and extended/default ACLs, rejects unsafe
links and conflicts, refuses nonempty evidence/output, and verifies copied artifacts.
The wrapper runs only migration and the synthetic security probe, prints a JSON
readiness report, and never invokes M78. The probe now supports empty evidence and
checks pinned dependency imports. Root mountpoint placeholders may survive repeated
verification; payload files there are rejected. No target sandbox paths were accessed
or changed in this preparation. DigitalOcean remains NOT TESTED / NOT READY.

Development validation of this update: 34 focused tests passed, including migration
idempotence and negative cases, plus wrapper failure gates. UID and ACL test cases
simulate unsafe metadata; they do not verify kernel enforcement. Both sample modes
passed. The full suite passed 2,252 tests in 778.55 seconds. It collected the initial
migration tests before the later additions; the final focused suite separately
passed all 34 current security tests. Shell syntax and diff checks passed.
Follow-up review: https://github.com/luiscarlosht/IntelligenceOS-Arbitrage/pull/70.

The probe now stops before creating any socket if UID, namespace, interface or
route checks fail. Four additional tests assert this gate with socket creation
forbidden. This closes a gap in the earlier probe, which recorded failures but
could continue to diagnostic connection attempts. No such probe was run on target.
