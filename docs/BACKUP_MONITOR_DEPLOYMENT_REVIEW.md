# Backup and monitoring deployment review — NOT INSTALLED

Updated 2026-10-23 UTC with application disk enforcement and restore proof. See
[watchdog/notification installation supplement](OPERATIONS_WATCHDOG.md). This is a proposed operator runbook, not an executed
change. Current deployed V0.2 lacks backup/monitor modules. Neither new service
is installed. Production restore, notification receipt, numeric ownership and
actual free space remain unverified. Keep the reporting service, its environment,
network denial and current release pointer unchanged. No SP-API credentials are
needed. Do not run installation blocks until a separate deployment is authorized.

## Review decisions and limits

| Item | Existing implementation | Review/activation requirement |
| --- | --- | --- |
| Backup schedule | 06:30 UTC daily, persistent catch-up; online SQLite copy; source opened read-only | Verify reporting identity/access and a complete first backup; do not overlap manual and unit backups |
| Retention | Newest 14 valid tool-owned snapshots after a successful publication; invalid/unknown/symlink entries are retained | Count is not a 14-day TTL or byte cap. Old preinstall backups are outside retention. Never automatically delete unknown data |
| Recovery objective | No production RPO/RTO established | Proposed RPO <=24 hours only while daily backups succeed; 30-hour alert threshold permits a longer gap. Measure drill time and agree RTO before claiming it |
| Isolation | Same-host backup, private 0700 directory; files 0600; SHA-256 and SQLite integrity | Not encrypted or off-host by this tooling; host loss remains unrecoverable from these copies alone |
| Runtime limits | Backup/monitor each 128 MiB, 25% CPU, 5 min systemd timeout; copy progress deadline 30 sec | Shared 2 GiB host: verify actual headroom. Two units can overlap; timeout is a failed check, not health |
| Monitor | Hourly; last two run results, 30-hour age window; history quick_check; >=256 MiB free on history and backup filesystems; 1 GiB directory budget; validated backup manifest freshness | Does not prove both modes ran, scheduler liveness, journal delivery or successful restore. Separate backup mount is checked; another writer can still consume space between checks |
| Disk budget | 1 GiB application budget including unknown/pending entries; pre-copy allowance, progress checks and shared lock; >=256 MiB reserve on source/backup filesystems | No filesystem hard quota; copy chunks and unrelated writers can transiently cross a limit. Application aborts/cleans its pending copy, without pruning old data to make room |
| Notifications | Optional tested HTTPS dispatcher and dry-run unit; no destinations configured or installed | External receiver/account plus recipient and receipt test still required; a same-VM dispatcher is not independent of VM failure |

Let D = measured logical SQLite size (`page_count * page_size`), W = existing
WAL/SHM/journal allocated bytes, U = unknown/corrupt/preexisting managed-directory
contents retained for investigation. Budget at least **16D + W + U + overhead**:
14 retained snapshots, one transient new snapshot and one restore-drill copy.
Reserve 20% overhead plus 256 MiB free. This is a planning allowance, not an
upper bound on SQLite growth or filesystem allocation. Existing history/reports,
OS logs and unrelated host usage need their own headroom. At 1 GiB and no W/U,
16D * 1.2 must fit; roughly 53 MiB per database already consumes that budget.
At/above budget or below free-space reserve, defer a new manual backup, notify
operator and investigate; stopping a future timer requires approved operator
action. The application now enforces its budget; this remains distinct from an OS quota. Unknown/corrupt entries count against the budget and symlinks fail closed.

## Operator prerequisites (read-only checks)

Run as the authorized host administrator, from the reviewed project checkout.
This environment previously denied systemd/netlink and production state access;
repeat on the actual host. Do not read environment contents or credentials.
All commands below are literal except the full reviewed Git revision explicitly
entered by the operator. Stop on any unexpected output or failure.

```bash
set -euo pipefail
cd /root/IntelligenceOS-Arbitrage
APP_USER=intelligenceos-arbitrage
APP_GROUP=intelligenceos-arbitrage
STATE=/var/lib/intelligenceos-arbitrage
BACKUPS=/var/lib/intelligenceos-arbitrage-backups
systemctl show intelligenceos-arbitrage.service -p User -p Group -p Result -p ExecMainStatus
systemctl is-enabled intelligenceos-arbitrage.timer
systemctl list-timers intelligenceos-arbitrage.timer --all
getent passwd "$APP_USER"
id "$APP_USER"
stat -c '%a %u:%g %n' "$STATE" "$STATE/history.sqlite3"
readlink -f /opt/intelligenceos-arbitrage/current
df -B1 "$STATE" /var/lib
du -s -B1 "$STATE"
```

