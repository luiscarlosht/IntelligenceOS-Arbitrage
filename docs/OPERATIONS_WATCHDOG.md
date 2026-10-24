# Disk enforcement, restore proof and external watchdog plan

Prepared 2026-10-23 UTC. Code and units are proposed; **nothing is installed or
sent**. Existing reporting services/release/network settings are preserved.
This supplements [deployment review](BACKUP_MONITOR_DEPLOYMENT_REVIEW.md); do not
run install/send blocks until separately authorized. No accounts, subscriptions,
recipients or credentials were accessed. Live product/Amazon access stays disabled.

## What is implemented locally

- Backup default application budget: 1 GiB including directory overhead, lock,
  all existing valid/invalid/unknown/pending files, counted as the greater of
  logical and allocated bytes. Symlinks/special files fail closed without deletion.
  Before copying, require `used + 1.2 * logical_database_bytes + 64 KiB <= budget`
  and enough free space for that allowance plus 256 MiB reserve. Check the source
  filesystem reserve separately. Manual and scheduled backup/restore/verification
  operations use the same nonblocking flock; contention fails safely.
- Recheck the budget and backup reserve on each SQLite 128-page copy callback and
  before publication. On failure, remove only this operation's pending directory;
  do not prune old snapshots to make room. Retention still keeps the newest 14
  valid snapshots after publication. Unknown/corrupt data is preserved and counts
  against the budget. `.backup.lock` is reserved for tooling; do not remove it
  while any operation is active. Other data in that directory needs investigation.
- This is **not a filesystem hard quota**: a copy chunk, SQLite allocation or
  unrelated concurrent filesystem writer can cross a threshold between checks.
  Initial admission is conservative; an overrun aborts the pending backup and
  preserves prior snapshots. OS/project quotas would need separate infrastructure
  review. Capacity planning and disk/usage investigation still matter.
- Monitor now checks the backup mount's free space and total directory budget as
  well as the history mount. CLI policy flags let reviewers choose explicit limits.
  Dispatcher currently uses the defaults, so keep all three at 1 GiB/256 MiB/30 h
  for the first rollout; differing policies require a reviewed dispatcher change.
- Restore checks capacity on its destination, reserves two database sizes plus
  64 KiB and 256 MiB, and requires a new destination with no sidecars. It copies
  to a private temporary file, verifies integrity and foreign keys and streams
  exact typed-row comparison (schema, data including duplicate rows, indexes,
  triggers/views) before atomic no-overwrite publication. It repeats sidecar
  checks just before publication. Use a private drill directory; there is no
  atomic lock on all possible sidecar filenames against arbitrary other writers.
- `verify-restore` repeats verification against the immutable snapshot, not newer
  live history. Row order is intentionally strict; a logically equivalent
  independently rebuilt database with different row/schema ordering can fail.
  Output contains snapshot hash, logical content hash and **verification** UTC time,
  not business data. It never changes capture timestamps. Large rows/BLOBs can
  cost CPU/memory; units retain a five-minute timeout and 128 MiB cap.

A snapshot checksum detects alteration, not authenticity against a compromised
application account. Same-host backup is still neither encryption nor host-loss
protection. Successful local restore tests are not production recovery evidence.

## Failure notification and watchdog boundary

| Component | Runs where | What it detects / dependency |
| --- | --- | --- |
| Backup and monitor | This VM, network denied | Disk admission, stale/corrupt/missing data and failed checks; cannot notify if VM dies |
| `app.ops_dispatch` | This VM, separate proposed unit | Runs health checks and reads loaded reporting/backup/monitor unit results plus active timers every 15 minutes; no success ping if these checks fail/unavailable. Still shares VM/systemd/power/network fate |
| External heartbeat receiver | Hosted service or a **different already owned host** | Receives healthy pings or `/fail`; alerts when expected pings stop. This is the VM-failure-independent part; it also detects outbound network/DNS/systemd failures as silence, without identifying the cause |
| Human notification integration | Receiver + owner-chosen destination | Delivers and escalates alerts; requires an actual recipient and receipt/acknowledgement test |

A same-VM Healthchecks/ntfy server or a second same-VM process is **not independent
of VM failure**. An external receiver does not back up the database and does not
prove restored business records. It has its own availability risks; periodic
human receipt checks and a second channel are advisable when available.

### Free options, official sources checked 2026-10-23

