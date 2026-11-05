# M86 — Walmart product analysis, independent of selling permission

Base: main `3204f19`, merged PR85. No Amazon/Walmart request, Google Sheets
write, migration, deployment, subscription or purchase was made. The implementation
reads local JSON only. Existing publishers, legacy decisions and history are unchanged.

## Capability audit

| Capability | Status before M86 | Evidence and limitation |
| --- | --- | --- |
| Walmart discovery and saved observations | Partial | `sheets_intake`, `walmart_observation`, `source_workbook`, `amazon_candidates`; saved browser exports and local reports exist. They do not establish a current acquisition quote or the requested six-member batch. |
| Six original Walmart candidates | Missing reliable recovery | No original six-member manifest located in committed files or inspected local Walmart artifacts. See recovery inventory below. No six products, ASINs or prices invented. |
| Source prices and identifiers | Partial | Historical item prices and Walmart IDs exist in distinct source populations. Missing GTIN/model/pack, shipping and freshness prevent verified acquisition costs. |
| Amazon identity matching | Works offline | `amazon_catalog`, `amazon_candidates`, `m66_opportunity.exact_match`: GTIN, model, brand, size, pack, variation, dates and references. Unresolved candidates remain unresolved; titles alone do not confirm identity. |
| SP-API authentication | Existing bounded live tools | `amazon_pilot` uses LWA refresh authorization and verified TLS. Prior authorized operation evidence is documented; credentials and present entitlements were not inspected or retested. |
| Catalog / Pricing / Fees | Partial analysis coverage | Existing parsers and controlled executors; `m80_contract.DATA` requests ranks; scoped fee estimates and observed prices remain separate. See field matrix. No general authorized analysis provider is registered in normal jobs. |
| Competition / demand / price history | Partial / missing | New-scoped observations supported; mixed Used/New counts and ranks cannot supply the research thresholds. General competitor monthly unit sales and retrospective price history unavailable through inspected SP-API path. |
| Financial math | Works offline | `profitability.analyze` → `amazon_evaluation.financial` → `analysis_engine.analyze_record`. Six FBA/FBM scenarios, $5 profit and 50% acquisition ROI defaults; missing fees are never zero. Prior reports expose finances while eligibility blocks, but lack the independent assessment vocabulary. |
| Workbook input/output | Works; separate responsibilities | `Amazon_Evaluation` has 24 columns including manual evidence JSON; `Amazon_Analysis` has 11 computed columns. `Walmart_Intake`/`Walmart_Batches`, Research Queue and historical tabs retain ownership. M86 introduces local reports only and writes no workbook tab. |
| Independent assessments / comparison | Missing before M86; now implemented | `app.product_analysis`, tests and empty recovery template. Both modes and all scenarios, explicit source shipping, financial/market/status separation, private six-sheet Excel + JSON. Actual six-product assessment remains blocked on source recovery. |

The prior M85 eligibility-first research instructions remain historical documentation.
**M86 starts with product evidence and financial/market analysis.** Eligibility is an
independent informational field and an unchanged prerequisite to later buying.

## Source recovery and population distinction

Inspected committed documentation, sample data, templates, tests and relevant local
artifacts under `/root/IntelligenceOS-Arbitrage/var`. The clean implementation checkout
is `/root/IntelligenceOS-Arbitrage-clean`. Source files were read, never modified.
Searches included six/six-product references and source/batch/identity manifests.
The local M85 gap export confirms twenty original ASINs and no populated evaluation
facts; it supplies no original Walmart six-product membership.

