# M85 Amazon evidence population

Based on main `67e7273` (PR84). The owner verified twenty original ASINs,
twenty BLOCKED decisions, zero populated evaluation records, and twenty-two
proposed **analysis** operations. This milestone does not claim a new live read.
It adds a complete gap view over PR82–84, without changing their schemas,
profit calculation, thresholds or publishers. No Amazon/Keepa transport exists
in this module. A manual assertion is auditable input, not independent verification.

## Work order and manual input

1. Run the gap report for all twenty ASINs. Screen each ASIN in Seller Central
   under the intended seller account, US marketplace and New condition first.
   Record restrictions and exact approval/document requirements. An invoice
   requirement is not satisfied by a retail receipt unless actually accepted.
2. Research exact Amazon/retailer GTIN, brand, model, size, package and variation
   only after eligibility is confirmed. Independently verify FBA permission.
3. Transcribe observed New prices, supported monthly demand and New-only offer
   counts. Rank is descriptive only. A mixed Used/New offer count is unusable
   for New competition. Missing monthly sales remains UNKNOWN.
4. For each FBA/FBM conservative/base/optimistic price, enter Revenue Calculator
   referral/fulfillment estimates with exact ASIN, mode, New condition and matching
   nested price_basis observation. Enter all acquisition and selling costs per
   complete matched unit. Explicit supported zero is allowed; blank is UNKNOWN.

Copy [the complete input template](../sample_data/amazon_evidence_manual_template.json)
privately and replace only fields backed by actual evidence. It contains one
original ASIN; repeat for others. Missing original ASINs appear automatically in
the report with all gaps. Duplicate and outside-cohort ASINs fail.
The [restriction example](../sample_data/amazon_evidence_manual_example.json) is
illustrative, deliberately incomplete and blocked. Never treat its dates or
seller alias as an actual observation. Do not commit completed private evidence.

The format is existing PR82 JSON with additive observation metadata. Every
observation, including eligibility, identity sides and nested fee price_basis,
requires `source`, `source_reference` (private saved screenshot/calculator/reference
identifier), aware `observed_at`, `confidence` HIGH/MEDIUM/LOW, `verified: true`,
`seller_alias`, `marketplace: ATVPDKIKX0DER`, and `condition: New`. Identity also
requires the existing product fields. Seller aliases avoid storing account IDs.
`verified` means the operator checked the transcription against that reference;
it does not prove provider truth or authorization. Preserve permission records
privately. Never include tokens, cookies or credentials.

The review clock defaults to UTC now. Observations expire under the existing
24-hour policy; identity also uses its existing freshness validator. Missing,
unverified, wrong-seller, wrong-condition and stale observations become UNKNOWN
before evaluation. The report retains the exact original evidence, its SHA256 and
validation issue paths separately. Explicit approval/restriction blocks survive
staleness. Reports therefore contain private source references: keep them private.
Historical source timestamps must never be replaced with the transcription time.

Optional [manual Keepa template](../sample_data/amazon_evidence_keepa_template.json)
uses the existing market-only adapter. No subscription is required. Enter only
observations the owner already has permission to use, retaining the New price
series and export timestamp. Rank does not supply monthly_sales. New offers need
`basis: new_offer_count`; monthly demand needs `authorized_sales`,
`bought_past_month_lower_bound`, or `validated_estimate` with an independent
`model_validation_reference`. Unavailable values stay UNKNOWN. Conflicting market
patches fail rather than replacing an observation.

## Read-only outputs and separate proposals

```bash
.venv/bin/python -m app.amazon_evidence_population --seller-alias OWNER_ALIAS --output /tmp/m85-empty-gaps.json
.venv/bin/python -m app.amazon_evidence_population --input /private/manual.json --seller-alias OWNER_ALIAS --output /tmp/m85-manual-gaps.json
.venv/bin/python -m app.amazon_evidence_population --input /private/manual.json --keepa-manual /private/keepa.json --seller-alias OWNER_ALIAS --output /tmp/m85-keepa-gaps.json
```

Each report has twenty per-ASIN gap groups: eligibility, documentation, exact
identity, New price, demand, New offers, fees and acquisition. All six financial
scenarios are checked independently even while eligibility blocks. Coverage counts
mean observations usable in that group, not profitability approval. Financial
group coverage requires both modes and all scenarios; the existing decision engine
can qualify a single complete mode. `populated_records` counts records containing
fields beyond ASIN, including incomplete records; it is not verified coverage.
An empty-cohort run yields 20 BLOCKED, 20 eligibility-first actions, zero coverage
in all eight groups and no publication requests. Reports use exclusive mode0600
output and never overwrite evidence. No history database is opened.

