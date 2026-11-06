# M90.1 controlled authentication and Catalog validation

Code and mocked testing only. No staging, deployment, credential reads, Amazon
requests, ledger modifications, service changes or symlink changes authorized.
The integration core is `app.m901.execute`; intentionally no live CLI is exposed
until the concurrency and permissions design is reviewed. M90's old token-pipe
command is not the M90.1 workflow and must not be used for this scope.

## Fixed scope and accounting

The exact full starting ledger hash is
`c79e2a7788c3b99ee75a17dc3150b9e2a609818ad2de3cce82f082e36c9b79f1`.
M90's history verifier additionally reconstructs the entire first twelve attempts
and verifies M89's canonical baseline, successful authentication attempt 13 and
chronology. No historical entries are discarded. The caller cannot select a new
baseline hash. Sole ledger: `/var/lib/intelligenceos-arbitrage/m89/ledger.json`.
The production `/current` symlink target is pinned too.

| Event | Used / ceiling | Remaining | Next action |
| --- | --- | --- | --- |
| Initial verified state | 13/49 | 36 | No dispatch |
| Durable independent claim; before attempt reservation | 13/49 | 36 | No dispatch until reservation fsync succeeds |
| Durable authentication reservation | 14/49 | 35 | One LWA POST |
| Authentication failure, uncertainty or crash | 14/49 | 35 | Stop; no attempt 15 |
| Authentication completion durably saved | 14/49 | 35 | Reserve Catalog attempt |
| Durable Catalog reservation | 15/49 | 34 | One Catalog GET |
| Catalog success, failure, uncertainty or crash | 15/49 | 34 | Stop; no retry |

POST goes only to `https://api.amazon.com/auth/o2/token`. GET goes only to
`https://sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items/B001BE12BA?marketplaceIds=ATVPDKIKX0DER&includedData=summaries`.
No redirects, retries, refreshes, offers, fees, eligibility calls or purchases.
Each request has a socket timeout and absolute deadline. Uncertain attempts remain
RESERVED or FAILED and charged. A failed durable write prevents the next dispatch.
An independent exclusive, fsynced `m901-no-replay.json` in the ledger directory
prevents replay after ledger-only rollback. Never remove this claim. A crash
between claim and reservation conservatively blocks the workflow without charging
an undispatched attempt. Restoring both the claim and ledger, or malicious changes
by their owner, cannot be detected by local files alone: independent immutable
storage would be required for that stronger threat model. Never restore accounting
files during code rollback.

## Security and actual permission findings

Inspected existing M89 authentication/configuration, M90 execution, M88 durable
storage/locking, private-path checks, deployment guidance and installed service
unit. Did not open credential files. Configuration is reused in memory only;
no tokens enter arguments, environment, ledger or other files. Responses are
bounded; only fixed safe result fields persist. Credentials clear after LWA;
token reference clears immediately when Catalog transport returns or raises,
and in outer cleanup on earlier failure. Core dumps are disabled. Python and TLS
libraries may retain immutable copies: reference disposal is not secure memory
zeroization. No request/error body or raw exception is logged by this core.

Observed `/root` and `/root/.intelligenceos-arbitrage-amazon` mode 0700/root;
actual shared lock mode 0600/root. getfacl confirms no extended ACL grants on
these three paths. Service uid 999/gid 987 is
`intelligenceos-arbitrage`, so it cannot traverse `/root` or open that lock.
The installed unit also has ProtectHome=true, NoNewPrivileges=true,
RestrictAddressFamilies=AF_UNIX and IPAddressDeny=any. It is an offline report
service. systemctl inspection of runtime state is denied by this sandbox; unit
contents are readable. Do not weaken `/root`, change this unit, duplicate the
lock or choose another lock. Existing lock acquisition uses O_NOFOLLOW without
O_CREAT, validates private metadata/inode and holds flock across both requests
along with the original ledger lock.

Live execution is BLOCKED. Recommended design for separate review: a narrowly
scoped privileged broker that alone opens the existing root-owned shared lock,
reads protected credentials, verifies reviewed account evidence, and owns both
HTTP calls and all authoritative accounting. It must have a separate reviewed
network-enabled runtime and sanitized output. Alternative: migrate every Amazon
writer atomically to one reviewed shared lock outside `/root` during an approved
maintenance cutover. Moving only this workflow is unsafe. Neither is implemented
or approved here.

