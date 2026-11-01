# M73 — offline catalog consolidation and discovery quality

M73 follows the completed M72 live pilot and merged PR #61. It performs local
analysis only. It does not authenticate, replay execution, load credentials or
live owner authorization artifacts, reserve ASINs, or invoke any provider,
retailer, eligibility, pricing, fee, FBA, listing, approval or purchase operation.
M63–M72 code, original evidence, baseline files and credentials are unchanged.

## Verified input contract

The M72 registry is opened read-only with the original immutable-table and
hash-chain verifier. A completed terminal state, ten consumed slots, no uncertain
slots, nine successful first pages, and an explicitly supplied checkpoint are
required before catalog import. The separate saved summary must agree. Each
request intent must hash to the original authentication/first-nine keyword
sequence. Every saved page must equal its durable registry response, including
query, request slot and proposal binding. Cursors are evidence only and are not
followed or exported into the consolidated catalog.

Reviewed immutable bindings:

- M71 proposal SHA-256: `b09cbea8033caa994b8a79c2451851b1cc91171548e73cadf1c1ebef35731103`.
- M71 original manifest file: `0161373a75c3a744c97bd20a0caefd7afb5527158794c15875ac1946963fa26c`.
- M72 completed checkpoint: `260e03e15b79c77b96430d3416a57fefc65c374421489fe34937d92e41077dd4`.
- M70 operation-bound baseline CSV: `75db3ae006381cbf71198ba7f81bcc6fac09dc439695c6d5d77fb48dead64a6e`.
- Original M70 full report: `228c29245ab8898fb4647aa5016b0e86b49ac6546ebef546480a65c941370a56`.

The original M70 JSON report is necessary: its CSV alone omits alternative values
and field provenance needed to preserve existing conflicts. Its explicitly reviewed
file digest is checked, its implementation must match unchanged M70, and re-export
through unchanged M70 must reproduce the exact CSV bound into the M72 operation.
Mock/generated/synthetic flags are rejected. The M72 source manifest is hash-checked
and limited to the original single Catalog-pages export; any rejected record stops
consolidation rather than silently shrinking the real-ASIN count.

The original M71 read-only history validation must still reproduce the frozen
proposal and all 97 exclusions/40 checked ASINs. Missing original locks are rejected;
M73 never bootstraps state in the private execution directory. Input digests and
historical inventory are rechecked before export and before publication of the final
output-digest manifest. A failed/incomplete output has no completion digest and must
not be used. Existing output directories and symlink paths are rejected.

## Actual reconciliation and readiness

| Measure | Actual |
|---|---:|
| M70 distinct baseline ASINs | 197 |
| M72 distinct new ASINs | 180 |
| Cross-cohort duplicate ASINs | 0 |
| Combined distinct real ASINs | **377** |
| Expected 377 reconciliation difference | **0** |
| Progress toward 1,000 | **37.7%** |
| Remaining distinct ASINs | **623** |
| Permanent exclusions retained | 97 |
| Excluded ASINs present in combined catalog | 41 |
| Previously checked seller-specific ASINs retained | 40 |
| Unexcluded real ASINs in combined catalog | 336 |
| Structurally complete catalog identities, excluding condition | 35 |
| Complete identities, including condition | **0** |
| ASINs with unresolved conflicts | 31 |

The 1,000 target counts all distinct real catalog observations, including historical
exclusions. It is not a count of sellable or research-eligible products. The separate
97-row exclusion table includes exclusions absent from these two source cohorts.
All 40 checked ASINs are present in the catalog and remain permanently excluded;
no historical seller-specific outcome is reinterpreted as current permission.

| Field | Missing or unresolved in combined catalog |
|---|---:|
| GTIN | 220 |
| Model | 131 |
| Condition | 377 |
| Pack quantity | 156 |
| Size | 145 |
| Variation | 164 |
| Product type | 197 |

A conflicted field remains null and counts as unresolved. Condition is unknown for
all products. Titles, unit counts, hierarchy, GTIN prefixes and neighboring products
never fill pack quantity, size, variation, model or condition. The original baseline
has 21 GTIN conflicts; M72 adds ten, for 31 total. None is automatically resolved.

M73 preserves aggregate baseline alternatives, original field provenance, original
source references and unsupported-observation indicators. A baseline alternative
cannot honestly be assigned to a particular original source when the old merged
report did not record that mapping. New M72 observations retain exact source-file,
page and row references. Baseline and M72 cohort membership is explicit per ASIN.

## Investigation of the ten M72 conflicts

All ten are **multiple distinct normalized GTINs from Catalog identifiers**.
Normalizing UPC/EAN padding and validating check digits does not collapse these
alternatives to one identity. The conflict report retains the actual alternatives
and original marketplace-scoped identifier datasets, query/slot and source row.

