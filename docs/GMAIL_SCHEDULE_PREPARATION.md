# Scheduled Gmail reports — proposal only, not activated

As of 2026-10-26, the operator confirms that Gmail API DEMO attempt 3 reached
Hotmail with both attachments. This validates that particular manual send.
It does not establish service-user access, OAuth publishing status, durable token
lifetime or unattended scheduling readiness. No further test email is authorized.
See [delivery confirmation](GMAIL_API_DEMO_THIRD.md).

## Proposed execution

The separate units under `ops/proposed-systemd/` are review artifacts, not installed
units or modifications to the existing offline service/timer. They propose one
fictional mock discovery XLSX report per day at **06:15 UTC**, subject to owner
approval of cadence, sender, recipients and report content. No live market data
is enabled. The scheduled report attaches the generated XLSX only; the manually
confirmed DEMO's additional Markdown attachment is specific to that demo.

The example `ops/examples/gmail-report.env.example` has empty sender/recipients
and both activation and OAuth-ready flags false. The service additionally requires
`/etc/intelligenceos-arbitrage/gmail-delivery.enabled`, which this preparation
does not create. The service runs `python -m ops.gmail_scheduled_report`, which
rejects disabled/unreviewed, non-Gmail, missing-recipient, missing-stage-log and
repeating in-process configurations before report generation or network access.
The OAuth-ready flag is a human attestation, not a Google status query.

The proposed timer has `Persistent=false` to avoid a catch-up send on enable/boot.
The one-shot service has `Restart=no`, a 120-second start limit and a further
10-second termination grace. HTTP operations retain 30-second socket timeouts.
No retries or SMTP fallback occur. Each daily invocation is a new report job;
a failed job is not replayed. After an ambiguous submission, the operator must
inspect Sent/recipient evidence before deciding on any manual resend. systemd
serializes this unit, but do not run parallel manual jobs against its token/state.

## Protected credentials for the nonroot service

Keep `/root/.config/arbitrage-gmail/token.json` and all existing attempt markers
unchanged. The current service uses `User=intelligenceos-arbitrage` and
`ProtectHome=true`: it cannot use the root token path. Do not relax `/root`, make
the token group/world readable, remove ProtectHome or run the report as root.

For a separately authorized deployment, provision a dedicated private directory
outside the release, reports, backups and repository:

- `/var/lib/intelligenceos-arbitrage-gmail-private`: service owner/group, **0700**.
- Its `token.json`: same service owner, **0600**, regular file, no symlink path
  components, no ACL grants to other accounts. Transfer through a protected
  channel with verified host keys, using a private temporary destination and
  atomic publication. Never put token values in chat, shell arguments or env.
- `/var/lib/intelligenceos-arbitrage-gmail-report`: separate service-owned **0700**
  directory for report, history and owner-only redacted stage evidence.

The proposed unit's StateDirectory entries and ReadWritePaths admit these two
paths with ProtectSystem=strict. Owner-only writable **directory** access is
necessary: the adapter may atomically replace token.json after refresh-token
rotation. A read-only credential mount alone would break that persistence.
For this proposal use persistent service-owned private state, rather than treating
systemd's read-only LoadCredential snapshot as a writable token store. The manager
must never re-seed an older token over a rotated one on each run. Unix permissions
protect storage, not application encryption; use protected host storage as needed.

Keep the token directory out of general report/SQLite backups and support bundles.
Back up/recover credentials only through a separately protected process. The
application rejects foreign-owned or group/world-accessible token files and
unsafe rotation parents. Code under /opt remains read-only and root-managed.
The separate unit permits network address families for DNS/HTTPS; existing offline
network-denial settings and the existing 06:00 timer remain untouched. Google
requests disable inherited proxies, verify TLS and refuse redirects. Where host
policy restricts egress, DNS and verified HTTPS to Google's fixed OAuth/Gmail
endpoints must be approved at deployment; no firewall rule is changed here.

## OAuth Testing expiry is a deployment blocker

For an External OAuth project in **Testing**, gmail.send authorizations and
refresh tokens expire after **seven days**. Enabling Gmail API does not change
publishing status, extend that lifetime or establish a new consent date. This
checkout has no verified consent-issuance date or publishing-status evidence;
do not invent an expiry date from the date of DEMO receipt.

Before enabling unattended delivery, the owner must review Google Auth Platform
Audience/publishing status and applicable sensitive-scope verification or
personal-use exceptions for project hale-inn-469716-f7. Resolve the appropriate
production publishing requirements, then obtain **fresh offline consent** for
exactly gmail.send with the existing local-browser authorization procedure and a
new private token filename. Production publishing alone must not be assumed to
repair an older Testing token. Do not expand to mailbox-reading scopes or purchase
Workspace as a workaround. Do not change Cloud consent settings in this task.

Production refresh tokens can still expire or be revoked. On invalid_grant,
stop delivery, review the safe stage reason and reauthorize interactively; retries
cannot repair revoked consent. Establish an operator failure-monitoring process
before activation, without including credential values or raw responses.

## Later deployment acceptance — not performed here

The merge/deployment, token provisioning, consent changes and schedule activation
require a separate instruction. Before activating, validate installed paths,
service account, ownership/modes, write/replace permission on the private token
parent and network policy under the actual service sandbox. A file-only check
with synthetic credentials can test read/rotation without contacting Google;
never use an email send as the permission check. Verify that report/backup
selection excludes private credential state. Verify unit syntax offline.

Only after those checks, approved publishing/fresh consent, recipient/content/
cadence review and explicit activation authorization should an operator provision
configuration and enablement file and install/enable the proposed timer. Do not
start the service to "validate" it: a ready configuration sends a message.
Rollback would disable only the new timer, remove its activation file and set
its enable flag false; leave existing offline schedules, credentials and attempt
evidence intact. No installation, daemon-reload, timer enable/start or test send
was performed during this preparation.

## Validation and sources

Mocked tests cover inactive/readiness gates, configuration rejection, safe OAuth
error reasons and synthetic owner-only token read/atomic rotation with foreign-UID
validation. A real host service-account/sandbox permission check remains pending:
the preparation sandbox could not chown to another UID. Clean-export tests must
pass without local credentials, markers, reports or ignored helper scripts.

Official references checked 2026-10-26:

- [Google refresh-token expiry](https://developers.google.com/identity/protocols/oauth2#expiration)
- [Sensitive-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)
- [systemd private state and read-only credentials](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
