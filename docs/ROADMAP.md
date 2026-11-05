# Roadmap

- M89 offline authentication diagnosis: local Internet socket creation reproduces
  EPERM in the restricted runtime; historical nested exception was not retained.
  Added sanitized transport diagnostics and an offline readiness report. No new
  Amazon attempts: 12/49 used, 37 remaining. A future retry requires approved
  network access and a separate authorized scope; see
  [authentication diagnosis](M89_AUTHENTICATION_DIAGNOSIS.md).

- M89 Walmart continuation: imported authorized Drive research; independently
  checked saved Catalog identity for B001BE12BA; preserved dimensional/core-size
  caveats and both UPC-conflict NEEDS_REVIEW rows. Bounded read-only executor and
  M86 report recovery added. Authentication transport failure consumed one attempt
  (12/49 total, 37 remaining); offers, eligibility and fees remain unresolved.
  See [continuation evidence and limits](M89_WALMART_CONTINUATION.md).

## Kroger source investigation — 2026-10-27

[Kroger access/terms assessment](KROGER_ASSESSMENT.md) and a
[conditional one-product/Amazon request plan](KROGER_ONE_PRODUCT_PLAN.md) are
prepared. Implementation depends on verified rights for cross-market sourcing
and evidence retention; no connector, registration, credentials, live request,
deployment, purchase or email is enabled. Target's affiliate route does not yet
establish an internal sourcing license.

## Status register — 2026-10-26

Implemented means code and fixture tests, live-verified means evidence from an
actual external interaction, deployed means installed/activated on production.
These are independent states. Deployment history below comes from existing release
handoffs; this milestone has not inspected or changed the running host.

| Capability | Implemented | Live-verified | Deployed | Blocked / next gate |
| --- | --- | --- | --- | --- |
| V0.2 CSV/mock reports + run history | Yes, existing | Offline fixture validation only; no real sourcing verified | Recorded V0.2 offline VM deployment; not re-audited here | Authorized fresh source and marketplace evidence |
| Source/match/enrichment SQLite persistence | Implemented in real-data-pilot PR; version 1, dedup and run linkage | No real supplier/SP-API/Keepa records | No | Permission/retention review before live data |
| Ten-product pipeline | Implemented offline with existing CSV, matching, Keepa contracts, screening and reporting | No; explicitly fictional fixed-clock fixtures | No | Approved ten-product CSV, seller evidence and account entitlement |
| Keepa adapter, ledger and dormant HTTP seam | Existing, reused; live code gate remains false | No account/key/request verified | No | Owner subscription/quote/license/balance and later live-enablement review |
| SP-API | Catalog/details pilot, safe count diagnostic and aggregate/detail coverage mapping; normal job unchanged | Owner-run B0G1MJ24B4 diagnostic retained HTTP 200 / Success with 5 total / 1 detail and matching context; breakdown and price validation unknown; fees/restrictions unattempted | No deployment performed | Partial coverage handling tested with synthetic evidence, excluded from ranking; cause of live count discrepancy remains unproven; no further live calls made |
| Supplier pilot | Permissioned EE Distribution evaluation CSV recommended conditionally | No account, permission or sample verified | No | Written ten-SKU internal-analysis/export/storage license and no-purchase sample quote |
| Gmail transport | Merged PR #12 | Owner confirmed attempt-3 Hotmail delivery with both attachments | Manual DEMO only; no scheduled email deployment | OAuth readiness, nonroot access and separate activation approval |
| Email scheduling | Separate inactive templates | No unattended execution verified | No | See Gmail scheduling preparation; explicitly excluded from this pilot |
| Backups / monitoring / notifications | Offline implementations and proposed units | No new live acceptance claimed | Deployment not established by preparation docs | Independent receiver, restore/deployment authorization |
| Scan Profit | No connector added | Official product source still unidentified | No | Owner-supplied official URL and documented export/API permission |

See [real-data pilot implementation](REAL_DATA_PILOT.md) and
[account/source owner checklist](PILOT_ACCOUNT_ACCESS.md). No account prerequisite
blocks independent fixture implementation. No paid calls, purchases, deployments,
production migrations or scheduled email activation are part of this PR.

Historical milestone notes below describe earlier scope; the register above is
the current status and avoids treating implemented code as live readiness.

## V0.1 — completed baseline

CSV screening, deterministic economics, openpyxl reports, SQLite run audit, sequential jobs, JSON logs, TLS SMTP, Docker and Ubuntu/Python CI. Baseline: 29 tests.

