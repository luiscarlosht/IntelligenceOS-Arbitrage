# M89 Amazon-first sourcing — offline phase

Starting commit: `b8fa9ec`. `app.m89` reuses the six saved M88 Catalog searches
and three targeted detail receipts. It creates a new research queue across all
56 distinct ASINs (60 original source/ASIN pairs). Original classifications are
retained per pair. A rejected pair does not exclude searching for a different
Walmart retail item; it also does not become an accepted pair.

```bash
python -B -m app.m89 --evidence-root var/m88-real-six-pilot \
  --output var/m89-amazon-first-offline-v1
```

Use a fresh output directory outside the M88 evidence tree. The command requires
the authoritative 11/49 COMPLETE ledger, verifies all eleven receipts against its
hashes and plan bindings, checks report products against saved receipts, and pins
all prior evidence/report files before publishing. Source hashes are rechecked
before atomic publication. No credential reads, HTTP calls, ledger updates or
execution endpoint exists. The offline audit guard blocks network/process access
and writes outside the new private report directory. Files are 0600; directories
0700. Runtime evidence/reports remain ignored and must not be committed.

Ranking is research priority: fewest missing Catalog identity fields and mapping
issues, then retained typed pack attributes, then ASIN. A single canonical GTIN,
brand, model and explicit size/variation provide a search lead, not retail-pack
verification or Walmart availability. Multiple barcode alternatives are retained.
MPN remains UNKNOWN where only a model was saved. The full queue preserves all
ASINs; the Browser Use checklist contains the first ten, with the first three as
the initial shortlist. Titles are navigation aids only.

Amazon lead identifiers and Walmart observations occupy separate fields. The
checklist requests independently observed UPC, model/MPN, brand, variation,
contents and outer sellable-pack evidence, actual screenshots and field provenance,
current Walmart seller/availability/price/tax/shipping, and explicit blockers.
Existing M88 source conflicts, agent-only review and absent screenshot binaries
remain recorded; no field is corrected by copying Amazon data. No price is refreshed
by identity research. Search results do not establish a match.

M86 `comparison` and `workbook` evaluate the shortlist with no invented Walmart
identity or financial observations. An ASIN in these rows is a research candidate,
not a confirmed matched destination. FBA/FBM conservative/base/optimistic scenarios
remain INSUFFICIENT_DATA until exact fresh identity and all attributed costs,
New selling prices and price-bound fees are available. Net profit/ROI stay UNKNOWN.
The unchanged targets are $5 net profit and 50% acquisition ROI. Acquisition includes
item price, tax, retailer/inbound shipping, prep, packaging and other costs; net
profit subtracts acquisition and all selling fees/costs once. No rank-to-sales
conversion or unsupported velocity assumption is introduced.

Outputs: `candidate-shortlist.json` (full queue plus top three),
`browser-use-checklist.md`, `browser-use-request.json`, `missing-data-report.json`,
M86 `comparison.json` / `comparison.xlsx`, `executive-summary.md` and
`conditional-amazon-plan.json`.

The later request plan is non-executable and reserves **zero** attempts now. For
up to three independently verified exact matches, its maximum is 1 authentication,
3 New offers, 3 account-specific listing-restrictions reads and 18 fee estimates
(three documented price scenarios × two fulfillment modes × three ASINs). Equal
price quotes should be deduplicated. Maximum 25 new attempts means 36/49 cumulative,
leaving 13; failures/uncertain dispatches and authentication all count. No searches,
retries or automatic refresh. Saved usable evidence must be reused first. A later
reviewed executor must use the existing authoritative cumulative ledger and new
operation scope; M88 operations cannot be replayed. Unknown permissions, fulfillment
eligibility or fee inputs remain unknown. No endpoint is dispatched by this phase.

`purchase_authorized=false`. No purchases, listings, account changes, subscriptions,
Sheets writes, deployment or merge is authorized by a research result.
