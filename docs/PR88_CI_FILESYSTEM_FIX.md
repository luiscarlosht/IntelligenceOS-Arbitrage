# PR #88: nonroot filesystem CI failure

## Cause and reproduction

Tests run 42255975414 on Ubuntu 24.04 / Python 3.12 failed with 3,570
passed, five failures and 106 setup errors. Its runner is nonroot. M90.3a
`FixtureFS` opened `/` and every ancestor using `O_NOATIME`. Linux requires
matching inode ownership or `CAP_FOWNER` for that flag; readable/searchable
root-owned `/` and `/tmp` therefore produce `EPERM` for the runner.
See the [Ubuntu 24.04 open(2) manual](https://manpages.ubuntu.com/manpages/noble/man2/openat.2.html).

The five M90.2b failures have the same cause. Synthetic tests change `OWNER`
and `ANCHOR`, but the descriptor walk still started at `/` with `O_NOATIME`.
`verify()` sanitized this underlying permission error to `VERIFICATION_BLOCKED`.
Tests expecting rejection passed early, masking their intended deeper checks.

The original focused tests pass as root (177 passed). Two new regressions reject
no-atime opens on traversal ancestors even as root: both fail against the old
modules, confirming that the patch repairs the triggering operation. The local
sandbox maps only UID 0 and prohibits switching to another UID or remapping it;
local nonroot execution was attempted but unavailable. Attempt 2 of the original CI run reproduced the exact same 5 failures,
3,570 passes and 106 errors on Ubuntu 24.04.5 as runner UID 1001
(job 128032075682, full suite 412.98 seconds). An explicit nonroot focused
step now precedes the full suite on the Ubuntu GitHub runner.

## Correction and preserved boundaries

Use `O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC` only for ancestors above
the protected fixture boundary. These descriptors support relative lookup/stat
but cannot enumerate directory entries, read data or fsync. Traversal does not
update directory atime. They are never substituted following an open failure.

Fixture roots, protected descendants, files and locks retain strict readable
`O_NOATIME` descriptors. M90.2b production has fixed `ANCHOR=/`, so every
production component retains the original no-atime requirement. No UID, owner,
mode, hardlink, symlink, device, inode, snapshot, reviewed-lock, history, journal,
nonce, durability, provenance or authority checks are relaxed. Missing required
flags and denied protected no-atime access still fail closed. No credentials,
production state, Amazon APIs, merge or deployment are involved.

## Validation

- Baseline rerun: [attempt 2](https://github.com/luiscarlosht/IntelligenceOS-Arbitrage/actions/runs/42255975414/attempts/2), 5 failed / 3,570 passed / 106 errors.
- Original focused tests: 177 passed as root.
- New ancestor regressions against original modules: 2 failed as expected.
- Corrected M90.2b / M90.3a focused tests: 181 passed.
- Corrected local full suite (Ubuntu 24.04.4, Python 3.12.3, UID 0):
  3,676 passed, 9 skipped in 1,083.26 seconds. Optional wheelhouse was not supplied.
- GitHub final validation is checked after publishing this commit; the workflow
  enforces nonroot execution for the focused filesystem tests and runs the full suite.
- Both documented offline orchestrator modes: succeeded.
