# M74 — intelligent offline Catalog discovery planning

M74 builds on merged PR #62 and verifies the completed M73 artifacts before
planning. It has one action, `plan`, and no live execution, authorization or resume
entry point. It makes no Amazon/authentication/retailer requests, creates no live
owner authorization or operation registry, and does not enable purchases. All
M63–M73 modules, original sources, reports and execution evidence remain unchanged.
The target counts distinct real observed ASINs, including permanent exclusions;
it does not count eligible or profitable products.

## Evidence verification and reproducibility

The caller supplies the reviewed SHA-256 of the original
`M73_output_digests.json`. M74 requires its exact twelve-file inventory and checks
every actual report file, including the workbook, CSVs and JSON. Missing files,
omissions, additional manifest keys, traversal, symlinks, unsafe permissions,
wrong digests and duplicate JSON keys fail closed. Manifest hash:
`07be04f0c8e96dd6999841beef75a45e5afa3177d931cb0d3323e47df497b773`.

M74 reuses unchanged `app.m73_evidence.load`: the original M70 report/CSV binding,
M71 proposal/file digest, completed ten-request M72 checkpoint, exact nine pages,
request intents and all historical exclusions are checked again. That loader's
existing temporary M70 serialization is a checksum verification; it never writes
the original baseline. M74 does not invoke M73 run/export or regenerate its files.
In-memory M73 analysis must equal the already completed report, summary and input
hash inventory. M74 also checks the reviewed 377/197/180/623 counts, 97 exclusions,
40 checked ASINs, 31 conflicts and 305 offline research candidates.

Input digests and the historical inventory are checked again before output and
before the final M74 completion manifest. Current code hashes must also remain
unchanged. An interrupted/failed output has no completion digest manifest and must
not be used. Existing output paths cannot be overwritten.

Planning contains no current-time fields. Workbook document properties and ZIP
metadata use a fixed serialization timestamp, not an observation date. Actual
original observation times remain in the immutable source chain. Equal inputs
and implementation produce identical JSON, CSV, XLSX and completion-manifest bytes.
The original evidence hashes are recorded under logical names without private paths.

## Observations and coverage limits

Verified baseline: **377 real ASINs**, **623 remaining**, 153 observed brand labels,
25 observed category labels, 97 exclusions, 40 checked seller-specific ASINs,
31 unresolved GTIN-conflict ASINs and 305 offline identity research candidates.
Eligibility and profitability remain unverified.

Nine M72 first pages executed q001–q009, each returning 20 distinct ASINs, with no
baseline overlap or pairwise ASIN overlap. All 36 observed query pairs have zero
shared ASINs. Exact brand/category label intersections are also reported. Every
page has an unfollowed cursor; a cursor is not evidence about remaining result
counts and is never exposed as an executable continuation in M74.

M71 has ten intents. `personal_care_accessories` is the only intent without a
completed M72 page. The other nine have one first page each, not exhaustive coverage.
Legacy M70 categories (`office`, `kitchen`, etc.) and M72 browse labels differ in
granularity; M74 does not infer a semantic mapping or marketplace-wide coverage.

Eleven exact observed category labels contain at most two ASINs: Accessories,
Cord Management, Flea Combs, Garage & Shop, Garden Stakes, Garden Twine & Twist Ties,
Interior Accessories, Magnetic Sweepers, Mats, Rakes and Seat Back Organizers.
The two-ASIN threshold is a reporting rule, not evidence of demand, supply or
marketplace scarcity. No new query has an invented ASIN yield, search volume,
marketplace product count or uniqueness probability. Those fields remain unknown.

## Candidate ordering and provenance

The deterministic manifest contains **51** first-page candidates:

- **41 original frozen M71 definitions**, preserving their q010–q050 IDs, exact
  definition hashes and proposal references. q001–q009 remain recorded as executed
  and cannot appear in the candidate list or future request allowlist.
- **10 new human-vocabulary hypotheses**, with separate `m74-nNNN` IDs and explicit
  configuration/code traceability. These are proposed new intents and wording, not
  verified service category IDs or proof of missing semantic coverage.

