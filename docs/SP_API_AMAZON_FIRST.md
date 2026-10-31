# SP-API Amazon-first pilot — prepared offline

Keepa subscriptions and live integration are deferred. **No paid service is
authorized.** This reuses our existing SP-API/evidence infrastructure. No live
Amazon/Keepa/browser calls, credentials, subscriptions, purchases, Sheets writes,
email, merge, deployment or scheduling were performed during preparation.

## Branch and PR #43 audit

GitHub reports [PR #43](https://github.com/luiscarlosht/IntelligenceOS-Arbitrage/pull/43)
merged on 2026-10-31 at 04:53:51 UTC into **`milestone/real-data-pilot`**, merge
commit `aea2a9ca56facd2dc2c98c270a9cb50e73be3e10`. It was **not merged into main**:
comparison against main diverges at `721f19ea...`, with two commits exclusive to
that branch. Main was verified at `1d46eb7aa698b802c1f83ed70f67825c13b4113a`.

This change starts directly from that main commit. It ports PR #43's reusable
`AmazonTarget`, job, provenance, persistence and independent verification contracts
into main without its Keepa parser, Finder plan or CLI. It adds a separate explicit
SP-API preparation/runner; no orchestrator selector changes. Existing unfinished
checkout edits are excluded from the PR. No merge or deployment is requested here.

## Saved evidence audit and generated outputs

The offline audit reads only eleven allowlisted catalog/candidate JSON reports in
`/root/.intelligenceos-arbitrage-amazon`. It never opens `credentials.json` or an
existing execution database. File SHA256 references, source fingerprints,
marketplace binding and successful detail/search attempts gate reuse. The existing
`catalog_saved_evidence.saved_evidence` helper verifies detailed evidence. Failed
or reserved-only operations cannot become successful evidence. Every original
report and unresolved operation remains intact.

| Audit result | Count |
| --- | ---: |
| Distinct ASINs mentioned in saved searches | 844 |
| Normalized reusable snapshots, including repeated observations | 1,035 |
| Deduplicated marketplace/ASIN targets | 845 |
| ASINs with reusable normalized catalog evidence | 54 |
| Prior detail-attempt ASINs retained in the audit | 55 |
| Selected national-brand targets | 20 |
| Walmart ZIP 76063 jobs | 10 |
| Saved sales-rank snapshots among selected targets | 0 |
| New requests / credential files read | 0 / 0 |

The 54 catalog ASINs include the earlier summary-only catalog pilot; they do not
all have complete product identity. The broader search-only leads remain in
`all-targets.json` with missing identity fields. A product being in the Amazon
catalog, or appearing first in keyword results, does not establish demand.

Generated owner-only files are under the ignored directory
`var/sp-api-amazon-first-20261031-final/`:

* `AMAZON-TARGETS.xlsx`: 20 readable targets; Read Me, Targets, Evidence and Audit
  sheets, explicit missing data, all identifier values and field-level provenance.
* `WALMART-BROWSER-HANDOFF.md` and `browser-handoff.json`: ten offline Browser Use
  tasks, **47 maximum query attempts** in total; stop early when the exact item is
  found or the task is unresolved. No task has been executed.
* `selected-targets.json` / `all-targets.json`: 20 selected targets / all 845
  deduplicated targets, with conflicts and historical observations preserved.
* `targets.sqlite3`: new additive target versions and prepared jobs using the
  existing ObservationStore/History boundary; existing databases are untouched.
* `audit.json`, `catalog-plan.json`, `summary.json`: provenance inventory, explicit
  query/request budget and offline execution summary.
* `sheets-proposal.json`: separate proposed target/job/outcome tabs, offline only.

Identifier lists retain every value and provenance. Multiple representations of
one GTIN are distinguished from genuinely different GTINs. Conflicting identifiers,
size, model or pack fields remain unresolved; no convenient UPC is selected.
Package quantity, number of items, unit count and included components are preserved
separately. `package_quantity=1` never implies one pen, one wipe or one battery.

Selection prioritizes detailed evidence, fewer mapping/conflict issues and complete
brand/model/size/pack/variant identity. It does not sort by rank or call the targets
profitable. Top handoff examples include Sharpie models 30072, 37175, 34821PP and
30665PP; Rubbermaid 1777087 and 2179274; Dove 45893080531.0; Clorox 31430 and
10044600600335; Energizer E92DP-8. Model strings are retained as reported.

## Current official SP-API findings — checked 2026-10-31

[The current search operation](https://developer-docs.amazon.com/sp-api/reference/searchcatalogitems)
supports `GET /catalog/2022-04-01/items` with keywords or identifiers, never both.
Identifier searches require `identifiersType` (ASIN/EAN/GTIN/ISBN/JAN/MINSAN/SKU/UPC),
with at most 20 identifiers. SKU searches additionally require sellerId. Brand
and classification filters apply to keyword searches. Page size is at most 20;
this pilot requests two results and never follows pagination.

[Search prerequisites](https://developer-docs.amazon.com/sp-api/docs/search-catalog-items)
require selling-partner authorization, Product Listing approval in the developer
profile and that role selected on the application. Amazon explicitly warns that
external identifiers and ASINs need not map one-to-one. This account's current
role/authorization settings have not been inspected; successful historical calls
are evidence of those calls, not proof that every requested dataset is available.

[The Catalog Items use-case guide](https://developer-docs.amazon.com/sp-api/docs/catalog-items-api-v2022-04-01-use-case-guide)
lists Product Listing for both getCatalogItem and searchCatalogItems. `salesRanks`
is a catalog includedData dataset, not a separate bestseller/monthly-sales service.
No additional Brand Analytics entitlement is assumed. Missing or denied attributes
remain missing; vendorDetails is vendor-specific and is not requested.

[The response schema](https://developer-docs.amazon.com/sp-api/docs/catalog-items-api-v2022-04-01-reference)
defines classification ranks (classificationId/title/rank) and display-group ranks
(websiteDisplayGroup/title/rank), grouped by marketplace. It also defines summary
brand, manufacturer, modelNumber, partNumber, size, color, style and packageQuantity,
identifier arrays, relationships and product-type attributes.

[The dedicated rate-limit page](https://developer-docs.amazon.com/sp-api/docs/catalog-items-api-rate-limits)
and current operation page specify 2 requests/second and burst 2 per account/app.
The combined reference still shows 5/5; this is a documentation discrepancy.
We retain the existing conservative 2 rps ceiling with 50% headroom, respect lower
reported rates and shared cooldowns, and stop on throttling. The rate header does
not describe every account/application limit. No throughput guarantee is made.

## Parser changes and demand limitations

`parse_target_item` wraps the existing `parse_catalog` without changing its legacy
return contract. The pilot additionally preserves:

| Useful field | Existing limitation | Pilot behavior |
| --- | --- | --- |
| brand, partNumber, separate size/color/style | Legacy listing lacks these dedicated fields | Preserve summary fields with observation provenance |
| structured unit_count and units/type | Existing detail parser flattens or marks complex values | Retain allowlisted structure, distinct from package quantity |
| number_of_items, included_components | Existing detail evidence already supports them | Reuse saved values; preserve structured fields when returned |
| salesRanks | Existing requests/parser did not retain it | Validate positive integer and category identity; retain each US rank separately |
| observation timestamp | Parsing old evidence must not freshen it | Preserve original saved time; future rank time is response capture time |
| source update time / historical demand / monthly sales | Not supplied by these snapshots | Explicit null / missing; no inference |

Ranks are usable only if actually returned. Our saved selected records have no
rank history, so zero ranks are reported. We cannot recover omitted fields from
already normalized evidence. Future captures retain category/rank type,
marketplace, local observation time and provenance; Amazon's source update time
remains unknown. Never compare ranks across categories as equivalent or convert
rank changes into verified sales. No bestseller discovery endpoint or monthly
sales estimate is promised. Pricing, fees and seller eligibility remain independent.

## Bounded catalog pilot and explicit queries

All ten proposed first-page requests use:

```text
GET https://sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items
marketplaceIds=ATVPDKIKX0DER
includedData=summaries,identifiers,relationships,attributes,salesRanks
locale=en_US&keywordsLocale=en_US&pageSize=2
keywords=<brand + wording below>&brandNames=<brand below>
```

| Brand | Explicit wording after brand |
| --- | --- |
| Sharpie | permanent markers fine point |
| Post-it | super sticky notes |
| Rubbermaid | easy find lids food storage |
| Ziploc | slider gallon bags |
| Clorox | disinfecting wipes |
| Dove | intensive repair shampoo |
| Energizer | MAX AAA batteries |
| Finish | Quantum dishwasher pods |
| Scotch | Magic tape |
| OXO | SoftWorks utensils |

National household, personal-care, office and kitchen brands are plausible Walmart
overlap hypotheses, supported partly by existing retailer observations. This is
not evidence that every Amazon variant/pack is sold by Walmart. No Target or
Walgreens collection is authorized by this plan; source-access decisions remain
unchanged. No category discovery request or title-based pack inference is hidden.

| Stage | Maximum requests | Current expected requests |
| --- | ---: | ---: |
| Saved audit, target workbook and browser export | 0 | 0 |
| LWA exchange | 1 | 0 |
| Keyword catalog searches, ten queries × one page × two results | 10 | 0 |
| Automatic detail/pricing/fees/restrictions | 0 | 0 |
| Catalog-stage ceiling | **11** | **0** |

The current saved seed already fills the 20-target cap. The future runner returns
before credential access rather than repeating searches to fill an already-full
queue. If a later reviewed inventory leaves slots, stop at 20 distinct eligible
targets or the end of ten requests; results may overlap, be incomplete or be empty.
Do not pad the list, retry, follow nextToken or assume every query returns two.

An optional identifier batch (at most 20 reviewed ASINs) is **separately disabled**:
`GET /catalog/2022-04-01/items?marketplaceIds=ATVPDKIKX0DER&identifiersType=ASIN&identifiers=<reviewed-list>&includedData=<same-data>&pageSize=20&locale=en_US`.
Its separate reservation would be one catalog request plus at most one LWA
exchange, **two requests**, not an addition to this catalog-stage ceiling.

Later enrichment is also separately disabled: at most three retailer-verified
targets, independently reserving three pricing, three fee-estimate and three
seller-restriction requests plus at most one LWA exchange (**ten requests total**).
Those are planning envelopes, not an implemented auto-enrichment action. Existing
partial-offer pricing gates and seller-specific restrictions still apply. Existing
$5 profit / 50% acquisition ROI defaults remain; unknown costs cannot become zero.
All current acquisition ceilings remain null.

## Quota, replay and handoff behavior

The explicit future runner reuses `amazon_pilot` secure credential loading,
verified-TLS/no-proxy/no-redirect/bounded-response transport, `OperationPacer`, the
shared `candidate-execution.lock` and the existing `candidate-executions.sqlite3`
execution/operation tables. It validates the reviewed file hash and current evidence
inventory, claims all query operations durably **before credentials**, consumes each
attempt before I/O, checkpoints only normalized evidence/allowlisted errors and
stops on failure, 429, Retry-After or an extended saved cooldown. Overall deadline
is 120 seconds; socket timeout and response bounds reuse the existing transport.
No new run or claim is written for the already-full saved queue.

No attempt is refunded or released after an uncertain failure. Renaming the output
or regenerating the same query cannot evade permanent query claims. There is no
automatic refresh command; changed evidence/query/version and any claim recovery
require explicit operator review. This preparation never opens the original
execution ledger, clears claims, replays pending work or changes cooldowns.

Walmart jobs use stable target + retailer + ZIP + query-version hashes and retain
the target revision, every uncertain barcode/model, required brand/size/variant/
retail pack and fields still needing verification. Save all query outcomes,
including no result, mismatch, unavailable and unresolved. Browser matched is only
a claim. New observations link to target/search-job IDs before independent exact
matching and existing profitability/reporting; target brand, ZIP, model, size,
color and package evidence must agree. Generic variant conflicts stay explicit.

Existing Walmart intake columns and producer/consumer ownership do not change.
The proposed separate tabs from PR #43 are represented offline only. No Sheets
client, browser session or producer is invoked. A repeated job is not a new
authorization: refresh requires a new version, prior-job ID and explicit reason.

## Exact one-line commands for a future SSH session

Run inside the existing SSH session; no host identity or credential is assumed.
The first command is offline and requires a new output directory:

```bash
cd /root/IntelligenceOS-Arbitrage && .venv/bin/python -m app.sp_api_targets prepare --output var/sp-api-amazon-first-operator-01
cd /root/IntelligenceOS-Arbitrage && .venv/bin/python -m pytest tests/test_sp_api_targets.py -q
```

Only after later explicit authorization to invoke the future runner, the exact
command for the **currently prepared** inventory is below. It currently exits with
20 saved targets and zero requests; no run invocation was made during preparation.
If evidence or the manifest changes, this hash must fail closed; prepare/review
again instead of substituting a fresh hash blindly.

```bash
cd /root/IntelligenceOS-Arbitrage && .venv/bin/python -m app.sp_api_targets run --manifest var/sp-api-amazon-first-20261031-final/catalog-plan.json --sha256 33284d87fd3fc53ca37d084c1c8e424c2aea2c07f6b3025d5ed5215652a4415f --max-requests 11
```

Keep the generated files private. No credentials in chat, shell arguments,
workbooks, normalized reports or browser tasks. No new account, paid service,
credential entry or service activation is required for offline preparation.
