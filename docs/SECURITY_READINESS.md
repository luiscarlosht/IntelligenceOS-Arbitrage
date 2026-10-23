# Amazon security readiness — review evidence, 2026-10-23 UTC

**Not ready for live Amazon data.** Registration is under review per the owner;
no authenticated registration case or submitted questionnaire was accessed.
This is a read-only, limited audit plus proposed branch controls, not an Amazon
certification or a claim of DPP compliance. No production settings changed.
No credentials, environment contents, unrelated application data or private keys
were read. Do not paste secrets into tickets, PRs or chat.

## Source and deployment evidence

Read AGENTS.md, product requirements, architecture and roadmap. GitHub API
verified [PR #4](https://github.com/luiscarlosht/IntelligenceOS-Arbitrage/pull/4)
merged at `70abe293210a7fc2db952cd2997089c187bee9e0`. Comparing inspected local
`f7009e26bfa21c504d8efafe69a07c0d9f006488` to remote main returned one merge
commit ahead and **no changed files**. Shell fetch failed DNS; connector reads
supplied current-main evidence. Baseline 116 tests passed with .venv Python 3.12.

`/opt/intelligenceos-arbitrage/current` resolves to V0.2 release
`68230d3fdaef588bb7ba5c8340f49a473e8386b7`; it lacks `app/backups.py`.
Installed reporting unit and timer files match the repository proposal: daily
06:00 UTC, two sequential offline jobs, dedicated user, no capabilities,
NoNewPrivileges, private temporary/devices, ProtectSystem=strict, ProtectHome,
AF_UNIX only and IPAddressDeny=any, memory/CPU/task/time limits. These are verified
**file settings**, not verification that systemd loaded/enforced them now.
System bus access and socket/netlink inspection were denied. Current active,
enabled, last result, listeners and journal history remain unknown. Prior
successful deployment evidence in VM_V02_RELEASE.md is historical only.

Observed metadata: environment file 0640 root:root, environment directory 0750
root:root; state directory 0750 nobody:nogroup in this restricted environment;
release app directory 0775 root:root; dated preinstall backup directory 0700
root:root. UID/GID mapping may differ from the host; owner must verify numeric
ownership, application service identity and effective access before claiming
least privilege. A symlink's 0777 mode is not target access permission.

## Registration question mapping

The exact account questionnaire and requested roles were not supplied. The
following maps control topics, not verbatim account-specific answers. Amazon's
[private registration guide](https://developer-docs.amazon.com/sp-api/docs/register-as-a-private-developer)
requires organization/data/use/security information and truthful answers.
Its [policy index](https://developer-docs.amazon.com/sp-api/docs/policies-and-agreements)
links regional DPP/AUP/agreements and a voluntary self-check; that self-check does
not establish formal compliance. Owner must compare the submitted form and
applicable regional policy before responding. Public pages checked 2026-10-23;
linked authenticated policy texts and the full self-check were not audited.

| Question/control topic | Verified evidence | Unknown or gap; required owner evidence |
| --- | --- | --- |
| Business purpose, data and roles | Offline CSV/mock workflow; configuration rejects live provider selectors; no HTTP Amazon adapter | Confirm private self-use, actual business/legal identity, case status, minimum roles and authorized operations; exclude orders/buyer PII unless separately justified and approved |
| Source authorization and sharing | No scraping/fetching in connector; proposed CSV preflight requires an authorization reference | A string is not a license. Owner must retain permission/export agreement, internal-use and redistribution rights; resolve SP-API/other-provider AUP compatibility |
| Network protection | Installed job unit file denies network; no app server needed | `/etc/ufw/ufw.conf` says ENABLED=no. This does not establish absence of cloud/nftables filtering. Effective host/cloud ingress/egress rules and open ports unverified; review before live access |
| Access control and MFA | Dedicated service account named in unit; protected environment file metadata | `/etc/ssh/sshd_config` has PermitRootLogin yes and includes drop-ins; effective SSH policy, password login, admin inventory, MFA, account removal and periodic access review unknown. Do not claim SSH hardening or MFA |
| Encryption in transit | SMTP code uses verified TLS; Amazon transport absent | Future adapter needs verified TLS, bounded responses/timeouts and endpoint policy; no successful live TLS request is claimed |
| Encryption at rest and keys | SQLite backups use checksums and private permissions | SQLite/checksums are not encryption. Disk/volume/backup encryption, key custody/rotation and off-host recovery unknown; no encrypted backup claim |
| Secrets management | No credentials committed in this change; no production credential access | No deployed Amazon credential lifecycle exists. Approve secure injection, scope, rotation/revocation and leak response before onboarding; environment files alone are not a complete vault |
| Audit logs and monitoring | Code writes structured events/error classes and SQLite run statuses; journal configured in unit | Effective journal persistence/retention, privileged access logs, tamper resistance, delivery and alert acknowledgement unknown. Proposed monitor is local-only, not installed and sends no alerts |
| Vulnerability/change management | Tests, branch/PR review and pinned release workflow; pip check passes locally | Dependency CVE scan, OS patch cadence, scan evidence, accountable owner and remediation SLA unverified. pip check is dependency consistency, not a vulnerability assessment |
| Retention/deletion/minimization | No live Amazon records requested; latest report replacement; local backup retention tool | History retained indefinitely; no Amazon retention/deletion policy or deletion verification across copies/backups. Owner must define data inventory, allowed retention, deletion and export recipients before ingestion |
| Backup/recovery | See evidence below; tested development SQLite snapshot/restore | No installed scheduled backup found, no accessible production restore drill, no separate failure domain, RPO/RTO not agreed |
| Incident response and staff practices | Proposed procedure below | No approved policy, exercise, security training, incident contact/on-call or tested notification evidence; owner must adopt and exercise |

Do not answer “implemented” from a proposed unit, a passing mock test, a previous
release document, an unreadable directory or an unverifiable platform setting.

## Backup and restore audit

Only reporting service/timer files were found at the project-specific installed
paths. No backup service/timer or `/var/lib/intelligenceos-arbitrage-backups`
exists; V0.2 cannot execute proposed backup tooling. This is evidence of a local
installation gap, not proof that every external backup system is absent.
The dated preinstall directory exists and is 0700, but contents and production
state were inaccessible. Prior documentation reports a consistent preinstall
backup; this audit cannot verify its checksum, contents or current recoverability.
No production snapshot was restored or production database opened.

Current development tests restore real SQLite snapshots into new scratch paths,
compare all run rows and integrity, and test WAL point-in-time recovery,
corruption, permissions, retention and overwrite refusal. These verify tooling,
not a production restore drill. Follow [SQLITE_BACKUPS.md](SQLITE_BACKUPS.md)
after an approved release/install. Record immutable release, snapshot ID/hash,
UTC capture/restore times, integrity, row counts and comparison result, operator,
RPO/RTO and permissions in private operational evidence; do not commit databases.
Never restore over live history or refresh a manifest timestamp to pass checks.

## Proposed controls and monitoring (not activated)

`app.authorized_imports` and the header-only template add an offline preflight;
[AUTHORIZED_IMPORTS.md](AUTHORIZED_IMPORTS.md) describes owner authorization.
It neither certifies permission nor supplies marketplace evidence.

`app.healthcheck` checks the last two recorded job results/timestamps (30-hour
window), SQLite quick_check, free space (256 MiB minimum), and checksum/integrity
validated backup freshness from manifest creation time. It returns nonzero and
logs fixed issue codes for missing/failed/stale/future evidence. It creates no
databases or snapshots and performs no repair. It cannot prove both workflow
modes ran, detect a stopped scheduler before the age window, attest a restore,
validate mount encryption, measure all backup space needs or notify a human.
Backup scans validate every entry and may be costly at scale; timeout fails the
unit. Review capacity and thresholds for the real database.

Proposed monitor service/hourly timer remain only in `ops/systemd`. They require
an approved release with monitor/backup modules and installed backup schedule.
A first check will fail until valid backups exist. After separate deployment
approval, verify units, run one backup, restore to private scratch, run the
monitor and inject a development failure. Configure an authorized alert channel
and test delivery/acknowledgement; local journal failure alone is not alerting.
Retain network denial until a separately reviewed live transport/egress change.
Do not run systemctl install/enable, firewall, SSH or encryption changes from this PR.

Proposed incident procedure for owner review: assign incident lead and backup;
triage monitoring/authentication anomalies daily; preserve restricted evidence
and UTC timeline without copying tokens; scope affected systems/data; obtain
operator approval for containment and token revocation; notify Amazon through
its current required channel/timeframe and affected parties according to the
applicable policy; recover using verified backups, reconcile lost runs, rotate
compromised secrets and document root cause/remediation. Owner must verify
notification deadlines against applicable policy, supply contacts and conduct
a tabletop before claiming an implemented incident program.

## Account-owner actions before live integration

1. Monitor registration case/admin email, supply the exact submitted question
   text and nonsecret answers for reconciliation, and respond to Amazon requests
   within its stated case deadline. Do not submit this document as proof of
   controls that remain unknown or proposed.
2. Confirm use case/roles/marketplace, account authorization, product data rights,
   fees/pricing and allowed data combinations. No paid service is authorized here.
3. Provide host-admin evidence for effective SSH, MFA/access reviews, cloud/host
   firewall, service identity, encryption/key management, patching and logs.
   Review targeted remediation and rollback before any production security change.
4. Approve a tested deployment of backup/monitor tooling separately; demonstrate
   production restore and alert receipt, assign an operator, decide off-host
   encrypted backup scope/cost and recovery objectives.
5. Adopt and exercise retention/deletion and incident/access policies. Authorize
   credential provisioning via a secure channel only after registration approval
   and control evidence review; never send values in chat.
6. Review a future adapter PR with authenticated sandbox/pilot evidence, verified
   TLS and least-privilege egress. Keep fees, eligibility, exact package/variation,
   demand, competition and freshness gates blocking when absent. No purchases or
   purchase-ready outputs are enabled by CSV permission or developer approval.

## Validation of this proposal

132 local tests passed; both documented sample modes completed successfully in
ignored development paths. Workbooks have four/six sheets and no formula cells.
A development CLI-equivalent snapshot/restore reproduced both history rows
exactly with integrity ok, and the monitor returned healthy on that development
state. Missing-path, stale backup/job, failed job and corrupt backup cases are
tested. `pip check`, `git diff --check` and proposed monitor unit verification
passed. None of this is a production restore or remote CI result.