Priority favors breadth of untested vocabulary rather than predicted productivity:
q010 is first because it is the earliest frozen phrase in the only untested M71
intent. Ten new intent hypotheses follow. Remaining frozen definitions retain
round-robin order; later personal-care phrases return at their original positions
instead of exhausting that intent before other categories. Exact normalized phrase
reuse is rejected, and shared words with executed phrases are reported as lexical
overlap only. Lexical overlap does not establish ASIN overlap.

The proposed M75 first twenty requests use:

| Order | Query ID | Exact phrase | Origin |
|---:|---|---|---|
| 1 | q010 | soap saver pouch | Original M71 |
| 2 | m74-n001 | silicone baking brush | New hypothesis |
| 3 | m74-n002 | luggage handle wrap | New hypothesis |
| 4 | m74-n003 | mesh laundry wash bag | New hypothesis |
| 5 | m74-n004 | shower curtain clips | New hypothesis |
| 6 | m74-n005 | microfiber dusting mitt | New hypothesis |
| 7 | m74-n006 | sewing seam gauge | New hypothesis |
| 8 | m74-n007 | tent guyline adjusters | New hypothesis |
| 9 | m74-n008 | bicycle valve adapter | New hypothesis |
| 10 | m74-n009 | monitor memo board | New hypothesis |
| 11 | m74-n010 | seedling transplant tool | New hypothesis |
| 12–20 | q011–q019 | Exact unchanged M71 phrases | Original M71 |

The new vocabulary is an explicit exploration choice. A broad legacy label can
already include products related to one of these proposed intents. No claim that
these searches will be unique, high demand, high margin or eligible follows.

## Request-cost scenarios

These projections apply the specified duplicate assumptions to the remaining
**623** distinct-ASIN target. Every projected page is assumed to contain twenty
usable observations. Duplicate rates include overlap with the accumulated catalog.

| Duplicate assumption | Result slots | Keyword pages | One hypothetical operation: auth + pages | Separate batches of at most 20 pages: auth / total |
|---|---:|---:|---:|---:|
| 25% | 831 | 42 | 1 + 42 = 43 | 3 / 45 |
| 50% | 1,246 | 63 | 1 + 63 = 64 | 4 / 67 |
| 75% | 2,492 | 125 | 1 + 125 = 126 | 7 / 132 |

These are conditional planning ceilings, not observed uniqueness rates, worst-case
bounds or authorization. Sparse pages and invalid observations can require more
requests; no finite completion guarantee follows. Monetary API costs are unknown
and are not estimated. The proposed M75 hard ceiling remains **21**, regardless
of these larger scenarios. Authentication is counted in every operation.

The 51 proposed distinct first-page definitions can supply at most 51 search pages.
The 50% and 75% scenarios need at least 12 and 74 additional reviewed definitions,
respectively, before their page estimates could be supplied without query reuse.
M74 never fills a shortfall by repeating a query or following an existing cursor.
Additional batches would need separately reviewed contracts, new operation IDs,
permanent registries and fresh owner authorizations; this plan does not create them.

## Proposed M75 contract — implementation and authorization still required

`M75-US-CATALOG-EXPLORE20-ONCE` and `m75-catalog-discovery.sqlite3` are a new proposed
operation identity and permanent registry, separate from M63/M67/M72. Neither is
allocated by M74. The contract is marked PROPOSAL_ONLY, live disabled and unauthorized.

The exact allowlist is one POST to `https://api.amazon.com/auth/o2/token` using the
existing account's refresh-token grant, then at most twenty US Catalog GETs to
`sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items`. The artifact enumerates
every phrase and parameter: `marketplaceIds=ATVPDKIKX0DER`, `pageSize=20`, M71's
included datasets and `keywords`. No other keys, identifiers, detail requests,
pageToken, retries, refreshes, eligibility, pricing, fees, FBA, retailer, listings,
purchases or approval submissions are allowed. Maximum raw result slots: 400,
so even zero duplicates cannot close the 623-ASIN gap in this batch.

A future reviewed implementation must acquire the existing exclusive account lock,
exclusively create and fsync its permanent registry and parent, persist an immutable
claim, and FULL-synchronously account for exact intent before every dispatch,
including authentication. Any prior claim blocks forever, including zero-request
stops and hard kills. Stop on the first error, throttle/Retry-After, timeout,
interruption, expiry, drift or uncertain dispatch. No retry, replay, resume,
replacement query or reassignment of unused slots is permitted. Preserve partial
successful pages privately and audit consumed/uncertain slots.