| Original artifact under the older checkout | Population | Finding |
| --- | --- | --- |
| `var/walmart-browser-2026-10-28/observations.json` | 0 | Discovery blocked before product visits; no candidate recovery here. |
| `var/walmart-amazon-review-20261028/comparison-summary.json` | 10 kitchen products | 8 ambiguous, 2 unmatched, 0 exact. Historic item prices exist; no evidence this is the requested six. SHA256 `7e0f7300dde9fab144e30da0ce7167183697214bd130fdac9f3f140ebac3b9e3`. |
| `var/walmart-identity-shortlist-20261029/identity-shortlist.json` | 8 plausible pairs | All unverified, source barcode/model missing; no six-member designation. SHA256 `046c6281446f9d0cea686e3d307544548ecb99b1c9520ba9d4a66ad935ab36ef`. |
| `var/sheets-amazon-five-offline-20261030/source-audit.json` | 5 sourced products | Original titles/prices/IDs below; no reliable sixth candidate. SHA256 `7a4eddc43f888308482c9d9647f557c288b384d969ff30399e59281605cfc8a8`. |
| `docs/GOOGLE_SHEETS_INTAKE.md` record-ID compatibility section | Another 5-record batch | Original IDs 17617453, 14922696, 14906288, 10310568, 12443828; regression product values explicitly illustrative. Distinct from the five below. |
| `var/verification/m85-gaps.json`, `amazon_research_queue.ORIGINAL_ASINS` | 20 Amazon ASINs | Separate seller research population; cannot serve as Walmart source evidence. |

Historical observations in the five-product audit (not the six-candidate POC):

| Walmart item ID | Saved exact title | Item price USD | Original observation UTC |
| --- | --- | --- | --- |
| 13952053139 | Duracell Coppertop AA Alkaline Batteries 8/PK | 9.73 | 2026-10-30T00:09:38.929+00:00 |
| 17011265 | Elmer's Liquid School Glue, Washable, 4oz., 1 Count | 1.17 | 2026-10-30T00:09:53.482+00:00 |
| 37481849 | Post-it Super Sticky Notes, Canary Yellow, 3 in. x 3 in., 4 Pads | 5.97 | 2026-10-30T00:10:04.917+00:00 |
| 47070933 | Scotch Transparent Tape, 3/4 in. x 1000 in., 4 Rolls | 8.52 | 2026-10-30T00:09:45.706+00:00 |
| 721324153 | Gorilla Clear Glue 5.75 Ounce Bottle, Pack of 1 Bottle | 11.18 | 2026-10-30T00:09:59.441+00:00 |

All five have empty source GTIN and ASIN hint in this artifact. Prices are stale
item observations, **not verified landed acquisition costs**. No ASIN is assigned
from a title or from a different population. Earlier failed/completed operations
are not replayed. This recovery result is bounded by locally available evidence;
it does not assert the six never existed in an external browser workspace or sheet.

## Explicit input contract

Start from `templates/m86_product_analysis.json`. An empty candidate list is a
valid recovery-blocked report and produces zero analyzed products, never six
fabricated rows. Supply original six-member batch/export membership and source
artifact paths + SHA256 in `source_inventory`; retain originals privately.
Each `candidates` entry extends the existing PR82 manual record:

- `candidate_id`: unique original batch/record key, independent of ASIN. Different
  Walmart products may share an ASIN; duplicate source keys fail.
- `asin`: confirmed candidate ASIN, or omit while unresolved. Do not fill an ASIN
  merely to make the report run. `identity.amazon_product` and
  `identity.retailer_product` retain title, GTIN, brand, model, size,
  `pack_quantity`, variation, HTTPS URL, original `observed_at`, `source_reference`,
  `confidence` HIGH/MEDIUM and `verified: true`. Retailer additionally requires
  `walmart_item_id`, matching the numeric suffix of a walmart.com `/ip/` URL.
- Every monetary observation has `value` as a decimal string, `currency: USD`,
  `source`, `source_reference`, aware `observed_at`, `confidence` HIGH/MEDIUM,
  `verified: true`. These are checked transcription assertions, not provider guarantees.
  Missing, future, >24-hour-old, assumed or unconfident observations cannot support
  financial classification. LOW confidence remains visible but insufficient.
