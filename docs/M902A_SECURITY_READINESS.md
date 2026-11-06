# M90.2a security hardening and production readiness assessment

## Executive summary

The broker has been hardened and remains **offline-only, not production-ready**.
Exact nested contracts, descriptor-relative storage, single-snapshot credential
parsing and single-snapshot historical ledger validation replace permissive or
race-prone broker operations. The two-request accounting model and independent
claim are preserved. No new live launcher, approval or production claim exists.

Read-only inspection was performed on the deployment filesystem visible to this
session on 2026-11-06. `/etc/hostname` reports `luiscarlosht-ubuntu-2gb`; Ubuntu
reports 24.04.4 LTS. No SSH, DNS, TCP, TLS or HTTP connection was made. The supplied
server address `137.184.180.155` was not independently checked: network interface
inspection was denied. Findings below describe the visible filesystem, not an
assertion of unrestricted host access.

The session is sandbox UID 0 with UID/GID maps `0 0 1`. Host non-root owners are
reported as overflow UID/GID 65534. `getent` reports the application account as
UID 999/GID 987 with `/usr/sbin/nologin`, but that does **not** identify every
65534-owned object. Systemd and firewall netlink inspection are denied. Ledger
ancestry and the protected credential file cannot be traversed. Inspection stopped
at these boundaries; no sudo, namespace escape, alternative mount, permission
change or credential read was attempted.

## Security findings by severity

| Severity | Finding | Disposition |
| --- | --- | --- |
| High | Seller evidence accepted extra fields and incompletely typed nested values | Fixed: exact field sets, identifiers, hashes, booleans, references and timestamps |
| High | Credential hash check and parsing reopened the pathname independently | Fixed: bounded descriptor snapshot is hashed and parsed once |
| High | Broker reads/claims/ledger writes relied on pathname validation followed by pathname I/O | Fixed for broker: component-wise O_NOFOLLOW directory opens, retained descriptors, identity checks and relative atomic persistence |
| High | Ledger hash and parsing used separate reads | Fixed: `history_bytes` validates the exact descriptor snapshot, including complete pinned history |
| High | Installed legacy Amazon runners can bypass account/authoritative accounting locks | Open: inventoried below; no installed code or launch permissions changed |
| High | Ledger ancestry and credential directory do not satisfy root-owned full-chain policy in this namespace | Open: fail closed; host ownership/ACL and filesystem remediation review required |
| High | Installed source directories/files are group writable | Open: unsuitable for a privileged immutable release; actual group membership/exploitability not established |
| High | Production ledger integrity/current budget cannot be verified through available access | Open: no execution readiness claim; existing-lock-only host preflight required |
| High | Running-release attestation and authenticated IPC launcher do not exist | Open: policy commit string remains a binding, not evidence of running source identity |
| Medium | Host firewall, actual runtime unit state and concurrent manual processes are unobservable | Open: host operator read-only assessment required |
| Medium | Root compromise, simultaneous ledger/claim rollback, privileged writers ignoring locks | Trust-model limitations; retain independent claims and operator audit records |
| Medium | Python cannot guarantee memory zeroization or erase exception-frame copies | Process isolation/exit and sanitized diagnostics required; no raw traceback to requester |

`m90` and `m901` legacy execution APIs remain manual seams with their original
approval-string and pathname assumptions. They are not substitutes for broker
approval or the future launcher. Their live use must be denied by the future
launch policy. No backward-incompatible live entry point was introduced.

## Changes implemented

- `app/m902_contract.py`: exact approval, binding and seller evidence schemas.
  No extra fields in any specified object. Duplicate keys, nonfinite JSON,
  nonobjects, oversized documents (>65536 bytes), arrays where scalars are
  required, boolean integers, invalid hashes, malformed aware timestamps,
  invalid identifiers and empty/whitespace/control-character references fail.
  Seller IDs are 1–32 uppercase ASCII alphanumerics; application/reviewer/approver
  identities are bounded ASCII identifiers. References are printable, trimmed,
  nonempty strings of at most 2048 characters. Timestamps use explicit ISO date,
  `T`, seconds and UTC/offset; dates and naive timestamps are rejected.