1. **Hosted Healthchecks.io:** [pricing](https://healthchecks.io/pricing/) lists
   Hobbyist $0/month for 20 jobs and 100 log entries/job. One aggregate operations
   check fits that advertised quota. Account creation and destination setup are
   owner actions; no account was created. Do not enable paid SMS/phone features.
   [Schedule documentation](https://healthchecks.io/docs/configuring_checks/)
   defines period/grace: propose 15-minute period and 15-minute grace, so silence
   alerts about 30 minutes after last success, subject to receiver/delivery delay.
   [Pinging API](https://healthchecks.io/docs/http_api/) supports success and failure
   signals; our sender uses HTTPS only and empty heartbeat bodies. Its secret URL
   must remain private. [Notification guide](https://healthchecks.io/docs/configuring_notifications/)
   supports email/integrations and email reminders; verify selected channel's
   actual free entitlement and recipient receipt in the owner's account.
2. **Self-host Healthchecks on an existing separate host:** [official guide](https://healthchecks.io/docs/self_hosted/)
   describes open-source BSD-licensed software. No software subscription is required,
   but host, TLS, patching, storage and outbound delivery are real responsibilities,
   not guaranteed $0 services. It must be outside this VM's failure domain. Do not
   deploy it to another project or buy a new host under this task.
3. **Optional ntfy-compatible failure/recovery destination:** [publishing guide](https://docs.ntfy.sh/publish/)
   documents HTTPS POST and token authentication; [configuration](https://docs.ntfy.sh/config/)
   covers ACLs/self-hosting. The optional sender emits only fixed failure/recovery
   text. An existing private authenticated instance can avoid a software
   subscription; hosting/relay costs and permissions still need confirmation.
   Public topics are not private notification channels. No hosted private-topic
   free entitlement or push-delivery guarantee is claimed. ntfy alone is not a
   missed-heartbeat watchdog. Prefer receiver-managed email first to avoid this
   second dependency unless the owner already has an authorized instance.

No external choice blocks implementing/testing this PR. **Activation only** needs
a receiver choice (hosted free Healthchecks or an existing external instance),
a recipient/backup operator and optional private notification destination. Supply
these through an approved secure setup process, not secret values in chat.

## Sender configuration and behavior

`templates/operations-notifications.json` is disabled and contains no destination.
`app.ops_dispatch` defaults to dry-run: it does not read config, write delivery
state or send anything. Explicit `--send` plus a private config is required.
Only HTTPS port 443 to explicitly configured hostnames is accepted; URL userinfo,
query/fragment, whitespace and redirects are rejected. Verified TLS is mandatory;
environment proxy inheritance is disabled. Each request has a 10-second socket
inactivity timeout and bounded response read; systemd's five-minute limit is the
whole-process bound. No endpoint, token, response body or raw error is logged.

Heartbeat is attempted every send-mode run; failed checks use `/fail`. Optional
notification POSTs are sent on first failure, changed recovery or six-hour failure
reminder. Delivery state is private and atomically replaced only for acknowledged
notifications; failed sends retry on the next 15-minute run, not an unbounded retry
loop. Endpoint failures are recorded as fixed issue codes. Two destinations are
attempted independently. No exactly-once claim: crash after delivery before state
commit can duplicate a message. Sender silence is caught externally. HTTP success
is acknowledgement by the endpoint, not evidence a human received the alert.

The current checks poll persistent failure/staleness; a transient unit failure
that recovers between polls can be missed. A live long-running reporting job can
briefly appear unsuccessful in the latest-history check; a `/fail` then recovery
is conservative, not proof of corruption. No OnFailure production drop-in is
installed. Use external reminder/escalation settings and operator review; code
reminders do not prove human acknowledgement or escalate to a second person.

## Concrete staged installation plan (not executed)

1. Complete host identity/capacity read-only checks and stage the reviewed immutable
   operations release using BACKUP_MONITOR_DEPLOYMENT_REVIEW.md. Its reporting
   pointer remains unchanged. Require tests/verified offline wheelhouse. The
   backup/monitor default flags now enforce policy; install only disabled units.
2. Run one authorized backup, a new-path restore and `verify-restore` below. Save
   redacted proof in restricted operational evidence; record actual restore time,
   data comparison, sizes/free space and UID/modes. Stop on any failure. Do not
   increase budgets or prune backups to hide a failure.
3. Stage the new dispatcher in dry-run with its own state directory and network
   denial. It should report unavailable/inactive timers until approved scheduling
   exists; this is expected and must not be bypassed by a fake success heartbeat.
4. After receiver/destination choice and separate network/send authorization,
   configure external period/grace/integrations and a private systemd credential,
   review the sender's narrow egress override, then perform delivery acceptance.
5. Enable backup/monitor timers after their drill succeeds. Enable dispatcher timer
   only after receipt and external-silence tests. Observe 24 hours and the 15th
   successful backup retention event. Do not alter reporting services or their
   security/network settings. A documentation/code merge is not installation.

The following commands assume variables from the main runbook (`OPS_RELEASE`,
`APP_USER`, `APP_GROUP`, `STATE`, `BACKUPS`, `SNAPSHOT`, `DRILL`) and an authorized
operator. They are review commands, not executed in this task:

```bash
(cd "$OPS_RELEASE" && runuser -u "$APP_USER" -- "$OPS_RELEASE/.venv/bin/python" -m app.backups verify-restore --snapshot "$SNAPSHOT" --destination "$DRILL/recovered.sqlite3")
for suffix in service timer; do
  test ! -e "/etc/systemd/system/intelligenceos-arbitrage-dispatch.$suffix"
  test ! -L "/etc/systemd/system/intelligenceos-arbitrage-dispatch.$suffix"
done
test ! -e /etc/systemd/system/intelligenceos-arbitrage-dispatch.service.d
install -o root -g root -m 0644 "$OPS_RELEASE/ops/systemd/intelligenceos-arbitrage-dispatch.service" /etc/systemd/system/
install -o root -g root -m 0644 "$OPS_RELEASE/ops/systemd/intelligenceos-arbitrage-dispatch.timer" /etc/systemd/system/
install -d -o root -g root -m 0755 /etc/systemd/system/intelligenceos-arbitrage-dispatch.service.d
cat > /etc/systemd/system/intelligenceos-arbitrage-dispatch.service.d/operations-release.conf <<UNIT
[Service]
WorkingDirectory=$OPS_RELEASE
ExecStart=
ExecStart=$OPS_RELEASE/.venv/bin/python -m app.ops_dispatch --history $STATE/history.sqlite3 --backups $BACKUPS --state-directory /var/lib/intelligenceos-arbitrage-dispatch
UNIT
systemd-analyze verify /etc/systemd/system/intelligenceos-arbitrage-dispatch.service /etc/systemd/system/intelligenceos-arbitrage-dispatch.timer
systemctl daemon-reload
systemctl start intelligenceos-arbitrage-dispatch.service
```

Dry-run may return nonzero for missing/inactive backup/monitor timers; inspect the
fixed issue codes, then stop. It sends nothing and does not require credentials.
Do not mask real health failures to pass acceptance. Keep dispatcher timer disabled.

### Send-mode override, only after external configuration and explicit authorization

Owner first creates/selects the external receiver and activates its email or other
approved integration to a confirmed recipient. Record the receiver check name,
period 15 min, grace 15 min and escalation/reminder policy outside Git. Use a test
check for acceptance. The secret ping URL is entered only through a secure editor
or existing secret-management process. Optional ntfy destination must be private
and approved; it can be omitted for receiver-managed email.

```bash
NOTIFY_CONFIG=/etc/intelligenceos-arbitrage/notifications.json
test ! -e "$NOTIFY_CONFIG"
test ! -L "$NOTIFY_CONFIG"
install -o root -g root -m 0600 "$OPS_RELEASE/templates/operations-notifications.json" "$NOTIFY_CONFIG"
sudoedit "$NOTIFY_CONFIG"
```

In that private file the operator sets `enabled` to true, adds the external
`heartbeat_url` and its hostname to `allowed_hosts`, and optionally supplies the
private ntfy topic URL/hostname/token. Do not print the file to a terminal log.
`read_config` validation runs inside the service; secret URLs never appear in
ExecStart or shell history. No API credentials for Amazon are involved.

Review endpoint IP ranges and the VM's DNS resolver path with the host operator.
The following accepts **nonsecret** approved endpoint/resolver IPs or CIDRs, validates
them before writing a unit override, and retains deny-by-default cgroup filtering.
DNS may require the local resolver or explicitly approved resolver addresses.
Do not permit all of the internet just to make a test pass. IP changes can cause
delivery failure and require operator review; the external receiver detects silence.
Application requests additionally restrict destination hostname, HTTPS and port443;
unit IP rules themselves do not restrict destination ports.

```bash
read -r -p 'Approved endpoint and DNS IP/CIDRs separated by spaces: ' NOTIFY_EGRESS_CIDRS
python3.12 - "$NOTIFY_EGRESS_CIDRS" <<'PY'
import ipaddress, sys
values = sys.argv[1].split()
if not values: raise SystemExit('Approved egress addresses required')
for value in values:
    network = ipaddress.ip_network(value, strict=False)
    if network.prefixlen == 0: raise SystemExit('Default routes are not approved egress')
PY
cat > /etc/systemd/system/intelligenceos-arbitrage-dispatch.service.d/send.conf <<UNIT
[Service]
LoadCredential=notifications.json:$NOTIFY_CONFIG
ExecStart=
ExecStart=$OPS_RELEASE/.venv/bin/python -m app.ops_dispatch --history $STATE/history.sqlite3 --backups $BACKUPS --state-directory /var/lib/intelligenceos-arbitrage-dispatch --send --config %d/notifications.json
RestrictAddressFamilies=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
IPAddressDeny=any
IPAddressAllow=localhost $NOTIFY_EGRESS_CIDRS
UNIT
systemd-analyze verify /etc/systemd/system/intelligenceos-arbitrage-dispatch.service
systemctl daemon-reload
```

This override changes only the **new** dispatcher, never production reporting or
the backup/monitor units. Inspect loaded sandbox/paths/allowlist without printing
credentials. Changes to host/cloud firewall or DNS remain separately reviewed;
no such commands are part of this task. A failure to resolve/connect stays a
failure rather than bypassing TLS or IP filtering.

### Activation and evidence

Do not send from the production unit until authorized. In a development sandbox,
use a separate test check/config/state and scratch history/backups. Test valid
health, low backup-space/budget (mocked in tests; never fill a production disk),
missing/corrupt snapshots, failed/missing unit results, transport failure and
recovery. Confirm receipt and acknowledgement with the actual selected recipient.
Then withhold the **test** heartbeat for >30 minutes and confirm the external
receiver independently detects silence. Running this test requires explicit send
and external-account authorization and has **not** been done. A no-network unit
test is not a live delivery or VM-failure-independence test.

After authorized acceptance and enabling backup/monitor timers via the main
runbook, the operator may enable the sender:

```bash
systemctl start intelligenceos-arbitrage-dispatch.service
systemctl show intelligenceos-arbitrage-dispatch.service -p Result -p ExecMainStatus
journalctl -u intelligenceos-arbitrage-dispatch.service --since '-10 minutes' --no-pager
systemctl enable --now intelligenceos-arbitrage-dispatch.timer
systemctl list-timers intelligenceos-arbitrage-dispatch.timer --all
```

Keep evidence of the reviewed release/configuration version (never secret URL),
receiver settings, actual sent/received/acknowledged UTC times, external-silence
and recovery notifications, operator and rollback readiness. Proposed escalation:
acknowledge within one hour, then backup operator if unacknowledged. Human
escalation must be configured and tested at the receiver; it is not implemented
by the local dispatcher. Confirm a real 06:30 backup, monitoring, and sender
cycle after installation. Failure of any acceptance step blocks unattended rollout.

### Rollback

For only the new sender, disable its timer, wait for an active dispatch to finish,
and then disable its external receiver check **as a planned maintenance action**
through the owner's external account. Otherwise silence correctly generates an
alert. Do not suppress an unexpected outage to make the receiver green.

```bash
systemctl disable --now intelligenceos-arbitrage-dispatch.timer
systemctl show intelligenceos-arbitrage-dispatch.service -p ActiveState -p Result
```

Once inactive, move only the newly installed dispatcher service/timer/drop-in to
a new private evidence directory using the same exact-file rollback pattern as
the main runbook and reload systemd. Preserve its private delivery state and
configuration pending owner retention/revocation decisions; never commit them.
Use the main runbook's independent rollback for new backup/monitor timers. No
production report service, release pointer, database, backup snapshot or unrelated
application is changed. If notification URLs were exposed, the owner must revoke
or rotate them at the receiver through an authorized secure process.

## Validation for this proposal

152 local tests pass (132 baseline). Both documented sample modes completed in
ignored development paths; four/six-sheet workbooks and formula safety checked.
A real development SQLite snapshot restored into a new path and re-verification
matched the content hash; monitoring reported healthy on that scratch state.
Tests cover budget admission, mid-copy overrun cleanup, low backup filesystem
space, lock contention, preserving older/unknown data, changed schema/duplicate
rows/NUL text/storage types, late sidecars, restore headroom and nonpublication
of a bad copy. Notification tests use injected senders/fake HTTPS handlers only,
including TLS policy, timeouts, redirect rejection, redaction, retry/transition/
reminder behavior and dry-run isolation. No real network notification is sent.

All six proposed units passed systemd verification; 13 shell blocks passed syntax
checks, `pip check` and `git diff --check` passed. These are not host installation,
production restore, external-account, external-silence or human-receipt tests.
Remote CI status is reported separately in the PR. No production service changed.

Start with [the consolidated manual-install checklist](OPERATIONS_HANDOFF.md)
for sequencing with backup/monitor staging, restore acceptance and rollback.
