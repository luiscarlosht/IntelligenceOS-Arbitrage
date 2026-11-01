# M61 account-specific eligibility discovery

Implements issue #48 as a local JSON intake/replay boundary. No credentials,
refreshes, Amazon calls, Seller Central access or purchases occur. M60's private
reports are neither inputs to the demo nor modified. Its reported outcome remains
one restriction, listing permission false, APPROVAL_REQUIRED for B0B1L79X41.
The replay test reproduces that response shape synthetically, not its private audit.

## Commands

Use Python 3.12 and the existing requirements. Output files must not exist;
exclusive creation prevents accidentally replacing historical evidence.

```bash
.venv/bin/python -m app.account_eligibility template --output var/m61-intake.json
.venv/bin/python -m app.account_eligibility validate --input var/m61-intake.json --output var/m61-validation.json
.venv/bin/python -m app.account_eligibility classify --input var/m61-intake.json --output var/m61-classification.json
.venv/bin/python -m app.account_eligibility export --input var/m61-intake.json --output var/m61-review.xlsx
.venv/bin/python -m pytest -q tests/test_account_eligibility.py
```

Template produces **20 empty slots**, zero sourced candidates, zero exact matches,
zero permissions and zero profitability results. Empty slots remain UNKNOWN and
review-required. Fill 20–50 slots from authorized real source observations; do not
pad a real cohort with examples. This implementation does not satisfy the real
20–50 exact-match acquisition goal without those observations. No supplied data
establishes such a cohort. Synthetic tests are explicitly labeled and separate.
JSON is the supported intake format. Keep all inputs/outputs under ignored var/;
never commit private reports or merchant IDs.

Top-level fields: `account_reference` (nonsecret alias, not merchant ID),
`is_synthetic`, `candidates`. Each candidate has:

| Object | Fields |
| --- | --- |
| retailer | retailer, title, url, gtin, brand, model, pack_count, variation, cost, availability, observed_at, provenance |
| amazon | asin, url (`https://www.amazon.com/dp/ASIN`), gtin, brand, model, pack_count, variation, observed_at, provenance |
| eligibility | asin, seller_reference (same alias), marketplace_id, condition, reference (local source reference), observed_at, restrictions |

GTINs are strings with valid check digits; pack count is a positive integer for
one complete selling unit. Cost is a decimal USD string; availability must be
`in_stock` to become an exact downstream candidate. Both source observations must
be fresh within 24 hours of the aware evaluation clock. Missing values remain
unknown; null is distinct from false. Use `--now` with an ISO timezone timestamp
for reproducible historical replay.

`restrictions` accepts either `{status: succeeded, response: {restrictions: [...]}}`
using the Amazon response shape or `{status: succeeded, data: ...}` using existing
saved-runner normalized data (`restriction_count`, `listing_permission.value`,
`reason_codes`, `reasons`, `approval_required`). Failed stages (429, 5xx, timeout,
uncertain) classify ERROR even if accompanied by an empty response. Missing or
wrong account/ASIN/US/new_new scope and stale/future checks classify UNKNOWN.
A raw empty restrictions array establishes only NO_REPORTED_RESTRICTIONS for the
explicitly supplied scope; no HTTP success or generic boolean suffices.

## Architecture and reporting

Reuses `RetailProduct`, `MarketplaceListing`, GTIN normalization and
`match_listings`; ASIN hints do not establish identity. Package, brand/model and
variation contradictions block exact matching. Reuses `parse_restrictions` and
`SellerContext` from the existing Amazon details architecture used by the saved
restriction workflow. It does not import or invoke the live executor.

The four openpyxl tabs are review, eligible, restricted and unknown. Eligible
means **exact candidate for independent downstream checks** only. An allowed ASIN
with a mismatched retail pack remains in review and outside eligible. FBA, fees,
ROI >=50% and net >=$5 flags remain independently null because M61 supplies no new
proof for them. Manual authorization and purchase_ready always remain false.
There is no buy-ready list. M59/M60 saved evidence remains independently scoped.

Reports contain sanitized reason codes, fixed approval instruction summaries and
HTTPS application links with query/fragment removed and Amazon hosts allowlisted.
Arbitrary response messages are omitted because they can contain merchant IDs;
original instructions remain in the original private evidence. Links are reference
text, never followed. Intake provenance must already be nonsecret. Workbook text
is literal, including formula-looking input. Classification includes account scope,
evaluation time, input SHA-256 and individual evidence hashes. Hashes provide
integrity references, not proof that operator-supplied evidence is authentic.

## New plan proposal — offline only

```bash
.venv/bin/python -m app.account_eligibility plan --input var/m61-intake.json --output var/m61-proposal.json --asins EXACT_ASIN --opt-in-plan
```

This command requires real, exact, uniquely identified targets (1–20 per proposed
batch), an account alias and a missing check. It excludes recorded attempts,
failures and restrictions; it cannot audit attempts absent from the supplied input.
It binds input bytes, exact ASINs, account, US/new_new and the proposed budget:
one authentication plus one restriction GET per ASIN; zero retries, pricing, fees,
catalog or retailer calls. Execution authorization and authorized budget stay zero.
A 20–50 candidate intake is partitioned into separately reviewed batches, never
silently submitted as one oversized run. Synthetic intake cannot generate a plan.

The proposal is deliberately **not an executable manifest**. Product Owner approval
is required for exact targets, a new manifest hash, budget/current entitlement,
private account continuity, and source rights. Before any later execution, re-audit
all historical attempts and immutable M60 exclusions, then use the existing
`ops.saved_target_restrictions.prepare/validate` architecture to bind saved targets,
exclusions, protected evidence and runner hashes. Its exclusive reservation,
durable attempt checkpoints, shared OperationPacer, cooldowns and deadline behavior must
remain the execution boundary. The current code offers no run/execute action and
does not change that runner or M60. Missing historical attempts are a plan-review
risk, never permission to retry.

## Evidence and remaining acceptance

Focused automated tests cover raw/normalized M60 approval shape, empty restrictions,
ASIN/pack/GTIN/variation mismatch, missing/wrong seller scope, stale/future evidence,
429/5xx/timeouts, contradictory permission, unknown downstream flags, no network,
formula-safe four-tab export, CLI round-trip, exclusive output and plan gating.
Real sourced candidates, authentic current account checks, FBA/cost evidence and
any purchases remain outside this offline implementation. PO decisions: provide
or authorize real source evidence and approve a separate exact live manifest if
wanted. No new default business thresholds or purchases are proposed.
