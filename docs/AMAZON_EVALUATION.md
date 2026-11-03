# Amazon evaluation (PR 82)

## Inspection before implementation

Existing `profitability.analyze` supplies Decimal net profit, acquisition ROI,
referral handling and break-even. `m66_opportunity.exact_match` already verifies
GTIN, brand/model, size, variation, pack count and fresh identity evidence.
M66 verification separates seller restrictions and FBA eligibility; its decisions
use older status names and its economics supports FBA only.
`research_contract` defines Amazon_Candidates, Walmart_Research, Profitability,
Top_Opportunities, Review_Queue and Run_Log. Amazon candidate eligibility starts
UNKNOWN; publisher preserves researcher cells. `amazon_research_queue` preserves
Walmart history and manual research while upserting the original cohort.
`sheets_publisher.update/index` provide literal cells and duplicate-key rejection;
`SheetsClient` supplies bounded verified TLS and separate read/write scopes.

Missing: dedicated Amazon_Evaluation schema, manual scenario evidence for both
FBA/FBM, placement/returns, margin, and the requested decision vocabulary with
explicit demand/competition/documentation gates. Add an opt-in CLI only; leave
legacy calculations, publishers, schemas, history and scheduled jobs untouched.

## Manual contract and decisions

`amazon_evaluation_fiskars.json` is the supplied observation, not a live Amazon
query. Its observation timestamp remains UNKNOWN. $59.84 is only the lowest
displayed price; rank 435 has no supplied category and nine offers include Used.
Neither is converted into New Buy Box, New competition or monthly sales.
Approval requirements remain separate from financial evidence. The approval
block wins even when financials are incomplete or hypothetically profitable.

Use the synthetic JSON as the manual input template. Each money observation needs
`value`, `currency: USD`, `source`, and timezone-aware `observed_at`. Explicit
verified nonapplicable costs may be zero; missing costs, including storage,
placement and returns allowance, block that scenario. If returns are not configured,
record an explicit documented zero. All inputs used for positive decisions must
be at most 24 hours old, never future dated. Each fee also needs ASIN, New condition,
FBA/FBM mode and an independently attributed `price_basis` observation equal to
that scenario's selling price. No fee extrapolation is performed.

`identity` uses the existing M66 Amazon/retailer product schema; fill both product
observations including exact pack, GTIN, model, brand, variation, size and URLs.
`eligibility` carries status, source, observed_at and approval_requirements.
`seller_documentation`, `policy_checks` and `fba_eligible` are attributed boolean
observations; monthly_sales and competing_offers are attributed integers. Record
seller/account and policy-review details in source references. A human must verify
supplier documents and applicable marketplace policy; retail receipts alone do
not establish an acceptable sourcing document. This tool does not certify policy.

Demand heuristic: evidenced monthly sales >=30 and competing New offers <=10.
These are conservative initial screening choices, not validated forecasts.
Unknown demand blocks. Rank alone cannot supply sales. All three price scenarios
must be complete for at least one mode. Base profit >=$5 and ROI >=50% is required;
conservative must also pass for BUY_CANDIDATE. Otherwise use REVIEW or REJECTED.
FBA additionally requires fresh independent FBA eligibility. Synthetic inputs
always remain REVIEW or blocked/rejected. BUY_CANDIDATE never authorizes purchases.
No legacy Top_Opportunities rows are created by this CLI.

ROI denominator reuses `analyze`: purchase + tax + inbound shipping + preparation
+ packaging + other acquisition costs. Include retailer shipping in other_cost.
Fees, storage, placement, returns and transaction costs reduce proceeds once.
Net margin = net profit / sale x100. Break-even holds each scenario's supplied
fixed fees constant; it is conditional on those fees, not a fresh Amazon quote
at the calculated break-even price. Fees can change with price/category/size;
re-enter verified scenario fees rather than inferring them.

## Offline acceptance and synthetic example

```bash
.venv/bin/python -m app.amazon_evaluation --input sample_data/amazon_evaluation_fiskars.json
.venv/bin/python -m app.amazon_evaluation --input sample_data/amazon_evaluation_synthetic.json --as-of 2026-11-03T16:00:00+00:00
```