- `app/m902_storage.py`: opens every directory component with O_DIRECTORY,
  O_NOFOLLOW and O_CLOEXEC; compares opened inode/device to the named component;
  retains descriptors through execution. Production anchor must be `/`; test
  anchors are synthetic private directories. Full protected ancestry must be
  broker-owned and not group/other writable; containing directories remain 0700.
- Files are opened relative to pinned directories with O_NOFOLLOW, O_NONBLOCK,
  O_CLOEXEC and O_NOATIME. Owner, mode 0600, single-link regular-file type,
  identity and stable read metadata are checked. Bounded read loops reject
  overflow. Directory edges and held lock names are rechecked before dispatch.
- Claims use relative exclusive creation; ledger replacement uses a relative
  exclusive temporary file and rename within the pinned directory. File and
  directory fsync remain mandatory. Unexpected ledger content changes are
  rejected before replacement. Descriptor-relative cleanup cannot be redirected
  into a substituted directory. A directory replacement during rename can leave
  an update in the original pinned directory, but causes a stop before the next
  request; it cannot redirect the write into the replacement directory.
- `m89_deployment.parse_configuration` parses bounded bytes; existing path-based
  configuration behavior delegates to it. Broker parses exactly the bytes whose
  credential digest was approved, without reopening the credential pathname.
- `m88_state.validate_ledger` validates an already-read object. `m90.history_bytes`
  pins and validates a single historical snapshot, including the entire original
  twelve-attempt canonical prefix and successful thirteenth authentication.
  Legacy callers retain their APIs. The broker uses only descriptor reads.
- Public broker execution still returns only the existing static allowlisted
  result or `STOPPED_NO_RETRY_OPERATOR_REVIEW_REQUIRED`, with no raw exception
  diagnostics. Requester remains a fixed-message encoder with no privileged
  imports, paths, transport selection or execution capability.

A pinned directory descriptor does not excuse an untrusted ancestor: ownership
validation is retained. Nor does it prevent an adversarial privileged process
from editing an inode in place. Root is trusted, and cooperative writers must
obey the same locks. Mount namespaces and root-controlled imports also require
review before deployment. No filesystem rule is relaxed to fit production.

## Read-only production inventory: scope and limits

Inspected static unit definitions, enablement symlinks, file metadata, ACL xattr
presence (not ACL values containing identities), installed source code, interpreter
symlink targets, dependency metadata and bounded launch-reference scans. Content
reads of deployed Python/dependency files used O_NOATIME; no deployed module was
imported or executed. No environment-file contents, credential digest or protected
seller/application identifiers were read or emitted.

Launch-reference scans covered `/etc/systemd/system`, `/usr/lib/systemd/system`,
`/etc/cron.d`, periodic cron directories including yearly, `/etc/init.d`,
`/usr/local/bin`, `/usr/local/sbin`, `/root/.config/systemd/user`, `/etc/sudoers.d`
and `/etc/crontab`. Matches were limited to the offline project service/timer.
Root and application crontab files were absent at their conventional paths.
No project sudo rule was found in readable `/etc/sudoers` or its drop-in directory;
base sudo configuration includes env_reset and secure_path. `/usr/bin/sudo`
exists, root-owned, mode 4755. **Sudo was not invoked.**

This does not prove absence of launch paths in inaccessible account homes,
external orchestration, alternate scheduler locations, shells, running manual
sessions or scripts outside the inspected locations. Application-home user units
are unobservable because `/var/lib/intelligenceos-arbitrage` is inaccessible.
Any installed Python module can also be invoked by an authorized operator with
an interpreter; absence of a matching service is not prevention.

### Installed Amazon writer matrix

Release aliases used below:

- V02: `/opt/intelligenceos-arbitrage/releases/68230d3fdaef588bb7ba5c8340f49a473e8386b7`.
- M89: `/opt/intelligenceos-arbitrage/releases/6a09b7a503906fa3fd96eae1ea9472d15859865f`.
- M90: `/opt/intelligenceos-arbitrage/releases/cb1125613fd7a18a991519ee251c577c578a855a`.

