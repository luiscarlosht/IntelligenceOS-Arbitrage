# Authorized retailer and supplier CSV imports

Copy `templates/authorized_products.csv` to a private ignored input directory.
The template contains headers only: no fabricated supplier records or dates.
Use UTF-8 CSV, exact header order, quoted commas/newlines and decimal USD amounts.
Keep GTINs as text to preserve leading zeroes. Partition at 10,000 rows.

Before importing, the owner must verify permission for internal product analysis
and retain a private agreement/export record. `authorization_reference` is a
nonsecret locator for that record, not an assertion that software verified it.
`provenance` describes the actual export/source and collection method. Do not
include credentials, buyer data, signed URLs or confidential agreement text.
Supplier name goes in `retailer`; the same schema supports both routes.

Required evidence: source name, product name, HTTP(S) product URL without embedded
credentials, valid check-digit GTIN or manufacturer plus exact model, positive
package quantity and purchase price, `in_stock`, actual timezone-aware retrieval
time, provenance, exact variation (use a documented actual standard designation
only when applicable), and authorization reference. `asin_hint` is optional and
never proves identity or seller eligibility. Missing or uncertain evidence must
remain missing; do not put zero for unknown costs or update retrieval dates
without collecting fresh authorized evidence.

```bash
.venv/bin/python -m app.authorized_imports var/private/products.csv
ARBITRAGE_MODE=discovery ARBITRAGE_INPUT=var/private/products.csv \
  ARBITRAGE_REPORT=var/private/review.xlsx \
  ARBITRAGE_DB=var/private/history.sqlite3 .venv/bin/python -m app.orchestrator
```

Run preflight and proceed only if exit status is zero **and** the owner verified
rights. Nonzero means invalid/missing/stale source evidence (24 hours), future
timestamps, bad structure or empty input. Diagnostics omit input values.
This separate strict preflight does not change legacy/discovery CSV compatibility
or automatically enforce permission on every connector invocation; operators must
use this review workflow. CSV content cannot prove legal permission.

The discovery connector ignores the extra authorization-reference column; retain
the input and permission mapping privately for audit. The template supplies no
Amazon data. Only the mock provider is selectable: unknown identity, missing
listing, fees, eligibility, demand, competition, package/variation or fresh
marketplace evidence remain blocked. Mock matches remain illustrative and
purchase_ready=false. Do not edit bundled fixtures to make an import pass.
