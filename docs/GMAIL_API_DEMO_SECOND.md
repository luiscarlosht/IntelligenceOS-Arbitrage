# Gmail API DEMO attempt 2 — prepared, not executed

The operator reported a refresh diagnostic result of success=true, HTTP 200,
oauth_error=null. That establishes refresh at that time, not historical demo
failure cause or submission success. The original demo has no historical API
stage evidence, so its outcome remains unknown. Inspect Sent mail before deciding
whether to run this second, separately identified attempt.

Comparison:

- Both paths read the same private token structure and form-encode client_id,
  client_secret and refresh_token for the same fixed HTTPS endpoint. Neither
  uses SMTP/App Passwords. The diagnostic discards refresh-token rotations;
  application delivery persists a returned replacement atomically before send.
- Application HTTP previously inherited environment proxies; the successful
  diagnostic explicitly disabled them. Application requests now disable proxies
  too. Proxy influence on the historical failure is unproven. Both paths refuse
  redirects and use verified TLS; application POST is now explicit.
- Regression mocks demonstrate that the old application accepted an explicitly
  empty returned scope, an incompatible token_type, error-bearing refresh
  responses with access_token, and nonstring replacement refresh tokens. These
  now stop before submission. Missing token_type remains supported; an explicitly
  supplied type must be Bearer. Credential fields must be nonempty strings;
  returned message IDs must be nonempty strings. JSON responses are object-only
  and size bounded. These are demonstrated validation defects, not established
  causes of the earlier stop.
- MIME serialization/base64url round-trip reproduces the Unicode subject, exact
  To header and both attachment bytes. No original serialization defect found.
  Acceptance is only recorded after validating the returned message ID.

Attempt 2 is a repository-native operator command in
`ops/gmail_api_demo_second.py`; it does not depend on the ignored first helper.
It uses fixed token path `/root/.config/arbitrage-gmail/token.json`, fixed sole
recipient `luiscarloshernandez@hotmail.com`, and existing `var/demo/DEMO.xlsx`
and `var/demo/DEMO.md`. Both attachments are required. It labels the subject as
fictional DEMO and attempt 2, with no live opportunity/purchase approval claims.

Independent evidence paths:

- `var/diagnostics/gmail-api-demo-2.attempted`: exclusive owner-only reservation
  before any work or network, then attachment hashes; never a delivery receipt.
- `var/diagnostics/gmail-api-demo-2.stages.jsonl`: owner-only redacted stage
  events with last completed stage, submission-started/acceptance flags, numeric
  HTTP status/errno and fixed error categories. No credential/provider contents,
  addresses, message IDs, exception messages or tokens are logged.

Thirty-second socket timeouts and a 90-second whole-attempt alarm bound the
command, including DNS. At most one refresh request and one message submission;
no redirects, retry, SMTP fallback, mailbox reading, schedule or deployment.
Existing email and refresh diagnostic reservations remain untouched. A second
invocation stops at its own marker without another network request. Preserve
the new marker even on local failure or ambiguous submission. A timeout after
submission starts does not prove non-delivery.

Run only directly in SSH when ready to perform the second send. Enter the
authorized primary Gmail sender address (not any credential):

```bash
read -r -p 'Authorized Gmail sender address: ' arbitrage_demo_sender
env -i HOME=/root PATH=/usr/bin:/bin \
  /root/IntelligenceOS-Arbitrage/.venv/bin/python -I -B \
  /root/IntelligenceOS-Arbitrage/ops/gmail_api_demo_second.py \
  --sender "$arbitrage_demo_sender" --send
unset arbitrage_demo_sender
```

Preparation used mocked HTTP only. No live refresh or send was executed.
