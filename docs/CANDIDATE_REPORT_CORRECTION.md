# Candidate-review workbook presentation correction

The completed real Amazon candidate stage saved `is_mock=false`, 21 successful
request observations and ten ambiguous source rows. The workbook nevertheless
inherited MOCK labels because unmatched screening rows defaulted to the mock
provider, and the generic discovery writer added unconditional mock warnings.
API success did not establish product identity or supply economics.

The opt-in candidate-review presentation now separates:

- LIVE eBay search observations via Price API, verified against the original saved
  export (including its hash in each row's provenance and live-page metadata).
- LIVE Amazon catalog observations, based on the saved nonmock search/detail
  records and matching selected ASINs. Mocked stages retain explicit MOCK labels.
- UNKNOWN economics: observed item price and reported shipping do not become
  verified acquisition costs, Amazon sale quotes, fees, profits or ROI.

The new Candidate Comparison sheet preserves all ten input ordinals, including
separate eBay listings that selected the same ASIN. It shows source title/seller,
observed item price, reported shipping, source link, selected candidate ASIN,
Amazon title, match status and concise evidence gaps. It uses wrapped wide title
and gap columns, frozen title/seller columns and header, autofilters, numeric USD
formatting and fixed readable row heights. Source links display the listing path
without tracking parameters; hyperlinks and the existing source/evidence sheets
retain the full supplied URL. Every supplied string is a literal Excel cell.

Unknown shipping stays blank; an explicitly reported zero stays numeric zero.
Verified acquisition costs, sale prices, fees, profits, ROI and rankings remain
blank in the corrected real report. All rows remain REJECT for sourcing; no
candidate becomes purchase-ready. Catalog timestamps/provenance are now shown
without suggesting that an ambiguous candidate is an exact match.

Presentation gaps compare only like, independently supplied structured fields.
Missing source identity, package quantity/contents or variation are unknowns,
not contradictions. A known unequal GTIN, manufacturer, model, retail package
quantity or shared structured variation attribute is explicitly marked CONFLICT.
Component counts and retail package counts are not compared interchangeably.
Title piece counts and inferred brands/variants are never promoted to facts.
Original misleading historical reason strings remain preserved in the original
JSON/workbook, not copied into corrected presentation gaps. The corrected report
is a presentation artifact; it does not rewrite historical SQLite screening or
assert a newly verified product match.

Future candidate-stage persistence uses this presentation mode too. Standard
legacy/discovery/DEMO reporting retains its behavior. A DEMO cannot opt into the
candidate-review mode to conceal mock provenance.

## Rebuild the corrected copy offline

```sh
cd /root/IntelligenceOS-Arbitrage
.venv/bin/python -m app.candidate_review_report \
  --saved-report /root/.intelligenceos-arbitrage-amazon/candidates-cabbbda426bff05faff0b6d8f051e62bde21fa927efafe9fc347e9380ee24f11.json \
  --source-export var/source-imports/20261027224527_ebay_us_6ae1298795263c2adcdb3ac7.json \
  --original-workbook /root/.intelligenceos-arbitrage-amazon/candidates-cabbbda426bff05faff0b6d8f051e62bde21fa927efafe9fc347e9380ee24f11.xlsx \
  --output /root/.intelligenceos-arbitrage-amazon/candidates-cabbbda426bff05faff0b6d8f051e62bde21fa927efafe9fc347e9380ee24f11-corrected.xlsx
```

This command has been run once to create the corrected copy. Existing outputs
and original/input paths are rejected; choose a new output for any later rebuild.
The original workbook SHA-256 remains
`d6a7697436f2766eb776809842dccfcee087b08272d8ba18fa77e6892b495716`.
Input hashes and the original run's status/attempt count appear in Job Execution
Summary. No new API requests, database modifications, credential access, email or
production changes are performed. Existing email helpers still pin the original
workbook; this correction does not alter or authorize email delivery.

Regression coverage includes ten-row rendering, false mock-label removal only
for explicit live evidence, mock/DEMO preservation, source/detail identity/hash
checks, missing versus zero shipping, unknown economics, genuine structured
conflicts, Excel formula safety, source links, no-overwrite outputs and unchanged
original bytes. Runtime workbooks/evidence are excluded from Git.
