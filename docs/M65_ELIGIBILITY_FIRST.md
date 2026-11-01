# M65 eligibility-first discovery and approval intelligence

M65 is offline. No Catalog, Restrictions, Pricing, Fees, retailer, browser,
credential, approval-application, listing-creation or purchase operation is
performed. It adds modules beside M63; original M60–M63 code, evidence,
authorization files, ledgers and behavior are unchanged.

## Architecture and interpretation

`m65_intelligence` imports allowlisted fields from existing private normalized
restriction reports or scoped raw response intake. Source-file SHA-256 and row
ordinal identify evidence without copying private file names, seller references,
messages, links, headers or token context. Inputs are bounded; credential-named
files are refused. Private values present in source context are redacted from
public identity labels. SQL inserts go to a new owner-only store under ignored
`var/`; no original evidence is rewritten.

The importer records API operation status separately from these outcomes:

| Classification | Meaning at the recorded account/US/New observation |
| --- | --- |
| `NO_REPORTED_RESTRICTIONS` | Explicit successful, scoped empty restrictions evidence |
| `APPROVAL_REQUIRED` | Explicit approval-required restriction code |
| `NOT_ELIGIBLE` | Explicit not-eligible restriction code |
| `OTHER_RESTRICTED` | Restrictions exist with another or unspecified reason |
| `UNKNOWN` | Missing, failed, malformed, contradictory or ambiguous evidence |

Historical observations retain their dates; they do not establish current
permission. API success alone is insufficient. FBA eligibility and purchase
authorization remain separate and unknown/false. `NOT_ELIGIBLE` takes precedence
if both that code and an approval code are present. Unknown reason text is reduced
to `OTHER`; private free text is never persisted.

The actual M63 report has 20 successful restriction operations: 18
`APPROVAL_REQUIRED`, two `NOT_ELIGIBLE`, zero unrestricted results. Its overall
`partial` value is explained by the shared enrichment engine checking Pricing
and Fees statuses too, although both were intentionally `not_requested`. M65
imports each restriction stage independently; it does not alter M63's status
computation or retry anything.

`m65_intelligence.build_audit` combines the unchanged M63 read-only historical
audit, imported ASIN observations and permanent future claims. Even failed,
unknown and uncertain prior work is excluded. Current local evidence yields 77
excluded ASINs, including **all 20 completed M63 targets**. A report's appearance
in a Catalog search is not itself an eligibility attempt. Audit coverage is only
as complete as the explicitly supplied local evidence; unknown records on other
hosts cannot be audited here. Keep stores specific to the existing authorized
account; never mix another account's evidence into this intelligence store.

## Manual M64 observations

Initialize the four facts supplied by the user:

| Brand | Observed ASIN | Scope | Minimum invoiced units |
| --- | --- | --- | ---: |
| OXO | B00L9X2CWQ | Brand | 200 |
| Avery | B001HA4JXQ | Brand | 100 |
| Command | B07H54NZ3K | Brand | 100 |
| Whitmor | B00AN8CTX0 | Brand | 100 |

All require at least one manufacturer/distributor purchase invoice. None offered
immediate approval on the observed screen. The seed records say
`VERIFIED_USER_OBSERVATION`, referring to the user's M64 report, not a new Codex
inspection. Review dates and additional requirements were not supplied and stay
null; insertion timestamps are separate. These observations are attached to the
exact ASIN. An application scope of Brand does not prove every other ASIN under
that brand has the same requirements.

Events are content-deduplicated and append-only. Reimporting the same observation
is a no-op. Corrections or later reviews append a new observation and preserve
the original; differing observations are not silently overwritten. SQL triggers
reject normal updates/deletes. This is not protection against a privileged actor
deleting/replacing a database or altering its schema. Keep normal private backup
and filesystem controls; M65 installs or changes none.

