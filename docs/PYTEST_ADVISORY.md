# pytest advisory investigation — 2026-10-24

The repository pinned `pytest==8.3.5`; the development venv also runs 8.3.5.
[GHSA-6w46-j5rx-g56g / CVE-2025-71176](https://github.com/advisories/GHSA-6w46-j5rx-g56g)
lists versions before 9.0.3 as affected, with 9.0.3 patched. The upstream
[pytest changelog](https://pytest.org/en/stable/changelog.html#pytest-9-0-3-2026-04-07)
records the insecure temporary-directory fix in 9.0.3 (#14343). This is local UNIX
temporary-directory handling; it is not evidence of a remote application exploit.
No exploit attempt or shared temporary-directory manipulation was performed.

`requirements.txt` now pins **9.0.3**, the minimal documented fixed release, to
avoid leaving the advisory unresolved in new installations. The full Python 3.12
CI job installs this pin and runs the full tests, both sample modes and the DEMO.
No production dependencies were changed. `pip check` checks installed dependency
consistency, not vulnerabilities or agreement with the requirements pin.

Local installation of 9.0.3 failed: the restricted package source returned no
available versions, including a retry using the explicit official PyPI index.
The venv therefore remains 8.3.5; local test results must be labeled with that
version and cannot establish compatibility with 9.0.3. Existing local baseline:
203 tests; final local validation is recorded in the PR. Run the full CI against
the new pin before merging. An authorized operator can later stage a verified
9.0.3 wheel/dependency set in a development wheelhouse, install it without network
and rerun `python -m pytest -q` plus both samples. Do not call the existing venv
patched merely because the requirements file changed.

Remaining: verify successful patched-version CI/clean installation and confirm the
repository alert closes after merge. No claim of a comprehensive dependency/OS
vulnerability audit, production remediation or absence of other advisories is made.