Each module below is an observed `<release>/app/<name>.py` installed file.
Account means the shared account flock; ledger means authoritative JSON ledger
flock, not SQLite transaction locking. Manual invocation uses the invoking
identity, not an intrinsic service identity. Actual current manual execution is
unknown. Installed copies were statically checked without execution.

| Installed path/module | Release | Trigger / identity | Account lock | Authoritative ledger lock | Concurrent broker risk / required remedy |
| --- | --- | --- | --- | --- | --- |
| `amazon_pilot.run_pilot` | M89, M90 | Manual CLI / invoker | No | No | Uncoordinated; retire launch permission or route through reviewed broker |
| `amazon_details.run_details` | M89, M90 | Pilot details action / invoker | No | No | Same; includes operations outside new broker scope |
| `amazon_pricing_diagnostic.run_pricing_diagnostic` | M89, M90 | Pilot pricing actions / invoker | No | No | Same; pricing is not broker-allowlisted |
| `amazon_candidates.execute` | M89, M90 | Direct candidates CLI / invoker | No by default | No | Direct invocation bypasses optional search guard; prohibit it |
| `amazon_candidate_enrichment.execute` | M89, M90 | Manual enrichment CLI / invoker | No | No | Pricing/fees/restrictions outside scope; prohibit direct invocation |
| `candidate_execution.execute_details`, `execute_research` | M89, M90 | Manual CLI / invoker | No | No | SQL operation claims do not serialize account requests; prohibit or repair |
| `candidate_recovery.run` | M89, M90 | Manual recovery CLI / invoker | No during run | No | Preparation lock is insufficient; delegates to research; prohibit or repair |
| `stored_candidate_search.run` | M89, M90 | Manual CLI / invoker | Yes through Reservations guard | No | Serializes if same existing inode/root; forbid alternate roots and lock creation |
| `sp_target_execution.run_prepared` | M89, M90 | Manual CLI / invoker | Yes | No | Same reviewed inode required; remove unauthorized launch access |
| `m63_catalog.run` | M89, M90 | Manual CLI / invoker | Yes | No | Same; separate accounting cannot bypass cumulative budget |
| `m67_execution.execute`, `m72_execution.execute` | M89, M90 | Manual approved plans / invoker | Yes | No | Some permit creating lock; fixed existing identity must be enforced before any use |
| `m75_execution.execute`, `m77_execution.execute`, `m80_execution.execute` | M89, M90 | Manual approved plans / invoker | Yes | No | Private accounting only; retire unauthorized launch routes |
| `m88.execute`, `m88_targeted.execute`, `m89_continue.execute` | M89, M90 | Manual approved plans / invoker | Yes, first | Yes, second | Same root/ledger/inodes required; old plans are not broker approval |
| `m89_deployment.authenticate` | M89, M90 | Manual authentication-only CLI / invoker | No | Yes | Serializes with broker ledger but not account-only writers; repair/retire |
| `m90.execute` | M90 only | Manual GET/token-pipe CLI / invoker | Yes, first | Yes, second | Old approval string/token pipe not allowed broker route; retire privileged launch access |
| `m901`, `m902`, `m902_requester` | Neither M89 nor M90 | Not installed in visible releases | N/A | N/A | Source checkout only; no installed broker or privileged IPC launcher |
| `app.orchestrator` | V02 via `/current` | Offline systemd service / intelligenceos-arbitrage | No Amazon requests | N/A | Mock legacy/discovery; keep restrictions and behavior unchanged |

Provider and transport primitives (`amazon_pilot.request_json`, `exchange_token`,
`m67_transport`, `m72_transport`, M75/M77/M80 transports and M71 adapter) are
reachable through the corresponding executors; they are not independently
approved operations. Root-owned launch policy must prohibit importing arbitrary
modules or selecting arbitrary executors, rather than rely on this table as an
access-control mechanism.

No Amazon-specific installed service, timer, cron job or local-bin wrapper was
found in the inspected scope. The offline service timer has an existing symlink
in `timers.target.wants`, and schedules 06:00 UTC daily with Persistent=true.
This establishes configured enablement, not runtime active status. `systemctl
show` failed with bus access denied; no start/stop/enable/disable was attempted.

