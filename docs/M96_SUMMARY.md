# M96 offline summary report

Generated from retained evidence on 2026-11-07. The queue has 30 ASINs across 28
brands. Zero ASINs have M79 verified identity; all have no recorded identity
conflict. All seller listing, FBA inbound and Walmart profitability outcomes remain
UNKNOWN. Zero live requests; no execution, listing or purchase authorization.

OXO, 3M and Wera brand observations are seeded; OXO's 200-unit / 180-day invoice
requirement is preserved. Original observation dates and ASINs were not supplied.
See [workflow and limitations](M96_BRAND_FIRST_DISCOVERY.md).

The operational CSV queue, importable screening template, derived registry and
fingerprinted JSON summary are in `var/m96-offline-review/` (untracked runtime
artifacts). Reproduce them using the documented offline command with a new output
directory. The following is the reviewable queue snapshot; it grants no permission.

| Rank | ASIN | Brand | Identity fields | Complexity hint |
|---|---|---|---|---|
| 1 | B008OAE82E | Titan | 9 | LOWER_APPARENT |
| 2 | B00JTSK47S | KINGLAKE | 9 | LOWER_APPARENT |
| 3 | B0188PM1VY | BAGAIL | 9 | LOWER_APPARENT |
| 4 | B072HMFZNF | Meeall | 9 | LOWER_APPARENT |
| 5 | B079MBRNG7 | Ugold | 9 | LOWER_APPARENT |
| 6 | B07B3NDQ86 | samstar | 9 | LOWER_APPARENT |
| 7 | B07B5X75BX | YEQIN | 9 | LOWER_APPARENT |
| 8 | B07D7WSD2G | GOWRAPS | 9 | LOWER_APPARENT |
| 9 | B07F232C3X | Rugged Tools | 9 | LOWER_APPARENT |
| 10 | B07TPRTV6P | joyoldelf | 9 | LOWER_APPARENT |
| 11 | B08211P47L | Qizpcer | 9 | LOWER_APPARENT |
| 12 | B0836LH4X3 | STARTOSTAR | 9 | LOWER_APPARENT |
| 13 | B08KR8B24Y | Ballucci | 9 | LOWER_APPARENT |
| 14 | B08PBFKGJG | Marbrasse | 9 | LOWER_APPARENT |
| 15 | B08V398W68 | Rhino USA | 9 | LOWER_APPARENT |
| 16 | B08WM3TX9K | NEATERIZE | 9 | LOWER_APPARENT |
| 17 | B09VTHZ4PN | GOWRAPS | 9 | LOWER_APPARENT |
| 18 | B0B7MNLBY9 | BAUMFEUER | 9 | LOWER_APPARENT |
| 19 | B0B95R46J7 | QiNZiN | 9 | LOWER_APPARENT |
| 20 | B0BMTKGDZZ | OMGelic | 9 | LOWER_APPARENT |
| 21 | B0CC22PJFX | Leicraft | 9 | LOWER_APPARENT |
| 22 | B0CDCLX412 | The Laundress | 9 | LOWER_APPARENT |
| 23 | B0CGX6W3GZ | SpaceAid | 9 | LOWER_APPARENT |
| 24 | B0CVSSJ7T7 | Carhartt | 9 | LOWER_APPARENT |
| 25 | B0CZS82TC5 | The Beadery | 9 | LOWER_APPARENT |
| 26 | B0D1R92WSZ | Vivihomety | 9 | LOWER_APPARENT |
| 27 | B0DBWL47H7 | Simple Houseware | 9 | LOWER_APPARENT |
| 28 | B0F4D4JDVH | WORKPRO | 9 | LOWER_APPARENT |
| 29 | B0FGHNM4ZR | WELKINLAND | 9 | LOWER_APPARENT |
| 30 | B0FZDYRMFK | Carhartt | 9 | LOWER_APPARENT |

Source fingerprints:

- M79: `1f47efab6e224535a1f58dab6d53df1b254fc0d46c00a803daadd157db28c2b6`
- M69: `48ebfcb6171c9f1669787348638293d2b9df584976d91a67014f8d8b0a4403ea`
- M94: `f30c57240de666e30fbb00c9690c6b1b229717a739ce6380120ec419102b2845`
- registry: `58b0bffeb61221739ac4d73df2c9c901fda507682b765ca77239758baa0d1b20`
- M95_0: `970de295fa69f3e97ccff1e31e5b03f71a4f07ebb19830f91c5bc2fd4030a30d`
- M95_1: `e793defc9cf9fc62a660768471123578edb6353b6dd0ab9a00ef2c0a1ad9f201`

## Offline validation

Python 3.12.3. M95 baseline: 50 passed. Final combined M94/M95/M96
regressions: 76 passed (including 16 M96 tests). Both documented offline
orchestrator sample modes passed with outputs under `/tmp`. Compilation and
`git diff --check` passed.

The full repository run completed with 3,775 passed, 9 skipped and one failure
in 785.58 seconds. That process had imported the initial FBA adapter before its
ASIN regex import was corrected; its sole failure was the resulting AttributeError.
The fresh final combined run above includes the corrected adapter and passes that
case. The full suite was not repeated after the correction or the four additional
M96 tests. No unrelated regression failure was reported.

The branch starts at merged M95 `05c93d141417333065fee2cf4feb7d304816b19a`.
M94/M95 historical evidence and the three pre-existing untracked files were not
modified. No production authorization records were created, and no credentials,
seller identifiers, live Amazon requests, purchases, listings or applications were
used. Further live execution requires explicit user approval.
