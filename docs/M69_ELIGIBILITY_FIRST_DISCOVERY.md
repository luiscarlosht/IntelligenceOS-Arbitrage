# M69 eligibility-first product discovery — offline only

M69 consolidates immutable M63/M67 restriction evidence, ranks saved Catalog
candidates and records explicit offline reviews. It never authenticates, calls
Amazon/retailers, purchases, submits offers/applications, creates request reservations,
or edits original authorizations, claims or outcomes. Existing M63–M68 code-bound
modules remain unchanged. No scheduler, automatic retries or live executor is added.

## Inspection findings and source constraints

The available original M63 outcome report has 18 `APPROVAL_REQUIRED` and two
`NOT_ELIGIBLE` outcomes. The M67 private ledger has another 18 and two, with 21
consumed request records including authentication. The M66 derived database has no
imported eligibility events/results; using it alone would miss all 40 checks.
M69 reads the immutable original sources directly instead of importing into that DB.
The four M64 manual observations and M66 Seller Central observations remain available.

The original 20-ASIN M63 `claimed_no_replay` proof, legacy execution ledger, M67
permanent global claims, derived exclusions and all imported historical attempts
form a union. Current evidence contains 97 permanent exclusions. Of 197 distinct
ASINs in the two saved authorized sources, 41 are permanently excluded, leaving
156 before review/identity filters. Historical labels come from M63 observations
and the frozen M67 ranking; current catalog changes do not silently rename the
brand/category of an old outcome.

Catalog identity remains incomplete: across 197 ASINs, 76 have valid GTINs, 99 have
model/pack data, 95 have size, 61 have variation and none has a mapped product type.
Saved data is not refreshed by M69. The available pool remains concentrated in the
brands/categories of earlier discovery; less represented does not imply smaller,
unrestricted or profitable. New source discovery requires separate authorization.
Do not pad a smaller pool with invented ASINs or identity values.

## Services and reports

- `app/m69_history.py` reuses M65 normalized restriction parsing, M63 historical
  auditing, M67 read-only SQLite snapshots and frozen-cohort validation. It preserves
  source hashes, scope, observation times and per-ASIN provenance; duplicate evidence
  never multiplies sample sizes. Missing/failed/ambiguous evidence stays `UNKNOWN`.
- `app/m69_discovery.py` reuses M66 source merging and M65 deterministic diversity
  ranking. New logic adds distinct-ASIN brand/category counts, source quality,
  condition review and exact account-evidence adjustments.
- `app/m69_workflow.py` records hash-linked immutable review events in a **new dedicated
  database**, with only `m69_reports` and `m69_events`. These are not API reservations.
  Existing non-M69 databases are rejected before any write. No reset/resume/retry or
  historical-ledger migration is exposed.
- `app/m69.py` provides `analyze`, `register`, `advance`, `status` and `manifest`.
  Registration reconstructs the analysis against its current inputs, protecting
  against invented/rescored rows even if someone recalculates a tampered file digest.

Analysis creates a new owner-only directory with immutable JSON and formula-safe CSV:

| File | Contents |
|---|---|
| `M69_analysis.json` | All ranked rows, component scores, selected pool, code/source bindings and limitations |
| `M69_candidates.csv` | Up to 100 distinct unclaimed candidates, all eligibility `UNKNOWN` |
| `M69_history.json`, `.csv` | Consolidated evidence and observed outcomes; API success is separate from eligibility |
| `M69_exclusions.json`, `.csv` | Original 40 and all other permanently excluded ASINs |
| `M69_brand_risk.json`, `.csv` | Distinct-ASIN sample sizes, five state counts, conflicts; no brand-wide permission |
| `M69_category_risk.json`, `.csv` | Equivalent descriptive category counts |
| `M69_review_pool.json` | Offline pool only, not a live eligibility manifest or authorization |
| `M69_summary.json` | Actual counts, distributions, missing data and zero-operation counters |

