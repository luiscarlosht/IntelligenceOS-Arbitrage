# Canonical Amazon operational workbook

The analysis pipeline now uses Intake workbook
`1q9TPwNTka_wzSo_T283LBP7iFpfAorR3_QYB19LKDHA` for
`Amazon_Research_Queue`, `Amazon_Evaluation` and `Amazon_Analysis`.
`SheetsEvidence` reads the original 20 queue identities in queue order and joins
attributed evaluation JSON by ASIN. Queue research columns never supply prices,
costs, fees, eligibility, market freshness or product verification. Missing
evaluation rows become ASIN-only blocked records. Evaluation rows outside the
queue are preserved but excluded from this pipeline.

Missing queue, malformed headers, missing/replaced/duplicate cohort ASINs and
Google authorization failures stop the run. There is no fallback to Research
Pilot. A missing evaluation tab is treated as absent evidence; a missing analysis
tab is represented only as an addSheet proposal in the saved preview. Preview
uses read-only OAuth scope and the transport rejects any write payload on a
read-only client. Metadata GET is exactly `/v4/spreadsheets/{id}?fields=...`,
without `/values` or a trailing slash before the query.

## Compatibility and migration risks before publication

No data migration occurs on merge. Existing Intake tabs, records, queue research,
custom columns and history are untouched. The old queue transfer CLI retains its
explicit Research Pilot source for compatibility; it is not invoked by analysis.
Do not run that legacy publication command as part of verification.

The cohort remains deliberately fixed to the original 20 ASINs. Expanding it is
a separate schema/policy change. Existing evaluation headers must match the
publisher schema; manual_evidence_json must contain normalized attributed evidence
with an ASIN matching its row. Visible eligibility/approval conflicts still block.
Evidence in Research Pilot is not copied automatically and may be missing in
Intake. Any later evidence migration needs owner review of provenance, seller,
condition, exact package/variation, timestamps and conflicting destination rows;
copying a record does not refresh it. Do not replace populated researcher rows.

Saved analysis previews are now schema v2 and bind the full queue/evaluation
snapshot as well as metadata and analysis cells. Old v1 previews must be
regenerated. Retain previous previews, published results and optional append-only
analysis history; do not migrate or replace historical SQLite ledgers. Existing
analysis history support and conservative evaluation gates are unchanged.

Tab creation/evidence seeding requires a separately reviewed and explicitly
approved publication step. This PR authorizes none. A preview can contain proposed
requests, but generating it performs no writes. Publication still requires owner
approval (`--approved`, also enforced by the publication function), a fresh
15-minute preview, source/output revalidation, current evidence-freshness checks,
and exact readback. Concurrent edits can still race after revalidation because
Sheets has no arbitrary-cell compare-and-swap; use one writer and pause editing
for a separately approved publication. Preserve the approved preview and exclusive
output result as audit artifacts. No automatic retry or rollback is safe after an
ambiguous write/readback failure.

## Exact DigitalOcean read-only verification after merge

These commands do not deploy. Run only after a separately authorized release has
installed the merged code in the existing checkout. They reuse the existing
credential file without displaying or modifying it. Do not add `--approved` or
`--publish-preview`. The output directory is private and unique; Sheets remains
read-only. No Amazon/Keepa calls are made.

```bash
ssh root@137.184.180.155 'cd /root/IntelligenceOS-Arbitrage && git log -1 --oneline && git status --short'
ssh root@137.184.180.155 'set -eu
cd /root/IntelligenceOS-Arbitrage
umask 077
verification_dir=$(mktemp -d /tmp/arbitrage-workbook-verification.XXXXXX)
export ARBITRAGE_SHEETS_CREDENTIAL_FILE=/root/.config/intelligenceos-sheets/service-account.json
.venv/bin/python -m app.analysis --sheets --sheets-preview --output "$verification_dir/preview.json"
.venv/bin/python -c '\''import json,sys; from app.amazon_research_queue import ORIGINAL_ASINS; from app.sheets_intake import SPREADSHEET; p=json.load(open(sys.argv[1])); assert p["schema"]=="analysis_publication_preview_v2"; assert p["workbook"]==SPREADSHEET; assert len(p["reports"])==20; assert {r["asin"] for r in p["reports"]}==set(ORIGINAL_ASINS); print("workbook:",p["workbook"]); print("ASINs:",len(p["reports"])); print("source snapshot:",p["source_sha256"]); print("decisions:",[(r["asin"],r["decision"]) for r in p["reports"]]); print("proposed requests only:",len(p["requests"]))'\'' "$verification_dir/preview.json"
printf "Saved read-only preview: %s/preview.json\n" "$verification_dir"'
```

Authorization failures stop without fallback, credential repair or writes. Check
existing service-account sharing through the owner outside this change. Review
missing evidence and proposed tab creation before considering any publication.
This task performed no live workbook inspection or writes; current tab/data state
and VM access must be verified with the commands above.
