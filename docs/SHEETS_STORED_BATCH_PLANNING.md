# Stored Sheets batch audit and offline Amazon planning

`app.sheets_candidate_plan` opens an existing intake database with SQLite
`mode=ro`, `query_only=ON` and a read transaction. It never initializes schemas,
creates a missing database, acknowledges Sheets or updates history. The selected-batch audit supports 1–1,000 records, requires one acknowledged
COMPLETE batch, exact count metadata, unique record IDs and distinct linked
observations for that batch. Other acknowledged batches are permitted and do not
invalidate the selected batch.
It verifies SQLite integrity/foreign keys, batch/row/observation hashes, original
raw JSON consistency, normalized payloads and equality of raw/exported/stored
observation timestamp instants. Original string timestamps remain in retained
rows even when normalized timestamps use a different equivalent UTC spelling.

Planning consumes products directly reconstructed from those stored rows. It
reuses the pure offline keyword formatter and does not change missing variants,
package quantities, shipping charges or identifiers. It requires explicit
reviewed ASIN selections with reasons. Historical first-page Amazon searches may
supply investigation leads only when the nonmock US report binds the exact
Walmart ID/URL, compatible declared brand, original source fingerprint, search
query, marketplace and completed search attempt. The report bytes are hashed.
Historical queries, incomplete coverage and observation times remain visible;
a changed query is never represented as a newly completed current-source search.
Evidence older than 24 hours is flagged, not automatically refreshed.

Completed catalog details can be reused for the same scoped ASIN. Conflicting
retained details or an uncertain earlier detail attempt require manual review;
they do not schedule a repeat call. Missing detail requests are deduplicated by
ASIN. Descriptive candidate selection is not exact matching or purchase approval.
Independent source barcode/manufacturer/model, package composition and variants
remain missing until supplied. Prior incompatible or unresolved ASIN selections
remain documented, not erased.

## Current local preview

The actual database `var/sheets-intake.sqlite3` contains one acknowledged batch
`walmart-76063-20261029T010727Z-five-v1`, five intake records and five source
observations. The local read-only audit verifies all retained hashes and timestamp
instants. Its repeated audit leaves database bytes and modification time unchanged.
Actual original JSON is retained locally; no raw rows are published by this change.

Private ignored outputs live under `var/sheets-amazon-five-offline-20261029/`:
`PREVIEW.md`, `reviewed-plan.json`, `selections.json`, `inputs.json` and
`evidence-inventory.json`. They record the five source rows' observation times,
explicit reviewed alternatives and the paths/hashes of saved evidence used.
Five saved first-page searches are reused as historical leads. Five nominated
alternative ASINs lack retained catalog details in the three local candidate
reports. The two saved enrichment reports cover a different nine-ASIN set.

First proposed stage: 1 token exchange + 5 catalog-detail GETs = **6 requests**;
searches, pricing, fees, restrictions, retries, pagination and refreshes are zero.
The five previously completed selected-ASIN details are not repeated: four have
fine/ultra-fine or pack differences; the professional chisel model is unresolved.

Only after catalog identity/package and authorized seller review, a separate
optional stage could require up to 1 authentication + 5 New/Consumer pricing +
5 seller-scoped new_new restrictions + 5 price-bound FBA fee estimates = **16**
additional requests, or **22** across both sessions. Fee requests require explicit
valid scenarios and may be skipped. Nothing here authorizes those requests or
supplies missing fees, eligibility or achievable prices.

## Future offline command

```sh
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && .venv/bin/python -m app.sheets_candidate_plan --inputs var/sheets-amazon-five-offline-20261029/inputs.json --output var/sheets-amazon-five-offline-20261029/next-preview.json'
```

This command performs local reads and creates an exclusive owner-only preview
file. Existing output files are never overwritten. It requires no credentials.
This offline planner has no execute flag. The existing Amazon candidate CLI now
provides generic prepare-details/run-details modes for a separate hash-bound
execution manifest; see STORED_CANDIDATE_EXECUTION.md. Do not pad source batches
or rerun completed searches/details. Legacy CSV candidate budgets scale with
validated batch size, preserving the ten-record 21-attempt contract.
No Amazon request, email, scheduling, sheet clearing or runtime database mutation
is performed during planning. Preparation makes no live calls. Publish only the focused code/tests/docs change;
keep runtime inputs, source databases and saved reports private and unchanged.