No credentials, seller identifiers, private response bodies or raw error messages
are exported. Immutable result references are hashes. Original credential/account
binding/authorization files are never loaded for new authorization or modified.
Source provenance and SQL protections cannot defend against privileged filesystem
rollback/tampering; retain the original private directory and backups.

## Deterministic scoring methodology

Scores are integer **research-priority heuristics**, not probabilities, eligibility
predictions or calibrated financial confidence. Absence of restrictions in the
historical dataset contributes no claim of permission for an untested ASIN.

| Component | Points |
|---|---|
| Valid GTIN / model / size / pack / variation / product type | +8 / +4 / +4 / +4 / +4 / +2 |
| Outside previous M63 seed brands | +8; does not claim the company is small or unrestricted |
| Observed invoice-heavy brand pathway | -35; exact observation, not a universal brand rule |
| Previous sample concentration | -6 for at least two distinct observed ASINs in the brand |
| Source quality | +6 saved M63 SP-API Catalog report, +3 supplied Catalog CSV, +1 supplied Catalog JSON |
| Catalog observation within 24 hours of analysis clock | +2 |
| Explicit compatible New condition evidence | +2; missing condition is `UNKNOWN`, zero points |
| Brand approval observations | `-min(12, 2 × APPROVAL_REQUIRED count)` |
| Brand ineligibility observations | `-min(20, 4 × NOT_ELIGIBLE count)` |
| Category reported blocks | `-min(6, (approval + ineligible + otherwise-restricted count) // 3)` |
| Exact-ASIN observed negative account evidence | -80, plus permanent exclusion |

Selection greedily subtracts 12 points per previously selected brand member,
8 per category member and 4 per known product type. Ties break by ASIN. Default
brand cap is 10, maximum pool 100, minimum priority -100. The established PHILIPS /
Philips LED grouping is retained; CSV distributions also retain source brand labels.
Brand/category counts describe only the observed selected samples, never Amazon-wide
rates. A soft penalty may omit a brand from a finite pool; it never permanently bans it.

Hard exclusions include all permanent claims/attempts, contradictory identity,
missing title/brand, explicit incompatible condition and exact-ASIN manual blockers.
Unknown catalog identity can remain in the research pool but cannot pass identity
review. Source classes are provenance heuristics, not proof of authorization or
permission. All exclusions are current even with a frozen analysis clock; `--as-of`
freezes scoring, not a counterfactual historical authorization state.

## Explicit workflow guards

`DISCOVERED → IDENTITY_VERIFIED → OFFLINE_RISK_REVIEWED → LIVE_ELIGIBILITY_PENDING
→ ELIGIBILITY_OBSERVED → FBA_REVIEW_PENDING → PROFITABILITY_REVIEWED
→ READY_FOR_HUMAN_DECISION`

Nothing advances automatically. Analysis marks rows `DISCOVERED` but does not create
a journal. Each explicit transition records a canonical evidence fingerprint, current
history hash, prior-event hash, code/source-bound analysis and UTC time. Skips, resets,
backwards clocks, stale reviews and evidence drift fail closed.

Review evidence JSON uses exactly `schema` (integer 1), `asin`, `marketplace`,
`condition`, `observed_at`, nonsecret `review_reference` (`manual:...`) and `payload`.
All are scoped to the same ASIN, US, `new_new`; reviews must be fresh within 24 hours.