Ledger stat/hash attempts returned Permission denied in this session; supplied
13-attempt facts are pinned but not independently verified. Remote seller
application authorization, Product Listing role and US marketplace participation
remain UNVERIFIED. The workflow requires a private operator-reviewed context
outside the repository: seller_id, marketplace_id, reviewer, aware reviewed_at
within 24 hours, plus seller_authorization, application_product_listing_role,
us_marketplace_participation and protected_credentials_binding, each containing
confirmed=true and a reference to actual evidence. Do not fabricate values or
silently set flags. This validates evidence presence, not remote authorization;
the reviewer must inspect the actual seller/application records and credential
binding. No extra remote verification requests are authorized by this budget.

## Production releases

Read-only `/current` inspection resolves to
`/opt/intelligenceos-arbitrage/releases/68230d3fdaef588bb7ba5c8340f49a473e8386b7`:
V0.2 merged PR #2, offline legacy/discovery report jobs. It is not M89.
Reviewed M89 is `6a09b7a503906fa3fd96eae1ea9472d15859865f`, a separate manual
validation release; M90 `cb1125613fd7a18a991519ee251c577c578a855a` was separately
staged per operator facts. Existing symlink and all services/timers stay intact.

## Staging approval and rollback

Staging approval authorizes only a separately named immutable release directory,
verified archive/commit, Python 3.12 dependencies and mocked tests. It does not
approve requests, credentials access or ledger writes. No staging performed here.
After approval, stage without replacing `/current`, services or timers; run the
commands below from that release. Pin all reviewed inputs and record results.

Rollback of staging means stop using the new release and retain the previous
staged release. Do not move `/current`, restore the ledger, remove the claim,
reset attempts or replay a failed workflow. After any possible request, inspect
authoritative accounting under both locks using the reviewed broker; report-only
recovery is required. No automatic repair/resume exists.

## Separate live-request approval

Required only after reviewed broker/lock design, actual service identity access
verification, independent production ledger hash verification and genuine seller
and role evidence review. Approval must name the final immutable commit, original
13-attempt hash, exact lock inode/path, credential source, evidence references,
POST attempt 14 and conditional GET attempt 15, ceiling 49 and no retries.
The integration approval constant is `APPROVE_M901_AUTH14_CATALOG15`; supplying
this string is not itself evidence of operator authorization. No live shell
command is provided while the permission blocker remains unresolved.

## Exact safe offline verification

From the repository, use the existing Python 3.12 environment:

```bash
cd /root/IntelligenceOS-Arbitrage-clean
/tmp/arbitrage-ci-fix-py312/bin/python -m pytest -q tests/test_m901.py tests/test_m90.py
/tmp/arbitrage-ci-fix-py312/bin/python -m pytest -q
ARBITRAGE_MODE=legacy ARBITRAGE_REPORT=/tmp/m901-legacy.xlsx ARBITRAGE_DB=/tmp/m901-legacy.sqlite3 /tmp/arbitrage-ci-fix-py312/bin/python -m app.orchestrator
ARBITRAGE_MODE=discovery ARBITRAGE_REPORT=/tmp/m901-discovery.xlsx ARBITRAGE_DB=/tmp/m901-discovery.sqlite3 /tmp/arbitrage-ci-fix-py312/bin/python -m app.orchestrator
```

Tests use synthetic credentials, private synthetic ledgers and mock transports.
They cover success, authentication failure, 401/403, 429, 5xx, redirects, timeouts,
catchable/uncatchable crashes, storage failures before/after dispatch, shared lock
contention/missing lock, credential disposal, replay and ledger-only rollback,
historical tampering, exact Catalog target and production-release drift.

## Recorded offline results

Python 3.12 existing environment, 2026-11-06:

- Before implementation: existing M90 baseline, 35 passed.
- Full existing suite: 3017 passed, 9 skipped in 778.06 seconds. Collection
  occurred before the new M90.1 test file was added.
- Final M90.1 test file: 35 passed in 1.10 seconds.
- Final focused M89 deployment + M90 + M90.1: 81 passed in 3.95 seconds.
- Final collection: 3061 tests. Full existing suite plus separately executed new
  tests cover 3052 passes and 9 skips; these totals are from split runs, not a
  claimed single final full-suite invocation.
- Both documented legacy and discovery sample modes: job_succeeded.
- git diff --check: clean.

Production accounting remains unchanged by this work: zero Amazon requests and
zero production reservations. The supplied starting state remains 13/49 used,
36 remaining, subject to independent verification in the approved runtime.
