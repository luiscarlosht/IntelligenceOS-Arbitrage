# M70 — scalable offline discovery and identity enrichment

M70 adds local authorized source adapters, conservative identity composition,
M69 history/scoring reuse, diversified selection and a non-executable Catalog
budget plan. No network transport, credentials, live adapter, scheduler, eligibility
check, reservation or execution path is added. M63–M69 modules/evidence are unchanged.

## Source contracts

`app.m70_sources` accepts a schema-1 JSON manifest with `sources`, each containing
`path`, `sha256`, `adapter`, `permission_reference`, `marketplace` and optionally
`observed_at`. Relative paths resolve beside the manifest. Marketplace is US
`ATVPDKIKX0DER`; permission references are nonsecret `local:...` or `manual:...`
owner references, not proof of licensing. Only ingest legitimately authorized exports.
No source URL is followed. Hash mismatches, symlinks, credential-like filenames,
duplicate JSON keys and invalid manifest contracts fail closed.

Adapters: `m63_json`, `m63_csv`, `amazon_catalog_items`, `amazon_catalog_pages`,
`local_json`, `local_csv`, `retailer_json`, `retailer_csv`. Local JSON accepts a list,
`records`/`items` wrapper, or a single identity. CSV uses the same flat identity
fields. Retailer records may omit ASIN but cannot introduce new Amazon candidates.
No retailer export with established permissions was available for this run.
Historical candidate-details wrappers contain search/detail and retailer snapshots;
they are not automatically treated as licensed retailer feeds or raw Catalog items.
Explicitly extract only authorized product records into the documented local schema
with their original timestamps and source references before later ingestion.

Example manifest entry (replace the path and hash with actual evidence):

```json
{"schema":1,"sources":[{"path":"authorized-products.json","sha256":"REPLACE_WITH_FILE_SHA256","adapter":"local_json","permission_reference":"manual:owner-export-reference","marketplace":"ATVPDKIKX0DER"}]}
```

Identity fields: `asin`, `brand`, `title`, `product_type`, `category`, `gtin`/`upc`,
`model`, `size`, `variation`, `pack_quantity`, `condition`, `observed_at`. GTINs are
checksum validated and normalized to 14 digits; original valid UPC strings remain
available. Titles never supply models, pack counts, sizes or identifiers. Missing
and invalid data stays absent. `inferred_fields`, `generated_fields`, and corresponding
field-status flags prevent their values becoming observed facts. Mock/synthetic
source flags and generated/inferred ASINs are rejected. Test fixtures are isolated.

Saved API pages require `pages`, each with `query_reference`, zero-based `page_index`,
US `marketplace_id`, `http_status=200`, `observed_at`, `items`, `page_token` and
`pagination.nextToken` when present. Chains are validated separately per query;
repeated/broken cursors fail. A final continuation cursor reports a partial query.
Maximum service page size is 20 and the pageable query window is 1,000 items.
Local CSV/list pagination defaults to 200 records. Bounds: 100 source files,
64 MiB each, 100,000 observations and 10,000 distinct ASINs by default. Imports are
bounded in memory; no infrastructure or product-per-request processing is needed.
Identical source files are counted once per role. ASIN deduplication is exact and
sorted; all accepted duplicate observations retain field provenance.

## Identity and ranking semantics

`app.m70_identity` merges only compatible source-observed fields. Contradictions
remain explicit alternatives with the affected field missing and status `CONFLICT`;
no preferred source silently overwrites them. Every field carries source hash,
page/row reference, timestamp and observed/missing/unsupported status. Confidence
is observed-field coverage percent, not a probability or manual verification.

Full completeness requires all ten identity fields, including condition, and no
conflicts/review blocks. `catalog_identity_complete` omits condition because Catalog
Items is condition-agnostic. `m69_core_complete` separately measures the seven
brand/title/GTIN/model/size/variation/pack fields for comparison. None implies verified
identity. Exact Amazon/retailer matching requires compatible brand, GTIN, model,
size, variation, pack and condition, independent source files, no conflicts, and
matching explicit ASIN if the retailer supplies one. Missing evidence yields UNKNOWN.
No product price, eligibility, listing access or profitability is inferred.

