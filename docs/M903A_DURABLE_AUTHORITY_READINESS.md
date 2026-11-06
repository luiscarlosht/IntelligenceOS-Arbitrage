# M90.3a — Durable authority infrastructure readiness

## Scope, architecture and trust boundaries

This milestone implements filesystem-backed **offline infrastructure**, not a
production migration tool. All constructors operate on isolated private fixtures
beneath `/tmp`. Production paths are design constants in manifest contracts only;
there is no production command, policy loader, source-path override, launcher,
socket, service, network transport or credential interface. `production_transition`
unconditionally rejects, including when a caller labels evidence independently
verified. No installed release or operational broker command is invoked; existing
broker regression tests remain synthetic with mocked transports.

Components:

| File | Responsibility |
| --- | --- |
| `app/m903a_fs.py` | Fixture-only pinned descriptors, private metadata validation, exclusive creation, atomic same-directory publication, durability barriers and existing-file locks |
| `app/m903a_contract.py` | Exact bounded canonical journal, registry and manifest schemas |
| `app/m903a_authority.py` | Separate registry and retained checkpoint, journal protocol, source audit, staged storage, manifest publication, successor verification and offline M90.2c adapter |
| `tests/test_m903a.py` | Isolated filesystems, forked crash tests, fsync injection, security and replay tests |

The M90.2c pure model and M90.2b root-only verifier remain unchanged. Source review
uses a separate class and ownership policy; it never relaxes protected destination
validation. Neither matching hashes nor synthetic receipts are proof of an actual
host maintenance freeze, writer retirement, kernel requester identity or verified
production runtime.

Three separate fixture roots model the retention domains:

- Source: preexisting account lock, old ledger lock, exact original ledger and a
  pre-reviewed historical claim index. The adapter has no source write methods.
- Protected destination: `authority/`, `m89/`, `claims/`, `journal/`, `evidence/`.
  The proposed production root remains `/var/lib/intelligenceos-arbitrage-protected`.
- Independent registry: separately retained `checkpoint.json`, outside source and
  destination. Nested/shared source/destination-registry roots are rejected.

A fourth logical anchor is the caller-retained checkpoint receipt from the last
successfully acknowledged operation. It is not automatically recovered from current
files. Tests retain it outside the destination/registry snapshots; production needs
an authenticated external or separately protected retention mechanism. Fixtures
may share a physical filesystem and do not prove independent hardware retention.

The historical production expectation remains 13/49 used, 36 remaining, purchases
false, full SHA `c79e2a7788c3b99ee75a17dc3150b9e2a609818ad2de3cce82f082e36c9b79f1`.
It was not read or freshly verified. This work consumed zero Amazon requests.

## Filesystem ownership and provisioning model

`FixtureFS` rejects production roots, relative/noncanonical paths, `..`, symlink
ancestry and cross-device descendants. It does not honor caller TMPDIR as a way
to select another root. It opens `/` and `/tmp` ancestry only to walk/pin the
fixture path; it never opens business production directories. A malicious host
root controlling mounts/kernel/code is outside this boundary. Do not mistake
this test facility for a privileged filesystem service.

Protected fixture directories require current test-owner UID and exact 0700;
files require that UID, mode 0600, regular type and link count one. Eventual
production requires root:root throughout protected ancestry, with no untrusted
write or ACL grants. There is deliberately no switch enabling a production root.
Directory and file opens use O_NOFOLLOW/O_CLOEXEC/O_NOATIME, O_DIRECTORY where
appropriate and O_NONBLOCK. Missing metadata-safe flags/access cause a stop.

Directories are opened component by component, compared with named identities and
retained as descriptors. File reads compare before/open/after device/inode,
ownership, mode, link count, size and nanosecond atime/mtime/ctime. Directory edges
are rechecked; publication stays on the pinned directory even if a pathname is
substituted, then fails closed on the mismatch. Reviewed source/account/new lock
identities are rechecked around side effects and immediately before publication.

Verification only opens existing descriptors O_RDONLY; it cannot create/truncate/
replace/unlink/chmod/chown anything. Locks use nonblocking exclusive flock on
existing read-only descriptors. Linux/local-filesystem semantics and trusted
storage are assumptions requiring host review; there is no writable-open or
unsafe atime fallback. Flock changes temporary kernel state, not persistent lock
contents or metadata. No production lock was acquired in this milestone.