## V0.2 — implemented; offline deployment recorded

Normalized retailer connector contracts and CSV ingestion; mock Amazon exact matching and ambiguity gates; richer expense model; confidence/data-quality and ranking; six-sheet reports; persistent project documentation. Real discovery remains dependent on authorized external data; mocks are not real opportunities.

## V0.3 — preparation implemented; live access pending

Official-source research, conditional cost model, provider/evidence contracts,
mock contract tests, bounded retry/timeout policy, SQLite usage reservations and
backup/restore tooling are prepared. [Handoff](V03_PREPARATION.md) documents
scope and validation; [research](V03_PROVIDER_RESEARCH.md) identifies owner account,
pricing and license decisions. Backup scheduling remains proposed for review.
No live adapters or paid integrations are enabled; V0.2 deployment is preserved.

Research Amazon SP-API, Keepa and authorized retailer/licensed product feeds. For each integration document API availability, account permissions, credentials, current authoritative pricing, usage/redistribution restrictions and estimated monthly cost before implementation/enabling. Implement mock contract tests and rate-limit/retry/freshness policies first. Get approval before any paid service. Prioritize historical price stability, demand, offer competition and fees. Do not wait for credentials to write interfaces; do not claim live readiness without authorized requests.

## V0.4 — AgentOps AI supervisor

Observe failed jobs, source quality, match accuracy, anomalous economics, API usage/costs and performance. Generate tests and proposed PRs. Use event-driven AI, not an LLM per product. Humans approve production deployment, purchases, infrastructure and sensitive credentials. See AGENTOPS.md.

## V0.5 — lightweight dashboard

FastAPI + React unless constraints justify a simpler stack: authentication, opportunities/search/filtering, execution history, source health, profit visualization, configuration controls and authorized report downloads. Assess measured load before PostgreSQL. Avoid microservices and paid infrastructure without demonstrated requirements.

## Delivery process

Inspect main and run tests; implement on a milestone feature branch; update documentation; run tests and sample workflows; commit, push and prepare PR. Do not merge or deploy without authorization. CI status and remotely executed workflows must be reported separately from local results.

## Amazon registration readiness review

See [SECURITY_READINESS.md](SECURITY_READINESS.md) for verified file evidence,
unknown effective production controls and owner actions. Authorized CSV template,
strict offline preflight and local health monitor are prepared for review only;
no production settings or live provider have changed.

## Backup enforcement and watchdog review

Disk admission/progress checks, restore proofs and optional notification transport
are prepared with offline tests. External silence detection requires an off-VM
receiver and owner-selected notification integration; same-VM checks are not
VM-failure-independent. Production deployment and live receipt/restore acceptance
remain pending. See [operations plan](OPERATIONS_WATCHDOG.md).

## Keepa offline adapter review

Official rendered pricing/terms, bounded mock transport contracts, token reservations,
pacing, permitted optional memory caching and conservative timestamped evidence are
prepared in [KEEPA_PREPARATION.md](KEEPA_PREPARATION.md). Live code gate and job
selector stay disabled. Scan Profit identification/permissions remain unresolved.

## Credential-free demonstration milestone

Pending pilot work is preserved with every public live entry point disabled.
The existing discovery/reporting path now powers a fixed-clock, clearly labeled
DEMO with threshold sensitivity, missing-fee/package/freshness failures and
sample authorized-export diagnostics with repair actions. SMTP settings reuse and backup/monitor installation are consolidated as handoffs.
An owner-authorized DEMO email attempt using existing WeinsteinAgent settings
failed DNS before SMTP connection; no message was submitted.
See [DEMO](OFFLINE_DEMO_HANDOFF.md), [operations](OPERATIONS_HANDOFF.md) and
[pytest remediation/verification limits](PYTEST_ADVISORY.md). No deployment or live Keepa/Amazon call is included.

## Gmail delivery confirmation and scheduling proposal

The operator confirms Gmail API DEMO attempt 3 arrived in Hotmail with both
attachments. HTTPS transport hardening and private safe-reason diagnostics are
consolidated for review. Scheduled reports remain disabled in separate proposed
units; service-owned private rotating-token state and OAuth publishing/fresh
consent are activation prerequisites. See [confirmation](GMAIL_API_DEMO_THIRD.md)
and [schedule preparation](GMAIL_SCHEDULE_PREPARATION.md). Existing schedules
and all attempt reservations are preserved; no additional email was sent.

## 2026-10-27 selected-validation evidence and next intake

