# M63 Amazon SP-API-first discovery

## Execution outcome, 2026-11-01

The authorized run was invoked after tests passed, but runtime DNS preflight
failed before credential loading, reservation or HTTP. New authentication,
Catalog, restriction, Pricing, Fees and retailer requests: **zero**. The 29-search
authorization remains unspent. A normal authorized SSH terminal with working
Amazon DNS/TLS is needed to run the prepared Catalog command.

The offline fallback exported **98 unique real ASINs** from authenticated,
source-bound historical Catalog observations dated October 28–30, not fresh
verification. Groups: kitchen 32, household 16, office 40, home improvement 10.
Fifteen returned brand labels are present; PHILIPS/Philips LED are treated as one
brand for sample diversity. One historically attempted product remains visible
in the discovery CSV with its flag; all 20 proposed eligibility targets exclude
the full 57-ASIN historical exclusion set. No ASINs were invented to reach 100.
All 20 sample rows still have missing identity fields; none is an exact retailer
match or ready for inventory. This fallback is not completion of fresh live
Catalog discovery.

Private deliverables: `var/m63-final-review-20261101/`; prepared Catalog input:
`var/m63-catalog-authorized-20261101/catalog-manifest.json`. The private command
handoff contains exact hashes, all 20 ASINs, safe offline validation and the
future restriction command, explicitly marked to wait for user review.

Validation: 1,237 tests passed (including 21 new tests); both documented legacy
and discovery mock sample modes completed with isolated outputs and no email.
The baseline was 1,216 passing tests. These checks establish implementation
behavior, not live Amazon access or seller eligibility.

Discovery alone is authorized: at most 24 keyword search requests plus at most
five identity-batch searches, never more than 29 Catalog searches. One separate
LWA exchange is allowed. Stop at 100 unique qualifying candidates; no retry,
Pricing, Fees, Listings Restrictions, retailer, browser, purchase, paid service,
approval application or seller-setting operation belongs to discovery.

## Implementation

`app.m63_catalog` reuses `amazon_pilot` authentication, private file security,
verified-TLS/bounded transport, `OperationPacer` and Catalog parsing. It is a
manual CLI, outside the default application/provider orchestration. The existing
20-target M62 runner and M60/M61 evidence are unchanged.

Twelve explicit keyword/brand queries cover kitchen, household, office and home
improvement. First pages are interleaved across categories before second pages;
page size is 20, at most two pages per query. Live selection caps each brand at
10 candidates and each category at 25. Query membership is a workflow grouping,
not proof of Amazon taxonomy, suitability or demand. Returned US summary,
explicit brand match and related title are required. Reject known exclusions,
variation parents, obvious hazard wording and explicitly large/heavy parcels.
Missing dimensions, UPC/model/pack/variation and selling/FBA suitability stay
unknown; these are research candidates, never inventory recommendations.

Search requests include summaries, identifiers, relationships, attributes,
dimensions and product types. Identity batches use `identifiersType=ASIN`, at
most 20 existing candidates each, and only run when identity is missing and the
100-candidate stop has not been reached. No new ASIN may enter through an
identity response. Duplicate observations retain provenance; contradictory
identity observations cannot enter the eligibility sample.

The shared private execution lock excludes simultaneous discovery launches.
Before credential access, exclusive fixed-name M63 evidence and accounting
files permanently consume this authorization's execution reservation. SQLite
`synchronous=FULL` records every attempt before network I/O; report checkpoints
are flushed/fsynced. Output renaming and manifest regeneration cannot replay the
authorization. Authentication, 24-keyword, five-identity and 29-total limits are
separate. Stop on the first request error, throttle or Retry-After; do not refund
uncertain requests. A 300-second dispatch deadline, ten-second socket timeout,
50% pacing headroom and historical shared cooldowns bound execution. Do not
remove reservations or run parallel executors. Crash recovery is offline export
and review, never automatic resume.

TLS/DNS preflight sends no HTTP and loads no credentials. If unavailable, it
fails before creating an execution reservation or spending an API attempt.

## Historical audit

`app.m63_history` opens only allowlisted Amazon evidence reports, plus a
read-only projection of the existing execution ledger. It never reads credential
contents. Report hashes and projected ledger operations bind the plan. It
excludes M60 `B0B1L79X41`, the existing `B0G1MJ24B4` exclusion, all non-search
per-ASIN attempts, failed/uncertain/reserved checks, and prior M63 eligibility
claims. The existing source-aware M58 audit resolves older ordinal-bound detail
attempts that lack `attempt.asin`. Mock reports do not establish real attempts.

This is conservative: a prior Catalog detail or Pricing attempt also excludes
an ASIN from the proposed new eligibility cohort. Merely appearing in a Catalog
search does not. Missing, malformed or changed known audit inputs block execution.
The audit covers available local records, not unknown records on another host.

## Commands on the authorized VM

