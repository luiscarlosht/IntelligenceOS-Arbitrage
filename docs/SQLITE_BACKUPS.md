# Proposed SQLite backup operations

V0.3 preparation only: no deployed files, environment, service or timer have
been changed. The V0.2 release lacks `app.backups`; the proposed units cannot be
installed successfully until a separate approved deployment supplies that module.

## Implementation and retention

`python -m app.backups backup --source DATABASE --directory PRIVATE_DIRECTORY --keep 14`
uses SQLite's online backup API with a read-only source connection. It includes
committed WAL data, checks integrity, produces a self-contained DELETE-journal
snapshot, and records a UTC timestamp and SHA-256 manifest. File and directory
fsync precede/complete atomic publication. Snapshot files are 0600 and the backup
directory must be private (0700); no credentials or raw errors are logged.

Each run creates a unique `sqlite-UTC-UUID/` directory containing only
`database.sqlite3` and `manifest.json`. Retention keeps the newest **14 successful
valid snapshots** (approximately 14 daily runs, not an exact age policy).
Retention occurs only after a valid new snapshot is published. It deletes only
recognized, checksum-valid, integrity-valid directories with this tool's marker
and exact expected contents. Corrupt, unknown, extra-content or symlink entries
are retained for investigation. Old one-time V0.2 backups are outside this managed
directory and will not be pruned. Do not mix other data into this directory.
Operate one backup process per directory; systemd serializes its unit.

Proposed `ops/systemd/intelligenceos-arbitrage-backup.{service,timer}` runs at
**06:30 UTC daily**, persistent catch-up, as the existing application user, with
128 MB memory cap, network disabled and a five-minute supervisor timeout. SQLite
copy itself has a 30-second progress deadline. Source SQLite WAL/SHM access needs
the application's state directory, but code always opens the source read-only.
The service never stops or restarts the reporting service. Missing databases,
corruption or permission failures fail the backup and preserve prior snapshots.
Check journal/service result; external alerting remains unconfigured.

This is local recovery protection, not a separate failure domain. Host loss can
lose both live state and backups. No cloud backup purchase or off-host transfer
is configured. Plan a separately authorized encrypted off-host copy later.
Space target: about `15 × database size` during publication, plus filesystem/WAL
overhead; measure actual sizes and monitor free disk. Backups do not include
workbooks, code or configuration. The release and environment rollback guide
remains [VM V0.2 release](VM_V02_RELEASE.md). If a provider usage database is
introduced operationally, give it a separate backup unit/directory and retention
review; it is currently offline test data only.

## Restore drill (safe, no service changes)

Use a development database or a permitted read-only snapshot, never replace live
history during a drill. Run from the branch checkout with its Python 3.12 venv:

```bash
mkdir -p var/restore-drill
.venv/bin/python -m app.backups backup --source var/history.sqlite3 --directory var/restore-drill/backups --keep 14
# Choose the printed snapshot directory name, without altering its contents.
.venv/bin/python -m app.backups restore --snapshot var/restore-drill/backups/sqlite-UTC-UUID --destination var/restore-drill/recovered.sqlite3
```

Restore validates marker, manifest hash, timestamps and SQLite integrity before
copying. Destination and SQLite sidecars must not already exist. The restored
database is checked and published without overwriting a file created meanwhile.
Validate `PRAGMA integrity_check`, `runs` rows/counts/statuses and UTC timestamps
against the chosen snapshot; later live rows will not be in an earlier backup.

Automated tests exercise a real WAL database with an open writer connection,
committed data, subsequent writes and a restored snapshot. They check the point
in time contents, preservation of the source/newer rows, permissions, overwrite
refusal, corruption, missing source, cleanup on failure and retention boundaries.

## Proposed activation after separate approval

1. Review/merge the preparation PR and authorize a release containing the module;
   verify its tests and immutable deployment path. Do not copy proposed units into
   `/etc` against the existing V0.2 release.
2. Create the application-owned 0700 backup directory
   `/var/lib/intelligenceos-arbitrage-backups`. Install/review unit files, verify
   them with `systemd-analyze verify`, then reload systemd.
3. Start the backup service once. Perform a restore drill to a **new** private
   scratch destination and compare history against that snapshot. Inspect logs,
   owners, permissions, byte sizes and free space before enabling the timer.
4. Only after validation, enable/start the backup timer. Review after the first
   daily trigger and after retention begins. Keep the existing reporting timer.

For an actual production restore, obtain approval, stop the reporting timer and
wait for any active job to complete. Take a new backup and preserve all current
database/WAL/SHM files together in a timestamped recovery directory. Restore to a
new database path, inspect it, and reconcile newer history before proposing a
switch of `ARBITRAGE_DB`. Never copy a backup over an open SQLite database. After
an approved configuration switch, run one job and verify history/reports before
re-enabling scheduling. Roll back by switching to the preserved original database
path while jobs are stopped. No automatic restore or data replacement is provided.

To disable a future backup schedule, disable its timer and let the current backup
finish; retain all snapshots and reporting configuration. This milestone does not
perform those production commands.