Owner-run authentication/pricing/fees/restrictions completed (4 HTTP 200s).
B0G1MJ24B4 is NOT_ELIGIBLE and excluded. New=1, Used=4 explains the aggregate
breakdown; documented aggregate coverage warning remains. Ten-product authorized
CSV request preparation is offline, uses existing persistence/reporting and has
no batch executor. Real authorized source rows and explicit price selections are
required before later execution authorization. See
[workflow and 31–41 attempt ceiling](AMAZON_AUTHORIZED_SOURCE_WORKFLOW.md).

## Walmart-to-Amazon owner priority, 2026-10-27

One-row intake is published as PR #22 with passing CI. The Walmart source CSV
extension is prepared offline using the existing connector/storage/reporting.
The next owner action is a BlueCart/Traject written commercial-use and sample
inquiry, not affiliate or seller registration. Public trial terms do not cover
this intended commercial use; no rights or real row are available yet. See
[exact access steps and enrichment request plan](WALMART_ACCESS_NEXT_STEP.md).

## M70 offline scalable catalog discovery

[Source/identity/ranking contracts and actual results](M70_CATALOG_DISCOVERY.md)
add hash-bound local imports, conservative identity merging, M69 history reuse and
a non-executable Catalog discovery plan. Capacity is tested above 1,000 ASINs;
available saved evidence contains 197. Further authorized source coverage is needed.
No live adapter, automatic execution, reservations or immutable-evidence changes.

## M71 Catalog discovery preparation

[Manifest, adapter and live-pilot prerequisites](M71_CATALOG_PREPARATION.md)
freeze 50 queries across ten category intents and an absolute 1+200+50 request
ceiling. A separate append-only request journal, conservative pacing, pagination
validation, private checkpoints and M70 import are tested offline. The CLI only
prepares/validates proposals; live transport, credentials and all selling operations
remain disabled. Separate reviewed activation and fresh owner authorization are required.

## M72 controlled Catalog pilot

[One-shot pilot and owner procedure](M72_CONTROLLED_CATALOG_PILOT.md)
add a separate fixed operation registry, global account lock, durable pre-dispatch
accounting and a 1-authentication/9-first-page-query ceiling. Fresh account/code/
proposal/history-bound owner authorization and explicit execution flag are required.
Private checkpoints feed unchanged M70 ingestion and identity quality reporting.
Implementation/testing is offline; no live authorization or requests occurred.

## M73 offline catalog consolidation

A read-only verifier binds the completed ten-request M72 operation/checkpoint and
original M70 baseline before combining observed identities. Private Excel/CSV/JSON
reports retain per-ASIN provenance, all exclusions, unresolved GTIN alternatives,
diversity, research priority and discovery scenarios. The actual union is 377 real
ASINs (623 remaining); no new network or seller-specific operations are enabled.
See [M73 evidence and review procedure](M73_CATALOG_CONSOLIDATION.md).

## M74 intelligent discovery planning (offline only)

M74 verifies every M73 completion-manifest file and reuses the unchanged read-only
source validator before planning. Fifty-one reviewable candidates distinguish 41
unexecuted M71 definitions from ten new vocabulary hypotheses. Observed overlap and
coverage stay separate from duplicate-scenario projections. A proposed M75 contract
caps a future new one-shot operation at 1 authentication plus 20 first-page searches;
no executor, authorization artifact or registry is created. Private deterministic
workbook/JSON/CSV reports bind input, code and output hashes. See
[M74 evidence, command and future-operation proposal](M74_DISCOVERY_PLANNING.md).

## M75 controlled Catalog expansion

A separate manual executor pins the M74 completion, canonical/file manifest and
exact contract before admitting one authentication plus twenty first-page keyword
requests. A new permanent M75 registry, existing exclusive account lock, durable
before-dispatch accounting, bounded TLS transport and fresh ten-minute owner
authorization enforce no replay. Original M72 and M63–M74 evidence remain unchanged.
Development ran only offline validation and synthetic tests; no live requests or
authorization artifacts were created. See [M75 review and future owner procedure](M75_CONTROLLED_CATALOG_EXPANSION.md).

### M76 — Offline Catalog Consolidation and M77 Discovery Planning

Implemented offline consolidation: 377 M73 + 400 new M75 = 777 distinct real ASINs;
223 remain. Outputs preserve provenance, identity gaps, 49 unresolved conflict
ASINs, 97 historical exclusions and 40 seller-check annotations. Zero fully
identity-complete or purchase-ready records. JSON/CSV/Excel and evidence hashes
are documented in [M76](M76_OFFLINE_CATALOG.md).

