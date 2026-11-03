# Google Sheets research pilot

The real M79 Top 20 was published through the authorized Google Drive connector on
2026-11-03. Readback verified twenty distinct original ASINs, original priority and
the six requested tab schemas. No Browser Use research, live Amazon request,
production credential access, purchase or deployment was performed.

Pilot: https://docs.google.com/spreadsheets/d/1FcbY7OLu5Vz50IehxuA23E6obwuxt6_SYtFgRUac0ps/edit

The file lives in the connected user's ChatGPT folder. Reuse this ID. Browser Use
needs access through the user's authorized account; public sharing was not enabled.

## Source and evidence

Original handoff: `var/m79-amazon-intelligence-final-20261103/M79_walmart_handoff.json`.
Reviewed SHA-256: `ae37c83d251d72a7e337ba5416f4e5d2e05d9b16dd45ef8df0e5d8fd636d9064`.
The M80 source validator verifies original membership, no exclusion/conflict/mock
flags, US marketplace and twenty distinct ASINs. The publisher also checks the M79
completion inventory and hashes the associated report before reading categories
and historical restrictions. ASIN syntax alone is not evidence of a real product;
the reviewed source pin and field-level references establish catalog provenance.

Top 20 starts with B00004OCNJ and ends with B00BTGSGFK. Full catalog contains 1,397
distinct observed ASINs. Top 100 uses the original research_queue. Excluded/conflicted
full-catalog records retain their restrictions. UNKNOWN stays UNKNOWN. Catalog list
prices never fill current amazon_price. Demand, fees and current eligibility are unknown.

Amazon_Candidates starts with the fourteen requested columns and adds
`gtin,size,variant,condition,identity_evidence,restrictions`. UPC values and source
references are JSON arrays preserving alternatives. All identifiers are literal text.
Identity evidence retains original observed times, field status, conflicts and quantity
basis. Historical restriction annotations remain historical, never current seller checks.

Catalog package quantity is preserved verbatim. Titles sometimes describe multiple
inner units with catalog package quantity 1. Investigate that ambiguity; never infer
pack conversion, split packs or rewrite the original Amazon record.

## Publisher

Install optional dependencies: `pip install -r requirements-sheets.txt`.
Dry-run reads no credentials and makes no network requests:

```sh
.venv/bin/python -m app.sheets_publisher \
  --handoff var/m79-amazon-intelligence-final-20261103/M79_walmart_handoff.json \
  --sha256 ae37c83d251d72a7e337ba5416f4e5d2e05d9b16dd45ef8df0e5d8fd636d9064 \
  --scope 20 --output var/new-top20-export
```

The fresh output directory contains the real CSV, Browser Use input/output JSON
contract and publication manifest. `--scope 100` and `--scope all` use the same schema.
For CSV imports, treat columns as text and disable conversion/formula interpretation.
Live publication uses literal Sheets stringValue cells, preserving leading zeros.

Live mode requires an explicitly authorized credential file (service-account or
authorized-user JSON supported by google-auth) and the existing spreadsheet ID:

```sh
export ARBITRAGE_SHEETS_ID=1FcbY7OLu5Vz50IehxuA23E6obwuxt6_SYtFgRUac0ps
export ARBITRAGE_SHEETS_CREDENTIALS=/approved/private/sheets-credentials.json
# Run the command above with a new output directory and --live --run-id RUN_ID.
```

Never put credentials in chat, Git or reports. No ambient ADC or production
credential discovery occurs. Connector authentication is managed separately and
does not configure this local CLI. The credential needs Sheets write scope and
access to this file. This adapter cannot create spreadsheets, preventing duplicate
creation on retries; missing ID/auth fails before any external mutation.

google-auth AuthorizedSession calls the official Sheets v4 HTTPS API with verified
TLS, 30-second request timeout and disabled redirects. 429/500/502/503/504 have at
most five attempts with bounded exponential backoff and jitter. Other statuses fail
immediately. Logs contain only structured event/status/attempt/run/count; response
bodies, tokens, credential paths and arbitrary exceptions are omitted. Ambiguous
transport failures stop for a fresh snapshot rather than blindly replaying changes.

Headers and duplicate keys validate before writes. Existing ASINs retain row positions.
Only owned Amazon metadata changes; research_status and custom columns remain intact.
Existing Walmart research, profitability, review notes and opportunity rows are never
rewritten by candidate publication. New research rows start REVIEW_REQUIRED. Nothing
clears or sorts a range. Run IDs upsert one log row; keep source content/scope fixed
when resuming the same ID.

