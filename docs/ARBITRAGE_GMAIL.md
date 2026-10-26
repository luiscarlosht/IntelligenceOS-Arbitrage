# Arbitrage Gmail preparation

Inspection on 2026-10-26 parsed only email assignment literals in
`/root/.weinstein_env` and `/root/.bashrc`, without sourcing either file.
The former specifies SendGrid (`smtp.sendgrid.net:2525`, username `apikey`).
Both `SMTP_APP_PASSWORD` and `SMTP_PASSWORD` are SendGrid-shaped keys;
the variable name does not establish Google provenance. A full Gmail address
appears as sender, which does not establish a Gmail authentication username.
There are duplicate sender assignments. No email assignments matched in
`.bashrc`, so no cross-file conflict was identified. No verified Gmail
configuration or Google App Password was established. Neither file nor
WeinsteinAgent was modified; no credentials were copied.

`ops/arbitrage-gmail.env` is a separate, password-free configuration. It fixes
`smtp.gmail.com:587` with STARTTLS, leaves the Gmail username for terminal entry,
and leaves recipients empty. Existing services do not load it. It does not
activate delivery or change production schedules. The application's existing
SMTP transport already supports verified STARTTLS, but this file is only wired
to the operator diagnostic. Delivery activation requires separate authorization.

Run directly in an interactive SSH terminal:

```bash
/root/IntelligenceOS-Arbitrage/.venv/bin/python -B /root/IntelligenceOS-Arbitrage/ops/smtp_auth_diagnostic.py --config /root/IntelligenceOS-Arbitrage/ops/arbitrage-gmail.env
```

This command DOES authenticate when the operator runs it. Enter the full Gmail
address, then a separate Google App Password created for Arbitrage at the hidden
prompt. Never enter a SendGrid key or regular Google account password. Password
shape validation rejects obvious wrong inputs but cannot prove provenance; the
operator must obtain the password from Google. Spaces in Google's grouped
16-letter display are removed. No password is persisted, read from inherited
environment variables, supplied in arguments, or printed. Hidden entry requires
a controllable terminal and stops if terminal echo cannot be disabled.
Python’s Unix getpass opens `/dev/tty` directly with an unbuffered wrapper;
if unavailable, it checks stdin through `fileno()`. Unsupported stdin wrappers
stop safely. `GetPassWarning` is fatal before any visible fallback read.

The diagnostic disables core dumps, uses the default trusted CA store and
hostname verification, performs EHLO, STARTTLS, EHLO and AUTH, and closes the
socket. It never calls MAIL FROM, RCPT TO or DATA. It prints only fixed protocol
labels and numeric response codes, redacting exception/server text. Temporary
AUTH failures stop mechanism fallback; permanent rejections may cause Python's
login method to try another advertised supported method. No reconnect occurs.
Authentication success does not establish delivery.

This preparation ran mocked tests only. No live SMTP connection, TLS session,
authentication or email submission was performed. The older
`SMTP_TEST_HANDOFF.md` records historical SendGrid work; its diagnostic commands
and credential-selection options are superseded by this Gmail procedure.

## Hidden-entry regression verification

A local controlling pseudo-terminal reproduced `io.UnsupportedOperation: File
or stream is not seekable` at `open('/dev/tty', 'r+')`, before getpass or a
password prompt. Buffered read/write opening requires seeking. The redundant
open is removed; Unix getpass owns terminal opening and echo restoration.
Regression tests exercise real getpass with synthetic input in a pseudo-terminal,
verify echo is disabled at the prompt and restored afterward, and verify failures
in stdin `fileno()` or terminal echo control never read visible input.

The earlier 268-to-264 count change came from replacing SendGrid credential-file
selection tests with Gmail configuration/hidden-entry tests: 17 collected cases
were removed (ambiguity 1, selection 5, invalid files 10, missing variable 1),
and 13 added (invalid configuration 6, valid configuration 1, configuration
failure 1, invalid hidden input 4, grouped hidden input 1). This was a coverage
change, not four skipped or failing tests. The old hidden-entry tests mocked
getpass and open, so they could not catch the terminal wrapper failure.

## Approved bashrc authentication-only mode

A subsequent scoped, literal-only inspection found one `SMTP_USERNAME` (valid
Gmail address shape) and one nonempty `SMTP_APP_PASSWORD` (16-letter shape).
No duplicates were found. `SMTP_PASSWORD`, `SMTP_USER`, `SMTP_HOST`, `SMTP_PORT`
and `SMTP_SECURITY` were absent. This supersedes the earlier bashrc finding.
No secret values are recorded here; shape does not establish Google provenance
or show that a password is fresh. No older SendGrid credential is read or reused.

