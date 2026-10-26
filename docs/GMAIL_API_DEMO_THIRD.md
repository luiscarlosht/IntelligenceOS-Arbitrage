# Gmail API DEMO attempt 3 — inbox delivery confirmed

The operator reports Gmail API enabled in project hale-inn-469716-f7.
No live call was made to verify that change. Attempt 3 uses the existing token
at `/root/.config/arbitrage-gmail/token.json`, the sole recipient
`luiscarloshernandez@hotmail.com`, and both existing `var/demo/DEMO.xlsx` and
`var/demo/DEMO.md` attachments. No credentials are read during preparation.

The new helper is `ops/gmail_api_demo_third.py`. Its independent exclusive
reservation is `var/diagnostics/gmail-api-demo-3.attempted`; redacted stage evidence
is `var/diagnostics/gmail-api-demo-3.stages.jsonl`. The reservation is created
only when the operator runs the command. All previous markers and stage evidence
are preserved. Never delete a marker to retry. Reservation is not proof of send;
API acceptance is not proof of inbox delivery. Failure after submission starts
can mean an ambiguous outcome.

Requests have 30-second socket timeouts and a 90-second whole-command alarm.
There is at most one refresh and one submission; no retries, redirects, SMTP
fallback or schedule changes. Both existing attachments are required and hashed
in the owner-only reservation. The subject explicitly identifies DEMO attempt 3.

HTTP failures record numeric status and known Google reason identifiers only,
including legacy accessNotConfigured and structured SERVICE_DISABLED reasons.
Error bodies are read with a 16 KiB limit; messages, metadata, URLs, headers,
credentials and unknown reason strings are never logged. Malformed, oversized
or unknown errors retain HTTP status and stage but omit reason details.
The reason list is filtered again by the stage writer. JSON stdout shows the
attempt and submission/acceptance flags; inspect the stage log for safe reasons.

## Operator confirmation recorded 2026-10-26

The operator confirms that Gmail API attempt 3 arrived at
`luiscarloshernandez@hotmail.com` in Hotmail with **both DEMO.xlsx and DEMO.md**.
This is recipient-reported inbox delivery, beyond API acceptance. The exact
receipt timestamp was not supplied. No additional email, refresh or mailbox
read was performed to record this confirmation. Existing token files and all
attempt reservations/stage evidence are preserved outside Git. **Do not rerun
attempt 3 or remove its reservation.** The earlier preparation text above is
historical; it does not describe the subsequently operator-executed command.

Scheduled delivery remains a separate, inactive proposal; see
[Gmail scheduling preparation](GMAIL_SCHEDULE_PREPARATION.md).

Inspect redacted evidence afterward:

```bash
cat /root/IntelligenceOS-Arbitrage/var/diagnostics/gmail-api-demo-3.stages.jsonl
```