| Target | Required payload and guard |
|---|---|
| `IDENTITY_VERIFIED` | `amazon_product`: all M66 product fields; valid GTIN, model, size, pack and variation reproduce the frozen Catalog identity fingerprint, with fresh manual provenance. Complete catalog fields alone never auto-verify. |
| `OFFLINE_RISK_REVIEWED` | `score_components_sha256`, `unknowns_acknowledged=true`, `condition_reviewed_new=true` |
| `LIVE_ELIGIBILITY_PENDING` | `separate_live_authorization_required=true`; complete history, fresh prior reviews, no claims or exact-ASIN manual blockers |
| `ELIGIBILITY_OBSERVED` | Current `history_sha256`; an immutable successful, scoped, nonconflicting API outcome. Restricted observations may be recorded here but cannot proceed unrestricted. A payload cannot assert eligibility. |
| `FBA_REVIEW_PENDING` | `independent_fba_review_required=true`; fresh API `NO_REPORTED_RESTRICTIONS` **and** independent existing-ASIN offer-creation review, no conflicts or blockers |
| `PROFITABILITY_REVIEWED` | `opportunity` using the existing M66 contract; fresh listing and FBA inbound verification, exact retailer identity, complete costs. Failed thresholds remain reviewed and blocked from READY. |
| `READY_FOR_HUMAN_DECISION` | Revalidated `opportunity` and `human_review_requested=true`; all current gates and thresholds pass. This never authorizes purchase or offer submission. |

Copy listing, brand popularity, Catalog access and a bare empty restrictions reply
cannot complete the listing/FBA gates. Commingling preview evidence is not FBA inbound
permission. Positive eligibility/offer/FBA evidence expires under existing M66 rules.
The intended downstream route remains an existing-ASIN offer-only workflow; no offers
are submitted. Re-review after source/code drift needs a fresh report/journal generation,
not edits to immutable events; original permanent execution exclusions always remain.

## Financial screening

Defaults remain minimum ROI 50%, minimum net profit $5/unit and $500 inventory budget.
Only explicit financial transitions accept `--minimum-roi`, `--minimum-profit` and
`--inventory-budget`; values must be finite/nonnegative and budget positive. Applied
targets are recorded with the review result. No financial evaluation runs in analysis.

Use `app.m66_opportunity.template(asin)` for the existing blank product/cost contract.
Required values include exact Amazon and retailer GTIN/model/size/variation/pack,
Amazon and acquisition prices, retailer shipping, sales tax, referral/FBA fees,
inbound, prep, packaging, storage, other acquisition and other selling costs, units,
USD, dated provenance and ASIN/condition/FBA sale-price fee scenarios. Missing values
are not zero; even legitimate zero costs must be explicit. No prices or fees are invented.

`net_profit = sale - acquisition - Amazon fees - inbound - other costs`, with each
component deducted once. ROI denominator is retailer price + retailer shipping + tax
+ inbound + prep + packaging + other acquisition. Referral/FBA/storage/other selling
charges reduce proceeds, not that denominator. Investment is this per-unit invested
cost × explicit units. The budget gate covers one proposal, not a jointly allocated
basket. M66's exact matcher and Decimal economics are reused without modifying them.
Calculations remain disabled until verified listing, FBA and identity gates pass.

## Exact offline commands

From the review branch on DigitalOcean, with the original files and Python 3.12 venv:

```bash
cd /root/IntelligenceOS-Arbitrage-M61
.venv/bin/python -m pytest -q tests/test_m69.py
.venv/bin/python -m pytest -q
m69_inputs=(
  --catalog /root/.intelligenceos-arbitrage-amazon/m63-catalog-discovery-01.json
  --catalog /root/IntelligenceOS-Arbitrage/var/m63-final-review-20261101/M63_amazon_candidates_100.csv
  --store var/m66-local/intelligence.sqlite3
  --history-dir /root/.intelligenceos-arbitrage-amazon
  --m67-manifest var/m66-expanded-review/M66_review_manifest.json
  --m67-sha256 8983bef70ce5cfd79d15b7611e4b5646784f37bfce1a88bd220286394303ee55
)
.venv/bin/python -m app.m69 analyze "${m69_inputs[@]}" \
  --maximum 100 --max-per-brand 10 --output var/m69-offline-review
```

An existing output directory fails rather than overwriting reports. Source hashes,
UTC analysis clock and implementation bindings are saved for reproduction. Do not
commit the reports or original private evidence. An empty/smaller pool is reported
honestly. Missing original M63/M67 sources block analysis. Unknown/conflicting original
outcomes and unbound additional M67 batches block live-review proposals.

