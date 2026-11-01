# M71 — real Catalog discovery preparation

M71 freezes a reviewable Catalog-only request proposal and implements bounded
request construction, accounting, pagination, pacing, response persistence and M70
handoff. **Preparation only:** no authentication, Amazon/retailer API requests,
eligibility checks, ASIN claims, offers, purchases or approval submissions occurred.
`app.m71` exposes only `prepare` and `validate`. There is no execution, authorization,
resume, scheduler or credential-loading command. `CatalogTransport.send()` fails
closed unconditionally. A later live entry point and TLS activation require a
separately reviewed change and fresh explicit owner authorization.

## Inspection and reuse

The base is merged PR #59, commit `67d991cc169ce669b1538dade588919218863177`.
M70's plan allocates one authentication, 200 keyword pages and 50 identifier pages.
M71 retains that ceiling and M70's existing saved-page adapter, source provenance,
ASIN deduplication and identity-quality/ranking engine. No discovery engine is copied.

`m69_history.consolidate` reads the original M63 proof/outcomes, legacy ledger,
M67 permanent claims/outcomes and frozen ranking, plus the derived store. It excludes
all claims conservatively; it does not rely on the derived store alone. M71 invokes
this read-only history with no catalog reanalysis. Missing, conflicting or unbound
history prevents proposal creation. Future changes to claims/history, code or pacing
invalidate validation against the original proposal. No M63–M70 module is modified.

Original M67's safeguards informed the new adapter: exact allowlists, durable
accounting before dispatch, one authentication, bounded pacing, no retries or refresh,
no replay after interruption, and no exception/response secrets in diagnostics.
M71 never invokes M63/M67 execution, creates their locks/ledgers, or opens production
credentials/account context. Existing authorization files and ledgers are not modified.

## Exact proposed coverage and request budget

| Phase | Exact proposal | Maximum requests |
|---|---|---:|
| Authentication | One LWA token exchange, no refresh/retry | 1 |
| Keyword discovery | 50 distinct unbranded phrases × at most four pages | 200 |
| Identity enrichment | At most 50 single-page identifier batches of up to 20 collected unclaimed ASINs | 50 |
| All other operations | Details, restrictions, pricing, fees, FBA, offers, retailers, purchases, approvals, retries | 0 |
| **Absolute total** | No phase borrowing, automatic extensions or new query partitions | **251** |

Ten category intents each receive five queries. The order is round-robin across
intents on the first page, then across still-active queries on each subsequent
page. Reaching the target early therefore does not start with five queries in just
one category. Queries contain no national-brand seeds or `brandNames` filter.
This reduces input concentration; it cannot guarantee returned brand diversity,
small brands, permissions, profitability or 1,000 distinct results.

Marketplace is US `ATVPDKIKX0DER`; Catalog requests are GET
`https://sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items` with
`marketplaceIds`, `pageSize=20`, and `includedData=summaries,identifiers,relationships,attributes,productTypes,classifications,dimensions`.
Keyword requests additionally contain the exact frozen phrase and, after the first
page, its exact prior response `pageToken`. No detail-by-ASIN endpoint is allowed.
Authentication is POST `https://api.amazon.com/auth/o2/token` with the private
refresh-token grant contract. Credentials and access tokens never appear in the
manifest, preview, request hashes, journal event payloads or summary.