Use the existing checkout and Python environment. Preserve any dirty work; do
not reset, clean, overwrite private evidence, deploy a service or touch backups.
No credential arguments or environment values should be printed or copied.

Prepare the Catalog input offline in a new directory:

```bash
cd /root/IntelligenceOS-Arbitrage
.venv/bin/python -m app.m63_catalog prepare --output var/m63-catalog-authorized-20261101
```

Preparation prints its actual manifest SHA-256. The deliverable's private
`M63_VM_COMMANDS.md` provides the literal hash for the prepared local input.
Run only that reviewed file/code/history combination:

```text
.venv/bin/python -m app.m63_catalog run --manifest var/m63-catalog-authorized-20261101/catalog-manifest.json --sha256 <literal prepared SHA256> --output var/m63-live-catalog-20261101
```

This command invokes only the authorized discovery. If TLS/DNS is unavailable,
no authentication or Catalog attempt is made. If a reservation already exists,
stop and inspect it; never rename/delete it to bypass replay protection. Code
or history drift fails closed: inspect the change and review a newly prepared
input rather than substituting a new hash blindly.

After a completed/interrupted reserved run, export its saved checkpoint offline
into a fresh output directory:

```bash
.venv/bin/python -m app.m63_catalog export --output var/m63-catalog-recovered-20261101
```

## Offline saved-evidence fallback

```bash
.venv/bin/python -m app.m63_catalog saved --output var/m63-saved-review-NEW
```

This reuses the M58/M62 source-bound audit of successful saved Catalog responses.
It does not turn old timestamps into current observations. Selected fields and
source report hashes are traceable; summary-only items explicitly lack identity
datasets. Known national-brand rules cover food containers/bags, office supplies,
dry sponges/tissues and A19 LED bulbs. Oversized tube lamps, obvious chemicals,
large tissue cases, bulk pen cases and large bakeware sets are excluded. Fragile
glass and LED products still require independent handling/suitability review.
Fallback selection permits up to 40 per category, 10 per brand, and stops at 100
or the actual supported count. Report a shortfall without adding invented rows.

## Outputs and eligibility review boundary

Private ignored output files:

- `M63_amazon_candidates_100.csv`: actual count, stable `amazon-us:ASIN` IDs,
  title/brand/grouping, Amazon URL, original timestamp, all available identifiers,
  model/pack/variation evidence, missing fields, previous-attempt flag and source
  evidence references. The requested filename does not promise 100 rows.
- `M63_eligibility_manifest_20.json`: up to 20 unique new ASINs, US/New, exact
  request specifications, source CSV hash and historical audit fingerprint;
  `execution_authorized=false` pending exact-cohort review.
- `M63_discovery_summary.json`: actual count, category/brand breakdown, request
  counts, execution duration, errors, evidence mode and explicit limitations.

The sample rotates across categories, prefers fewer missing fields, limits each
brand to two products (PHILIPS/Philips LED share a limit) and excludes every
audited attempted ASIN. An ASIN-level restriction lookup does not require a
retailer match; missing UPC/model/pack/variation still blocks subsequent exact
matching and purchase decisions. All five M61 classifications remain available.

`ops.m63_restrictions validate` is offline. The separate `run` action requires
`--execute-reviewed`, the literal reviewed manifest SHA-256 and exact ASIN count.
**Do not invoke run until the user reviews this exact cohort and command.**
It reuses the existing bounded enrichment engine, hidden seller-account prompt
and restriction parser, with a permanent M63 cohort reservation. It allows one
authentication and at most 20 distinct one-attempt restriction requests, no
retries or other API operations. Arbitrary response messages and links are
removed before persistence because they can echo private seller identifiers;
allowlisted reason codes remain. No approval link is followed. Reservation or
history drift blocks replay before credentials. No live restriction execution
is part of this milestone.

Only a later `NO_REPORTED_RESTRICTIONS` result can enter the retailer queue,
subject to exact UPC/GTIN/model/variation/pack matching, additional selling/FBA
checks, fresh economics, $500 budget, ROI >=50% and net >=$5 per unit. An empty
restriction response is not unconditional selling or inventory approval.

CSV text is formula-safe and UTF-8 with BOM. Import identifiers as Text in
Excel/Sheets to preserve leading zeros. Upload the candidate CSV to the existing
IntelligenceOS-Arbitrage Drive folder using Drive's New → File upload. Reports
and private runtime inputs are never committed. This task does not upload or
change sharing settings.

## Verification

Synthetic tests cover offline preparation, manifest/history drift, exclusions,
deduplication, category/brand diversity, target/29-request ceilings, identity
batches, malformed responses, auth/403/429/timeouts, no retries, durable accounting,
replay protection, CSV output/hashes, original timestamps, missing data, and the
future restriction runner's 20-ASIN bound and seller redaction. No test uses live
credentials, calls Amazon, or writes to the original private evidence directory.