M77 remains an offline proposal: 23 unused query hypotheses offer 460 hypothetical
slots and project 230 incremental ASINs at an assumed 50% duplicate rate. Yield is
not guaranteed. Separate implementation, review and owner authorization remain
future work; no M77 executor or permission artifact exists.

## M77 — Controlled Catalog Discovery Expansion

Implement the separately authorized one-shot scope for all 31 reviewed M76
candidate phrases, q020–q050: at most one LWA + 31 Catalog first-page searches,
620 raw observations, new permanent no-replay registry and preserved M72/M75 history.
Deliver strict original-chain validation, interactive expiring authorization,
locked durable accounting, bounded TLS/pacing/deadline, private compatible exports,
read-only recovery and offline failure/security regression coverage.
Implementation does not authorize live requests, deployment, purchases or a
1,000-ASIN success claim. Baseline remains 777, with 223 remaining until separately
authorized observed evidence proves otherwise. Correct the misleading M76
“unobserved intent” rationale in new documentation without changing its outputs.
See [M77 operator handoff](M77_CONTROLLED_CATALOG_EXPANSION.md) and
[validation audit](M77_SAFETY_AUDIT.md).

M81: owner pilot readiness and archived code provenance; M82: exact saved-receipt
profitability; M83: integrated offline dashboard/workbook and separate weekly observation
history. These milestones remain proposals until reviewed/merged. Live Amazon acquisition,
Walmart sourcing, purchases and deployment each require separate authorization; no
historical catalog list price or synthetic result clears those gates.

M84 prepares an independently reproducible, bytecode-free offline release, local
configuration validation, read-only host preflight and isolated operational runbook.
Target security remains NOT_TESTED until separately authorized host validation;
artifact authentication, staging and deployment remain owner approval gates.

M87 prepares offline six-product Walmart evidence integration with M86, explicit
new-batch identity, saved Agent exports and bounded Amazon request previews.
Fresh collection and a reviewed approval-bound live executor remain separate gates.

M88 adds a source-only human-reviewed browser intake and six-row blank template
with five explicitly unverified historical leads. Offline validation publishes
M87-compatible input without network access or Amazon budget changes. Real source
observations and exact Amazon matching remain outstanding. See
[browser intake](M88_BROWSER_INTAKE.md).

M88 executor: a separate owner-invoked read-only 31-attempt conditional SP-API
pilot, cumulative ceiling 49, durable pre-dispatch accounting and no replay.
Unresolved source identities remain unresolved; offers/fees require exact matches.
Offline synthetic tests cover failures, interruption, accounting and reports.
See [executor handoff](M88_AMAZON_EXECUTOR.md). Live results belong to private
versioned reports; implementation alone is not proof of successful acquisition.

M88 identity enrichment: inspect the 60 saved candidate records / 56 distinct
ASINs offline before additional calls. Preserve all source evidence and 7/49 ledger;
produce per-product barcode/variant/package gaps and a prioritized ordinary-browser
handoff. Three textual leads remain unverified; no compatible lead is established
for the other three cohorts. See [offline identity comparison](M88_IDENTITY_ENRICHMENT.md).

M88 enriched reconciliation imported a second authentic six-row Browser Use JSON
and compared all 60 saved pairs offline: 0 exact, 34 rejected, 26 needing review.
No additional Amazon requests; cumulative accounting remains 7/49 COMPLETE.
Required source conflicts, missing screenshots and model/package ambiguities block
acceptance and supported profitability. New M86 JSON/Excel and missing-data reports
preserve the original evidence. See [reconciliation](M88_ENRICHED_RECONCILIATION.md).

M88 targeted verification ranked 26 unresolved pairs and performed one approved
three-ASIN Catalog detail pass. Four new HTTP attempts (auth + three details) bring
the unchanged cumulative accounting history to 11/49 COMPLETE. Independent Amazon
MPNs/dimensions are now retained, but source/model/package ambiguities leave zero
exact matches and zero supported profitability products. No offers/fees sent.
See [targeted continuation](M88_TARGETED_VERIFICATION.md).

## M89 Amazon-first sourcing: offline research preparation

Offline shortlist/checklist generator implemented from saved M88 Catalog evidence.
No new Amazon HTTP requests; ledger remains 11/49 COMPLETE with 38 remaining.
Independent exact Walmart retail identity and complete M86 economics remain the
next gates; three verified profitable products are not yet established.
See [M89 sourcing](M89_AMAZON_FIRST_SOURCING.md).
