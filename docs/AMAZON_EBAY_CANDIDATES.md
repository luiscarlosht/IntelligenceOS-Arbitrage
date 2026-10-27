# eBay → Amazon catalog candidate stage

Prepared offline for the ten listings imported from Price API job
`6ae1298795263c2adcdb3ac7`. No Amazon execution is authorized or performed by this
PR. No credentials, pricing, fees, restrictions, email or production settings
were accessed. The original Price API export and imported CSV remain unchanged.

## Reviewed request manifest and exact operator command

[The source-bound manifest](../ops/examples/amazon-ebay-candidates-20261027.json)
contains all ten ordinals, eBay item IDs, source fingerprints and literal title
keyword queries, including the canvas-art listing at ordinal 2. Ordinals 4 and 7
remain separate despite identical titles. The manifest binds the existing CSV:

- Path: `/root/IntelligenceOS-Arbitrage/var/source-imports/ebay_6ae1298795263c2adcdb3ac7_offline/observations.csv`
- SHA-256: `cabbbda426bff05faff0b6d8f051e62bde21fa927efafe9fc347e9380ee24f11`
- Marketplace: `ATVPDKIKX0DER` (US).

After PR review and separate live-execution authorization, the operator command
is exactly (prepared here, **not run**):

```sh
cd /root/IntelligenceOS-Arbitrage
.venv/bin/python -m app.amazon_candidates run \
  --source /root/IntelligenceOS-Arbitrage/var/source-imports/ebay_6ae1298795263c2adcdb3ac7_offline/observations.csv \
  --manifest /root/IntelligenceOS-Arbitrage/ops/examples/amazon-ebay-candidates-20261027.json \
  --execute
```

This uses the existing private Amazon credential loader only during explicit
execution. It does not prompt for credentials or use environment-loaded production
configuration. Plan generation has no credential/private-directory/network access:

```sh
.venv/bin/python -m app.amazon_candidates plan \
  --source /root/IntelligenceOS-Arbitrage/var/source-imports/ebay_6ae1298795263c2adcdb3ac7_offline/observations.csv \
  --manifest /tmp/amazon-ebay-candidates-review.json
```

A regenerated plan must match the committed manifest. Source path, bytes, query,
request parameters, policy or limits changes invalidate execution; do not edit a
hash to force acceptance. A new source snapshot requires a newly reviewed plan.
Do not rerun the Price API importer to generate this manifest: an import timestamp
and expanded CSV headers would change its source-byte hash.

## Request bounds

| Operation | Maximum | Request |
| --- | ---: | --- |
| Authentication | 1 | Existing LWA refresh exchange, POST `https://api.amazon.com/auth/o2/token` |
| Keyword search | 10 | GET `/catalog/2022-04-01/items`, US marketplace, source title as `keywords`, `keywordsLocale=en_US`, `locale=en_US`, `includedData=summaries`, `pageSize=10` |
| Selected candidate details | 10 | GET `/catalog/2022-04-01/items/{selected_asin}`, same marketplace/locale, `includedData=summaries,identifiers,relationships,attributes` |
| **Total HTTP attempts** | **21** | Zero retries, one page and at most one detail per source row |

The first distinct returned ASIN is selected deterministically for investigation,
not as a product match. Empty pages skip details. Duplicate ASINs within a page
are deduplicated, but source rows never are. Provider next-page tokens are neither
persisted nor followed. More results, multiple candidates or incomplete coverage
remain ambiguous. No query broadening, identifier searches, pagination, token
refresh on failure, fallback candidate or downstream request is hidden in this
budget. Each auth/search/detail attempt is reserved and fsynced before transport.
Calls are sequential, paced at least 0.5 seconds apart, bounded to the existing
10-second socket timeout / 1 MiB body limit and a 300-second CLI alarm deadline.
Auth, 429, transport, permission and parser failures stop the stage without retry.

Official contract: Amazon's [Catalog Items 2022-04-01 model](https://github.com/amzn/selling-partner-api-models/blob/main/models/catalog-items-api-model/catalogItems_2022-04-01.json).
The implementation reuses the existing verified-TLS, no-proxy/no-redirect transport
and token exchange. No new provider is registered with the orchestrator.

## Evidence and matching

`parse_catalog(..., expected_asin=...)` now accepts any valid requested ASIN while
requiring response identity equality. Its default remains the historical pilot's
fixed ASIN, retaining compatibility. Unknown seller eligibility, prices and fees
remain unknown. Search and detail observations carry separate provenance and
aware retrieval timestamps; source timestamps are never replaced.

Titles retrieve candidates only. Exact identity requires the existing deterministic
GTIN or manufacturer/model checks, consistent package quantity, matching structured
variation and no unresolved mapping/source issues. ASIN hints alone do not suffice.
The new optional generic CSV `source_package_contents` contains a canonical JSON
array of independently verified package components; it must equal US-scoped
`included_components` detail evidence. No package components/counts, brand or
variation are extracted from titles. Missing composition, unsupported unit-count
semantics, conflicting count/variation attributes, parent relationships or
unverified material keep matching blocked. Unsupported attributes are not promoted
to identity evidence. Both older generic CSV header versions remain accepted.

Even a fully verified singleton is only exact within this bounded candidate set,
not proof that the full Amazon catalog has no duplicate ASIN. Multiple/unexamined
candidates are never promoted after examining only the first detail. The ten
current eBay rows lack sufficient identity/package/variation evidence and will
therefore remain unverified or ambiguous even when a detail looks similar.

## Persistence, failures and replay

Before credential loading, an exclusive owner-only report is reserved at:

`~/.intelligenceos-arbitrage-amazon/candidates-cabbbda426bff05faff0b6d8f051e62bde21fa927efafe9fc347e9380ee24f11.json`

The source hash fixes the report name; an existing report blocks replay before
credentials or HTTP. Preserve it after failure. A changed output filename cannot
bypass the one-shot reservation. Do not delete reports to retry.

All ten original source payloads/ordinals are present before authentication and
checkpointed with normalized search candidates, selected details, attempts and
states: `unmatched`, `candidate_unverified`, `ambiguous`, `exact`, `failed` or
`not_attempted`. A controlled failure still records remaining source rows.
Sibling `.sqlite3` and `.xlsx` outputs reuse ObservationStore, existing screening
and formula-safe Excel reporting. JSON is checkpointed during the run; SQLite and
Excel are finalized afterward. A hard process kill may leave only JSON or an
incomplete checkpoint; no automatic retry/recovery is attempted. Source row
evidence is retained in the original CSV regardless. A report-export failure
must be investigated locally without repeating HTTP.

No raw provider responses, next-page tokens, request headers, access tokens,
credential values or arbitrary exception text enter reports. Source seller,
condition, full URL, prices/shipping, unknowns and provenance are retained. An exact
identity does not supply purchase approval, pricing, fees or seller eligibility;
all resulting sourcing rows remain rejected until independent evidence is supplied.

## Regression validation

Synthetic transports cover 21-attempt completion, zero-result detail skipping,
multiple and paginated candidates, duplicate ASINs, missing/contradictory package
and variation evidence, title/ASIN-hint-only blocking, arbitrary and mismatched
ASIN details, malformed search responses, failure at authentication/search/detail
and the final request, source/manifest tampering, replay protection, deadlines,
redaction, unchanged source rows, SQLite ordinal retention and offline plan CLI.
