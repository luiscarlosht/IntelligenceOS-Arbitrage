# Offline DEMO and authorized-import handoff

All products, prices, fees, eligibility and demand in these fixtures are fictional.
**Nothing here is a live deal or purchase approval.** No credentials are needed.
The demo ignores ambient mail/provider environment configuration, uses only the
existing CSV connector, mock provider, matching, screening and workbook writer,
and performs no network calls or job-history writes.

```bash
.venv/bin/python -m app.demo
```

Outputs (ignored, never committed): `var/demo/DEMO.xlsx`, `DEMO.json`, `DEMO.md`.
Every workbook tab starts with DEMO; rows, provenance and workbook title say DEMO.
The JSON/Markdown include the threshold sensitivity and actionable CSV validation.
The evaluation clock is fixed at **2026-10-24 12:00 UTC** to keep acceptance
repeatable. This clock evaluates controlled fixtures only; it does not freshen
production evidence. Existing sample modes keep their real-clock stale-data gates.

## Expected selection

Default budget is $500 **per unit**, profit >=$5 and acquisition ROI >=50%.
Acquisition includes all supplied acquisition expenses, and every fee must exist.
Explicit fixture zeroes represent known fictional zero expenses, never missing fees.
The real financial formula, unrounded comparisons, inclusive boundaries and mock
confidence cap of 50 are unchanged. Independent `budget_units` does not allocate
a basket across rows or authorize spending.

| Fixture | Acquisition USD | Profit USD | ROI | Default outcome |
| --- | --- | --- | --- | --- |
| passing | 10 | 10 | 100% | REVIEW, fictional only |
| boundary | 10 | 5 | 50% | REVIEW, inclusive thresholds |
| low-profit | 5 | 4 | 80% | REJECT, profit |
| low-roi | 20 | 9 | 45% | REJECT, ROI |
| over-budget | 501 | 300.50 | approximately 59.98% | REJECT, one unit exceeds $500 |
| package-mismatch | 10 | 10 | 100% | REJECT, package 1 versus 2 |
| missing-fees | unknown | unknown | unknown | REJECT, missing fulfillment fee stays missing |
| stale | 10 | 10 | 100% | REJECT, source and marketplace evidence are 48 hours old |

Workbook ROI is rounded for display; `over-budget` displays 60.0%, but screening
uses the unrounded value. Changing **only** budget to $600 adds `over-budget`;
profit to $4 adds `low-profit`; ROI to 40% adds `low-roi`. Package, fee and freshness
failures remain blocked in all scenarios.

## Authorized-source samples and validation

`sample_data/authorized_source_sample.csv` is one structurally valid fictional
owner-export row matching `templates/authorized_products.csv`. Replace its example
URL, identity, permission reference, provenance, quantities, price, stock and
original timestamp with actual authorized evidence before real use. It supplies
no Amazon fees, seller eligibility or demand. A sample permission reference is
**not** proof of licensing or authority.

`demo_authorized.csv` supplies eight controlled screening cases, including one
intentionally stale row. `demo_invalid_authorized.csv` demonstrates invalid price,
quantity, URL and naive timestamp, and missing identity, permission and provenance.
The generated DEMO validation section names each row/field and the repair action.
For arbitrary authorized exports use the existing preflight (now with `findings`
containing corrective actions as well as the compatible `issues` list):

```bash
.venv/bin/python -m app.authorized_imports sample_data/authorized_source_sample.csv
.venv/bin/python -m app.authorized_imports sample_data/demo_invalid_authorized.csv
```

Preflight uses current UTC, so dated samples eventually fail freshness; this is
expected. Exit 0 means no field issues, exit 1 means fix the findings. Never change
an original observation timestamp just to pass. Obtain a new authorized export.
At the fixed DEMO clock the one-row sample has no issues; the eight-row file has
`Row 8: Stale source timestamp`. Invalid input reports field-level repairs and
stays rejected. Neither preflight nor DEMO asserts verified authorization or
marketplace access. Input URLs are validated syntactically and never fetched.

See [SMTP review](SMTP_TEST_HANDOFF.md), [operations checklist](OPERATIONS_HANDOFF.md)
and [Keepa preparation](KEEPA_PILOT.md). External evidence, credential provisioning,
email receipt and installation acceptance remain owner actions.

## Validation evidence (2026-10-24)

206 local tests passed on Python 3.12.3 / pytest 8.3.5. Both documented sample
modes succeeded in isolated `var/offline-handoff/` state with SMTP settings cleared;
legacy/discovery workbooks had four/six sheets and no formula cells. DEMO produced
two default REVIEW fixtures and six rejected fixtures; threshold sensitivity matched
the table. The one-row authorized sample passed current-clock preflight; deliberately
invalid input exited 1 with 11 actionable findings. Offline Keepa plan reported
zero calls/tokens and disabled execution. A scratch SQLite snapshot restored into
a new path, verified one table/two run records and matching content hash, and
healthcheck returned no issues. `pip check` and `git diff --check` passed. Patched
pytest 9.0.3 installation/CI is separate pending verification; see the advisory note.
No production reporting/provider state or services were changed. A subsequent explicit
owner instruction authorized read-only WeinsteinAgent email inspection and one
DEMO email attempt using existing settings. That attempt failed DNS before
connection/authentication/submission; see the SMTP handoff. No provider call occurred.