Additional manually executable source checkouts were observed at
`/root/IntelligenceOS-Arbitrage`, `/root/IntelligenceOS-Arbitrage-M61`, and the
current `/root/IntelligenceOS-Arbitrage-clean`. The first contains original
pilot/details/pricing modules; M61 contains candidate/enrichment/research runners;
the current checkout contains the full milestone inventory above. They are not
installed service entry points, but root can invoke them manually. No matching
scheduled launch reference was found in the inspected configuration. Include them
in the future operator access/retirement review; do not delete history. The
M61/current `ops/m78_sandbox/{prepare,rollback,verify}.sh` files are deployment
scripts in source checkouts, not evidence of enabled services, and were not run.

### Filesystem ownership and permission matrix

All numeric identities are **namespace observations**. Every row below was read
without changing permissions/ACLs/owners. Device observed where accessible:
64769. ACL presence means a POSIX ACL xattr name was present, not reviewed grants.

| Path | Observed UID:GID / mode | Inode | ACL | Assessment |
| --- | --- | ---: | --- | --- |
| `/root` | 0:0 / 0700 | 1738 | Absent | Protected ancestor |
| `/root/.intelligenceos-arbitrage-amazon` | 0:0 / 0700 | 267669 | Absent | Suitable visible metadata |
| Existing `candidate-execution.lock` | 0:0 / 0600, nlink 1 | 287204 | Absent | Existing regular file; not opened/locked/created during assessment |
| `/var` | 0:0 / 0755 | 80888 | Absent | Root controlled |
| `/var/lib` | 0:0 / 0755 | 80889 | Absent | Root controlled |
| `/var/lib/intelligenceos-arbitrage` | 65534:65534 / 0750 | 1310721 | Absent | Non-root owner; conflicts with broker root-owned chain; traversal denied |
| `/var/lib/intelligenceos-arbitrage/m89` | Permission denied | Unknown | Unknown | Stop inspection; do not infer ledger metadata |
| `m89/ledger.json`, `m89/ledger.lock` | Permission denied | Unknown | Unknown | Cannot safely lock/read/hash |
| `/etc` | 0:0 / 0755 | 42 | Absent | Root controlled |
| `/etc/intelligenceos-arbitrage` | 0:0 / 0750 | 280292 | Present | ACL grants require host review; no writable group mode observed |
| `/etc/intelligenceos-arbitrage/m89` | 65534:65534 / 0700 | 550738 | Absent | Non-root owner, conflicts with broker policy |
| Protected `m89/live.env` | Permission denied | Unknown | Unknown | Contents and hash not read |
| `/opt` | 0:0 / 0755 | 1736 | Absent | Root controlled |
| `/opt/intelligenceos-arbitrage` | 0:0 / 0755 | 278412 | Absent | Root controlled |
| `/opt/intelligenceos-arbitrage/releases` | 0:0 / 0755 | 278413 | Absent | Root controlled |
| V02 release root | 0:0 / 0755 | 278414 | Not inspected | Release name is not immutable-source attestation |
| M89 release root | 0:0 / 0755 | 540748 | Not inspected | Same |
| M90 release root | 0:0 / 0755 | 1075929 | Not inspected | Same |
| `/opt/intelligenceos-arbitrage/current` | 0:0 / symlink 0777 | 281150 | Absent | Target is exactly V02 above; unchanged |

All three release `app` directories are root-owned mode 0775. Every observed
application `.py` source is group/other writable by mode: 13/13 V02, 168/168 M89,
169/169 M90 (sampled installed Amazon files are 0664). This fails the proposed
nonwritable privileged-source policy. It does not establish which non-root
accounts belong to the owning group or prove an active compromise.

`findmnt` resolves `/opt` to root filesystem `/`, type ext4. Ledger-specific mount
resolution was not available through the inaccessible ancestry. No mount changes
were made. Filesystem type alone does not certify storage/fsync behavior.

### Ledger integrity result

**BLOCKED / NOT VERIFIED.** The ledger directory and existing ledger lock cannot
be traversed with available privileges. No ledger lock was opened or created;
no ledger bytes, digest, attempts or metadata were changed. The account lock was
also left unopened because the coordinated ledger lock was unavailable.

