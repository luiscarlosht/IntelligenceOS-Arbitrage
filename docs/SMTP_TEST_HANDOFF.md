# SMTP reuse and authorized DEMO email — DNS BLOCKED

The owner explicitly authorized inspecting WeinsteinAgent and sending the already
generated DEMO report using the existing addresses. Earlier no-access/no-send
constraints were superseded for this specific email task. No WeinsteinAgent code,
configuration, cron, service or environment file was modified.

## Existing mechanism and exact active non-secret settings

Inspected [email_config.py](https://github.com/luiscarlosht/WeinsteinAgent/blob/main/email_config.py),
[weinstein_mailer.py](https://github.com/luiscarlosht/WeinsteinAgent/blob/main/weinstein_mailer.py)
and [attachment sender](https://github.com/luiscarlosht/WeinsteinAgent/blob/main/WeinsteinMinimalEmailSender.py).
Local copies matched the inspected remote Git blob hashes. The loader resolves
`notifications.email` plus private environment overrides. Its YAML defaults are
Gmail, but **active environment overrides select SendGrid**, so those defaults
must not be mistaken for the actual relay.

| Setting | Confirmed active configuration / mapping |
| --- | --- |
| Provider | Existing SMTP mechanism; no new account or purchase |
| `SMTP_HOST` | `smtp.sendgrid.net` |
| `SMTP_PORT` | `2525` |
| `SMTP_SECURITY` | `starttls`, using this project's mandatory verified TLS |
| `SMTP_USER` | Existing configured SMTP username; SendGrid documents the literal `apikey` |
| `SMTP_PASSWORD` | Existing secret resolved by Weinstein `SMTP_APP_PASSWORD` / `SMTP_PASSWORD`; never printed or committed |
| `EMAIL_FROM` | Existing sender from the resolver; no new address requested |
| `EMAIL_TO` | Existing two recipients from the resolver; no new addresses requested |
| Attachment | `var/demo/DEMO.xlsx`; six DEMO tabs, fictional fixtures only |
| Subject run identifier | `DEMO — fictional fixtures only; never live deals` |

[SendGrid's official SMTP documentation](https://www.twilio.com/docs/sendgrid/for-developers/sending-email/integrating-with-the-smtp-api)
confirms `smtp.sendgrid.net`, API-key authentication and TLS on port 2525 (also
25/587). This task uses the already configured service and makes no claim about
its subscription/quota. No new key, plan or recipient was provisioned.

## Reuse decision

Reuse Weinstein's `load_email_settings` for addresses/provider/credential resolution,
then adapt that in memory into existing `app.config.Config` and
`app.mailer.send_report`. This preserves this project's verified TLS, 30-second
socket timeout and XLSX attachment path without adding a mail module or importing
any trading/data runner. The inspected Weinstein HTML helper lacks attachments;
its minimal attachment helper does not explicitly supply a verified SSL context.
Reusing the resolver with the existing report sender avoids copying either sender.
The original Weinstein code is unchanged.

The one-off operator script parses **only allowlisted email variables** from the
existing private environment source as data (never shell `source`/`eval`), calls
the existing resolver, disables core dumps and bytecode writes, validates the
expected provider/recipients and sends no unrelated report. Secret values stay in
the process and never enter command arguments, logs, Git, generated report or PR.
The script lives only in ignored `var/demo/send_with_existing_email.py` and is not
an automatic job, CI action, installed integration or new module. It hard-stops
unless the expected existing SMTP configuration is present. It writes an exclusive
private attempt marker to prevent automatic duplicate delivery. Python cannot
guarantee memory erasure or prevent swapping.

## Actual result, 2026-10-24 UTC

Configuration-only inspection confirmed an enabled SMTP provider, existing sender,
two recipients and a present credential without displaying values. An initial
expected-provider guard stopped before any network access when environment
overrides differed from Gmail defaults. It was corrected to the resolved SendGrid
settings. Exactly one SMTP connection attempt then failed with **`gaierror`** while
resolving `smtp.sendgrid.net`. No SMTP connection, TLS session, authentication,
message submission, provider acceptance or recipient receipt occurred. No retry
was made. The private marker records this attempt; it is not a delivery receipt.

The same sandbox also cannot resolve GitHub through shell Git, although the
connected GitHub plugin can publish code. No SMTP/email connector with the needed
existing configuration is available. The remaining blocker is DNS/outbound SMTP
from an authorized sending runtime, not missing email addresses or a request for
credentials. No firewall or production network denial was changed to bypass it.

On an authorized host with working DNS and outbound TCP 2525, the operator can
reuse the prepared script. Since the observed failure occurred before connection,
a subsequent operator-controlled attempt may archive the exact failed-attempt
marker as evidence and run once. Do not automatically clear markers or retry an
ambiguous post-submission failure. Keep the existing configuration unchanged and
do not log secrets. No further email settings need to be supplied in chat.

`app.mailer` supports STARTTLS or implicit SSL and paired authentication. Empty
`EMAIL_TO` disables delivery. SMTP errors after report generation make an
orchestrator job fail while retaining the workbook; structured logs/history store
exception class only. Direct callers must redact raw exception messages. There
are no automatic retries, OAuth/XOAUTH2, bounce tracking or inbox confirmations.
Acceptance by SMTP, if later achieved, must be distinguished from inbox receipt.

## Authentication-only SSH diagnostic (2026-10-26)

The separate `ops/smtp_auth_diagnostic.py` parses only allowlisted SMTP credential
assignments from `/root/.weinstein_env` as data. It never sources the file,
expands shell expressions, imports WeinsteinAgent, reads ambient credentials or
writes credentials. Duplicate assignments, shell references, malformed values and
ambiguous credentials stop before any network call. Secret values and provider
replies are never displayed. The existing sender and attempt marker are untouched.

Approved inspection found both `SMTP_APP_PASSWORD` and `SMTP_PASSWORD` nonempty.
The approved file alone does not establish resolver precedence; their equivalence
is not assumed. No credential was selected and no authentication was executed.

Run directly in an interactive SSH terminal:

```bash
python3.12 -B /root/IntelligenceOS-Arbitrage/ops/smtp_auth_diagnostic.py
```

With the current ambiguous configuration this stops, reporting variable names
only. Once the operator confirms the intended variable, select it explicitly by
adding `--credential-variable SMTP_APP_PASSWORD` or
`--credential-variable SMTP_PASSWORD`. These arguments contain names only, never
keys. The script reads the selected value directly into process memory; it does
not prompt for or persist a key, and never changes the source file.

The endpoint remains fixed at `smtp.sendgrid.net:2525`, username literal `apikey`.
It uses the system trust store with certificate and hostname verification, EHLO,
mandatory STARTTLS, EHLO again, authentication and socket close. It never calls
MAIL FROM, RCPT TO or DATA, enables SMTP debug output, or retries a connection.
SMTP login may negotiate supported AUTH methods. Core dumps are disabled;
Python cannot guarantee memory erasure or prevent swapping.

Exit 0 means authentication succeeded; exit 1 identifies the stopping stage and
exception class (or ambiguous variable names). Authentication success does not
establish sender authorization, message acceptance or inbox delivery. Tests use
synthetic credential files and mocked SMTP; no live authentication was performed.
The previous marker remains a reservation, not a delivery receipt. This diagnostic
does not require or permit archiving or removing it.

## Authentication disconnect review (2026-10-26)

The operator reports that both explicit variable selections reached authentication
and raised `SMTPServerDisconnected`, with no email submission. An approved local,
in-memory comparison of the resolved values returned **same**. No value, length,
hash, prefix or encoded form was recorded. The file was not changed.

The diagnostic calls Python's `smtplib.login('apikey', key)` with its default
`initial_response_ok=True`. Inspection of the installed Python 3.12 implementation
shows preference order CRAM-MD5, PLAIN, LOGIN, restricted to advertised mechanisms.
Thus advertising PLAIN and LOGIN selects PLAIN first, regardless of advertised
order. PLAIN and LOGIN can send an initial response; AUTH exchanges can include
334 challenges. A 535 (or other authentication rejection) becomes
`SMTPAuthenticationError`, which login catches before trying another supported
mechanism. `SMTPServerDisconnected` escapes immediately, with no next mechanism
or reconnect. The old output did not capture advertisements or selected mechanism;
the reported disconnect alone cannot identify either or establish an invalid key.

`TrackedSMTP` now reports allowlisted advertised AUTH labels after verified TLS,
counts unrecognized tokens without displaying them, reports each attempted
mechanism, and records numeric SMTP response codes through `getreply`, including
AUTH challenge codes. A disconnect without a response is labeled `code=unavailable`.
It never records wire commands, AUTH payloads, server reply text or exception text.
Unknown labels are redacted. SMTP debugging remains disabled. Authentication
selection/fallback behavior is preserved for diagnosis; there is no new live
attempt or change to production configuration. No submission command is used.

Mock-only tests exercise the real inherited login/auth implementation with all
protocol exchanges replaced, verifying preference, fallback after rejection,
no fallback after disconnect, challenge handling, and redaction. Separate tests
mock `getreply` to verify numeric codes and disconnect reporting. No actual
advertisement or response code from the user's earlier attempts is known.

## Temporary authentication failure policy

Authentication now stops immediately on every 400–499 AUTH response, including
responses received after a challenge or after an earlier mechanism's rejection.
`TrackedSMTP.auth` converts these failures to `TemporaryAuthenticationError`, a
separate SMTP exception that bypasses `smtplib.login`'s mechanism fallback. Only
the numeric code is retained in that exception; raw server text is not copied.
The socket is closed, with no reconnect or automatic retry. Existing redacted
response-code tracking remains active. Fallback after permanent 5xx authentication
rejections is unchanged. Verified STARTTLS and the literal `apikey` username remain.

This policy supersedes the earlier blanket description of fallback on authentication
rejection. Mocked tests cover temporary codes, failures after challenges, failure
on a later mechanism and cleanup; no live request was made. Account status needs
clarification before another send test. No further live attempts are authorized
by this change, and the previous attempt marker remains untouched.
