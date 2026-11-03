# M78 isolated DigitalOcean installation

Status: **NOT READY**. This procedure supersedes the earlier existing-sandbox
migration procedure. Development and PR preparation are authorized. Installing
files on DigitalOcean, applying installation, and starting the synthetic unit
require separate explicit owner approval. Production evidence staging, M78
production execution, Amazon calls, M77 registry changes, ACL changes, service
restarts and reboot are outside this authorization.

## Fixed paths and preservation

The only runtime destination is:
`/mnt/intelligenceos_data/arbitrage/m78-isolated`.
The existing `/mnt/intelligenceos_data/arbitrage/sandbox/m78` is preserved in full.
Do not copy from it, traverse it for installation, strip its ACLs or change its
ownership. M76/M77 evidence, the M77 registry and production services are untouched.
A sibling beneath `sandbox` would inherit the incompatible ancestor boundary.

`install.py`, `launch.py`, legacy `migrate.py` and the default read-only `audit.py`
use the isolated destination. There is no destination CLI override. `prepare.sh`
now refuses all execution; split empty-layout preparation bypasses integrity checks.
The legacy migration utility remains for regression coverage but is not part of
this procedure. Use the wrapper and fresh installer below.

Host facts supplied for this preparation: the dedicated volume is mounted;
`/mnt/intelligenceos_data` and its `arbitrage` child are root-owned and ACL-free;
`sandbox` has an extended ACL; the new destination is absent and not a symlink;
intelligenceos-m78 has UID 997/GID 986. Recheck from the direct host context. The
root-only development namespace cannot establish host account mappings.

## Exact read-only host preflight

From the reviewed checkout, on the host, with no server mutation:

```sh
sudo /usr/bin/python3 -B /root/IntelligenceOS-Arbitrage-M61/ops/m78_sandbox/audit.py
```

This inspects destination ancestors and absence, account identity and processes,
namespace maps, mounts and systemd version. It does not traverse the old sandbox,
read production evidence, create directories or launch a unit. Overall FAIL and
NOT_TESTED are intentional: metadata cannot prove runtime isolation or dependency
trust. Review every issue and the actual account mapping; a zero process exit code
alone is not readiness. Symlinks, unexpected ACLs or inspection errors stop review.

## Dependency trust: new reviewed bytecode-free profile

Use [M78 dependency trust](M78_DEPENDENCY_TRUST.md) for the A/B comparison,
independent PyPI artifact authentication, exact SHA-256 pins, acquisition commands,
offline bundle construction, source revision and independent reproduction procedure.
The recommendation is B: openpyxl 3.1.5 and et_xmlfile 2.0.0 from approved purelib wheels,
with no compiled bytecode. The historical 401-file count is retired for fresh installs;
exact path/hash comparison remains mandatory. No sandbox hashes become trusted.

The new manifest explicitly identifies `m78-wheels-no-bytecode-v1`, the reviewed Git
source commit, exact approved wheel digests and complete file map. Old flat manifests
are refused without fallback. The builder deterministically copies raw wheel files
and committed sources; no pip installation, generated metadata or compilation occurs.
Every file is still required and hashed. The installer rejects bytecode even when
listed in a candidate manifest. Pins authenticate PyPI distribution bytes, not signed
publisher builds: these releases have no publisher attestations, and independent
review/acceptance of that trust anchor is required before adoption.

## Fresh installation design and approval-scoped commands

Only after the trust review, approve the exact tool revision, bundle, manifest and
server-change operation. Place the approved root-owned ACL-free bundle at
`/root/m78-approved-bundle` and approved manifest at `/root/m78-reviewed-sha256.json`
under that separate approval. Installing/updating the reviewed checkout also requires
server-change approval. Never source the bundle from the restricted sandbox.

All bundle and destination ancestors must be root-owned, free of group/world write,
ACLs and symlinks. All files must be regular, single-link files without special bits.
Unexpected nested mounts, including same-device binds, fail. Inspection errors fail
closed. The dedicated account must be idle; the operator must serialize all root
administration and account jobs. No jobs are killed automatically.

```sh
# Read-only artifact/destination preflight, after approved artifact placement:
sudo /usr/bin/python3 -B ops/m78_sandbox/deploy_verify.py \
  --manifest /root/m78-reviewed-sha256.json --bundle /root/m78-approved-bundle

# ONLY after explicit approval for server changes and the synthetic probe:
sudo /usr/bin/python3 -B ops/m78_sandbox/deploy_verify.py \
  --manifest /root/m78-reviewed-sha256.json --bundle /root/m78-approved-bundle --apply
```

Review PREFLIGHT_PASS before apply. The installer verifies the exact bundle inventory
and explicit bytecode-free profile, probe metadata, all existing destination files/directories, and free
space (missing bytes plus 256 MiB reserve) before mutation. It creates root-owned
0755 base/root/code/deps/evidence and private UID 997/GID 986 output (0700).
Only new output is chowned; existing metadata is never repaired. Source bytes are
copied exclusively to code/app, code/ops and deps, with mode 0444, fsync and digest
checks. Sources and destinations are rechecked afterward. No ACLs/xattrs or ownership
are inherited from source files. Runtime code, dependencies and evidence bind read-only.

An existing matching partial installation can resume; conflicting/truncated files,
nonempty evidence/output, unsafe metadata or unexpected entries stop without
overwrite. A second successful apply preserves file inodes. Empty systemd mountpoint
placeholders under root are allowed; payloads are refused. Publication is resumable,
not atomic or guaranteed crash-durable. Preserve any interrupted artifacts for review.
An interrupted output mkdir before chown may need separately approved remediation.

The wrapper starts only the fixed transient intelligenceos-m78-sandbox unit after
installation success. The probe requires the exact complete boolean check set for
UID/GID, user/network namespaces, loopback-only interfaces, routes, denied IPv4/IPv6
connections, capabilities, read-only binds, hidden host paths, dependency imports,
empty evidence and synthetic output read/write/delete. It does not execute M78.
Namespace failure has no host-process fallback. Keep PrivateUsers, PrivateNetwork,
IPAddressDeny and all other restrictions intact; never weaken them for a PASS.
Host runtime libraries and concurrent privileged administrators remain trusted.

Retain two complete approved apply/probe reports (repeat only after the transient
unit is collected), tool revision, manifest digest and runtime provenance. Synthetic
PASS still leaves production readiness pending owner review. `launch.py run` is not
an approved trial procedure: evidence staging and trial-specific checks require
separate review and authorization. No production readiness claim is made here.

Rollback under explicit approval may stop only the transient sandbox using
`sudo sh ops/m78_sandbox/rollback.sh`. It preserves all installation artifacts and
original trees. No persistent unit, production service restart, ACL removal, host
network change, reboot or automatic cleanup is part of this installation.

## Development validation for this preparation

Python 3.12.3: 2,310 full-suite tests passed in 740.98 seconds with final code/tests
held fixed. All 77 focused security tests passed, both fictional README sample modes
passed in a clean environment with /tmp outputs, and shell syntax/whitespace checks
passed. These results do not authenticate dependencies or establish target isolation.
