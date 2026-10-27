# Offline eBay Price API exports

`app.priceapi_export` imports an already completed eBay US search export without
transport, credential access or environment configuration:

```sh
.venv/bin/python -m app.priceapi_export --source supplied-export.json --output-directory var/new-offline-import
```

The output directory must be new. The source remains unchanged and SHA-256 is
recorded. The first ten distinct eBay URL item IDs retain result order. Provider
IDs are not fabricated when null. The adapter preserves full URLs, shop name/ID,
condition, search price/currency, supplied shipping and shipping-inclusive price
in generic source context. Older generic CSV headers remain valid. Search metadata
time is provenance only; missing individual offer time, stock, purchase quote,
package identity and license reference remain unknown.

The existing CSV/source validation, screening, SQLite evidence and Excel pipeline
persist all rows even when missing data blocks sourcing. No catalog match is
invented. Candidate keyword searches cannot establish exact identity; independent
GTIN or manufacturer/model plus package and variant evidence is required.

The candidate-only proposal caps authentication at one, searches at ten (one page
each), and candidate details at ten (one per listing): 21 HTTP attempts, no retries
or downstream pricing/restriction/fee calls. The JSON plan and workbook reflect
this budget. The generic source planner's downstream budget is not an execution
plan for this workflow. A future executor needs bounded keyword search, arbitrary
ASIN detail parsing (current catalog parser is fixed-ASIN), richer attributes and
explicit ambiguity handling. Nothing is enabled by this adapter.

Validation: synthetic duplicate URL/tracking, null shipping versus explicit zero,
condition/seller retention, unchanged original bytes and persisted unmatched rows.
Runtime exports/reports/databases must not be committed.