Inspect existing backup directory with `stat`, `du` and `df` if it exists. Compare
numeric UID/GID with `id`; never recursively chown an existing data directory.
Application user must read history and SQLite sidecars and access its state
directory. Do not run production jobs from the checkout during this review.
Measure logical size without creating a missing DB:

```bash
runuser -u "$APP_USER" -- /opt/intelligenceos-arbitrage/current/.venv/bin/python - <<'PY'
from contextlib import closing
from pathlib import Path
import sqlite3
p = Path('/var/lib/intelligenceos-arbitrage/history.sqlite3')
with closing(sqlite3.connect(p.as_uri() + '?mode=ro', uri=True)) as db:
    size = db.execute('PRAGMA page_count').fetchone()[0] * db.execute('PRAGMA page_size').fetchone()[0]
print('logical_database_bytes', size)
for suffix in ('-wal', '-shm', '-journal'):
    sidecar = Path(str(p) + suffix)
    if sidecar.exists(): print(suffix, sidecar.stat().st_blocks * 512)
PY
```

Record private evidence of measurements, required 16D allowance, actual mount
locations, quota decision, operator and UTC time. Do not activate while disk,
identity, restore or notification requirements remain unresolved.

## Stage an isolated operations release (only after deployment authorization)

This stages the reviewed code under a separate immutable operations path. Units
will use an override pointing there; the reporting symlink does not move. Requires
an already approved **local verified wheelhouse** containing every pinned runtime
requirement; no network dependency installation or paid service is needed.
Do not fall back to TLS bypasses or unreviewed dependencies.

```bash
read -r -p 'Approved full 40-character Git commit: ' APPROVED_REV
[[ "$APPROVED_REV" =~ ^[0-9a-f]{40}$ ]]
test "$(git rev-parse HEAD)" = "$APPROVED_REV"
test -z "$(git status --porcelain)"
OPS_RELEASE=/opt/intelligenceos-arbitrage/operations/$APPROVED_REV
WHEELHOUSE=/opt/intelligenceos-arbitrage/wheelhouse
test -d "$WHEELHOUSE"
test ! -e "$OPS_RELEASE"
install -d -o root -g root -m 0755 "$OPS_RELEASE"
git archive "$APPROVED_REV" | tar -x -C "$OPS_RELEASE"
python3.12 -m venv "$OPS_RELEASE/.venv"
"$OPS_RELEASE/.venv/bin/python" -m pip install --no-index --find-links "$WHEELHOUSE" -r "$OPS_RELEASE/requirements.txt"
"$OPS_RELEASE/.venv/bin/python" -m pip check
chown -R root:root "$OPS_RELEASE"
chmod -R go-w "$OPS_RELEASE"
(cd "$OPS_RELEASE" && runuser -u "$APP_USER" -- "$OPS_RELEASE/.venv/bin/python" -m app.backups --help)
```

If staging fails, leave an unreferenced release for investigation; do not switch
services to it. Verify code/venv traversal permissions as application user.

## Install disabled units and overrides (after authorization)

The following assumes first installation, with no preexisting project backup or
monitor unit/drop-in. Treat dangling symlinks as existing files and stop for review. If any exists, stop and review it; do not overwrite it.
`install -d` may adjust an existing directory: create the backup directory only
when absent; otherwise assert ownership/mode without changing it.

```bash
for kind in backup monitor; do
  for suffix in service timer; do
    test ! -e "/etc/systemd/system/intelligenceos-arbitrage-$kind.$suffix"
    test ! -L "/etc/systemd/system/intelligenceos-arbitrage-$kind.$suffix"
  done
  test ! -e "/etc/systemd/system/intelligenceos-arbitrage-$kind.service.d"
  test ! -L "/etc/systemd/system/intelligenceos-arbitrage-$kind.service.d"
done
if test ! -e "$BACKUPS"; then
  install -d -o "$APP_USER" -g "$APP_GROUP" -m 0700 "$BACKUPS"
fi
test ! -L "$BACKUPS"
test "$(stat -c %a "$BACKUPS")" = 700
test "$(stat -c %u "$BACKUPS")" = "$(id -u "$APP_USER")"
test "$(stat -c %g "$BACKUPS")" = "$(getent group "$APP_GROUP" | cut -d: -f3)"
for kind in backup monitor; do
  for suffix in service timer; do
    install -o root -g root -m 0644 "$OPS_RELEASE/ops/systemd/intelligenceos-arbitrage-$kind.$suffix" /etc/systemd/system/
  done
  install -d -o root -g root -m 0755 "/etc/systemd/system/intelligenceos-arbitrage-$kind.service.d"
done
cat > /etc/systemd/system/intelligenceos-arbitrage-backup.service.d/operations-release.conf <<UNIT
[Service]
WorkingDirectory=$OPS_RELEASE
ExecStart=
ExecStart=$OPS_RELEASE/.venv/bin/python -m app.backups backup --source $STATE/history.sqlite3 --directory $BACKUPS --keep 14 --maximum-bytes 1073741824 --minimum-free-bytes 268435456
UNIT
cat > /etc/systemd/system/intelligenceos-arbitrage-monitor.service.d/operations-release.conf <<UNIT
[Service]
WorkingDirectory=$OPS_RELEASE
ExecStart=
ExecStart=$OPS_RELEASE/.venv/bin/python -m app.healthcheck --history $STATE/history.sqlite3 --backups $BACKUPS --maximum-backup-bytes 1073741824 --minimum-free-bytes 268435456
UNIT
systemd-analyze verify /etc/systemd/system/intelligenceos-arbitrage-backup.service /etc/systemd/system/intelligenceos-arbitrage-backup.timer /etc/systemd/system/intelligenceos-arbitrage-monitor.service /etc/systemd/system/intelligenceos-arbitrage-monitor.timer
systemctl daemon-reload
systemctl cat intelligenceos-arbitrage-backup.service intelligenceos-arbitrage-monitor.service
```

