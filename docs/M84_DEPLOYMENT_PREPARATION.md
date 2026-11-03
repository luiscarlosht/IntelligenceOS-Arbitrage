# M84 isolated offline release preparation — no deployment authorization

This is a proposed repeatable deployment, not an installation or production-readiness claim. No server changes, credentials, service operations, evidence staging or live API calls were performed. All host-changing steps below require separate explicit owner approval. Original M76–M80 evidence, M77 registry, M78 isolated installation, ACL-restricted sandbox and existing services must remain untouched.

## Artifact trust and offline build

Use a reviewed full Git commit containing the integrated reporting pipeline. Review/merge the stacked PRs in order; never substitute an unreviewed branch name. The new profile `sales-intelligence-offline-v1` exports exact ordinary `app/**/*.py` Git blobs and a reviewed offline entrypoint. It is separate from M78's frozen historical inventory: no 127/401-file compatibility requirement and no bytecode regeneration. The builder never installs, runs package hooks or trusts the old sandbox.

Two pure-Python wheels only, pinned versions and release-artifact SHA-256:

| Artifact | SHA-256 |
| --- | --- |
| openpyxl-3.1.5-py2.py3-none-any.whl | 5282c12b107bffeef825f4617dc029afaf41d0ea60823bbb665ef3079dc79de2 |
| et_xmlfile-2.0.0-py3-none-any.whl | 7a91720bc756843502c3b7504c77b8fe44217c85c537d85037f0f536151b2caa |

On a separately approved connected acquisition workstation, independently inspect official PyPI release-file metadata at `https://pypi.org/pypi/openpyxl/3.1.5/json` and `https://pypi.org/pypi/et_xmlfile/2.0.0/json`. Select those exact filenames, compare the independently obtained `digests.sha256` to the reviewed table, record TLS origin, acquisition time and reviewer approval, and save the original metadata privately. These are PyPI release metadata hashes, not publisher attestations. Neither a local sandbox digest nor a regenerated inventory establishes authenticity.

Create a fresh wheelhouse containing exactly those two files:

```sh
python -m pip download --no-deps --only-binary=:all: --require-hashes \
  -r ops/m78_sandbox/runtime-wheels.txt --dest /local/fresh-reviewed-wheelhouse
sha256sum /local/fresh-reviewed-wheelhouse/*.whl
```

Download only after metadata review; transfer metadata, reviewer record and wheels offline without executing them. Record the transfer digest independently. The builder validates approved filename/artifact pins, purelib metadata, internal RECORD hashes/sizes, complete membership and dependency versions. It rejects native extensions, bytecode, executable hooks, extras, symlinks, hardlinks and unapproved packages. Failure has no legacy fallback.

On the offline development/release workstation (fresh output outside the repository and wheelhouse):

```sh
python -B -m ops.intelligence_release build \
  --repo /local/reviewed-checkout --commit REVIEWED_FULL_40_HEX_COMMIT \
  --wheelhouse /local/fresh-reviewed-wheelhouse --output /tmp/intelligence-release-A
python -B -m ops.intelligence_release verify \
  --repo /local/reviewed-checkout --commit REVIEWED_FULL_40_HEX_COMMIT \
  --wheelhouse /local/fresh-reviewed-wheelhouse --release /tmp/intelligence-release-A \
  --manifest-sha256 OWNER_REVIEWED_MANIFEST_SHA256
```

An independent reviewer rebuilds in a second fresh directory from independently authenticated wheels and reviewed Git objects, compares manifest SHA and every file byte, and records approval. Build output is private/exclusive; no packages are installed into the host. The manifest records exact source hashes, full Git commit, dependency artifact pins, entrypoint hash and complete runtime file map. File counts are derived, never trust roots. The runtime additionally checks the owner-pinned manifest and every file before imports. `python3 -I -S -B` disables ambient site packages and bytecode. The supported base is Ubuntu 24.04/Python 3.12; separately authenticate the OS/Python/SQLite runtime through the owner's signed OS package/image baseline and record actual versions/digests. Wheel verification alone does not authenticate the OS.

## Exact read-only host preflight

After owner review, from an already authorized checkout on the host:

```sh
python3 -B -m ops.intelligence_release host-preflight
```

This command only reads metadata, mountinfo, passwd/group metadata and process UID status. It never creates directories, removes ACLs or starts a unit. It checks root-owned unwritable ACL-free `/mnt` ancestors, the dedicated separate read/write volume, absent fresh destination and UID 997/GID 986 with no processes. A disappearing/unreadable process fails closed. Independently compare the mounted volume identity with the approved DigitalOcean volume inventory; the script checks mount structure, not provider attestation.

