# Consolidated backup / monitor manual-install handoff — NOT INSTALLED

This is the entry point for the existing operations implementation. It adds no
second backup or monitor mechanism. No installation, production reads, service
changes, notification sends or restore of production data occurred in this task.
Keep the production reporting service/timer, release pointer, environment and
network denial unchanged throughout a future operations-only installation.

## Ordered owner/operator checklist

| Order | Action and authoritative procedure | Required evidence / stop condition |
| --- | --- | --- |
| 1 | Choose reviewed commit and authorized operator; inspect host identity, state ownership and disk capacity using [operator prerequisites](BACKUP_MONITOR_DEPLOYMENT_REVIEW.md#operator-prerequisites-read-only-checks) | Real UID/GID, mounts, logical SQLite size, sidecars and free space. Do not read credentials. Stop on inaccessible/unknown production state. |
| 2 | Agree recovery goals and space budget in [review decisions](BACKUP_MONITOR_DEPLOYMENT_REVIEW.md#review-decisions-and-limits) | Default 1 GiB backup budget and 256 MiB reserve; plan 16 database copies plus sidecars/unknown entries and overhead. Count retention is 14 successful snapshots, not 14 days. No hard filesystem quota or off-host copy is provided. |
| 3 | Stage immutable operations code with [isolated release instructions](BACKUP_MONITOR_DEPLOYMENT_REVIEW.md#stage-an-isolated-operations-release-only-after-deployment-authorization) | Separate operations path; verified local wheelhouse matching requirements including patched pytest if installing the full requirements file. Production reporting pointer does not move. |
| 4 | Install **disabled** backup/monitor units and path overrides using [first-install checks](BACKUP_MONITOR_DEPLOYMENT_REVIEW.md#install-disabled-units-and-overrides-after-authorization) | Existing files/symlinks/drop-ins cause a stop, not overwrite. Verify effective sandbox, user and paths. No timer enabled yet. |
| 5 | Run authorized first backup and new-path restore drill via [backup and restore procedure](BACKUP_MONITOR_DEPLOYMENT_REVIEW.md#first-backup-restore-drill-and-monitor-after-authorization); use existing `app.backups verify-restore` | Manifest/hash/integrity plus schema/typed business-record comparison; actual restore duration, sizes and private modes. Compare against snapshot, never changing live history. No live DB replacement. |
| 6 | Select off-VM receiver and recipient using [watchdog choices](OPERATIONS_WATCHDOG.md); stage dispatcher dry-run with its own operations release/state | Missing unit/timer issues must remain visible. Dry-run reads no destination credentials and sends nothing. Same-VM polling alone cannot detect loss of that VM. |
| 7 | After separate send/network authorization, follow [send-mode override](OPERATIONS_WATCHDOG.md#send-mode-override-only-after-external-configuration-and-explicit-authorization) and [acceptance](OPERATIONS_WATCHDOG.md#activation-and-evidence) | Private systemd credential, narrow egress, actual receipt, recovery and withheld **test** heartbeat for >30 minutes. Receiver schedule proposal: 15 min plus 15 min grace. No heartbeat URL or token in Git/logs. |
| 8 | Enable backup/monitor timers only after their restore/disk/notification acceptance; then dispatcher after receipt/silence acceptance | Backup 06:30 UTC daily; monitor hourly; dispatcher every 15 min. Verify next cycles, 24-hour behavior and the 15th backup retention event. No reporting restart. |
| 9 | If acceptance fails, follow [backup/monitor rollback](BACKUP_MONITOR_DEPLOYMENT_REVIEW.md#rollback-of-this-first-operations-only-installation) and [dispatcher rollback](OPERATIONS_WATCHDOG.md#rollback) | Disable only new timers; wait for active work; preserve snapshots, evidence and private state. Coordinate planned receiver maintenance. Never delete production history. |

The older guides contain executable command blocks and remain the single source
for commands. This checklist unifies their dependencies; it does not waive their
activation gates. Backups can run before monitor acceptance to create evidence,
but unattended activation waits for complete acceptance. A monitor failure is not
permission to relax thresholds or relabel an old backup as fresh.

## Development evidence versus external requirements

Offline tests exercise retention, budgets, failed copies, restore verification,
monitoring and injected notifications. Scratch workflow uses only `var/` under the
checkout. Production identity/capacity, effective systemd controls, first production
snapshot/restore drill, RPO/RTO agreement, an independent receiver, approved
recipient/backup operator, live notification receipt and silence detection remain
unverified external requirements. Installation/deployment is explicitly excluded
from this milestone. An off-host backup and host-loss recovery plan are still
needed before claiming disaster recovery. The optional SMTP report sender is
separate from watchdog notification transport; see [SMTP handoff](SMTP_TEST_HANDOFF.md).
