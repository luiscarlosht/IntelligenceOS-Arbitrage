# Confirm Gmail delivery and prepare inactive scheduled reports

The operator confirms Gmail API DEMO attempt 3 arrived at Hotmail with both
DEMO.xlsx and DEMO.md. Record that recipient-reported result without another
send, live refresh or mailbox read. Preserve every local attempt marker and the
existing root credential; exclude credentials, local env and runtime evidence
from Git.

Consolidate HTTPS transport validation, disabled inherited proxies, bounded
responses, no redirects/retries, private stage evidence and allowlisted Google
error reasons. Include the separately reserved operator helpers and mocked
regressions. Make the historical SMTP helper self-contained so CI no longer
imports an ignored runtime script; retain its hidden-input/literal parsing fixes.

Prepare separate **uninstalled, disabled** report service/timer templates and
empty example configuration. Activation and OAuth-readiness gates reject unready
runs before network access. Propose service-owned 0700 rotating-token state and
0600 tokens outside /root, reports and ordinary backups, preserving ProtectHome
and read-only code. Document Testing's seven-day refresh-token limit, publishing
review and fresh offline consent as deployment prerequisites. The proposed
06:15 UTC cadence and recipients/content still require owner approval.

Validation: 357 repository tests passed using synthetic credentials and mocked
transports; clean-export tests and both documented offline sample modes passed.
Pytest collection is confined to tests/ so ignored runtime diagnostics are not
imported; seven historical local-only tests account for the earlier 364 count.
Proposed unit syntax passed systemd-analyze verify on this host. Remote CI must
be checked against this PR's final head SHA and reported separately.

Remaining acceptance: actual host service-user/sandbox filesystem access,
appropriate OAuth publishing/fresh consent and explicit deployment/activation
authorization. UID ownership behavior is mocked locally because the preparation
sandbox cannot chown to another UID. API acceptance can be ambiguous on timeout;
there is no automatic resend. The scheduled job attaches one generated XLSX,
not the DEMO's extra Markdown. No production unit/timer, Cloud setting,
credential or existing attempt marker is changed; no new email is sent.