Manual intake is JSON, not arbitrary Seller Central text. Export the current
observations, edit/add rows using the same schema, give each new review a
nonsecret `manual:review-alias` source reference, and import the new file.
`review_date` must be timezone-aware if known; never substitute today's date for
an unknown historical review. Boolean and numeric values must be typed, not
strings. Requirement codes are validated in `manual_observation`; use
`OTHER_REVIEW_REQUIRED` for requirements that need a future schema extension.
Do not insert seller identifiers, private documents, credentials or application
links. `NEEDS_REVIEW` observations do not count as verified review completion.

With the actual M63 evidence, exact-ASIN coverage marks four reviews complete
and the remaining **14 approval-required ASINs `NOT_REVIEWED`**. No brand-level
observation marks an uninspected sibling ASIN reviewed.

## Ranking and conservative cohort selection

`m65_ranking` accepts the existing saved M63 Catalog report, M63 CSV, or an
explicit JSON candidate list with ASIN, US marketplace, original aware timestamp
and source provenance. It deduplicates ASINs, flags conflicting identity, keeps
missing data visible, and prefers useful identity evidence. It never fetches
anything. Explicit product types from supplied observations are supported; none
is inferred from a title.

Base priority points:

| Signal | Points |
| --- | ---: |
| Valid, unambiguous GTIN | +8 |
| Model, size, package quantity, variation | +4 each |
| Explicit product type | +2 |
| Brand outside the previous 12 discovery seeds | +8 |
| Brand with a verified observed invoice pathway requiring >=100 units | -35 |
| Brand represented by at least two historical checks | -6 |

These are deterministic research-priority heuristics, **not estimated eligibility
probabilities**. A brand penalty is a soft selection signal, not a universal
eligibility finding. Unknown/unreviewed pathways are not treated as immediate
approval. The default minimum base score is zero; lower-scored candidates are
deferred for priority review and are not used to pad a cohort. An explicit
`--minimum-score` change is part of the resulting manifest and needs separate
review before any future execution.

Greedy selection subtracts 12 points per already-selected product of that brand,
eight per category and four per known product type. ASIN breaks ties. Unknown
product type earns no diversity credit. Default brand cap is two and the cohort
maximum is 20. Previously checked/reserved ASINs, conflicting identities and
missing brand/title are excluded. Every untested row's eligibility remains
`UNKNOWN`, including selected rows. No model/pack/title match becomes permission.

The actual saved input contains 100 products from the previous 12 seed brands
and lacks product-type fields on all 100 normalized records. The default dry run
therefore proposes **12 unchecked products across six brands and four category
groups**, deferring invoice-heavy low-priority candidates rather than filling 20.
It cannot supply outside-seed brands or verified product-type diversity without
additional permitted input. It does not claim the selected products are
unrestricted or retail-arbitrage viable.

## Offline commands

Run from the repository with Python 3.12. Outputs are private and exclusive: use
a fresh output directory or file instead of overwriting an earlier review.

```bash
.venv/bin/python -m app.m65 init --store var/m65/intelligence.sqlite3
.venv/bin/python -m app.m65 export-manual --store var/m65/intelligence.sqlite3 --output var/m65/manual-export.json
.venv/bin/python -m app.m65 import-manual --store var/m65/intelligence.sqlite3 --input var/m65/manual-export.json
```

Import the existing private M63 restriction report using its exact reviewed
path. Do not pass the authorization file, a new simulated report, credentials,
or a different seller's records:

```text
.venv/bin/python -m app.m65 import-history --store var/m65/intelligence.sqlite3 --input <existing private M63 restriction report.json>
```

Export sanitized history or review coverage:

```bash
.venv/bin/python -m app.m65 export-history --store var/m65/intelligence.sqlite3 --output var/m65/history-export.json
.venv/bin/python -m app.m65 coverage --store var/m65/intelligence.sqlite3 --output var/m65/manual-coverage.json
```

Prepare a future cohort from saved input only:

```bash
.venv/bin/python -m app.m65 prepare --store var/m65/intelligence.sqlite3 --catalog /root/.intelligenceos-arbitrage-amazon/m63-catalog-discovery-01.json --history-dir /root/.intelligenceos-arbitrage-amazon --output var/m65-next-review --max-checks 20 --max-per-brand 2 --minimum-score 0
```