`app.m70_discovery` projects observed identities to unchanged M69 scoring/history
contracts and restores original provenance afterward. It preserves original source
quality points and adds +20 full-identity and +10 complete-core-identity points.
M69 permanent claims, condition/manual blocks and identity exclusions remain active.
Brand restriction observations retain capped penalties, never blanket bans.
Greedy selection applies M69 brand/category/type diversity penalties and a default
10-per-normalized-brand cap, with deterministic ASIN tie breaks. Maximum shortlist
is 200, default 150; an undersized pool is never padded. All eligibility remains
UNKNOWN. Read-only original M63/M67 history is required; missing ledgers fail closed.
No M69 workflow event or permanent claim is created.

## Offline commands and outputs

```bash
.venv/bin/python -m app.m70 analyze --sources var/m70-sources.json \
  --store var/m66-local/intelligence.sqlite3 \
  --history-dir /root/.intelligenceos-arbitrage-amazon \
  --m67-manifest var/m66-expanded-review/M66_review_manifest.json \
  --m67-sha256 8983bef70ce5cfd79d15b7611e4b5646784f37bfce1a88bd220286394303ee55 \
  --output var/m70-offline-review
.venv/bin/python -m app.m70 plan --output var/M70_catalog_discovery_plan.json
```

New output paths are mandatory. Reports are owner-only, formula-safe and ignored
by Git. Do not commit raw reports, source files, private histories or credentials.

| Output | Content |
|---|---|
| M70_catalog_1000.csv | All actual distinct ASINs; filename expresses target only |
| M70_identity_quality.csv | Missing/conflicting/unsupported fields and field provenance |
| M70_candidate_ranking.csv | Ranked selected shortlist with explainable scores/history |
| M70_exclusions.csv | All permanent excluded ASINs, including those outside current sources |
| M70_source_coverage.json | Hash-bound sources, imports/rejections, duplicate rates, partial pagination |
| M70_summary.json | Actual counts, distributions, target attainment and zero-operation counters |
| M70_report.json | Complete reproducible report including every ranked/excluded row |

## Actual saved-source run — 2026-11-01

Two existing M69 authorized inputs: original M63 saved JSON (100 observations,
SHA-256 `7ce135f07753798af1154cb5bdf8f0731683d14a8527574d9c7678bb89084d25`)
and exported M63 CSV (98 observations,
`0374cbd9463421addfd39054d19280a811e5476ce6138a8b630d72173b0fe612`).
All 198 observations were accepted. One duplicate ASIN observation (0.5051%) gives
197 distinct ASINs. No complementary identity enrichment or retailer matches were
available. Twenty-one ASINs have conflicting identity values.

| Measure | Actual | Target |
|---|---:|---:|
| Distinct ASINs | 197 | 1,000 |
| Fully complete identities | 0 (0%) | 80% |
| Core identities complete under M70 conflict rules | 46 | descriptive |
| Source brand labels | 25 | 50 |
| Categories | 4 | 10 |
| Ranked shortlist | 130 | 100–200 |
| Selected source brand labels | 23 | descriptive |
| Permanent exclusions | 97 | exclude all |
| Excluded ASINs present in catalog | 41 | descriptive |

Missing fields: GTIN 121; model 97; pack 97; size 101; variation 135;
product type 197; condition 197. Brand/title/category are present for all ASINs.
Full completeness is stricter than M69's catalog completeness; its previous 21
complete selected identities are not being asserted to satisfy the new definition.
Categories in the catalog: office 64, kitchen 57, household 41, home_improvement 35.
Shortlist: office 42, kitchen 41, household 24, home_improvement 23.
Full brand/category distributions are in the generated summary.

