# V0.2 dedicated VM release

Deployed 2026-10-23 UTC with explicit VM deployment authorization. Application
commit: `68230d3fdaef588bb7ba5c8340f49a473e8386b7` (merged PR #2, verified
against freshly fetched origin/main). No merge was performed. Initial checkout
was clean; original checkout and its runtime files were preserved.

## Installed layout

- Root-owned code and Python 3.12.3 venv:
  `/opt/intelligenceos-arbitrage/releases/68230d3fdaef588bb7ba5c8340f49a473e8386b7`.
- `/opt/intelligenceos-arbitrage/current` points to that release.
- Dedicated system account/group: `intelligenceos-arbitrage`, nologin shell.
- Root-owned environment: `/etc/intelligenceos-arbitrage/offline.env`.
- Writable state: `/var/lib/intelligenceos-arbitrage/` (application owned).
- Reports: `legacy-illustrative.xlsx` and `discovery-mock.xlsx` in state directory.
- History: `history.sqlite3` in state directory; original history imported intact.
- Prior `opportunities.xlsx` retained in both checkout and deployed state.
- Pre-install backup: `/var/backups/intelligenceos-arbitrage/20261023T221212Z/var/`.
  Backup directory is root-only. SQLite backup API used; integrity verified.
- Installed read-only validator: `/opt/intelligenceos-arbitrage/validate_deployment.py`.
  Source is `ops/validate_deployment.py` on the deployment milestone branch.

## Schedule, logs and operation

`intelligenceos-arbitrage.timer` is enabled, persistent, daily at **06:00 UTC**;
first scheduled trigger is 2026-10-24. Systemd serializes invocations of its
oneshot service. The service runs legacy then discovery sequentially, exits,
and remains inactive until the next trigger. Both executions share SQLite but
have separate report paths. A failed execution makes the unit fail, visible in
systemd/journal; there is no immediate automatic retry or external alerting.
Do not run concurrent standalone jobs against these output paths.

```bash
systemctl status intelligenceos-arbitrage.timer
systemctl show intelligenceos-arbitrage.service -p Result -p ExecMainStatus
systemctl list-timers intelligenceos-arbitrage.timer
journalctl -u intelligenceos-arbitrage.service --since today
systemctl start intelligenceos-arbitrage.service
runuser -u intelligenceos-arbitrage -- sh -c 'cd /opt/intelligenceos-arbitrage/current && PYTHONPATH=. .venv/bin/python /opt/intelligenceos-arbitrage/validate_deployment.py'
```

JSON application events go to the host's journal with run IDs, UTC timestamps
and redacted error classes. Journal retention follows existing host policy;
export incident logs if longer retention is required. SQLite retains final
execution metadata indefinitely; latest workbooks are atomically replaced daily.
No report archival/retention deletion is configured. Back up state regularly
using SQLite backup API or while the service is stopped; keep backups root-only.

The unit has a read-only filesystem except state, hidden home directories,
no privileges/capabilities, network disabled, 512 MB memory cap, 50% CPU quota
and 15-minute timeout. No ports, email, live providers or paid services enabled.
Offline operation has $0 incremental vendor fees, excluding existing hosting
and storage. Optional integrations require their own configuration/authorization
and a reviewed service change before network access can be enabled.

## Validation evidence

- Baseline checkout: `python -m pytest -q` via existing venv: **94 passed**.
- Installed release after dependency installation: **94 passed**; `pip check` clean.
- Both documented sample modes executed through the installed service as the
  nonroot user, final SQLite run IDs **2** and **3**, status `succeeded`.
- Legacy: four sheets, three candidates, one REVIEW and two REJECT.
- Discovery: six sheets, three candidates, one REVIEW and two REJECT at deployment
  time. Every row explicitly MOCK, purchase-ready false; no formula cells.
- SQLite integrity check: `ok`; timestamps timezone-aware. Preexisting run retained.
- Future-clock check two days later rejects all three discovery fixtures; original
  24-hour gate and fixture timestamps unchanged. Fixtures were fresh at deployment
  time and expire naturally. REVIEW is illustrative and never purchase approval.
- Systemd unit verification passed; initial service result success/exit 0;
  timer active/enabled. Docker and external CI were not run for this VM install.

## Rollback without deleting data

This is the first supervised installation; there is no prior deployed service.
To return to the pre-deployment operational state:

1. Run `systemctl disable --now intelligenceos-arbitrage.timer`, then
   `systemctl stop intelligenceos-arbitrage.service`. Stopping may leave a running
   history row if interrupted; inspect it before restarting.
2. With the service stopped, copy `/var/lib/intelligenceos-arbitrage/` to a new
   root-only timestamped backup directory. Preserve all post-release history and
   reports. Do not overwrite or delete either backup.
3. Leave this service disabled. The original checkout and original `var/` remain
   untouched; the pre-install backup above provides a second recovery copy.
   This restores the previous unscheduled state without discarding new history.

For a subsequent release rollback, stop the timer/service, back up current state,
verify the previous retained release/venv, and atomically replace `current` with
a symlink to that release (`ln -s PREVIOUS_RELEASE current.rollback` then
`mv -T current.rollback current`). Restore matching backed-up unit/environment
files if changed, run `systemctl daemon-reload`, run one service execution,
verify reports/history/logs, then re-enable the timer. Never restore a database
over newer history without explicitly preserving it and reviewing schema
compatibility; V0.2 does not migrate the legacy runs schema.

Remaining operational limits: bundled mock data only, daily snapshots become
stale, no live eligibility verification, no SMTP delivery/alerts, and no automatic
backup schedule. Small sample runs validate installation; the 10,000 candidate
limit is not a measured capacity guarantee under the service memory cap.