Explicit provisioning is separate: `provision_destination` requires an empty
fixture root, creates only the proposed protected directories and dedicated new
**ledger** lock, and fsyncs parents. `provision_registry` exclusively creates its
initial registry and returns its retained receipt. Neither touches or creates the
original account/old ledger locks; tests supply preexisting synthetic locks.
Provisioning cannot be called on the source class and is never invoked by readers.
There is no reset or repeated-provisioning repair path.

Descriptor errors close newly opened files and never cache an unvalidated child
directory. Uncertain directory provisioning quarantines the fixture object.

Writes use exclusive files, bounded write loops, file fsync and parent fsync.
Publication uses an exclusive `.pending` file and atomic same-directory rename,
then fsyncs the parent again. Cross-device publication fails without copying as a
fallback. Existing pending files, partial journal entries and unexplained artifacts
are retained and block later operations. The infrastructure never unlinks failed
artifacts to force a passing result. Source files and credentials are untouched.

## Durable journal schema and validation

Journal records are separate exclusive files `journal/00000001.json`, etc., not
in-place updates of one mutable log. The implementation appends records; it does
not replace, truncate or silently repair an existing record. Limits: 1024 records,
65536 bytes per record. Every observed filename must match the exact monotonic
sequence from one; missing, duplicated, reordered or unexplained names fail.

Canonical storage encoding is sorted-key compact UTF-8 JSON with a final newline,
no nonfinite values and no duplicate keys. Readers require the exact canonical
bytes; alternate whitespace is not silently normalized on disk. Fixed record keys:

```text
version, migration_id, generation, sequence, previous, kind, transition,
nonce, operation_claim, payload_sha256, decision, record_sha256
```

Version is integer 1. Integers reject booleans. IDs/digests are lowercase 64-hex;
generation/sequence are positive. Previous points to the previous sealed record
hash (all-zero hash at genesis). `record_sha256` hashes the canonical record without
its own seal. Kind is INTENT or COMPLETE; records must alternate and match their
nonce, transition, operation claim and payload. Transition order is exactly the
eight M90.2c advances after PRECHECK. No duplicate nonce or operation claim is
accepted. Operation-claim IDs are recomputed from migration ID, generation and
transition, not accepted solely because they look like hashes.

Staging payload binds exact ledger and claim-index bytes. Commit payload binds
the full proposed authority manifest. Other transition payloads bind phase,
ledger, claims and runtime digests. A valid local chain is checked against BOTH
the independently retained registry and the last acknowledged retained receipt;
it is never sufficient by itself.

## Independent nonce/checkpoint registry

The separately retained registry uses exact keys:

```text
version, migration_id, generation, sequence, journal_sha256, nonces,
operation_claims, decision, pending, claims_sha256
```

The maximum registry/claim-index document is 1 MiB. Lists reject duplicates;
identities/generations/types are checked strictly. Decision is OLD,
PENDING_NO_WRITERS or NEW. Pending is a real boolean. The reader reconstructs the
entire expected checkpoint, consumed lists and decision from the journal and
requires exact registry equality. A retained checkpoint additionally binds the
full canonical registry hash, migration/generation, latest sequence/hash and
last acknowledged decision.

Transition protocol, while holding account → old ledger → new ledger locks:

1. Validate actor/runtime, freeze window, next phase, current journal, registry and
   retained checkpoint. Validate side-effect inputs before consumption.
2. Exclusively create INTENT; fsync record and journal directory.
3. Append nonce and deterministic operation claim to a pending registry checkpoint,
   publish it atomically, fsync its file and directories. Consumption is durable
   before any staged copy or authority-manifest side effect.
4. Perform only the fixed side effect for that phase. There is no caller-selected
   command, executable, import, file path or arbitrary effect callback. Fault
   callbacks are fixture-only injection hooks, not privileged launch interfaces.
5. Append matching COMPLETE; fsync record/directory. Publish the completed registry
   and fsync its barriers. Independently read/validate local consistency.
6. Only after lock contexts close cleanly acknowledge a new retained checkpoint
   receipt. The caller must retain it independently before the next transition.
   Lost acknowledgement is a no-writers/manual-investigation condition.