`--max-checks` means maximum restriction checks (1–100), not total HTTP requests.
The proposed budget uses the **actual** selected count and at most one separate
authentication exchange. No unused quota is added to another stage. The exact
manifest file digest is printed in the summary. Offline schema/code validation:

```text
.venv/bin/python -m app.m65 validate --input var/m65-next-review/M65_proposed_manifest.json --sha256 <literal file SHA256 printed by prepare>
```

The private delivery handoff under `var/m65-final-review/` contains literal paths,
the actual proposed digest and exact commands for this VM. Nothing here executes
the proposed checks.

## Future execution boundary — disabled

M65 has **no CLI execute/run action and no live transport adapter**. Its manifest
is a proposal with `execution_authorized=false` and `live_executor_enabled=false`.
Do not feed it into M63's completed authorization or runner. The previous 20
checks are permanently excluded and must never be replayed.

`m65_batch` implements/test-drives only future accounting primitives. A later
reviewed adapter must validate a separate authorization record with exact
manifest file SHA-256, exact ordered ASINs, US/New scope, exact budget, review
reference/time, expiry and an explicit execution flag. Code hashes, source,
ranking, store revision and historical audit hashes bind the proposal. No
authorization record is generated or approved automatically.

Permanent transactional batch and per-ASIN claims precede any future request.
Attempt counters are consumed once before a transport can run; duplicates,
out-of-scope operations and exhausted budgets are rejected. A failed/uncertain
attempt is not refunded. The fixed `UNKNOWN`/`FAILED`/`UNCERTAIN` stop primitive
blocks follow-up attempts. These helpers were exercised only against temporary
synthetic stores; real dry-run preparation creates **no claims or attempts**.
There is no retry, refresh, release, auto-resume, budget expansion, Pricing, Fees
or retailer stage. Live adapter integration remains a separate review; these
offline helpers alone are not a complete live executor.

## Profitability contract and safety assessment

`m65_readiness` tracks listing permission, FBA eligibility, selling price,
referral/FBA fees, acquisition cost, tax, inbound shipping, prep/packaging/storage
and other costs, exact GTIN/model/size/variation/pack match, net profit, ROI and
inventory allocation independently. Unknown values remain null. Evaluation is
disabled; no zero fees, inferred prices, estimates or hypothetical profits are
created. Thresholds remain ROI >=50%, net >=$5 and inventory allocation <=$500.
Each eventual value needs its own scope, source, timestamp and selling-unit
evidence. `NO_REPORTED_RESTRICTIONS` alone never grants FBA, purchasing, listing
creation or unconditional permission to sell.

The new modules never load credentials or call a network adapter. Reports copy
only allowlisted evidence and source hashes. The prior workflow and all source
files stay unchanged. Main limits are the small biased historical sample,
unknown review dates, incomplete product-type data, absent non-seed brands,
historical rather than current eligibility, and incomplete profitability inputs.

## Verification

```bash
.venv/bin/python -m pytest -q tests/test_m65.py
.venv/bin/python -m pytest -q
```

Tests use synthetic fixtures and temporary stores. They block sockets and real
Amazon credential/transport access; cover every classification, malformed and
missing evidence, privacy, exclusions, deterministic/diverse ranking, invoice
penalties, manual import/deduplication, authorization/digest/budget gates,
permanent claims, no retries, safe stopping, immutable originals and disabled
commercial actions. The documented legacy/discovery mock sample modes are also
run with isolated output files and email disabled. No live requests or commercial
actions are part of implementation or validation.

Local verification on 2026-11-01: baseline 1,237 tests passed; final **1,286
tests passed**, including 49 new M65 tests. Both isolated legacy and discovery
mock sample modes completed successfully. The real dry run contains zero
authorization claims and zero request attempts. Its historical audit matches
the original 77-ASIN exclusion inventory byte-for-byte by recorded hashes.