Synthetic only, ASIN B000000001: base sale $40, purchase $10, tax $1,
inbound $1, prep $0.50, packaging $0.50: invested acquisition $13.
Referral $6; FBA fulfillment $5 or FBM $7; storage $0.25, placement $0.25,
returns $1; other acquisition/transaction costs explicitly $0.
FBA net $14.50, margin 36.25%, ROI 111.53846%, fixed-fee break-even $25.50.
FBM net $12.50, margin 31.25%, ROI 96.15385%, break-even $27.50.
Conservative/base/optimistic prices are $36/$40/$44 with explicitly supplied
scenario fees. All numbers are fictional test inputs, not Fiskars estimates.

## Sheets and DigitalOcean commands

Only `Amazon_Evaluation` in the requested research workbook is managed. Missing
ASINs are inserted once; existing rows, manual edits and custom columns are never
overwritten. All writes use literal strings. Duplicate keys or schema mismatch
stop publication. Use one writer and pause sorts/inserts during publication;
Sheets has no arbitrary-cell compare-and-swap. A fresh snapshot is checked before
one atomic batch; readback detects changes without rollback or automatic retry.
The CLI reads at most 20,002 rows, A:X, and the reused transport caps responses at
4 MiB. No other tab is written and no history database is opened.

A:W are descriptive manual observations; X (`manual_evidence_json`) holds the
structured, attributed manual evaluation input. Edit X using the supplied JSON
template for computation; display-only edits never establish verified finances.
Use `--read` to calculate fresh results without changing cells. The initial seed
is not automatically refreshed, and positive eligibility expires after 24 hours.
Manual Amazon inputs still needed: New selling prices per scenario, seller-specific
eligibility, exact current acquisition and identity, all mode-specific fees/costs,
New offer counts, supported demand estimates and seller/policy documents. Keepa
30/90-day statistics can be transcribed with their condition, statistic definition,
source and observation time into observations/notes; never infer missing statistics
or monthly sales. No Keepa API subscription or Amazon calls are required.

These exact commands assume the reviewed code is already installed by a separately
authorized release. They do not deploy it. Existing VM and credential path come
from PR 81's runbook; neither credentials nor VM services were accessed here.

Read-only Sheets publication preview:

```bash
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && ARBITRAGE_SHEETS_CREDENTIAL_FILE=/root/.config/intelligenceos-sheets/service-account.json .venv/bin/python -m app.amazon_evaluation_sheets --input sample_data/amazon_evaluation_fiskars.json'
```

Publish missing evaluation rows:

```bash
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && ARBITRAGE_SHEETS_CREDENTIAL_FILE=/root/.config/intelligenceos-sheets/service-account.json .venv/bin/python -m app.amazon_evaluation_sheets --input sample_data/amazon_evaluation_fiskars.json --live'
```

Read-only evaluation of manual Sheet evidence:

```bash
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && ARBITRAGE_SHEETS_CREDENTIAL_FILE=/root/.config/intelligenceos-sheets/service-account.json .venv/bin/python -m app.amazon_evaluation_sheets --read'
```

## Verified connected-account publication

2026-11-03: the same pure planner created `Amazon_Evaluation!A1:X2`, sheet ID
106, using the connected Google Drive/Sheets account. One Fiskars row contains
the supplied approval requirements and UNKNOWN missing values. All six original
tabs' full-grid values/formula snapshots matched before/after (21/21/21/1/21/2
populated rows respectively). Top_Opportunities remains header-only. This is a
spreadsheet update, not a VM deployment. VM service-account execution is untested.
Header gray/bold/wrapped styling and frozen row were verified through API reads;
normal-zoom native visual fit was not independently verified.

Manual Sheet eligibility/approval cells that disagree with the structured JSON
block evaluation; synchronize both when entering reviewed evidence. Other display
columns never override scenario evidence. This intentionally small manual bridge
has no automatic opportunity publisher or Amazon/Keepa acquisition.