Top 20 data and COMPLETE marker commit atomically. Larger scopes use deterministic
25-candidate partition IDs with atomic per-partition completion, then a parent COMPLETE
marker only after all partitions verify. Recover by rerunning the same ID from fresh
reads: ASIN rows and researcher fields survive. Missing parent marker means incomplete
full publication. A lost structural response may produce already-exists on retry;
rerun to replan against observed metadata. Batches above 1.8 MB fail before mutation.
The supported bound is 10,000 candidates and sheet grids <=20,002 rows.

Use one publisher per spreadsheet across hosts; the CLI also locks this host's publisher.
Browser Use can edit research cells during metadata updates, but must not insert/delete/
sort rows while publication runs. Sheets does not provide ASIN compare-and-swap across
a read and later write. Native research tables may need manual range extension after
larger-scope updates; the data schema and ASIN upsert remain independent of table styling.

Official references: [atomic batch updates](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate)
and [quotas/backoff](https://developers.google.com/workspace/sheets/api/limits).

## Browser Use

Exported browser_contract.json is schema version 1: real candidate input, exact
output columns, allowed match statuses and one sample output with the first real ASIN
and UNKNOWN research fields. That sample is not a Walmart observation.
`schemas/walmart_research_v1.json` is portable JSON Schema; Python additionally
validates identity and URLs. Write only Walmart_Research, keyed by ASIN.

Allowed statuses: EXACT_MATCH, POSSIBLE_MATCH, NO_MATCH, NOT_FOUND, REVIEW_REQUIRED.
Keep all seventeen requested columns. Use string UNKNOWN, aware UTC timestamps and
decimal USD strings. Confidence 0–1 describes evidence, not a calibrated probability.
Record actual Walmart evidence URL, seller, fulfillment, availability and shipping;
unknown shipping is never zero. A title or barcode alone cannot prove exact identity.

`validate_observation(row, candidate, identity_review=None)` rejects unreviewed exact
assertions. Until independently reviewed, use POSSIBLE_MATCH or REVIEW_REQUIRED.
For EXACT_MATCH supply a separate saved identity_review object with owner_reviewed=true,
the exact asin, artifact_sha256, matching walmart_url/evidence_url/research_timestamp,
and amazon_size/walmart_size, amazon_variant/walmart_variant,
amazon_condition/walmart_condition pairs. Each pair must explicitly match, known
frozen identity cannot be contradicted, condition must be NEW, and barcode/model/
brand/pack count must match. UNKNOWN dimensions need independently reviewed evidence.
The caller retains and hashes the original artifact; flags alone do not authenticate
a provider response. Research validation grants no eligibility or purchase approval.

## M81–M84 continuation

This branch incorporates latest merged main e209e73 (PR #76, including #75) and
retains the existing M82–M84 implementation. M81 authenticates archived evidence;
M82 requires exact saved Walmart identity and all ten explicit expense inputs;
M83 produces ranked review proposals, executive workbooks and immutable separate
observation history; M84 prepares pinned offline releases and host preflight without
deployment. See the milestone documents for receipt schemas and commands.

Decimal economics includes purchase, shipping, tax, prep, packaging, inbound,
referral, FBA, storage and transaction costs. Gates remain >=50% acquisition ROI
and >=$5 profit, fresh demand, exact identity, account/product FBA and listing
eligibility, authenticity/brand and invoice risk review. Missing fees never become
zero. Passing records are REVIEW_PROPOSAL_ONLY; never PURCHASE_READY.

Browser research does not automatically become an owner-reviewed cost receipt.
WALMART_QUOTE additionally requires availability=IN_STOCK, product_condition=NEW,
and explicitly observed seller and fulfillment; unknown offer context excludes a proposal.
After research, pin original evidence and supply M83 WALMART_QUOTE,
AMAZON_FBA_FEE_ESTIMATE and OWNER_RISK_REVIEW receipts with the authorized M80
ledger to app.decision_pipeline for offline profitability/ranking/executive reports.
The real sheet remains BLOCKED/UNKNOWN with no Top_Opportunities until evidence
passes those gates. Fictional decision demos are separate and never published here.

## Manual recovery

If authentication becomes unavailable, generate the real dry-run CSV. Import into
a temporary tab of the existing pilot with text conversion disabled, verify twenty
distinct ASINs and merge only publisher-owned columns by ASIN. Preserve research_status
and every researcher column. Do not replace the workbook or research tabs. For a new
manual workbook, create the six SCHEMAS tab names and exact headers. Prefer the tested
publisher for subsequent upserts. No historical input is changed by these operations.