- `financials.FBA` and `financials.FBM` each contain `conservative`, `base`,
  `optimistic`. Every scenario needs `selling_price`, `purchase`, `sales_tax`,
  `retailer_shipping`, `inbound_shipping`, `preparation`, `packaging`, `other_cost`,
  `referral_fee`, `fulfillment_fee`, `storage`, `placement`, `returns_allowance`,
  `transaction_cost`. FBM fulfillment is merchant shipping/handling cost, never an
  invented Amazon FBA fee. Use supported explicit zero for nonapplicable costs;
  omitted values are UNKNOWN. **M86 `other_cost` excludes retailer shipping**:
  the adapter adds it exactly once before invoking the inherited formula. Do not
  copy legacy other_cost containing shipping without splitting its documented basis.
- Selling prices require matching `asin` and `condition: New`. Referral and
  fulfillment observations additionally require matching ASIN, New condition,
  `mode` and nested attributed `price_basis` exactly equal to the scenario price.
  All scenarios must be complete and conservative <= base <= optimistic. Quotes
  at one selling price cannot silently serve another. Price scenarios are research
  estimates; their documented basis must support them, and assumptions stay flagged.
- `market.monthly_sales` / `market.competing_offers` (or PR82 top-level fields)
  need the common metadata plus exact `asin`, US `marketplace: ATVPDKIKX0DER`,
  `condition: New`, and a nonnegative integer. New competition needs
  `basis: new_offer_count`. Demand needs `authorized_sales`,
  `bought_past_month_lower_bound`, or `validated_estimate` with independent
  `model_validation_reference`. Rank-derived sales and mixed counts are unusable.
  A lower bound below 30 cannot establish low demand. Conflicting duplicated
  observations block confident classification. Preserve category-scoped rank and
  historical fields through the existing market schema; rank never becomes units.
- `eligibility` uses ELIGIBLE / APPROVAL_REQUIRED / RESTRICTED / UNKNOWN with its
  original account-specific evidence. Stale ELIGIBLE displays UNKNOWN; observed
  restrictions remain visible. Neither eligibility nor FBA permission is required
  for financial math. Existing documentation/policy/FBA eligibility fields still
  control the inherited buying decision. No result is purchase authorization.

## Assessments and financial meanings

`financial_assessment_by_mode` requires exact, fresh identity and all three
complete price-bound scenarios. Base profit >=$5 and ROI >=50% yields PROMISING;
complete below-threshold evidence yields BELOW_TARGET. The overall result is
PROMISING if either mode qualifies, BELOW_TARGET only if both modes are complete
and below target, otherwise INSUFFICIENT_DATA. Conservative downside remains
visible; PROMISING is a base-case research filter and makes no demand assertion.

`market_assessment` requires supported fresh monthly demand and New competition
for the exact matched product. >=30 and <=10 yields ATTRACTIVE; valid observations
that fail either yield UNATTRACTIVE; missing/unsupported data yields
INSUFFICIENT_DATA. These market thresholds and profit/ROI are configurable CLI
options. No price-history risk cutoff is silently invented.

ROI denominator is all acquisition costs including source shipping, tax, inbound,
prep, packaging and other acquisition. Net profit deducts referral, fulfillment,
storage, placement, returns and transaction once. Net margin is net profit/sale.
Gross margin is explicitly **(sale - source item price)/sale**, before shipping,
fees and other costs. Break-even holds the supplied fees constant, matching PR82;
it is not a repriced fee quote. All calculations use the existing Decimal engine.

The inherited result is retained as `legacy_decision` for audit. `decision` may
remain BLOCKED while financial_assessment is PROMISING. M86 adds a conservative
block when legacy BUY_CANDIDATE lacks trusted selected-mode costs, supported
market evidence or exact identity; no research assessment can promote a decision. M86 does not consume these research assessments
in purchasing, rename BUY_CANDIDATE, publish opportunities, or modify old gates.
`purchase_authorized` is always false. Original evidence and hashes accompany
results. Data-quality validation can be stricter than legacy calculations; use
the independent assessment and its missing fields for M86 research conclusions.

## Local reports and read-only DigitalOcean verification