Run inside direct interactive SSH, after confirming the stored App Password
was issued by Google for this Arbitrage account:

```bash
/root/IntelligenceOS-Arbitrage/.venv/bin/python -B /root/IntelligenceOS-Arbitrage/ops/smtp_auth_diagnostic.py --bashrc /root/.bashrc
```

This mode reads only SMTP_/EMAIL_ assignment literals without sourcing bashrc,
expanding variables, executing substitutions or loading inherited secrets.
`SMTP_USER`/`SMTP_USERNAME` and `SMTP_PASSWORD`/`SMTP_APP_PASSWORD` are explicit
aliases; supplying both members of either pair is rejected even if equal.
Duplicate relevant names, nonliteral expressions and wrong provider settings
are rejected before connecting. Unrelated lines are ignored. Missing host,
port and security use fixed Gmail defaults (`smtp.gmail.com:587`, STARTTLS),
with certificate and hostname verification enforced by the diagnostic.
EMAIL_ values never cause delivery. This mode uses the approved stored password
without a password prompt; the separate-config mode retains fail-closed hidden
entry. Neither mode sends email or changes services/settings. The command does
perform authentication when the operator runs it; validation here used mocks.

## Authorized one-time Gmail DEMO test (2026-10-26)

`ops/gmail_demo_once.py --send` reuses the existing one-time sender's private
stage tracker. It parses approved `/root/.bashrc` assignments as literals,
keeps the password in memory, uses smtp.gmail.com:587 with verified STARTTLS,
and submits only to luiscarloshernandez@hotmail.com. Both existing DEMO.xlsx
and DEMO.md are attached when present. Subject and body explicitly identify
fictional DEMO data and disclaim live opportunities. One AUTH PLAIN operation,
15-second socket timeouts and a 120-second whole-attempt deadline apply.

The independent `var/diagnostics/gmail-demo.attempted` reservation prevents
repeat attempts. Existing SendGrid markers are preserved. Fixed stage records
are written to `var/diagnostics/gmail-demo.stages.jsonl`; DATA 250 acceptance
is distinct from inbox delivery. Any ambiguous submission stops without retry.
No production schedule, service or WeinsteinAgent configuration is changed.

The earlier diagnostic task is idle and records no live authentication by the
agent. A diagnostic launched separately in SSH is outside this sandbox's
process namespace; no authoritative result was available here. The network
preflight failed DNS (`gaierror`, errno -3) before authentication or submission.
No Gmail attempt marker was reserved. Run once directly over SSH:

```bash
/root/IntelligenceOS-Arbitrage/.venv/bin/python -B /root/IntelligenceOS-Arbitrage/ops/gmail_demo_once.py --send
```

## Non-sending OSError investigation (2026-10-26)

The saved Gmail stage log records `connection_banner` started at
15:49:38.399293 UTC and failed with OSError at 15:49:53.407989 UTC.
This locates the failure inside `SMTP.connect('smtp.gmail.com', 587)`;
DNS resolution, TCP connection and banner reading are inside that operation.
The approximately 15-second duration is consistent with the socket timeout,
but the historical log lacks errno and cannot prove the underlying cause.
`last_completed_stage` updates only after `tracker.call` returns, so it remains
`preflight` when this first SMTP operation fails. Credential parsing, attachment
construction, TLS context creation and marker creation/write/fsync already
completed. The existing Gmail marker predates connection and must be preserved;
no authentication or message submission started in this logged attempt.

Errors now report a fixed operation label and numeric errno (null when absent),
without exception messages, credential values or server responses. Preflight
operations including attachment reads and marker creation/fsync have their own
labels. Existing-marker protection still blocks sends; no marker reset is added.

Run this read-only diagnostic directly in SSH:

```bash
/root/IntelligenceOS-Arbitrage/.venv/bin/python -B /root/IntelligenceOS-Arbitrage/ops/gmail_demo_once.py --diagnose
```

It parses approved bashrc literals without execution, checks attachment reads,
inspects marker presence without writing, checks verified TLS configuration and
resolves Gmail DNS with a 10-second deadline. It never constructs an SMTP client,
connects, authenticates or submits. It cannot test TCP reachability or inbox
delivery. The sender retains its 15-second socket timeout and 120-second whole
attempt deadline (including DNS); neither timeout enables retries.

Validation: 297 tests passed, including redacted errno/preflight failure tests
and mocked DNS errors/deadlines. Both offline sample modes passed. Local literal
credential parsing and attachment reads passed with DNS mocked; no live DNS or
SMTP request was made. Gmail and SendGrid marker hashes remained unchanged.