The supplied historical baseline remains an expectation, not a new observation:
SHA-256 `c79e2a7788c3b99ee75a17dc3150b9e2a609818ad2de3cce82f082e36c9b79f1`,
13/49 used, 36 remaining, purchases unauthorized. This milestone itself consumed
zero requests. It cannot rule out unrelated writers since the last operator
verification. “Future attempt 14/15” is a plan, **not a current reservation**.

A future host operator must open only the existing reviewed account lock, then
existing reviewed authoritative ledger lock, with O_NOFOLLOW and no O_CREAT,
validate descriptor metadata/identity and acquire nonblocking exclusive locks.
If either is missing/replaced/unavailable, stop. Read the ledger once through a
validated descriptor with O_NOATIME (otherwise stop to preserve metadata), pin
its complete SHA and call the pure `history_bytes` validator using trusted code.
Emit only hash-match, validated counts/ceiling and purchase prohibition, never
historical account identifiers. Do not use old `m90 preflight` here: it can create
a missing ledger lock. No command that creates state is an authorized workaround.

### Service, runtime and egress observations

The installed offline service is root-owned mode 0644, executes as
`intelligenceos-arbitrage`, uses `/current/.venv/bin/python -m app.orchestrator`
for legacy and discovery, and references the offline environment file (contents
not read). Its installed definition preserves ProtectHome=true,
NoNewPrivileges=true, RestrictAddressFamilies=AF_UNIX, IPAddressDeny=any,
ProtectSystem=strict, empty CapabilityBoundingSet and StateDirectoryMode=0750.
Do not use or weaken this service for live Amazon execution.

Observed interpreter/dependency paths:

| Release | Python / dependencies | Limitation |
| --- | --- | --- |
| V02 | `.venv/bin/python -> python3.12 -> /usr/bin/python3.12`; openpyxl 3.1.5, pytest 8.3.5 distribution metadata | app/source modes unsuitable for root broker |
| M89 | Same system Python symlink; openpyxl 3.1.5, pytest 9.0.3 metadata; venv 0750 | non-root identities partially unmapped; no root execution performed |
| M90 | No `.venv` present; requirements pin openpyxl 3.1.5, pytest 9.0.3 | Runtime not provisioned; no install authorized |

`/usr/bin/python3.12` is root-owned mode 0755. Symlink target and distribution
metadata inspection do not verify all executable/dependency contents or import
paths. A future broker needs its own audited immutable interpreter/dependency
manifest; it must not inherit user site, PYTHONPATH, cwd imports or writable
bytecode caches. Read-only inspection never executed these deployed interpreters.

`nft list ruleset` failed: netlink socket denied. No firewall state or DigitalOcean
cloud firewall policy can be certified. `ip address show` was likewise denied.
The installed unit's deny-all policy is observed configuration, not independently
tested effective network enforcement. No Amazon endpoint was resolved or probed.

## Launcher architecture recommendation

| Option | Advantages | Constraints here |
| --- | --- | --- |
| Root-operated direct one-shot | Small lifecycle, explicit operator control, no automatic restart | Alone does not attest an unprivileged message sender; current core requires distinct broker/requester UIDs |
| Narrow sudo wrapper | Familiar delegation; sudo binary exists | No project rule exists; NoNewPrivileges blocks elevation from offline service; SUDO_UID alone is not kernel peer evidence; never authorize general Python/shell |
| Unix-domain IPC with kernel peer credentials | SO_PEERCRED provides actual connected requester UID; offline AF_UNIX restriction is compatible | Needs a reviewed private `/run` endpoint, strict framing, bounded listener and connection handling |

**Recommend a root-operated, manually started, one-shot Unix-domain
SOCK_SEQPACKET launcher**, accepting at most one bounded request from the fixed
application UID after checking SO_PEERCRED. This is the Unix-domain option, with
no persistent daemon, socket activation or automatic restart. It satisfies the
existing distinct-identity core without treating a caller string or sudo
environment variable as authentication. A short-lived listener is justified by
kernel-backed requester authentication; there is no public TCP/HTTP endpoint.