An intent durable before registry update causes disagreement if interrupted;
registry consumption without side effect remains pending. Neither authorizes
re-execution. Missing/partial/conflicting/older checkpoints block rather than
resetting counters or reconstructing a fresh registry. A last acknowledged OLD
decision is NOT permission to use the old authority when current files disagree.

### Full rollback and external-anchor limitation

Restoring journal alone, a valid older prefix plus manifest, or journal plus local
registry is rejected against the retained newer checkpoint. This is implemented
and tested. If **every** trust anchor is rolled back together, including that
checkpoint, policy/generation context and any independent registry, a coherent
old state cannot be distinguished by local hashes alone.

Production must bind the latest generation/sequence/digest/nonce set to separately
protected or external authenticated monotonic retention: for example an audited
root-operated checkpoint service or append-only/WORM store outside the same
backup/restore domain. Its authentication, authorization, availability and
anti-rollback semantics need independent review. No such service is installed or
contacted here. The fixture receipt is an unsigned synthetic object, not a
cryptographic production attestation. Do not mint a replacement receipt by reading
whatever registry happens to be present after a crash or restore.

## Fixed-source audit adapter and weaker trust

`SourceFixtureFS` and `audit_source` implement a read-only, fixed-relative-layout
adapter corresponding to the design source
`/var/lib/intelligenceos-arbitrage/m89/ledger.json`. They accept only temporary
fixture roots; that production path is never accessed. Existing synthetic paths
are fixed within the source root: account/candidate-execution.lock,
m89/ledger.lock, m89/ledger.json and m89/claim-index.json.

The source class requires a nonempty, unexpired FreezeReview bound to migration
and generation with reviewed inode/device → owner/mode/ctime profiles and evidence
digest. Source profiles may represent application ownership; protected destination
validation remains strict. Ctime pinning detects deletion/recreation even if a
filesystem reuses an inode number. The freeze is explicitly SYNTHETIC_ASSERTION;
claiming INDEPENDENTLY_VERIFIED does not unlock a real source reader. There is
no production policy trust key or host adapter.

The adapter acquires the existing account lock before the existing old ledger
lock, checks reviewed identities and the exact source-directory artifact set,
reads through bounded no-atime descriptors and validates complete raw SHA and
all historical attempts via `m902_history.validate_snapshot`. It validates the
canonical claim index and requires the original consumed M89 embedded claim,
complete evidence/binding/attempt mapping and only historically accounted consumed
claims. Duplicate/conflicting origins, missing records, unresolved/future claims
or unexpected source entries fail. The source class refuses every provisioning/
write/publication method; it creates no locks and never changes source metadata.

The internal AuditedSnapshot retains copy bytes with a nonrevealing repr. Only its
`report()` is diagnostic output: fixed status/counts, purchase prohibition, weaker
source-trust label and production_qualified=false. Raw copy payloads are internal
trusted-process data, never IPC output or logs.

The supplied pre-reviewed claim index is not a discovery mechanism. Unknown
historical directories, deleted claims, retained tokens and active legacy writers
cannot be disproved by its contents. A production source adapter must independently
verify maintenance freeze, complete scope inventory and claim evidence before
relying on the snapshot. Advisory locks cannot restrain uncooperative writers.
If this independent trust is unavailable, production remains disabled. M90.2b's
root-only verifier is not altered to accept weaker ownership.

## Authority manifest schema and publication

The strict canonical version-1 manifest contains exactly:

```text
version, migration_id, generation,
source_path, destination_path, account_lock_path,
source_identity, destination_identity,
account_lock_identity, source_lock_identity, destination_lock_identity,
ledger_sha256, prefix_sha256, ceiling, purchase_authorized, claims_sha256,
runtime_sha256, release_commit, previous_checkpoint, approval_nonce,
authority, active_authorities, retirement_sha256
```

Paths must equal the existing source, fixed Strategy B destination and unchanged
account-lock design constants. Identities contain exactly unsigned device and
positive inode integers. Generation is positive; version/ceiling reject boolean
or float substitutions. Ceiling must be 49, purchase_authorized must be false,
authority must be NEW and active_authorities exactly [NEW]. Runtime/retirement/
ledger/prefix/claim digests are 64-hex and release commit 40-hex. Previous checkpoint
contains exactly sequence/hash. Unknown keys, duplicate keys, nonfinite input,
malformed identities or inconsistent generation are rejected.

