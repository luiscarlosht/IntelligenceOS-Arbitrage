# One-time OAuth refresh diagnostic

Prepared for the operator to run directly over SSH; no live request was made
by Codex. This script reads only the dedicated Arbitrage token file, posts once
to Google's fixed HTTPS token endpoint, and never calls any Gmail endpoint.
It does not authorize, read a mailbox, send email or change production settings.

```bash
env -i HOME=/root PATH=/usr/bin:/bin \
  /root/IntelligenceOS-Arbitrage/.venv/bin/python -I -B \
  /root/IntelligenceOS-Arbitrage/ops/gmail_refresh_diagnostic.py
```

Input: `/root/.config/arbitrage-gmail/token.json`. The directory must be
owner-only 0700 and credentials private, regular and owned by the executing
user. Existing email markers are never consulted or changed.

Before network activity, the script exclusively creates a separate private
`/root/.config/arbitrage-gmail/refresh-diagnostic.attempted` reservation.
Subsequent invocations stop without another request. Preserve this reservation
even after timeout; no reset command is provided.

One POST maximum, no retry, verified TLS, no redirects or environment proxies.
Socket timeout is 15 seconds and the whole process has a 40-second alarm,
including DNS and response reads. Response parsing is bounded to 64 KiB.
No debug logging, exception text, token values, OAuth descriptions or provider
payloads are printed. Core dumps are disabled.

Output contains only `success` (boolean), `http_status` (numeric or null), and
`oauth_error` (recognized allowlisted name or null). Exit code is 0 for success,
1 otherwise. Null status means no status was captured; it does not prove Google
never received the request. HTTP 200 with success false indicates an invalid or
unexpected token response, including an unexpectedly broad returned scope.
Unknown provider errors are suppressed. No raw response is persisted.

Access tokens and any returned replacement refresh token are discarded; the
input credential file is not modified. A successful diagnostic confirms refresh
only, not message-submission permissions, acceptance or inbox delivery. A
returned rotation is deliberately not applied by this diagnostic. An
`invalid_grant` can reflect expiration/revocation or other authorization issues;
it does not prove a specific cause. Do not rerun or reauthorize automatically.