The future operator starts it only for an independently approved execution window.
A root-controlled `/run` directory and narrowly accessible socket grant IPC only,
not `/root` traversal. Bound accept/read deadlines and exactly one fixed frame;
reject oversize/truncated/extra frames and unauthorized UIDs before claim creation.
Reject ancillary file-descriptor passing and close any received descriptors with
close-on-exec handling. An authorized requester can cause denial of service, but
cannot issue approval,
choose policy/paths/imports or obtain credentials. Provisioning and cleanup are
future deployment changes, not performed here. Never unlink the shared account
lock or replay claim during socket cleanup.

The launcher must independently verify the fixed immutable release plus all
imports/interpreter/dependencies, scrub environment and cwd, close unrelated FDs,
disable core dumps and emit only sanitized output. It must load fixed protected
policy, approval/evidence paths and credential source, validate every existing
lock and invoke only the two fixed transports. No shell, arbitrary argv, generic
Python module selector, caller host/URL or restart behavior is permitted. Keep
approval provisioning separate from launch/IPC permissions.

## Network isolation recommendation

Retain the fixed direct HTTP adapters: exactly one LWA POST and one conditional
Catalog GET for B001BE12BA, US marketplace, summaries only. Verified TLS, original
hostnames/SNI, bounded bodies/responses, no redirects, proxies, retries or token
refresh remain application controls. The 40-second deadline covers both phases.

For a separately approved deployment, use a dedicated one-shot network namespace
with an independently configured deny-by-default egress filter. Permit only TCP
443 to a short-lived reviewed address set for the two fixed hosts, established
return traffic and required local IPC. Resolve addresses in an independently
controlled provisioning step, respect TTLs, and supply a read-only fixed hostname
mapping for the short run; deny general DNS/other egress inside the execution
boundary. No such resolution was performed in M90.2a.

Address churn, shared Amazon infrastructure and IPv4/IPv6 differences mean an IP
allowlist cannot prove hostname/path/method authorization. Keep certificate and
hostname verification and exact code-level request allowlists. Fail closed on
stale mappings, missing address families or mismatches; never automatically widen
the firewall or retry. Drop network-admin/system-admin capabilities in the broker,
prevent namespace/mount escape, protect cgroups and prevent untrusted children.
The privileged namespace setup itself needs independent implementation/security
review; a process retaining host root capabilities would weaken this boundary.

A reviewed existing egress proxy could add CONNECT hostname enforcement, but
would require explicit transport/proxy design changes; the current adapters
intentionally ignore proxy environment. Do not silently introduce a proxy or TLS
interception. No network-only control can replace fixed application requests and
trusted immutable code. Cloud firewall state still needs a host/operator audit.

## Remaining blockers and exact remediation plan

1. **Obtain host-side read-only evidence** through a separately approved operator
   session with real UID/GID visibility. Inspect effective unit state, remaining
   account/user schedules, manual launch routes, ownership, ACL grants, mounts and
   firewall/cloud policy. Do not bypass this sandbox's denied access.
2. **Verify authoritative accounting under existing locks** using the procedure
   above. Require exact baseline, validated 13 attempts, ceiling 49, purchases
   false and no unresolved claims/reservations. Any drift stops planning; never
   repair/reset counters or restore historical ledger bytes.
3. **Resolve filesystem layout explicitly.** Root-only protected credentials and
   claim storage are required. Root-owned final ledger files alone do not protect
   an application-owned parent against rename. A possible reviewed remedy keeps
   the authoritative ledger path but makes its full parent chain root controlled,
   moving offline service outputs to a separate application-writable child.
   That entails separately approved service/path/ownership changes and is NOT
   authorized here. Alternatively review a complete pinned-inode filesystem
   design with every writer coordinated; do not relax ancestor validation merely
   because descriptor reads pass tests. Keep the existing account lock unchanged.
4. **Retire/coordinate legacy writers.** Inventory actual launch permissions and
   operator procedures; prohibit arbitrary root interpreter/module execution
   through any app-accessible wrapper. Route only the fixed operation through the
   broker. Separately review M89's account-lock omission and all unlocked legacy
   direct runners; installing a new broker alone does not fix them.