The manifest binds the checkpoint immediately BEFORE its commit INTENT, avoiding
a circular manifest/journal digest. The INTENT/COMPLETE pair binds the manifest's
complete canonical hash and approval nonce; the final registry binds their head
and NEW decision. Verification locates that exact commit pair and checks the
prior sequence/hash, not simply whether a manifest exists.

Before commit, raw staged ledger and claims are revalidated, original source is
rechecked under the freeze, and runtime evidence is measured. Publication begins
only after durable commit intent AND pending nonce-registry consumption. Exclusive
manifest.pending → atomic rename → directory fsync establishes publication.
Registry remains PENDING_NO_WRITERS until completion durability is acknowledged.
A visible manifest after a rename or fsync fault cannot enable a writer. Old source
is never rewritten, restored, selected as fallback or made a second authority.

The raw source ledger is copied without JSON reserialization. The historical claim
index is copied byte-for-byte and its exact digest is anchored. Empty new claims
are never a substitute for old consumption. No attempt 14/15 is reserved and no
request is dispatched by any of these components.

## Successor verifier contract

`AuthorityStore.verify` is an offline-testable successor for the new layout. It
requires an explicit Context and independently retained checkpoint, not a policy
derived from current files. It uses existing locks and read-only descriptors; no
provisioning, replay, retry, repair, fallback or state creation is reachable.

It independently checks:

- Protected root/child ownership, modes, ancestry, link counts and reviewed locks.
- All 16 intent/completion records, strict phase order, canonical hash chain,
  consumed nonces/operation claims, separate registry and retained checkpoint.
- Exact authority manifest, generation, previous checkpoint, consumed nonce,
  source/destination identities, single NEW decision and retirement-policy digest.
- Exact ledger bytes, entire original history and twelve-attempt prefix, ceiling
  49, purchase prohibition and retained historical claim index.
- Actual fixture runtime-bundle bytes against the independently supplied runtime
  hash, plus strict release metadata against the supplied release identity.
- No pending files, unexplained ledger/claims/authority files or incomplete intent.

Successful output is only SYNTHETIC_VERIFIED, production_qualified=false,
live_enabled=false, NEW authority, 13 used, 36 remaining, ceiling 49, purchases false.
Errors from step, source audit, adapter and verifier are normalized to the fixed
AUTHORITY_BLOCKED code with suppressed raw exception diagnostics. Low-level
contract/storage helpers are internal and must not be exposed as a production API.

This verifier runs in the migration/post-cutover **maintenance freeze** and retains
the three-lock order. A later normal-execution verifier should use account → new
ledger and root-retained source evidence, not depend indefinitely on an
application-owned old path. That role separation needs M90.3b review. The current
version accepts only the original thirteen-attempt baseline; future continuation
needs a separate explicitly reviewed accounting/version contract.

Runtime measurement here covers a synthetic bundle and release metadata. It is
not a deployed interpreter/dependency/CA/import attestor or proof of an actual Git
checkout. The expected Context, retirement digest, freeze scope and caller UID are
trusted synthetic inputs. Real kernel peer authentication, independently approved
runtime evidence and legacy launch retirement are still blockers.

## M90.2c integration and receipt provenance

`advance_model` calls the unchanged pure model first, with its existing strict
approval/evidence checks, and binds model plan/runtime/source/prefix/three lock
identities to the filesystem context. Only then does the fixed durable transition
execute. Returned receipts have actual synthetic file/registry durability checks.
A rejected receipt or model transition consumes no nonce or side effect.

Receipt qualities are explicit: SYNTHETIC_ASSERTION, DURABLE_SYNTHETIC,
INDEPENDENTLY_VERIFIED, MISSING, UNCERTAIN and CONFLICTING. Only the first two may
feed the offline model path; missing/uncertain/conflicting receipts block. A bare
INDEPENDENTLY_VERIFIED label is also rejected because no independent production
attestation verifier is configured. `production_transition` always rejects,
regardless of label. No boolean confirmation flag enables production operations.

A durable synthetic receipt proves local fixture I/O barriers under trusted kernel/
filesystem assumptions. It does not prove a real freeze, genuine operator approval,
old-writer retirement or effective network isolation. Raw fixture step nonces are
not an approval issuer or an authentication boundary. The future adapter must
verify protected approvals, actual kernel identity, generation/transition/evidence
bindings and independent attestation before any production transition. None is
implicitly authorized by the completed offline storage tests.

