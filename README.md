# IntelligenceOS Arbitrage — Sprint 1 MVP

A working **offline** sourcing-analysis pipeline. It reads a CSV of candidate products, computes net profit and acquisition-cost ROI, screens against 50% ROI / $5 profit and produces a formatted Excel workbook. All bundled inputs are **fictional examples**, not live deals. It does not scrape retailers, call marketplace APIs, send emails or purchase anything.

## Run

```bash
python -m pip install -r requirements.txt
python -m app.pipeline
```

Output: `reports/arbitrage_report.xlsx`.

## Calculations

`net_profit = sale_price - buy_cost - referral_fee - fulfillment_fee - inbound_shipping - other_cost`

`ROI = net_profit / (buy_cost + inbound_shipping + other_cost) × 100`

Values are estimates supplied in the CSV. Eligibility and exact matching must be verified against live, authorized data before purchasing. The `REVIEW` status is not purchase approval.

## Next milestones

1. PostgreSQL job history and audit trail.
2. Authorized product feed / marketplace API integrations, with provenance and freshness timestamps.
3. Scheduling and retry/alert workflow.
4. SMTP or email API delivery with secrets stored outside source control.
5. AI-assisted ambiguous matching and event-driven AgentOps review; human-approved PRs only.
6. Seller-account permissions, fulfillment fees and listing eligibility checks.

No seller credentials or secrets are required for this starter.
