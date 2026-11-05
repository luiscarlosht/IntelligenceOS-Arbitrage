# M89 authentication transport diagnosis — offline only

Starting commit: `753304d`. The authoritative ledger remains unchanged at
12/49 attempts used, 37 remaining. Its exact statuses are eleven COMPLETE and
one FAILED, rather than twelve successful/COMPLETE entries. Attempt 12's failure
metadata is in the cumulative ledger; no `receipt-12.json` was written. The M89
execution status remains STOPPED_NO_RETRY. Prior evidence/reports are never
rewritten or repaired.

## Findings

The historical failure records `AmazonFailure`, `transport_error`, no HTTP status,
no Amazon error code and no underlying errno. The shared HTTP adapter replaced
all non-HTTP transport exceptions with this generic failure and suppressed their
tracebacks. Consequently, the original DNS/TCP/TLS/proxy/timeout layer cannot be
proved retrospectively from the saved evidence.

Safe local diagnostics reproduce a concrete blocker: creating either an IPv4
or IPv6 stream socket raises PermissionError/EPERM (errno 1). The environment also
sets `CODEX_SANDBOX_NETWORK_DISABLED=1`. These probes do not resolve a hostname,
connect, send bytes or make HTTP requests. This confirms the current runtime
denies Internet sockets and strongly supports a sandbox restriction as the
historical cause. It does not prove whether the historical request first failed
at DNS or socket creation; the missing nested exception prevents that distinction.

The default TLS context initializes successfully with CERT_REQUIRED, hostname
checking enabled and 120 trusted CA certificates. No proxy or CA override
environment variables are present. The adapter deliberately disables inherited
proxies with `ProxyHandler({})`. A local TLS context is not a remote certificate
or TLS-handshake test. DNS, remote TCP, Amazon TLS, remote credential validity and
SP-API permissions remain UNTESTED.

M88 authentication receipts 1 and 8 record token_received=true. Their frozen
plans and the failed M89 plan all pin the same shared HTTP implementation:
`c2ceaae127e9faabffb387cffccb168ae9111c9182ec01466b5627dc53f61fc7`.
M88 and M89 use the same POST `https://api.amazon.com/auth/o2/token`, UTF-8 form
body, refresh_token grant, Content-Type application/x-www-form-urlencoded,
ten-second request timeout, verified TLS, no proxies and no redirects/retries.
The US marketplace is ATVPDKIKX0DER; marketplace IDs correctly belong to later
SP-API operations and are not token-exchange parameters.

The existing private research credential file passes ownership, mode, bounded
JSON and required-field validation. Its saved account binding matches, with US
marketplace and new_new condition. No credential/seller values appear in the
report. This validates local configuration only, not Amazon's acceptance.

## Corrective action

`amazon_pilot._request_json` now records a fixed transport category, safe nested
exception type, bounded numeric errno and stage (TLS-context setup, opener,
open or read). It still discards exception messages, URLs, headers, request bodies
and credential/token values. HTTP status and existing error handling remain intact;
there are no retries or changes to TLS/proxy/request policies.

`app.m89_auth_readiness` provides an offline-only command. A Python audit guard
blocks DNS, connect, send, HTTP and subprocess activity while permitting only
unconnected socket creation. It verifies frozen authentication receipts/plan
hashes, validates local credentials without printing them, probes local TLS/socket
readiness and verifies the preservation inventory before and after reporting.
It has no live execution or ledger-write operation.

The sandbox permission restriction cannot be fixed through application headers,
credential rotation, TLS weakening or proxy overrides. Use an approved
network-enabled runtime for any later live work; do not bypass the sandbox.
No host/network/seller configuration was changed during diagnosis.

## Retry decision

One live retry is **not justified in this blocked runtime**. A later explicitly
authorized authentication-only retry can be justified after an approved runtime
provides the required network access and passes local readiness. That future
operation must start from the real 12/49 ledger, reserve attempt 13 before
dispatch, stop after one outcome, and make no subsequent SP-API calls. A successful
socket probe alone would not prove DNS/TCP/TLS or credential validity. The old
M89 operation is already claimed and must not be replayed.

No live retry is implemented, attempted or authorized by this report.
`purchase_authorized=false`.

## Artifacts and validation

Runtime report: `var/m89-auth-readiness-v2/authentication-readiness.json` and
`authentication-readiness.md`, with a preservation manifest covering 126 prior
files. All hashes, including the authoritative ledger, are unchanged. Reports
and credential artifacts stay uncommitted.

Regression tests simulate nested URLError(PermissionError/EPERM), DNS failure,
certificate verification failure, other SSL failure, connection refusal,
unreachable network, timeout, response-read timeout and unclassified exceptions.
They check no secret text survives, no HTTP status is invented, no retry occurs,
and offline readiness never resolves or connects. The audit guard itself is
tested against dispatch events. M88 and M89 executor regression tests also pass.
Final counts and sample-mode validation are in runtime `validation-results.json`.