## Crash consistency and recovery matrix

All faults stop. In-process uncertain storage is poisoned; reopening additionally
requires journal/registry/retained checkpoint agreement. No artifact is silently
removed and no pending effect is replayed.

| Window | Conservative result |
| --- | --- |
| Before intent file creation | No recorded consumption/effect. Old last checkpoint remains; no automatic retry |
| During intent write | Partial exclusive record remains; canonical/schema validation fails |
| After intent file fsync, before/after journal directory fsync | Registry/retained checkpoint do not acknowledge the new intent; no effect |
| During registry publication | Pending artifact or checkpoint disagreement; no effect or writer eligibility |
| After nonce consumption, before effect | Durable consumed nonce and pending intent; never reuse it |
| During staged ledger/claim copy or its fsync/rename | Staged data inert/uncertain; source unchanged; no authority manifest |
| Before/during manifest creation | Commit intent and consumed approval remain; no automatic dispatch or retry |
| After manifest file fsync, before directory durability | Manifest/pending state cannot certify authority; no writers |
| After atomic rename, before manifest parent fsync | Visible manifest plus pending registry; UNKNOWN/no writers until independent reconciliation |
| After manifest directory fsync, before completion/registry acknowledgement | New decision may be durable but not independently acknowledged; no fallback to old; manual fix forward |
| During completion or final registry fsync | Retained receipt remains older; even coherent newly visible files disagree and block |
| After acknowledgement | New authority only; a restored older journal/manifest/registry conflicts with retained receipt |
| During post-cutover verification | Live eligibility never emitted; NEW is not reverted; manual investigation |
| Lost successful acknowledgement/process exit | Caller retains old receipt; current files disagree; manual independent checkpoint reconciliation required |

The implementation never infers OLD is safe from an exception or a missing final
receipt. Source preservation means evidence remains intact, not permission to
resume old writers. Reconciliation/fix-forward is intentionally not implemented;
it needs narrow new approval, actual storage evidence and retained independent
anchors. There is no destructive reset, nonce deletion or automated repair tool.

Process-kill tests demonstrate process-crash behavior, not sudden host power loss
or dishonest storage hardware. Fsync durability relies on a reviewed local
filesystem, mount configuration and storage stack. Cross-filesystem rename,
unsupported no-atime/locking behavior and uncertain barriers must block; never
substitute an unreviewed weaker storage mode.

## Security and fault-injection evidence

Starting branch/commit verified clean:
`milestone/m90-2c-authority-cutover-design`,
`d6d01acacc3cf844d02aef33e5c425acd05b5b4e`.
Work branch: `milestone/m90-3a-durable-authority`.

Safe offline commands used:

```bash
/tmp/arbitrage-ci-fix-py312/bin/python -m pytest -q tests/test_m903a.py tests/test_m902b_verify.py tests/test_m902c.py
/tmp/arbitrage-ci-fix-py312/bin/python -m pytest -q
/tmp/arbitrage-ci-fix-py312/bin/python -m pip check
ARBITRAGE_MODE=legacy ARBITRAGE_REPORT=var/m903a-legacy.xlsx ARBITRAGE_DB=var/m903a-legacy.sqlite3 /tmp/arbitrage-ci-fix-py312/bin/python -m app.orchestrator
ARBITRAGE_MODE=discovery ARBITRAGE_REPORT=var/m903a-discovery.xlsx ARBITRAGE_DB=var/m903a-discovery.sqlite3 /tmp/arbitrage-ci-fix-py312/bin/python -m app.orchestrator
git diff --check
```

Tests include forked subprocess exit at 26 named journal/registry/manifest barriers;
13 individual fsync-call failures; copy and post-verification failures; journal,
valid-prefix and joint journal/local-registry rollback; nonce/operation replay;
claim absence/duplication/unresolved state; corrupt/extra attempts; schema attacks;
symlink/hardlink/owner/mode/inode/directory attacks; source replacement during open;
source-lock replacement immediately before publication; EXDEV without fallback;
content/metadata preservation; lock order/contention; expired freeze; mismatched
requester/runtime; duplicate/stale authority; missing independent checkpoint;
receipt provenance; sanitized diagnostics; network/protected-production-path guards;
and a verifier that forbids every writable open.

