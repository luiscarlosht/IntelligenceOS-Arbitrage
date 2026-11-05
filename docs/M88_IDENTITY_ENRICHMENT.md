# M88 offline identity comparison and Browser Use handoff

`app.m88_identity` consumes the original M88 plan, six-source manifest and
hash-bound normalized search receipts. It validates the completed original
operation (1 authentication + 6 searches, 7/49) and verifies each receipt against
the cumulative ledger. It never imports or invokes the executor's execute path,
reads credentials, requests vendor data, changes a ledger or rewrites source
observations. Existing exact-match/purchasing gates are unchanged.

```bash
python -m app.m88_identity --plan <original-operation>/plan.json \
  --plan-sha256 <reviewed-original-plan-sha256> --output <fresh-output-directory>
```

Source/code hashes on an archived live plan do not authorize another live run.
This command needs the original plan's byte digest and completed receipt hashes,
not a currently executable live plan. Code changes must not force a replay merely
to analyze saved evidence. It publishes exclusive private 0700/0600 artifacts:

- `identity-gap-report.json`: all 60 source/candidate comparisons, original values,
  valid/invalid typed barcode evidence, source gaps, Amazon missing fields and
  mapping issues, retained-field coverage and research priority explanations.
- `browser-use-request.json`: common collection rules and six prioritized requests.
- `browser-use-checklist.md`: copy-ready ordinary-browser handoff with original URLs.

Every output pins the inputs; hashes are rechecked before publication. Offline
network/process/credential-access guards cover the comparison and publication.
Duplicate source mappings, ledger/receipt drift and overwrites fail closed. The
original ledger is read, never reset or updated; no lock file is created.

## Evidence semantics

Candidate brand/model/size/variation/packageQuantity and typed identifiers are
usable *Amazon-side observations*. Every saved UPC/EAN/GTIN is checked for its type,
length and checksum, while preserving the original identifier. Equivalent EAN/UPC
forms collapse only in a separate canonical-set field. Multiple different GTINs
remain alternatives, never an arbitrarily selected first identifier. They do not
become Walmart barcodes or establish retail-pack equivalence.

The executor retained normalized receipts, not raw responses. Manufacturer,
manufacturer part number and structured product/package dimensions were not
retained. It cannot now be established whether they appeared in the raw HTTP
response. Saved model numbers must not be relabeled as manufacturer part numbers.
Size strings containing measurements are preserved as strings, not converted into
new structured physical dimension evidence.

The source importer recorded some counts of package contents, while Amazon
packageQuantity often describes one retail package. An 8-cell pack and an Amazon
packageQuantity of 1 are not directly comparable quantities. The comparator keeps
both original values, exposes the unverified source pack basis, and extracts
*textual clues* for human review only. It does not normalize contents into sellable
packs. Textual measure/unit differences, count/sheets conflicts, multipacks,
product-family terms and brand clues lower research priority; even these warnings
are not independently verified product facts. No physical unit conversion is
inferred. Displayed ounces versus fluid ounces still need basis confirmation.

Priority is a transparent heuristic: source-title/brand clue, shared title terms,
explicit count/measure clues and penalties for conflicting text. It is not match
confidence, probability, profitability or evidence sufficient to confirm identity.
Only the highest-ranked unconflicted textual lead is highlighted for each source;
all alternatives and warnings remain in JSON. The top conflicting candidates are
listed separately for diagnostic review. All `verified_exact_match` values remain
false. No source fields, fees, sale quotes, match decisions or eligibility are
upgraded by this phase.

## Findings from the authentic saved M88 receipts

- Elmer's 17011265: B000Q3KHCM is the strongest textual lead; model E304 and 4 Oz.
  are retained, but multiple canonical barcode alternatives, incomplete variation
  themes and package hierarchy remain unresolved. Walmart brand/model/barcode/
  size/selected formulation and pack review are missing. Purple glue and multipack
  alternatives must not be silently equated with the source.
- Duracell 13952053139: B003SI0TD4 is the strongest textual lead. Its brand,
  8-count size/style and barcode observations can support later comparison.
  Walmart needs its own retail-pack barcode, actual model/MPN, AA chemistry/line,
  selected variant and cell-versus-pack count evidence. The saved Amazon model
  field `1` is not a confirmed manufacturer part number.
- Gorilla 721324153: B07GQ1CT47 is the strongest textual lead; model 4572502,
  5.75 Fl Oz and Bottle 1 Pack are retained with ambiguous barcode alternatives
  and package hierarchy. Walmart formulation, bottle count, barcode, model,
  selected size/variant and net-content units need independent evidence.
- Post-it 37481849: no compatible lead established. Returned cohorts include
  different pad counts, a 50-sheet/pack-of-2 alternative, regular versus Super
  Sticky and other sizes. Confirm the supplied 3 x 3 / 4-pad / 90-sheet description
  against actual screenshots; never change it to fit a candidate.
- Scotch 47070933: no compatible lead established. Transparent 3/6/12/24-roll
  alternatives and Magic/invisible 4-roll tape are distinct textual candidates.
  Capture exact tape family/finish, roll count, core/refill packaging, dimensions,
  barcode and manufacturer part number.
- Pen + Gear 711088244: no compatible brand lead in this first page. Similar
  tape sizes from Scotch, Amazon Basics and other brands are not substitutions.
  Capture the Pen + Gear brand/model/barcode and selected 4-roll configuration
  independently; leave an absent Amazon pairing unresolved.

All search cohorts remain partial first pages. This phase does not expand them.
All six sources lack independently reviewed identifiers and selected-variant
identity; zero exact matches remain the correct result. The Browser Use handoff
requires field-level screenshots/excerpts, timestamps, reviewer attestation,
Sacramento CA 95829 context, explicit UNKNOWNs and preservation of previous prices.
No browser run or message to Browser Use is initiated by this module.