All 40 checked ASINs and every permanent exclusion are absent from the shortlist.
Historical outcomes stay 36 APPROVAL_REQUIRED, four NOT_ELIGIBLE, zero
NO_REPORTED_RESTRICTIONS. Every M70 identity/shortlist eligibility stays UNKNOWN.
Network and authentication primitives were blocked during the actual run. Two
runs with identical inputs/clock produced identical reports. Sixty-six protected
source/history/store files retained identical bytes, sizes and modification times.
Generated final artifacts reside in `var/m70-offline-final/`; plan is
`var/M70_catalog_discovery_plan_final.json`. Canonical report hash:
`61483d1f9412f5133cc5fc156bdcf9e2129785612720037bfbe16f20bd6cbd22`. No M63–M69 evidence was rewritten.

## Future Catalog discovery — planning only

Required operations: `GET /catalog/2022-04-01/items` (`searchCatalogItems`) for
reviewed keyword/category partitions and ASIN identifier batches; optional
`GET /catalog/2022-04-01/items/{asin}` (`getCatalogItem`) for missing details.
Request summaries, identifiers, relationships, attributes, productTypes,
classifications and dimensions. Condition still needs separate legitimate evidence.
No executable API discovery adapter is supplied in this milestone.

Default proposal: 50 reviewed query slots × at most four pages, 20 items/page;
200 keyword requests, 50 identifier-page requests, zero detail requests and one
authentication request, maximum **251 total requests**. Zero retries, restrictions,
pricing, fees or retailer requests. This is a ceiling, not permission or guaranteed
yield. Fifty identifier batches only cover 1,000 inputs if all batches fit 20 and
require no extra pagination. Any additional page consumes its existing phase budget.
At unique qualifying yields of 100%/50%/25%, the arithmetic estimate for 1,000 ASINs
is 50/100/200 keyword pages; query exhaustion/overlap/poor coverage can still fail.
Queries and filters remain NOT_YET_REVIEWED; owner review must freeze actual coverage.
Never assume the theoretical 4,000 raw keyword slots are distinct or complete.

Actual configured pacer defaults: search/detail caps 2 RPS, headroom 0.5, effective
1 RPS each; environment overrides may only lower caps. Plan records the process's
actual configured values. No persistent pacer state is read or written. Account
usage limits and response headers remain unknown without separately authorized calls.
Amazon's [rate-limit guide](https://developer-docs.amazon.com/sp-api/docs/catalog-items-api-rate-limits)
lists account/application 2 RPS, burst 2, application search/detail 500/250 RPS and
keyword application 50 RPS. Its [operation reference](https://developer-docs.amazon.com/sp-api/docs/catalog-items-api-v2022-04-01-reference)
currently lists 5 RPS/burst 5 instead. Keep conservative repository caps; the first
applicable service/account/application threshold governs. A future executor must
respect rate headers, Retry-After/cooldowns and stop on throttling without retries.
At default configuration, the 250 Catalog slots require approximately 250 seconds
of pacing alone, excluding authentication, latency and service cooldowns.

Future execution requires a separately reviewed adapter and frozen request/query
manifest, exact source/code/history digests, existing US account scope and **fresh
explicit owner authorization**. Durably consume each request before transport;
uncertain dispatch remains consumed. Checkpoint query/filter hash, page index,
response hash, seen-ASIN digest and counters. Store opaque tokens privately; export
hashes only. Deduplicate after each page, stop at terminal/repeated/broken cursor,
service window, phase budget or first failure. Save partial evidence and report the
gap; no automatic retries, refreshes, query expansion or continuation authorization.
`project_pages` validates saved page sequences and proposed budgets offline only.

## Validation

Baseline full suite: 1,653 tests. M70 tests exercise 1,240 distinct synthetic test
ASINs, 60 brands/12 categories, duplicates, provenance, conflicts, missing fields,
no generated enrichment, retailer exact matches, permanent exclusions, deterministic
ranking, CSV identity preservation, local/API saved pagination, configuration,
request ceilings, blocked network/authentication/reservation primitives, protected
evidence preservation and unchanged M69 fixture compatibility. Synthetic identifiers
exist only inside tests and never supplement actual reports.
