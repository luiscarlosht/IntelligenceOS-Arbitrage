# M88 human-reviewed Walmart intake (offline)

Template: `templates/m88-real-six-pilot.json`. It uses M87's
`walmart_pilot_batch_v1` schema with human review and local evidence fields.
The five IDs in `research_lead` are historical, UNVERIFIED discovery leads only;
no title, price or current product identity is prefilled. The sixth lead is
unspecified. Any six distinct authentic products may be supplied. This is a new
pilot, never a reconstruction of an original six-member cohort.

1. Copy the template into a new private, versioned directory under `var/`.
   Keep the prior M88 directory, reports and Amazon ledger unchanged. Use private
   permissions (`umask 077`) and do not commit completed observations or captures.
2. Visit products manually through an ordinary browser. Do not use automated
   fetching, bypass access blockers or solve access controls for this workflow.
   If the browser cannot show the evidence, leave that row incomplete. Do not
   fabricate a sixth product or import fewer than six.
3. For each selected product, enter its numeric `walmart_item_id` and canonical
   HTTPS `url` (no query/fragment), exact displayed `title`, selected `variation`
   and integer `pack_quantity` for the retail sellable package. Describe an
   observed single/default variant explicitly; never infer it from a search title.
   Record `brand`, `gtin`, `model` and `size` where displayed; otherwise retain
   `UNKNOWN`. These unknowns can block later exact matching.
4. Enter the displayed `seller`, `shipping_availability` including location and
   fulfillment context, and `observed_at` as an ISO timestamp with timezone,
   e.g. `2026-11-05T14:30:00+00:00`. Record the actual time, not this example.
   Enter USD item price in `acquisition.purchase.value` as a decimal string.
   Enter a supported shipping charge in `retailer_shipping.value`, or leave it
   null if unknown. Use `"0"` only when explicitly supported by evidence; do not
   interpret membership offers or conditional free shipping as universal zero.
5. Save screenshots, browser print-to-PDF or a manually written evidence record
   retaining the displayed URL, title, selected variant/pack, price, seller,
   shipping context and observation time. Exclude account/customer information.
   `source_evidence.path` identifies an existing local file relative to the intake
   JSON (absolute paths also work); `sha256` is its `sha256sum` value and
   `description` explains what it supports. `source_reference` is a short capture
   reference. Review the capture against every transcribed field, enter the
   `reviewer` name or alias, then set `human_reviewed: true` on that row.
6. Supply all six rows and run the commands below. Validation is local only and
   verifies schema/attestations/file hashes, not the truth of screenshots. It
   rejects observations older than 24 hours or in the future. Preserve stale
   evidence and collect a new observation rather than changing its timestamp.

From the repository root, use an existing Python 3.12 environment with project
requirements installed. Both output parents must exist; choose new output paths
outside the input directory. Substitute actual paths and digests:

```bash
python -m app.walmart_intake --input var/m88-browser-v1/intake.json \
  --sha256 <intake-json-sha256> --output var/m88-import-v1
sha256sum var/m88-import-v1/m87-batch.json
python -m app.walmart_evidence --input var/m88-import-v1/m87-batch.json \
  --sha256 <m87-batch-sha256> --output var/m88-analysis-v1
```

The first command emits private `m87-batch.json` and `validation.json` using an
exclusive atomic directory publication; invalid inputs publish nothing. The
second runs the existing M87/M86 pipeline and creates `normalized.json`,
`execution-preview.json`, `comparison.json` and `comparison.xlsx`. Run without
`--as-of` for real observations. Inputs and evidence files are never rewritten.
Outputs are directory mode 0700/file mode 0600; overwrites and symlink paths fail.

All Amazon identities, seller eligibility, prices, demand and fees remain unknown.
The importer rejects supplied Amazon evidence to keep this source-only workflow
reviewable. Missing acquisition costs remain missing, never zero. Expect
INSUFFICIENT_DATA assessments, unresolved Amazon matches and
`purchase_authorized=false`. Human review does not confirm an Amazon match.
The existing M87 preview is a proposal with live execution disabled. This intake
makes no network requests, accesses no credentials and neither reads nor resets
any Amazon ledger. A future live scope must preserve the existing cumulative
49-attempt ceiling including authentication/retries and obtain individual network
permissions. No purchases, listings, paid integrations or Sheets writes occur.