A different command produces **Amazon_Evaluation seed proposals** only:

```bash
ARBITRAGE_SHEETS_CREDENTIAL_FILE=/root/.config/intelligenceos-sheets/service-account.json .venv/bin/python -m app.amazon_evidence_population --input /private/manual.json --seller-alias OWNER_ALIAS --evaluation-proposal --output /tmp/m85-evaluation-proposal.json
```

It opens the existing read-only client and reuses PR82's sparse seed planner,
headers and literal cell helpers. It proposes only explicitly submitted rows,
never twenty fabricated observations. Invalid values are sanitized before proposed
seeding; exact originals and validation issues remain in `manual_import_audit`.
Existing evaluation rows are skipped entirely, including their custom columns.
Review skipped ASINs separately: this tool cannot fill gaps in existing rows.
The proposal includes input/snapshot hashes and is deliberately **not accepted**
by the analysis publisher. It grants no write permission and has no execution
option. Any approved future seed/update execution must freshly revalidate source,
destination, timestamps, cell/batch limits, approval and readback using the
existing controls. Do not replay a saved requests array against Sheets.

Computed Amazon_Analysis previews remain the separate PR84 command:
`.venv/bin/python -m app.analysis --sheets --sheets-preview --output /tmp/m85-analysis-preview.json`.
That preview reads workbook evidence, not local proposed imports, so zero existing
evidence still yields twenty BLOCKED decisions. No `--approved` or publication
command is part of M85 verification.

## Migration and preservation assessment

No migration, tab creation, evidence copying, publishing, queue edit, API call,
purchase or deployment occurs on merge or report generation. The fixed cohort
comes from PR84's queue reader on `--sheets`; queue cells never become evaluation
facts. All Intake tabs and historical workbooks/ledgers remain untouched.
Research Pilot evidence is not automatically copied. Review seller, permissions,
condition, exact identity, original dates and destination conflicts before any
separately approved migration. Preserve original bytes and references; copying
never refreshes an observation. Existing PR82/83 workflows remain available;
the stricter M85 intake validation applies when using this module.

## Exact DigitalOcean verification

After a separately authorized installation of the reviewed commit, these commands
read the existing checkout and workbook. They perform no deployment and no remote
workbook writes. Local private report files are the only outputs. Do not repair
credentials or change sharing as part of these checks. No VM command was executed
by this implementation task.

```bash
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && git log -1 --oneline && git status --short'
ssh root@137.184.180.155 'set -eu
cd /root/IntelligenceOS-Arbitrage
umask 077
verification_dir=$(mktemp -d /tmp/arbitrage-m85.XXXXXX)
export ARBITRAGE_SHEETS_CREDENTIAL_FILE=/root/.config/intelligenceos-sheets/service-account.json
.venv/bin/python -m app.amazon_evidence_population --sheets --seller-alias OWNER_ALIAS --output "$verification_dir/gaps.json"
.venv/bin/python -m app.analysis --sheets --sheets-preview --output "$verification_dir/analysis-preview.json"
.venv/bin/python -c '\''import json,sys; from app.amazon_research_queue import ORIGINAL_ASINS; g=json.load(open(sys.argv[1])); p=json.load(open(sys.argv[2])); assert g["schema"]=="amazon_evidence_gaps_v1"; assert len(g["records"])==20; assert {r["asin"] for r in g["records"]}==set(ORIGINAL_ASINS); assert not g["requests"]; assert not g["purchase_authorized"]; assert p["schema"]=="analysis_publication_preview_v2"; assert len(p["reports"])==20; print(g["coverage"]); print("analysis proposed operations:",len(p["requests"]))'\'' "$verification_dir/gaps.json" "$verification_dir/analysis-preview.json"
printf "Private verification artifacts: %s\n" "$verification_dir"'
```

Replace OWNER_ALIAS with the intended private alias before running. Until real
attributed evidence exists, expect twenty BLOCKED, zero populated records, and
zero complete groups. Twenty-two analysis operations are expected only while the
analysis tab is absent and the source state still matches the owner's baseline;
existing destination changes affect that count. Inspect every ASIN's validation
issues and gaps, not just counts. Authorization/schema failures stop without
fallback or writes.

Offline checks: `python -m pytest -q`, `python -m app.orchestrator`, and
`ARBITRAGE_MODE=discovery ARBITRAGE_REPORT=var/discovery.xlsx python -m app.orchestrator`.
