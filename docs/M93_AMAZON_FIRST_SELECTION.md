# M93 Amazon-first selection

M93 selects Amazon research leads before further Walmart searches using only
existing retained evidence. This authorized offline workflow does not close M92's
unresolved identity or economics gates.

## Capability assessment and reuse

M89 already deduplicates and ranks Amazon Catalog identities by completeness and
typed package attributes. M91 pins six Catalog search receipts and the original
Walmart observations. M92 revalidates these pins, adds three detail receipts and
retains all 60 pair reviews (56 distinct ASINs), including historical public
research and package contradictions. M93 calls M92's builder, M89's ranking,
`product_analysis.assess`, the established Decimal profitability engine, and the
existing offline publication and formula-safe Excel helpers. No architecture,
provider, account, database or credential workflow is added.

## Result and evidence gap

**30 identity-ranked research leads; zero defensible promising selling
opportunities and zero VERIFIED_PROFITABLE products.** The retained population
contains 56 ASINs, but none has supported Amazon New selling price, seller
competition, demand or seller-specific eligibility. Consequently fewer than 20
(and in fact zero) defensible opportunities exist. Catalog identities alone cannot
establish profitability or selling permission. The remaining 26 ASINs are listed
as unselected, not rejected products.

Every selected row has outcome ELIGIBILITY_UNKNOWN and economics status
INSUFFICIENT_EVIDENCE. RESEARCH_PRIORITY is a separate screening label and tab,
never a verified outcome. Empty INELIGIBLE, INSUFFICIENT_EVIDENCE and
VERIFIED_PROFITABLE outcome tabs remain explicit. Approval-required and scoped
restrictions block progression. Listing New eligibility, approval requirement,
FBA eligibility and restrictions each retain their own value, source, timestamp
and original evidence. Missing seller evidence is UNKNOWN. Public/Catalog data
cannot supply account eligibility. Scoped adverse evidence remains blocking after
expiry; positive permission requires fresh evidence.

Ranking uses M89's identity completeness and typed package evidence, with ASIN
tie-breaks. There is no supported price, profit, demand or eligibility ranking.
The queue's next action is separately authorized seller screening before further
Walmart sourcing. No new evidence collection is performed or authorized here.

Exact identifiers, UPC alternatives, models, MPNs, variation, package quantities,
retained attributes and original timestamps remain in JSON and Excel. Catalog
package quantity does not prove contents. All source observations are explicitly
historical retained evidence, not current verification. Prior Walmart pair
rejections are scoped to those pairs and do not establish ASIN ineligibility.
Historical Walmart prices remain in pair evidence, never current acquisition
inputs for Mansfield TX 76063.

Profitability reuses the existing 24-hour, identity, confidence, attribution and
scenario gates. Referral and FBA fees require exact ASIN, New condition, mode and
price basis. Purchase, retailer shipping, inbound shipping, tax, preparation,
packaging, placement, storage, returns allowance, transaction and other costs must
be explicit, including evidenced zeros. Retailer shipping is folded once into
other cost. Net profit >= $5 and acquisition ROI >= 50% are unchanged; complete
passing FBA scenarios, exact identity, independent seller/FBA permission and the
existing verification gates are required for VERIFIED_PROFITABLE. Missing costs
leave profit and ROI UNKNOWN. No report grants purchase approval.

## Reproduction

Run with Python 3.12 and installed project dependencies from the repository root:

```bash
.venv/bin/python -m app.m93 --output var/m93-amazon-first --as-of 2026-11-06T18:00:00+00:00
```

Use a fresh output directory; `--limit` accepts 1–30, default 30. Without `--as-of`,
evaluation uses current UTC; original timestamps are never refreshed. Outputs are
`amazon-candidates.xlsx`, `amazon-candidates.json`, and `evidence-gap.md`.
Reports remain ignored and are not committed. JSON bytes and Excel cell values
reproduce with a fixed clock; workbook ZIP metadata may vary. Large nested JSON
cells are split into ordered fragments on Detailed Evidence, with references in
the main table; JSON retains the original structure without truncation.

No network requests, Seller Central login, SP-API calls, Walmart account access,
purchases, inventory creation, credential handling or production changes occur.
The offline audit guard blocks network/process creation during report generation.

## Review preparation

Proposed PR: **M93: add evidence-gated Amazon-first candidate selection**.
The workflow and reports are implemented, while viable opportunity discovery
remains blocked on external seller, price, market, exact identity and cost evidence.
Publish only after passing tests and explicit branch-publishing approval; do not
merge or deploy. Validation results are recorded in the local PR summary.

Final validation (Python 3.12.3): **3,704 passed, 9 skipped** in the complete
regression suite; **28 passed** in focused M93 tests. The earlier combined
M93/M92/M91/product-analysis run passed 129 tests. Legacy and discovery sample
modes succeeded with isolated `/tmp` workbook/database paths. Repeated JSON bytes
and Excel cell contents match, generated workbooks contain no formula cells, and
`git diff --check` passes. No branch publication, merge or deployment occurred.