```bash
/root/IntelligenceOS-Arbitrage/.venv/bin/python -m app.product_analysis --input templates/m86_product_analysis.json --output /tmp/m86-recovery-review
```

Use a new output directory outside the input evidence directory. The CLI makes
exclusive private output (directory 0700, files 0600), refuses overwrite/symlinks,
and uses the existing offline audit guard and atomic publication boundary. Output:
`comparison.json`, `comparison.xlsx` with Executive Summary, Product Comparison,
Financial Scenarios, Data Quality and Missing Info, Source Inventory and Evidence.
Input evidence is retained in JSON; Excel formula triggers are escaped and cells
are bounded. Oversized cells abort publication without truncating evidence.

The side-by-side sheet exposes exact source identity, base acquisition and selling
observations, every fee/cost, FBA/FBM profit/ROI, demand, New competition, history,
separate assessments, seller status, provenance and missing fields. JSON preserves
all three scenarios unrounded. Rank is best-mode base profit only when every
product has both complete modes and sufficient market evidence; otherwise it is explicitly research priority by
exact identity then fewest evidence gaps, with source ID breaking ties. There is
no unsupported portfolio or sales-volume ranking. With zero recovered products,
there is no product ranking at all.

After a separately authorized installation of the reviewed code, these commands
verify without live provider access or Sheets writes (not executed on the VM here):

```bash
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && git log -1 --oneline && git status --short'
ssh root@137.184.180.155 'set -eu
cd /root/IntelligenceOS-Arbitrage
umask 077
m86_dir=$(mktemp -d /tmp/arbitrage-m86.XXXXXX)
.venv/bin/python -m app.product_analysis --input templates/m86_product_analysis.json --output "$m86_dir/report"
.venv/bin/python -c '\''import json,sys; from pathlib import Path; p=Path(sys.argv[1]); r=json.loads((p/"comparison.json").read_text()); assert r["recovered_candidates"]==0; assert not r["purchase_authorized"]; assert r["recovery_status"]=="INCOMPLETE"; assert (p/"comparison.xlsx").is_file(); print(r["recovery_blockers"])'\'' "$m86_dir/report"'
```

These commands change only new private `/tmp` report files. To analyze recovered
originals, replace the input with a reviewed private M86 manifest; never alter
source timestamps or point output at historical evidence. The fixed template is
intentionally incomplete. No credential path, deployment step or live CLI exists
in this workflow.

## POC conclusion and next evidence

**No one of the requested six can currently be called most promising:** their
original membership cannot be established reliably from inspected evidence, and
there is no complete verified acquisition/New-price/scoped-fee set for them.
Recover the original six-member export and saved source artifacts first. Then
verify exact units/identifiers and original quotes, populate fresh scenario costs,
New prices, supported demand and New-only competition using already saved or
separately approved new evidence. Run this analysis regardless of selling status.
Eligibility research remains separate and must clear before any buying approval.

See [Amazon coverage](M86_AMAZON_COVERAGE.md) and
[provider recommendation](M86_PROVIDER_ASSESSMENT.md). Local runtime reports are
private ignored artifacts, not committed or published analysis results.

## Validation

Stable full offline run: **2,794 passed, 9 skipped** (909.36 seconds). The suite
was collected before the final additional M86 cases; the final focused run passed **258 tests**, covering
all **97 M86 cases** plus PR82/83/85 evaluation, analysis and intake tests.
Final report guards additionally require sufficient market evidence for financial
ranking and finite ordered historical price statistics. The original broad run
overlapped implementation and its immutable-code checks correctly detected source
drift (one failure and one setup error); the subsequent stable run passed.
No code-integrity or authorization gate was changed to obtain that result.
Both documented sample modes passed with isolated private `/tmp` outputs and no
mail settings. Their four/six-sheet workbooks contain no formulas. Recovery JSON
and Excel generated successfully; source artifact SHA256 values remain unchanged.
No VM verification or remote CI result is claimed.