Check effective paths, user, sandbox, limits and network denial. Unit verification
alone does not establish runtime enforcement. Record checksum of source unit
files and overrides in private deployment evidence. Stop if verification fails.
No timer is enabled by this block.

## First backup, restore drill and monitor (after authorization)

Recheck disk capacity immediately before starting. Ensure no manual backup process
is running. `systemctl start` below writes a new backup and may prune older valid
snapshots after publication; it does not replace live history. Record the new
snapshot name printed in the service journal and set it below; never guess the
newest directory or refresh timestamps.

```bash
systemctl start intelligenceos-arbitrage-backup.service
systemctl show intelligenceos-arbitrage-backup.service -p Result -p ExecMainStatus
journalctl -u intelligenceos-arbitrage-backup.service --since '-10 minutes' --no-pager
read -r -p 'Snapshot directory name from successful backup event: ' SNAPSHOT_NAME
[[ "$SNAPSHOT_NAME" =~ ^sqlite-[0-9]{8}T[0-9]{12}Z-[0-9a-f]{32}$ ]]
SNAPSHOT=$BACKUPS/$SNAPSHOT_NAME
test -d "$SNAPSHOT"
DRILL=$(mktemp -d /var/lib/intelligenceos-arbitrage-restore-drill.XXXXXXXX)
chown "$APP_USER:$APP_GROUP" "$DRILL"
chmod 0700 "$DRILL"
(cd "$OPS_RELEASE" && runuser -u "$APP_USER" -- "$OPS_RELEASE/.venv/bin/python" -m app.backups restore --snapshot "$SNAPSHOT" --destination "$DRILL/recovered.sqlite3")
(cd "$OPS_RELEASE" && runuser -u "$APP_USER" -- "$OPS_RELEASE/.venv/bin/python" - "$SNAPSHOT" "$DRILL/recovered.sqlite3" <<'PY'
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
from app.backups import validate_snapshot
source = validate_snapshot(Path(sys.argv[1]))
with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as a, closing(sqlite3.connect(Path(sys.argv[2]).as_uri() + '?mode=ro', uri=True)) as b:
    assert b.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    expected = a.execute('SELECT * FROM runs ORDER BY id').fetchall()
    actual = b.execute('SELECT * FROM runs ORDER BY id').fetchall()
    assert actual == expected
    print('restored_snapshot_rows', len(actual), 'integrity_and_exact_comparison', 'ok')
PY
)
stat -c '%a %u:%g %s %n' "$SNAPSHOT/database.sqlite3" "$SNAPSHOT/manifest.json" "$DRILL/recovered.sqlite3"
df -B1 "$STATE" "$BACKUPS" "$DRILL"
du -s -B1 "$BACKUPS" "$DRILL"
systemctl start intelligenceos-arbitrage-monitor.service
systemctl show intelligenceos-arbitrage-monitor.service -p Result -p ExecMainStatus
journalctl -u intelligenceos-arbitrage-monitor.service --since '-10 minutes' --no-pager
```

Compare restore to the immutable snapshot, not a live database that may now have
new rows. Record snapshot hash/manifest capture time, restore start/finish time,
row comparison, sizes/free space, UID/modes and operator in restricted evidence.
The restored scratch database is private production-derived data: retain only
for the approved drill evidence period, then have the operator remove that exact
scratch artifact under the approved data policy. No blanket deletion command is
provided. Recovery tooling never switches `ARBITRAGE_DB` or overwrites live data.

## Notification and scheduling acceptance gate