Use verified TLS without inherited proxies, redirects, SDK retries or automatic
refresh, at most one effective search request per second with no burst, lower
frozen/saved/response limits and existing cooldowns respected, a ten-second socket
timeout and a 120-second hard operation deadline.

Future explicit owner authorization must be interactive, at most ten minutes old,
UTC-expiring and bound to the new M75 operation, exact reviewed executable code,
M74 manifest file/canonical digests, completion and contract-file digests, current
evidence/history, existing account/credential binding and US marketplace, exact
query sequence, integer 1/20/21 budget and no-replay acknowledgement. Validate before
credential loading and before every dispatch under the lock. All historical
approvals are inapplicable. M74 creates no authorization artifact or authorization
command, and its hash-bound plan is not owner permission.

## Exact offline planning command

```bash
.venv/bin/python -m app.m74 plan \
  --m73-dir var/m73-final \
  --m73-digests-sha256 07be04f0c8e96dd6999841beef75a45e5afa3177d931cb0d3323e47df497b773 \
  --baseline-dir var/m70-offline-final \
  --baseline-report-sha256 228c29245ab8898fb4647aa5016b0e86b49ac6546ebef546480a65c941370a56 \
  --proposal var/m71-preparation/M71_manifest.json \
  --private /root/.intelligenceos-arbitrage-amazon \
  --checkpoint 260e03e15b79c77b96430d3416a57fefc65c374421489fe34937d92e41077dd4 \
  --sources /root/.intelligenceos-arbitrage-amazon/m72-catalog-pilot-output/M72_M70_sources.json \
  --summary /root/.intelligenceos-arbitrage-amazon/m72-catalog-pilot-output/M72_summary.json \
  --store var/m66-local/intelligence.sqlite3 \
  --m67-manifest var/m66-expanded-review/M66_review_manifest.json \
  --m67-sha256 8983bef70ce5cfd79d15b7611e4b5646784f37bfce1a88bd220286394303ee55 \
  --output var/m74-final
```

The actual output already exists; a later verification run needs a fresh sibling
path. `var/` is ignored. Files use 0600 and directories 0700. Outputs include:

- `M74_discovery_plan.xlsx` and matching CSV tables for summary, queries, observed
  coverage/overlap, intent gaps, diversity, scenarios, exclusions, conflicts and M75 design.
- `M74_query_manifest.json`, `M74_M75_contract_proposal.json`,
  `M74_coverage_overlap.json`, `M74_budget_scenarios.json`,
  `M74_history_summary.json`, `M74_executive_summary.json` and `M74_planning_report.json`.
- `M74_evidence_digests.json`, binding original inputs, implementation, canonical
  query manifest and every output file. The CLI prints its file SHA-256.

All observations, human hypotheses and scenario projections are explicitly labeled.
CSV/Excel strings are formula-safe. Raw credential/account values, owner artifacts,
access tokens, private paths and continuation cursor values are absent from reports.

## Actual validation

Baseline: **1,903 passed**. Targeted M74: **28 passed**. Final full regression:
**1,931 passed in 200.98 seconds**. Both documented offline sample modes passed
with socket connections blocked. Tests cover the original digest inventory, changed
and resealed reports, wrong source/checkpoint bindings, deterministic byte output,
query/phrase replay fencing, budget arithmetic and authentication overhead, contract
bounds, synthetic fixtures never entering real reports, privacy, no network or
historical execution/report export, protected paths and mid-export evidence drift.

Two actual guarded planning runs produced byte-identical files, including the
workbook and completion manifest. Twenty-seven original input/report files retained
identical hashes; all 68 private-directory entries retained identical inventory,
sizes, modes and mtimes. Network calls and production credential/live-owner-artifact
reads were blocked. No request, authorization, registry, merge or deployment occurred.

Canonical query manifest SHA-256:
`e9119972fd0257d9da5f1dbb1518567c859001d0a957946a0f846b9d26931105`.
Completion file SHA-256:
`0224671c5011e26182c7f117516149d83cb97c1a77b4f362e59b2627005a815a`.