Proposed new code destination: `/mnt/intelligenceos_data/arbitrage/intelligence-isolated/release`. It must be absent. No traversal or mutation of `/mnt/intelligenceos_data/arbitrage/sandbox/m78` or `/mnt/intelligenceos_data/arbitrage/m78-isolated` is needed. Even a clean preflight returns `readiness=FAIL`, `target_security=NOT_TESTED`: no installed target exists, independent artifact/OS approvals and kernel isolation remain owner gates. **Do not claim production readiness from preflight.** This command was not executed against DigitalOcean during development.

## Proposed configuration, validated offline

Private configuration schema (substitute reviewed pins, new report name and actual aware review time):

```json
{
  "schema": 1,
  "mode": "OFFLINE_REPORT_ONLY",
  "release": "/mnt/intelligenceos_data/arbitrage/intelligence-isolated/release",
  "release_sha256": "REVIEWED_RELEASE_MANIFEST_SHA256",
  "manifest": "/var/lib/intelligenceos-sales/inputs/manifest.json",
  "manifest_sha256": "REVIEWED_INPUT_MANIFEST_SHA256",
  "history": "/var/lib/intelligenceos-sales/state/observations.sqlite3",
  "output": "/var/lib/intelligenceos-sales/reports/OWNER_NEW_RUN_ID",
  "as_of": "2026-11-03T12:00:00+00:00"
}
```

```sh
python -B -m ops.intelligence_release config-check \
  --config /local/proposed-config.json --sha256 OWNER_REVIEWED_CONFIG_SHA256
```

Validation only reads this configuration and metadata; it does not execute it or inspect credentials. Unknown keys/live mode/path escapes fail. Successful syntax/layout validation still says readiness FAIL and target security NOT_TESTED. Runtime inputs, source pins, freshness and no-overwrite publication receive separate checks in the decision pipeline. Configuration is not a permission file.

## Separately authorized host changes — owner checklist, not an installer

1. Obtain explicit approval for exact destination, reviewed code/dependency/OS manifests, new UID 997/GID 986 use, dedicated `/var/lib/intelligenceos-sales` layout, evidence **copies**, resource budget and isolated unit. Confirm free disk and 2 GB shared-host headroom. No production or historical paths may be repurposed.
2. An authorized operator creates only the fresh code destination. Copy ordinary verified release files exclusively; reverify every byte against the independently reviewed manifest. Code directories root:root 0755, files root:root 0644, no ACLs, links, mount crossings, group/world writes, unexpected files or caches. Validate all ancestors before and after copying. Do not chmod/chown a preexisting target, strip ACLs or use recursive commands against the arbitrage parent. Stop on any existing object or unexpected metadata.
3. Separately create new private state, reports and staged-input directories beneath `/var/lib/intelligenceos-sales`, owned 997:986 mode0700, ACL-free and nonsymlink. SQLite files use0600, single links. State/report writes intentionally stay outside `/mnt`; the application refuses deployment-volume output. Budget their storage on the OS disk and stop before exhaustion; do not silently redirect into the old sandbox. Never run this preparation as a service account with access to production credentials.
4. Only after separate evidence-staging approval, copy approved quiescent original M80 ledger, original M79 handoff if used, saved receipts and their original artifacts into the **new** inputs directory. Preserve source bytes and reverify approved pins after copy; assign copy ownership997:986/mode0600 to satisfy read-only private-ledger validation. Rewrite only the newly created input manifest to reference staged copies and independently review its new hash. Do not edit original ledgers, histories or their embedded bindings; never copy authorization files, tokens or account credentials. Historical import validates recorded paths semantically without replaying them.
5. Owner verifies target metadata, mount boundaries, exact manifest/file set, input pins, OS baseline and account isolation. Perform a synthetic-only run inside the proposed kernel sandbox and prove network access and credential-path access are denied. Verify read-only input/code mounts and writable paths experimentally using fictional data. Stop on any failed target/isolation check. No `ready=true` flag is generated by these development tools.
6. Only after operator approval, run a new **offline reporting** unit. It must use UID997/GID986, `NoNewPrivileges=yes`, `PrivateNetwork=yes`, `RestrictAddressFamilies=AF_UNIX`, `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`, `PrivateDevices=yes`, `ProtectKernelTunables=yes`, `ProtectKernelModules=yes`, `ProtectControlGroups=yes`, `RestrictSUIDSGID=yes`, `LockPersonality=yes`, `MemoryDenyWriteExecute=yes`, `CapabilityBoundingSet=` and `UMask=0077`. Make release and staged inputs read-only; allow writes **only** to the new state and report directories. Hide production application roots, `/root`, credential stores and unrelated evidence. Do not grant `/mnt` writes. Use `MemoryMax=512M`, `TasksMax=16`, `CPUQuota=50%`, a measured execution timeout and disk monitoring. Validate these settings on Ubuntu24.04 before any real evidence import; do not weaken them to make a failure disappear.
7. Command inside that approved sandbox (not executed by this task): set only `INTELLIGENCE_RELEASE_SHA256` to the reviewed release-manifest digest and execute `/usr/bin/python3 -I -S -B /mnt/intelligenceos_data/arbitrage/intelligence-isolated/release/run.py --manifest /var/lib/intelligenceos-sales/inputs/manifest.json --manifest-sha256 REVIEWED_INPUT_SHA256 --history /var/lib/intelligenceos-sales/state/observations.sqlite3 --output /var/lib/intelligenceos-sales/reports/NEW_RUN_ID --as-of ACTUAL_AWARE_REVIEW_TIME`. No secrets/environment credential passthrough, shell interpolation, live client or timer is needed. A stale first pilot produces UNKNOWN, not refreshed data.