| ASIN | Distinct normalized GTIN alternatives |
|---|---:|
| B082VH421C | 5 |
| B077T1LQCV | 2 |
| B06ZZXF81G | 2 |
| B096WGP63W | 2 |
| B088MMQMX7 | 2 |
| B0833YRXKT | 2 |
| B0CX1KB48V | 2 |
| B015HWXG4M | 6 |
| B07KGPBC24 | 2 |
| B07Q5WKCRW | 2 |

B096WGP63W and B088MMQMX7 each have alternatives beginning `00` and `20`.
This observation does not establish which represents a unit, case, or correct
selling pack. No alternative is preferred by prefix, array position, frequency,
title, brand, or apparent package relationship. Every conflict stays UNRESOLVED.
Manual follow-up needs authoritative product/GTIN ownership and package/variation
identity evidence before selecting an identifier. M73 performs no external lookup.

## Diversity, priority and discovery coverage

The combined report contains 153 observed brand labels and 25 observed category
labels. These are source labels, not a harmonized taxonomy or independently verified
brands; M70 category buckets and M72 browse labels differ in granularity.

The deterministic research ranking scores ten points per non-null observed identity
field, from 0 to 100, breaks ties by ASIN, and places historical exclusions, conflicts
and existing review blocks after unblocked records. It retains every ASIN and every
blocker. There are 305 records unblocked for **offline identity research**, with the
other 72 blocked by exclusions or conflicts. Missing fields remain visible. This
ranking measures field coverage only, not demand, margin, eligibility or readiness
to buy. All eligibility values remain UNKNOWN and purchases remain unauthorized.

Conservative duplicate scenarios for the remaining **623** unique ASINs:

| Assumed duplicate rate against accumulated catalog | Additional result slots | Full 20-result pages, rounded up |
|---|---:|---:|
| 25% | 831 | 42 |
| 50% | 1,246 | 63 |
| 75% | 2,492 | 125 |

These are planning estimates, not executable budgets. Page estimates assume every
page has 20 results; sparse pages, invalid records or increasing overlap require
more. They exclude authentication and all enrichment operations. M72's zero observed
duplicate rate is not extrapolated. No new discovery request is authorized here.

## Exact offline command

From the reviewed repository checkout, with all existing immutable inputs present:

```bash
.venv/bin/python -m app.m73 \
  --baseline-dir var/m70-offline-final \
  --baseline-report-sha256 228c29245ab8898fb4647aa5016b0e86b49ac6546ebef546480a65c941370a56 \
  --proposal var/m71-preparation/M71_manifest.json \
  --private /root/.intelligenceos-arbitrage-amazon \
  --checkpoint 260e03e15b79c77b96430d3416a57fefc65c374421489fe34937d92e41077dd4 \
  --sources /root/.intelligenceos-arbitrage-amazon/m72-catalog-pilot-output/M72_M70_sources.json \
  --summary /root/.intelligenceos-arbitrage-amazon/m72-catalog-pilot-output/M72_summary.json \
  --store var/m66-local/intelligence.sqlite3 \
  --m67-manifest var/m66-expanded-review/M66_review_manifest.json \
  --m67-sha256 8983bef70ce5cfd79d15b7611e4b5646784f37bfce1a88bd220286394303ee55 \
  --output var/m73-final
```

The actual run creates `var/m73-final`; choose a new sibling output path for a later
repeat. All reports are ignored by Git and owner-only (directory 0700, files 0600).
No report, raw source, runtime database or credential is committed.

`M73_review.xlsx` contains summary, audit, catalog, identity quality, conflict review,
ranking, diversity, exclusions and discovery scenarios. Matching `M73_*.csv` files
are formula-safe and the workbook stores text safely. `M73_report.json` preserves
full identity/provenance detail; `M73_summary.json` provides redacted metrics.
`M73_output_digests.json` is written only after final immutable-input validation.
Oversized Excel evidence cells fail rather than silently truncating provenance.

## Validation

Baseline regression: **1,873 passed**. Targeted M73: **30 passed**. Final full
regression: **1,903 passed in 237.55 seconds**. Both documented offline sample
modes passed with socket connections blocked. Tests use temporary synthetic fixtures only; those
products are never included in the real reports. Coverage includes operation status,
request count, pinned checkpoint/proposal/source drift, hash-chain corruption,
original baseline reproduction, conflicts, missing fields, synthetic rejection,
privacy, formula safety, protected paths, no-overwrite output, no credentials/network/
execution, preserved exclusions and immutable-file metadata, and input drift during
export. Both documented sample modes are run with socket connections blocked.

Actual consolidation was also run with socket connections and credential/live-owner-
authorization file reads blocked. Nine original input files retained identical hashes;
all 68 private-directory entries retained identical inventory, sizes, modes and mtimes.
No M63, M67 or M72 registry, report, source, credential or authorization was modified.