Before unattended activation, the owner must name a recipient and backup operator,
select an already authorized channel, approve sender/secret handling and configure
the reviewed opt-in notification adapter or an approved host monitoring integration.
A disabled-by-default HTTPS sender is supplied in app.ops_dispatch; see OPERATIONS_WATCHDOG.md for configuration and activation gates. Do not put a webhook/token in a
unit, CLI, PR or chat. Keep backup/monitor services offline; any notifier needs a
separate least-privilege process and reviewed outbound policy. Do not weaken
reporting/network isolation to send alerts.

Required delivery cases: reporting/backup/monitor failed or timed out; stale or
future timestamps; missing/corrupt backups; low free space on either mount;
backup directory >=1 GiB review budget; missed hourly heartbeat/disabled timer.
An external heartbeat/watchdog is required for VM/systemd failure because a local
failed unit cannot report its own absence. Budget and backup-mount checks are now implemented; independent missing-heartbeat detection must still run outside this VM. Test alerting with **development scratch state** (missing and corrupt
snapshot, failed/stale run, threshold crossing), not production corruption or
filling a disk. Test the independent watchdog by withholding a test heartbeat.

Proposed notification targets for review: route failed-unit events within 15
minutes and stale/disk/heartbeat alerts within one hourly cycle; acknowledge
within one hour and escalate to backup operator if unacknowledged. These are
proposed service expectations, not current capabilities. Record actual received
UTC timestamps, acknowledgement and recovery message. Confirm de-duplication,
retries and redacted payloads. Choose a channel before claiming executable
notification configuration; no destination has been supplied or contacted.

Only after written acceptance of restore, disk rules, notification receipt and
watchdog evidence, an authorized operator may run:

```bash
systemctl enable --now intelligenceos-arbitrage-backup.timer intelligenceos-arbitrage-monitor.timer
systemctl is-enabled intelligenceos-arbitrage-backup.timer intelligenceos-arbitrage-monitor.timer
systemctl list-timers intelligenceos-arbitrage-backup.timer intelligenceos-arbitrage-monitor.timer --all
```

Persistent timers may trigger immediately for a missed schedule. Inspect both
results after activation, the next 06:30 UTC backup, 24 hours of monitoring and
after the 15th successful snapshot exercises retention. Keep reporting timer
unchanged. This guide is intentionally **not activation-ready** until missing
notification/watchdog configuration and production evidence have been resolved.

## Rollback of this first operations-only installation

Disable only the two new timers. Allow any active backup or monitor to finish;
do not kill a backup or delete its `.pending` directory during execution.
Leave all snapshots, scratch evidence and the immutable operations release intact.

```bash
systemctl disable --now intelligenceos-arbitrage-backup.timer intelligenceos-arbitrage-monitor.timer
systemctl is-active intelligenceos-arbitrage-backup.service intelligenceos-arbitrage-monitor.service || true
systemctl show intelligenceos-arbitrage-backup.service intelligenceos-arbitrage-monitor.service -p ActiveState -p SubState -p Result
```

Once both services are inactive, record the rollback. For complete removal of
new unit files, move the exact first-install files and overrides into a new
root-only evidence directory rather than deleting them:

```bash
ROLLBACK_DIR=$(mktemp -d /var/backups/intelligenceos-arbitrage-operations-rollback.XXXXXXXX)
chmod 0700 "$ROLLBACK_DIR"
for kind in backup monitor; do
  mv "/etc/systemd/system/intelligenceos-arbitrage-$kind.service" "$ROLLBACK_DIR/"
  mv "/etc/systemd/system/intelligenceos-arbitrage-$kind.timer" "$ROLLBACK_DIR/"
  mv "/etc/systemd/system/intelligenceos-arbitrage-$kind.service.d" "$ROLLBACK_DIR/"
done
systemctl daemon-reload
readlink -f /opt/intelligenceos-arbitrage/current
systemctl is-enabled intelligenceos-arbitrage.timer
systemctl show intelligenceos-arbitrage.service -p Result -p ExecMainStatus
```

A monitoring adapter added later needs its own rollback without affecting other
host applications. No reporting restart or symlink rollback is needed because
this plan never changes the reporting release. Backup copies remain available
for manual reviewed recovery. A real live-database restore remains a distinct
operation requiring approval and preservation/reconciliation of newer history;
see [SQLITE_BACKUPS.md](SQLITE_BACKUPS.md). Rollback here does not prove recovery.

## Original documentation-only validation (before enforcement changes)

Documentation-only change: 132 existing tests passed; both sample modes completed
in ignored development paths. All eight shell blocks passed `bash -n`, proposed
backup/monitor units passed `systemd-analyze verify`, and `pip check` plus
`git diff --check` passed. Syntax/unit verification does not validate production
permissions, available wheels, disk capacity, notification delivery or successful
installation. No deployment, scheduler change or production restore was executed.