## Monitoring, recovery and rollback

The reporting CLI emits only completion class/count or a redacted error type. Do not log raw receipts, ASIN sets, signed permissions or credential environment. Owner monitors unit exit status, memory/time/disk limits, expected workbook/JSON presence, complete source-pin matches, data-quality flags, freshness, excluded counts and history schema/chain checks. Alerting remains local/owner review; no paid service or outbound message is enabled. A nonzero exit, missing output or stale evidence is failure; a partial staging directory is never promoted.

History is a derived append-only SQLite database. Stop only the **new** offline reporting unit before an authorized backup; use SQLite online backup or a verified quiescent copy, mode0600, and record its digest/chain terminal value. Store approved backup copies separately from original acquisition evidence. Verify restore with fictional data first; never overwrite the M77 registry or an acquisition ledger. Retention/deletion requires an owner-reviewed policy; do not auto-delete historical evidence.

Rollback stops/disables only a newly approved reporting unit/timer. Keep reports, own history and all original evidence for audit. Select a previously reviewed immutable release in a new approved configuration and a fresh output name; never overwrite code in place or reset a consumed live request claim. No existing production service restart, server reboot, ACL removal or purchase operation is part of rollback.

**Remaining authorization boundaries:** PR review/merge, independent artifact/OS authentication, actual target isolation checks, all host mutations/evidence staging, first live Amazon pilot, actual Walmart acquisition, and purchasing. These are separate gates; this release-preparation milestone crosses none of them.

## Separate future fee acquisition approval (not implemented or executed here)

M80's 42-request authorization does **not** cover fee estimates. If the owner cannot provide independently reviewed saved estimates, a separately reviewed fee-only acquisition pilot would need a new exact ASIN/account/marketplace/price allowlist, fresh explicit permission, immutable request accounting, no retries/replay and its own transport/security tests before execution. Do not append calls to M80 or reuse its permission.

Proposed maximum for the same twenty products: **two HTTP attempts** (one LWA authentication attempt plus one `POST https://sellingpartnerapi-na.amazon.com/products/fees/v0/feesEstimate` with up to twenty explicitly priced ASIN entries). No fallback to twenty individual calls, refresh, retry or pagination. Freeze exact US marketplace, ASIN, New condition review, FBA fulfillment, conservative observed selling price/currency, explicit shipping assumptions and correlation identifiers in the reviewed payload. Any uncertainty/mismatch consumes the claim and blocks downstream fee qualification.

Amazon documents a default batch usage plan of 0.5 requests/second, burst1; honor lower returned limits and Retry-After by stopping, never automatic retry. Owner must verify current seller authorization and developer/application Pricing/Product Listing permissions against the provider's current role matrix before approving. The batch estimate is not a fee guarantee, storage/other costs still need explicit evidence, and it does not prove FBA permission or invoice acceptability. Recheck current usage/charges with the account owner; no paid service or API acquisition is enabled by this proposal.

Sources reviewed 2026-11-03: [batch operation/usage](https://developer-docs.amazon.com/sp-api/reference/getmyfeesestimates), [batch maximum and prerequisites](https://developer-docs.amazon.com/sp-api/docs/get-product-fees-batch), [operation role matrix](https://developer-docs.amazon.com/sp-api/docs/product-fees-api). Revalidate provider documentation before implementing or approving that separate pilot.

Archived acquisition plans retain every original source directory as a deny-write boundary,
including M76/M77 roots inherited through M79. Downstream report/history paths are checked
against these roots even when the optional handoff is omitted. These archived boundaries
are compared as validated absolute directory names; their original files need not be
available or readable on the reporting host. Actual staged inputs still receive strict
nonsymlink, single-link, byte-pin and read-only journal checks. No authority-path guard is
relaxed for evidence: only Git-authenticated release **source code** names (for example
`m77_authorization.py`) use the separate exact source-map verifier.