A weaker source ownership-profile test demonstrates it does not relax protected
storage validation. Source-audit tests compare persistent source contents and
nanosecond metadata without modifying them. Failed artifacts are preserved in
fixtures for examination. Dependency check passed and both sample jobs succeeded.
Recorded results on 2026-11-06:

- Baseline M90.2b/M90.2c: 141 passed, 0 failed, 0 skipped.
- Final focused M90.3a + M90.2b + M90.2c: **247 passed, 0 failed, 0 skipped** in
  32.75 seconds, including all **106 new M90.3a tests**.
- Full repository run: **3665 passed, 0 failed, 9 skipped** in 774.23 seconds;
  collection contained 3674 tests.
- The final descriptor-error cleanup/quarantine guards were added while the full
  run was in progress. The final focused run rechecked every new infrastructure
  test afterward, including close-on-initial-metadata-error behavior; no existing
  implementation files were modified. These are full-run plus final focused
  results, not a claim that the full run collected the later guard refinements.
- Both offline sample workflows: job_succeeded. Dependency check: no broken
  requirements. Final whitespace checks: clean.

Some ownership cases use mocked metadata because the test sandbox does not grant
arbitrary host-UID operations. No real application-owner permission or host
namespace behavior is certified by these tests. Independent security review and
host-specific verification remain prerequisites.

## Remaining production blockers and M90.3b requirements

1. Independently review the implementation/protocol, syscall assumptions and fault
   matrix. Audit exact manifest/registry schemas, resource bounds and source trust.
2. Implement authenticated protected policy, approval and independently verified
   receipt loading. Bind true host/kernel requester identity, full immutable
   interpreter/code/dependency/CA runtime and retirement/network evidence. No
   caller-supplied quality enum, UID or nonce is production authorization.
3. Implement the external/separately protected monotonic checkpoint retention
   boundary and receipt authentication. Prove acknowledgement/crash semantics,
   generation changes and restoration rejection across all local backup domains.
   Local hashes cannot detect simultaneous rollback of every anchor.
4. Complete host-side ledger/claim/lock/mount/owner/ACL/writer inventory under
   separately approved read-only access. Supply a real independently verified
   maintenance freeze and complete historical claim inventory. No current budget
   is certified from these fixtures. Preserve all raw original claim evidence.
5. Review a fixed-production-path adapter with OWNER=0 and trusted mount/namespace
   boundaries; do not add a production switch to FixtureFS. Separate provisioning
   from source auditing and successor verification, and separate maintenance
   verification from ordinary new-authority execution locking.
6. Close credential-access and legacy writer/network isolation problems without
   treating this milestone as permission to read/change credentials or services.
   Existing reporting and `/current` remain unchanged; no generic privileged
   Python/shell/systemd launcher may be delegated to the requester.
7. Add further offline concurrency, power-loss/storage-emulation, attestation,
   generation rollover and manually approved fix-forward tests before proposing
   a runnable cutover command. No reset or replay recovery is acceptable.
8. Only after independent review may separate approvals cover production storage
   provisioning, policy/runtime deployment, source-audit lock acquisition,
   maintenance freeze and exact authority cutover. A no-request verification is
   another explicit operation; it must not silently provision or repair state.
9. Any later live authentication/Catalog workflow needs separate seller/application
   evidence, one-time approval, fresh locked budget verification and network
   authorization. Purchases remain unauthorized. This milestone has no HTTP code.

No production command or operator migration invocation is supplied. Independent
production trust, external anchor integration and host-specific readiness remain
blocked; synthetic success cannot remove those gates.

## Zero-production-change confirmation

No production ledger/credential reads or writes, production lock acquisition/
creation/replacement, directory provisioning, deployment, staging, package install,
service/timer/environment change, firewall/network probe, `/current` or release
modification, push or merge occurred. No DNS/TCP/TLS/Amazon API request or purchase
was performed or authorized. Source and destination paths in contracts are design
bindings only. All exercised storage was in isolated synthetic `/tmp` fixtures;
illustrative sample outputs stayed in repository `var/`. Production changes:
**zero**. Live Amazon requests: **zero**. Historical 13/49 remains unverified.