5. **Prepare a new immutable release design**, not reuse group-writable staged
   trees for privileged execution. Verify actual commit/content manifest and
   interpreter/dependency ownership/modes/ACLs with no caller-controlled imports.
   Do not change existing release permissions or `/current` in this milestone.
6. **Implement/review the one-shot kernel-authenticated IPC launcher and independent
   egress controls offline.** Test hostile clients, lifecycle cleanup and bounded
   failures. Keep restart disabled and approval provisioning separate.
7. **Obtain separate deployment approval**, then separately authorize any live
   two-request operation only after reviewed seller evidence, credential binding,
   exact release/locks/ledger and approval expiration/nonce are independently
   verified. No production approval/evidence document is fabricated by this work.

## Proposed M90.3 acceptance criteria

- All blocked host observations completed and retained as sanitized evidence.
- Actual running immutable code/dependency identity verified, not just a commit
  string in policy; root-only policy and approval provisioning enforced.
- Existing account lock unchanged; authoritative ledger lock existing and pinned;
  all launchable writers coordinated or unavailable to the requester.
- Filesystem ancestor, ACL and persistence design approved and verified; claim
  storage retained independently from ledger rollback.
- One-shot SO_PEERCRED launcher implemented, offline-tested and separately reviewed;
  requester cannot supply paths, imports, arbitrary HTTP, commands or approval.
- Independent deny-default egress design verified without weakening the offline
  service. DNS/TLS/IP limitations and fail-closed behavior explicitly tested.
- No-request host preflight confirms original baseline and absence of replay
  claims. Deployment and any actual execution have separate explicit approvals.
- Crash, storage failure, timeout and replay paths retain 13→14→conditional 15
  accounting with no automatic retry/resume/reset or purchases.

## Offline verification and results

Starting checkout was clean at `11f192877cfd84285755797a017ef5f17a6de9a3` on
`milestone/m90-2-secure-execution-broker`; work uses the new
`milestone/m90-2a-security-hardening` branch. Existing history is preserved.

Safe local commands (existing Python 3.12 environment, no package installation):

```bash
/tmp/arbitrage-ci-fix-py312/bin/python -m pytest -q tests/test_m89_deployment.py tests/test_m90.py tests/test_m901.py tests/test_m902.py tests/test_m902a.py
/tmp/arbitrage-ci-fix-py312/bin/python -m pytest -q
ARBITRAGE_MODE=legacy ARBITRAGE_REPORT=var/m902a-legacy.xlsx ARBITRAGE_DB=var/m902a-legacy.sqlite3 /tmp/arbitrage-ci-fix-py312/bin/python -m app.orchestrator
ARBITRAGE_MODE=discovery ARBITRAGE_REPORT=var/m902a-discovery.xlsx ARBITRAGE_DB=var/m902a-discovery.sqlite3 /tmp/arbitrage-ci-fix-py312/bin/python -m app.orchestrator
/tmp/arbitrage-ci-fix-py312/bin/python -m app.m902
/tmp/arbitrage-ci-fix-py312/bin/python -m pip check
git diff --check
```

Baseline focused suite: 202 passed. Final hardened focused suite: 447 passed in
13.13 seconds, including 245 new M90.2a tests. Final full repository regression:
**3418 passed, 9 skipped in 713.68 seconds**, one complete run including the new
tests. Collection: 3427 tests. Both sample workflows: job_succeeded. Dependency
check passed; inert broker readiness output confirmed. `git diff --check` passed.

Final read-only comparison confirmed the same `/current` target and account-lock
UID/GID 0:0, mode 0600, device 64769, inode 287204, nlink 1. This comparison does
not establish current ledger state or exclude concurrent unrelated writers.

## Production change confirmation

No production deployment, staging, installation, source/configuration writes,
service operations, permission/ownership/ACL/firewall changes, symlink changes,
credential reads, credential hashes, seller identifiers, lock creation/acquisition,
ledger reads/mutations, live requests, DNS probes, pushes or merges were performed.
The only writes are repository development artifacts and synthetic offline test/
sample outputs. The observed `/current` target is unchanged. Production change
count: **zero**. Request consumption by this milestone: **zero**. Current account
budget remains **unverified**, with supplied historical expectation 13/49.
