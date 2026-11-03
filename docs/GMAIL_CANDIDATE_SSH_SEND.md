# Fresh one-shot candidate-review email from interactive SSH

The prior attempt remains `gmail-ebay-candidate-review-20261027.*` under
`var/diagnostics/`. It failed during token_refresh after credential validation,
with a network-category error; message submission never started. No Gmail HTTP
rejection or acceptance was observed. Do not remove or reuse those records.

Credential-free diagnostics from the Codex shell failed DNS resolution for
Google OAuth, Gmail and GitHub (`gaierror`, errno -3). This session declares
restricted network access. A credential-free outbound TCP connection to a public
endpoint was denied with PermissionError / errno 1, confirming this execution
environment restricts outbound sockets. This is not evidence of invalid Gmail
credentials. The previous log did
not retain the underlying socket errno, so the historical root cause cannot be
proven more specifically. Direct interactive SSH networking is not tested here.
No credential read, token refresh or email was performed during diagnosis.

The prepared helper `ops/gmail_candidate_review_ssh_once.py` uses the existing
Gmail API integration and the exact previously verified workbook SHA-256:
`d6a7697436f2766eb776809842dccfcee087b08272d8ba18fa77e6892b495716`.
It validates the saved real 21-request report, ten ambiguous rows and zero exact
matches before using credentials. The same approved subject, plain-text summary,
sole recipient `luiscarloshernandez@hotmail.com` and workbook attachment remain.
The existing sender address is parsed as a literal without executing shell
configuration or loading SMTP passwords. No credentials/private configuration
are included in the message.

The fresh attempt uses separate, exclusive owner-only records:

- `var/diagnostics/gmail-ebay-candidate-review-ssh-1.attempted`
- `var/diagnostics/gmail-ebay-candidate-review-ssh-1.stages.jsonl`
- `var/diagnostics/gmail-ebay-candidate-review-ssh-1.outcome.json`

The helper reserves before OAuth or submission. One refresh and at most one
submission, no retries or fallback, a 90-second overall timeout and existing
30-second socket timeouts apply. It refuses an existing fresh-attempt record.
Gmail acceptance is distinct from recipient inbox delivery. If submission is
uncertain, preserve evidence and do not automatically repeat the command.
Credential refresh-token rotation, only if returned by Google, follows the
existing secure integration; no production configuration or schedule changes.

Verified offline with `--check`; it reads only the saved report/workbook, creates
no send attempt, and does not access credentials. Mocked tests verify recipient,
subject/body, attachment bytes, fresh reservation, replay protection and failures.

Run this in your direct interactive SSH terminal (not through Codex):

```sh
cd /root/IntelligenceOS-Arbitrage
.venv/bin/python -m ops.gmail_candidate_review_ssh_once --send
```

`--send` requires an interactive terminal and is not invoked during preparation.
The printed outcome and owner-only outcome JSON record acceptance/submission
flags without provider response bodies or secrets. All old reports remain intact.