To record a manually selected row from the CSV, use the analysis digest reported by
`analyze` (only a public ASIN and digests belong in these arguments):

```bash
.venv/bin/python -m app.m69 register "${m69_inputs[@]}" \
  --analysis var/m69-offline-review/M69_analysis.json \
  --analysis-sha256 REVIEWED_ANALYSIS_SHA256 --asin SELECTED_ASIN \
  --workflow-store var/m69-review/workflow.sqlite3
.venv/bin/python -m app.m69 advance "${m69_inputs[@]}" \
  --asin SELECTED_ASIN --target IDENTITY_VERIFIED --evidence LOCAL_IDENTITY_REVIEW.json \
  --workflow-store var/m69-review/workflow.sqlite3
```

Review the remaining stages explicitly using their payload contracts above. `status`
reads the journal without writing. Once individual ASINs reach `LIVE_ELIGIBILITY_PENDING`,
a separate `manifest` action accepts one to twenty repeated `--asin` values and a new
`--output` file. It rechecks permanent history, current exact-ASIN manual evidence,
code/source bindings and pending-review freshness. No replacement ASINs are added.

That output is `M69_LIVE_REVIEW_PROPOSAL_ONLY`, with a proposed one-authentication +
N-restrictions budget and zero other operations/retries. **It is not executable by
unchanged M67 and is not owner authorization.** A future pilot requires a separately
reviewed frozen executable manifest/adapter contract and fresh explicit authorization.
M69 does not manufacture M66-compatible manifests or weaken M67 to accept new formats.
After additional batches, supply/reconcile their frozen provenance in a separately
reviewed extension before preparing further cohorts; all their global claims are
excluded immediately even before reconciliation.

Stop after offline reports/reviews. Do not invoke M67 execution, create reservations,
request tokens, source retailers, submit applications/offers, purchase or merge/deploy
automatically. SQL immutability and file hashes do not protect against root rollback;
never restore older copies over the original execution ledgers or authorizations.

## Milestone validation and actual offline output

Baseline: 1,579 passed. M69 targeted: 74 passed. Final full suite: 1,653 passed.
Both legacy and discovery mock sample jobs exited 0 with socket connections blocked.
New tests cover consolidated counts/provenance, missing and conflicting evidence,
all permanent claims, deterministic ranking, no blanket brand bans, condition scope,
tampered analyses, immutable stage chains, explicit reviews, no replay, exact identity,
separate listing/FBA gates, disabled economics, missing fees, cost basis/thresholds,
CSV formula safety, redacted errors and blocked network/execution primitives.

The actual run evaluated 197 unique ASINs and selected 100 across four categories
and 23 source brand labels (22 normalized brand groups). All 40 historical ASINs and
all 97 permanent exclusions are absent from the pool. The observed cohort remains
36 approval-required, four ineligible and zero no-reported-restrictions. Those are
selected-cohort observations, not population estimates.

Only 21 selected products have complete catalog identity fields; none is automatically
identity-verified or eligible. Selected missing fields: GTIN 62, model 59, pack 59,
size 62, variation 78 and product type 100. Every selected row remains `DISCOVERED`,
eligibility/listing permission `UNKNOWN` and FBA `FBA_UNKNOWN`. No real product was
advanced to financial review. The derived DB still lacks imported API results;
consolidation reads the original reports/ledger directly and never rewrites it.

Protected M63 proof/outcomes, legacy execution ledger, M67 global ledger, frozen
manifest/ranking, source files and derived store were byte-for-byte unchanged after
the real analysis; private file inventory/metadata were unchanged. Repeating the
analysis with the same clock/inputs produced the identical canonical report hash.
Generated reports are under ignored `var/m69-offline-review/` and are not committed.
No live Amazon/retailer requests, authentication, real execution reservations,
purchases, listing submissions, approval applications or authorization changes occurred.
