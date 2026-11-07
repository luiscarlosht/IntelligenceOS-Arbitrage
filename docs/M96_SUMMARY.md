# M96 retail arbitrage summary

Implemented from latest main `05c93d141417333065fee2cf4feb7d304816b19a` on
`milestone/m96-retail-arbitrage-discovery`, verified through connected GitHub.
This supersedes the prior brand-first proposal for the retail-only scope.

## Evidence and limitations

All ten retained M95 live results classify as APPROVAL_REQUIRED using the merged
M95 classifier. They are integrated into a separate derived historical file and
excluded from discovery, alongside M69/M94 tested ASINs and the historical audit.
Original reports, authorization records and pre-existing untracked backups are
preserved. No credentials or seller IDs are used.

The catalog has 1,397 ASINs. The output contains 30 research leads across 28 brands,
with brand cap 2 and category cap 5. Zero selected identities are M79 verified:
the verified-candidate shortfall is 30. No known identity conflicts are admitted.
Low-complexity category allowlisting and risk-term exclusion reduce apparent
complexity but cannot establish safety or regulatory clearance. Seller permission,
FBA eligibility and retail profitability remain UNKNOWN for all selected ASINs.
No defensible listing-ready or profitable retail opportunity is established.

OXO/3M/Wera observations are dated seller-specific evidence, not universal bans;
brand observations lower priority. OXO invoice terms remain restriction evidence
only. There is no wholesale sourcing or approval-application implementation.

Operational outputs are in `var/m96-retail-review-final/`: candidate CSV, screening
CSV, derived registry JSON, classified M95 history JSON and fingerprinted summary
JSON. Runtime reports are untracked under repository policy; this snapshot and
[workflow](M96_BRAND_FIRST_DISCOVERY.md) make them reviewable and reproducible.

## Candidate snapshot

| Rank | ASIN | Brand | Category | Identity |
|---|---|---|---|---|
| 1 | B00JTSK47S | KINGLAKE | Plant Labels | UNVERIFIED |
| 2 | B0188PM1VY | BAGAIL | Laundry Bags | UNVERIFIED |
| 3 | B072HMFZNF | Meeall | Magazine Holders | UNVERIFIED |
| 4 | B079MBRNG7 | Ugold | Plant Labels | UNVERIFIED |
| 5 | B07B3NDQ86 | samstar | Letter Trays & Stacking Supports | UNVERIFIED |
| 6 | B07B5X75BX | YEQIN | Rulers | UNVERIFIED |
| 7 | B07D7WSD2G | GOWRAPS | Luggage Tags | UNVERIFIED |
| 8 | B07F232C3X | Rugged Tools | Tool Bags | UNVERIFIED |
| 9 | B07TPRTV6P | joyoldelf | Drawer Organizers | UNVERIFIED |
| 10 | B08211P47L | Qizpcer | Business Card Holders | UNVERIFIED |
| 11 | B0836LH4X3 | STARTOSTAR | Plant Labels | UNVERIFIED |
| 12 | B08KR8B24Y | Ballucci | Letter Trays & Stacking Supports | UNVERIFIED |
| 13 | B08PBFKGJG | Marbrasse | Letter Trays & Stacking Supports | UNVERIFIED |
| 14 | B08V398W68 | Rhino USA | Tool Bags | UNVERIFIED |
| 15 | B09VTHZ4PN | GOWRAPS | Luggage Tags | UNVERIFIED |
| 16 | B0B7MNLBY9 | BAUMFEUER | Shelf Dividers | UNVERIFIED |
| 17 | B0B95R46J7 | QiNZiN | Laundry Bags | UNVERIFIED |
| 18 | B0BMTKGDZZ | OMGelic | Shelf Dividers | UNVERIFIED |
| 19 | B0CC22PJFX | Leicraft | Business Card Holders | UNVERIFIED |
| 20 | B0CDCLX412 | The Laundress | Laundry Bags | UNVERIFIED |
| 21 | B0CVSSJ7T7 | Carhartt | Tool Bags | UNVERIFIED |
| 22 | B0CZS82TC5 | The Beadery | Storage Boxes & Organizers | UNVERIFIED |
| 23 | B0D1R92WSZ | Vivihomety | Letter Trays & Stacking Supports | UNVERIFIED |
| 24 | B0DBWL47H7 | Simple Houseware | Drawer Organizers | UNVERIFIED |
| 25 | B0FGHNM4ZR | WELKINLAND | Tool Bags | UNVERIFIED |
| 26 | B0FZDYRMFK | Carhartt | Tool Bags | UNVERIFIED |
| 27 | B0054P8UUS | Dritz | Rulers | UNVERIFIED |
| 28 | B016DR1GMO | Clip Strip | Shelf Dividers | UNVERIFIED |
| 29 | B016GU0M4Q | HiMo | Crochet Hooks | UNVERIFIED |
| 30 | B071X6K9D3 | MaxGear | Business Card Holders | UNVERIFIED |

## Input SHA256 fingerprints

- M79: `1f47efab6e224535a1f58dab6d53df1b254fc0d46c00a803daadd157db28c2b6`
- M69: `48ebfcb6171c9f1669787348638293d2b9df584976d91a67014f8d8b0a4403ea`
- M94: `f30c57240de666e30fbb00c9690c6b1b229717a739ce6380120ec419102b2845`
- registry: `b43682ecd2698ee60ce875a2ff1f461b6d41e131e7711a805b3b1da8a6cf0a5e`
- M95_0: `970de295fa69f3e97ccff1e31e5b03f71a4f07ebb19830f91c5bc2fd4030a30d`
- M95_1: `e793defc9cf9fc62a660768471123578edb6353b6dd0ab9a00ef2c0a1ad9f201`

## Offline validation

Baseline focused suite: 66 passed. Final M94/M95/M96 focused suite: 106 passed,
including 46 M96 tests. Both documented offline orchestrator sample modes passed
with workbook/database outputs under `/tmp`. Compilation and diff checks passed.
Full repository regression suite: **3,810 passed, 9 skipped in 802.14 seconds**
(13 minutes 22 seconds), with no failures. The full run used the final implementation.

No live API request, Seller Central submission, purchase, listing, inventory change,
production authorization record, merge or deployment occurred. Stop after offline
implementation and validation; separate explicit approval is required for live work.