The service supports `classificationIds` for keyword searches; no verified IDs
were available in the frozen inputs. Category names below are **intent labels**,
not fabricated browse IDs or active service filters. The current search operation
has no product-type filter parameter; `productTypes` is requested as observed data,
not sent as a query filter. Adding verified category IDs requires refreezing the
proposal and renewed review. [Official operation reference](https://developer-docs.amazon.com/sp-api/docs/catalog-items-api-v2022-04-01-reference).

The theoretical 4,000 keyword result slots are neither unique nor guaranteed.
At 20 items/page, 1,000 distinct usable ASINs would require 50/100/200 keyword pages
at hypothetical 100%/50%/25% unique usable yields. Sparse results, overlap, excluded
ASINs or exhausted queries can miss the target within 200 pages. Query pagination
is at most four pages (80 result slots), below the service's 1,000-result window.

Identifier targets are the first at most 1,000 sorted distinct **newly discovered,
unclaimed** ASINs. M70's existing 197 products are not silently added to that list.
Forty checked eligibility ASINs and every historical exclusion are filtered before
explicit identifier requests. Generic keyword results may incidentally contain
excluded ASINs: retain their provenance but never admit them to the candidate set.
Identifier responses cannot introduce a new ASIN or additional page; a continuation
cursor stops the operation for review. No attempt is made to fetch every page at
extra cost or spend unused keyword slots on identifier work.

## Pacing, accounting and interruption behavior

The frozen manifest records actual process configuration from M70's plan and the
unchanged `OperationPacer`. Repository search cap is 2 RPS and default headroom is
0.5, giving effective 1 RPS. Configured environment values may only lower the cap;
changes invalidate current-proposal validation. Returned rate-limit headers can only
reduce the effective rate. Burst capacity is not used. No persistent legacy pacer
state is written. A future live preflight must read/reconcile outstanding global
cooldowns and serialize with the existing account execution lock before any dispatch.

Amazon's [rate-limit guide](https://developer-docs.amazon.com/sp-api/docs/catalog-items-api-rate-limits)
lists account/application 2 RPS, burst 2, application search 500 RPS and keyword
application 50 RPS. Its operation reference currently lists 5/5. M70 records that
discrepancy and M71 preserves the lower configured caps. Actual account usage plan
and headers remain unknown; there was no live probe. First failure, 429, or any
Retry-After response stops with no automatic retry, refresh or sleep-and-resend.
At default configuration the maximum 250 Catalog requests require approximately
250 seconds of pacing alone; authentication and latency add time. The internal
adapter deadline is finite and at most 900 seconds, checked before dispatch and
after response. Future live transport needs an independent hard deadline and bounded
network timeout so a blocked socket cannot overrun the account authorization window.

`m71_journal.Journal` creates only a **new dedicated path** using exclusive creation
and owner-only permissions. It never opens/migrates/resets/resumes an existing ledger.
Append-only SQLite events bind the proposal, record a one-shot START, ATTEMPT,
RESPONSE and terminal STOP/COMPLETE, with a hash chain and update/delete triggers.
Each attempt consumes its phase and total request slot in a committed FULL-synchronous
transaction **before** the transport can dispatch. An interruption after that commit
burns the slot, even if no response arrives. No M63/M67 ASIN reservation is made.
The journal used in tests is a new synthetic temporary file; preparation does not
create a real execution journal or consume request slots.

The frozen preview numbers logical proposed slots; actual consumed slot numbers
are sequential and omit skipped terminal/target-reached pages. Skipped logical
requests are unused capacity, never reassigned to extra queries or operations.
Request hashes bind phase and exact parameters (opaque cursor included only inside
the hash); successful page checkpoints retain query ID, page index, timestamp,
response hash, manifest hash and actual slot. Response/token contents stay private.
The pending request hash can be reconciled against the frozen queries and prior
private cursors even if dispatch is interrupted before the response checkpoint.

`checkpoint(path, manifest)` opens the dedicated journal read-only, validates its
chain/budget/binding and returns saved pages plus uncertain consumed slots. A hard
kill with no terminal marker is `UNCERTAIN_NO_REPLAY`. Recovery is evidence export,
never dispatch continuation. Completed/stopped/uncertain runs cannot be reopened
through the Journal constructor. Database/trigger protections do not defend against
privileged filesystem rollback; retain original journals and backups. A future live
global operation registry must prevent recreating an authorized operation under a
new path; M71's disabled transport cannot perform any live replay.

## Saved evidence handoff to M70

Successful pages are persisted after each validated response. Invalid ASINs,
oversized/malformed pages, wrong marketplace datasets and repeated/invalid cursors
stop the whole run. Earlier successful pages survive. M70 already recognizes a
final nextToken as a partial query window and will not fetch another page.

`save_catalog(result, new_private_directory)` writes `M71_catalog_pages.json`,
`M71_M70_sources.json` and a redacted `M71_discovery_summary.json`. The local source
manifest uses M70's `amazon_catalog_pages` adapter, file SHA-256, US scope and a
nonsecret permission reference. Page records include the proposal/response hashes,
original timestamps and private cursor chain. Secret/account keys are removed,
known private credential/token values are redacted from product fields, and only
allowlisted Catalog product datasets are saved. Authentication bodies are hashed
in memory and never persisted. No price is inferred; identity data remains observed,
not verified, and eligibility remains UNKNOWN.

The M70 engine remains responsible for cross-source deduplication, conflicts,
missing-field indicators, identity quality and diversified candidate ranking.
Catalog presence never supplies seller condition, listing permission or eligibility.
Synthetic rehearsal responses are tests only; never label or export them as real
catalog observations. No rehearsal was run against real services in this milestone.

## Actual frozen preparation artifacts

```bash
.venv/bin/python -m app.m71 prepare \
  --store var/m66-local/intelligence.sqlite3 \
  --history-dir /root/.intelligenceos-arbitrage-amazon \
  --m67-manifest var/m66-expanded-review/M66_review_manifest.json \
  --m67-sha256 8983bef70ce5cfd79d15b7611e4b5646784f37bfce1a88bd220286394303ee55 \
  --output var/m71-preparation
```

A new owner-only directory contains `M71_manifest.json`, `M71_request_preview.md`
and `M71_manifest.sha256.json` (file digest plus canonical proposal digest).
Existing output directories are rejected. The same history/configuration/code
produced identical manifests twice. Actual output contains 97 permanent exclusions,
all 40 checked-ASIN references, 50 queries and the 251-request ceiling.

File SHA-256: `0161373a75c3a744c97bd20a0caefd7afb5527158794c15875ac1946963fa26c`.
Canonical proposal SHA-256: `b09cbea8033caa994b8a79c2451851b1cc91171548e73cadf1c1ebef35731103`.
These digests describe the artifact generated for this code/configuration/history;
any changes require a new proposal and renewed review. Original protected evidence
(seven proof/outcome/ledger/store/frozen-source files) retained identical hashes,
sizes and modification times. All 62 entries in the private directory retained
identical inventory/size/mode/modification metadata. Production credential contents
were not loaded or hashed. Generated private manifests/reports are ignored by Git;
this document contains the reviewable query list and operation contract.

Validate a frozen artifact against the current read-only evidence using the same
history arguments plus `validate --manifest ... --sha256 FILE_SHA256` in place
of the `prepare --output ...` action. No authorization file is created or consumed.
A failed validation uses fixed redacted errors and creates no request/account state.

## Separately authorized live pilot instructions

1. Review every frozen keyword phrase, scope, phase cap, identity dataset and
   exclusion reference. The target is 1,000 real distinct new ASINs, not a guarantee.
2. Implement/review the live-only entry point: existing account/credential binding,
   fresh current-history validation, private fresh owner authorization tied to exact
   file/proposal/code digests, global cross-version lock, outstanding cooldown checks,
   a permanent one-shot operation registry and a new dedicated request journal.
   It must reject old M63/M67/M68 authorizations; none authorizes Catalog discovery.
3. Keep private credentials in their existing owner-only store; load them only after
   authorization checks. Enable only the existing TLS-verified, no-proxy,
   no-redirect one-shot HTTP primitive behind that reviewed entry point. Account
   for one token exchange before transport; no credential logging or automatic refresh.
4. Before sending, recheck authorization expiry, deadline, code/history/manifest
   integrity and allowed endpoint/parameters. Keep the 251 total and individual
   1/200/50 caps. Persist intent before dispatch; never retry an uncertain slot.
   Any stop requires read-only reconciliation and a fresh explicit owner decision;
   no automatic continuation or replacement ASINs/queries.
5. Save valid/partial pages privately, audit checkpoints, and pass the generated
   source manifest to unchanged `app.m70 analyze` with original immutable-history
   arguments. Report actual new/excluded/duplicate counts and missing/conflicting
   identities. Do not invoke restrictions, pricing, fees, FBA, offers or approvals.

There is deliberately **no live command to run in M71**. Fresh authorization alone
does not bypass its disabled send method. Merge/deployment and paid enablement are
not part of this milestone.

## Validation

Baseline: 1,720 tests passed. Targeted M71: 74 passed. Final full regression:
**1,794 passed in 140.07 seconds**. Both documented legacy/discovery sample modes
exited successfully with socket connections blocked. Tests block network,
authentication helpers, M63/M67 execution/reservations and protected-ledger writes.
Coverage includes deterministic diversified queries, tampered/resigned manifests,
phase and absolute budgets, before-send accounting, configured/header pacing,
throttling/failures, interruption before/after dispatch, no replay, hard-kill
checkpoint recovery, forced chain tampering, cursor/page validation, 97-style
permanent exclusion semantics, 40 checked ASINs, privacy, live-send/CLI gates and
M70 import of complete/partial saved pages. Synthetic scale reaches exactly 251
consumed slots and 1,000 distinct unclaimed products without any live requests.

## Frozen keyword query list

| Query | Category intent | Exact keyword phrase |
|---|---|---|
| q001 | garden | plant support clips |
| q002 | pet_accessories | pet grooming comb |
| q003 | craft_supplies | embroidery hoop |
| q004 | kitchen_accessories | silicone jar spatula |
| q005 | home_storage | fabric drawer dividers |
| q006 | office_accessories | cable management sleeve |
| q007 | sports_accessories | yoga mat strap |
| q008 | automotive_accessories | car seat gap organizer |
| q009 | hand_tools | magnetic parts tray |
| q010 | personal_care_accessories | soap saver pouch |
| q011 | garden | seed starting trays |
| q012 | pet_accessories | pet food scoop |
| q013 | craft_supplies | crochet stitch markers |
| q014 | kitchen_accessories | bamboo steamer liner |
| q015 | home_storage | under shelf basket |
| q016 | office_accessories | desk document tray |
| q017 | sports_accessories | bicycle tire lever |
| q018 | automotive_accessories | tire valve caps |
| q019 | hand_tools | precision screwdriver holder |
| q020 | personal_care_accessories | travel toothbrush case |
| q021 | garden | garden plant labels |
| q022 | pet_accessories | aquarium cleaning brush |
| q023 | craft_supplies | beading storage tray |
| q024 | kitchen_accessories | tea infuser basket |
| q025 | home_storage | vacuum storage bag |
| q026 | office_accessories | book binding rings |
| q027 | sports_accessories | swimming ear plug case |
| q028 | automotive_accessories | microfiber applicator pad |
| q029 | hand_tools | sanding block |
| q030 | personal_care_accessories | silicone scalp brush |
| q031 | garden | watering can rose |
| q032 | pet_accessories | bird cage perch |
| q033 | craft_supplies | craft cutting mat |
| q034 | kitchen_accessories | dough scraper |
| q035 | home_storage | closet shelf separator |
| q036 | office_accessories | reusable notebook cover |
| q037 | sports_accessories | resistance band handles |
| q038 | automotive_accessories | car visor clip |
| q039 | hand_tools | woodworking marking gauge |
| q040 | personal_care_accessories | reusable shower cap |
| q041 | garden | garden kneeling pad |
| q042 | pet_accessories | pet travel bowl |
| q043 | craft_supplies | felting needle holder |
| q044 | kitchen_accessories | reusable baking liner |
| q045 | home_storage | bedside storage caddy |
| q046 | office_accessories | desktop card holder |
| q047 | sports_accessories | camping utensil pouch |
| q048 | automotive_accessories | automotive trim tool |
| q049 | hand_tools | tool roll pouch |
| q050 | personal_care_accessories | cosmetic brush holder |
