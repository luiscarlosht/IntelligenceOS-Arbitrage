# M76 — Offline Catalog Consolidation and M77 Discovery Planning

M76 consolidates the original validated M73 catalog and completed M75 observation
chain. It provides one deterministic offline CLI, with no network client, credential
loading, live requests, registry writes, executor or authorization generator.
Baseline: merged M75 PR #64, `ad4c5fc6956e6328b9f724ea4b75acddaaa583d3`.

## Validation and preservation

`m76_evidence` reuses `m74_evidence.verify` to validate every original M73 output
and reproduce its in-memory analysis from the original M70/M72/history evidence.
It validates pinned M74 completion, outputs and reconstructed planning report.
`m75_registry.inspect` opens the permanent registry read-only and validates its
immutable schema, full event hash chain, exact request intents, responses and
terminal completion. The required M75 checkpoint is
`27003995ccec549ea0d61e3b9597b24eab39fcba6ffb7e547ac64ed67dfb8454`.
This is the **terminal event-chain SHA-256**, not the SQLite file SHA-256.
The manifest separately binds the raw database file hash.

The original M75 preflight must bind unchanged code, request sequence, baseline,
historical exclusions and M73 evidence. All 21 slots must have responses, all 20
keyword pages must be successful, and no slot may be uncertain. M76 reproduces
the M75 saved pages, M70 source manifest and summary in a new temporary directory
and requires exact hashes before importing the original source with `m70_sources.ingest`.
It verifies zero rejected records and the reviewed M75 quality/count summary.
No existing source, output, checkpoint or registry is updated or replayed.

`m76_analysis` uses existing `m70_identity` normalization and merge contracts.
Exact ASIN equality is the only deduplication key. It fails closed unless baseline
377, M75 distinct-new 400 and union 777 reconcile, including exclusion accounting.
Missing fields remain null; observed alternatives and unresolved conflicts remain
explicit. Each M73 record is also retained verbatim in `historical_m73_record`,
preserving original cohort, per-field evidence, source classes, unsupported values
and flags without assigning aggregate alternatives to invented original sources.
Historical seller checks remain annotations; eligibility is never recalculated.

Inputs and implementation are checked again before the completion manifest is
published. A failed export can leave an incomplete new directory, which has no
completion manifest and must not be treated as completed. Always use a fresh path.
Directories are 0700; files are 0600; symlinks and output paths within historical
input directories are rejected. Excel and CSV strings use existing formula-safe
contracts. Workbook timestamps and ZIP metadata are normalized for byte determinism.
Private reports are ignored by Git and must not be committed.

## Actual consolidated outcome

Two guarded runs produced identical hashes for all 17 files, with sockets/DNS and
credential/owner-artifact reads blocked. Metadata for all 139 protected evidence
entries remained unchanged. Original inputs are hash-checked by the validators.
Actual output: `var/m76-validated/`; independent equal run:
`var/m76-determinism-check/`.

| Metric | Count |
| --- | ---: |
| M73 real ASINs | 377 |
| M75 distinct new real ASINs | 400 |
| Consolidated real ASINs | 777 |
| Remaining to 1,000 | 223 |
| Catalog structurally complete | 111 |
| Fully identity-complete | 0 |
| Unresolved conflict ASINs | 49 |
| Prior unresolved conflict ASINs | 31 |
| Permanent exclusions / in catalog | 97 / 41 |
| Previously seller-checked / in catalog | 40 / 40 |
| Purchase-ready inventory | 0 |

| Missing or conflicted field | ASINs |
| --- | ---: |
| GTIN | 432 |
| Condition | 777 |
| Brand | 1 |
| Model | 210 |
| Pack quantity | 322 |
| Size | 253 |
| Variation | 225 |
| Product type | 197 |
| Title / category | 0 / 0 |

M75's own 76 structurally-complete records and 18 conflict ASINs are reconciled
independently. Real observations do not establish exact identity, selling permission,
profitability or purchase approval. Eligibility and economics remain UNKNOWN.

## M77 proposal

31 unused reviewed phrases remain after fencing all M72/M75 query IDs. Rank by
fewest observed M75 pages in the exact intent label, then original reviewed order
and query ID. Coverage tables retain each M75 query's returned, distinct, duplicate,
overlap and incremental counts. All 20 M75 pages yielded 20 new ASINs each; that
observed yield is descriptive and supplies the full-page capacity assumption.
No future query is claimed to reproduce it. Intent labels are not a harmonized
marketplace taxonomy or evidence of absence from Amazon.

Select the first 23 unused query hypotheses: 460 full-page slots. At an assumed
50% duplicate rate, projected incremental distinct ASINs are 230, exceeding 223 by
seven. At 25%, 50% and 75% duplicates, at least 15, 23 and 45 full pages are needed.
The 75% scenario needs 14 additional reviewed definitions beyond the 31 available.
Sparse pages, rejected records and further overlap can require more work. M77 needs
separate future review, implementation and explicit authorization; this milestone
creates no executor, authorization artifact or inherited request allowance.

## Outputs and SHA-256

JSON includes the complete catalog/report, summary, identity gaps/conflicts,
historical annotations and M77 proposal. Matching CSV tables cover the catalog,
identity gaps, conflicts, annotations, M75 query coverage, M77 ranked queries and
scenarios. `M76_catalog_review.xlsx` includes all tables. The executive Markdown
summary describes the result and planning assumptions.

`M76_evidence_manifest.json` binds original input evidence, all application Python
source hashes, the canonical report digest and every primary output file.
`M76_digest_report.txt` binds that manifest and repeats all primary file digests;
its own SHA-256 is printed by the CLI. No circular/self-hash is claimed.

| File | SHA-256 |
| --- | --- |
| Evidence manifest | `0e8c1840d7f9860c36422baa5d828bfc9d29493bac77d2c80af71daf0b67577b` |
| Digest report | `c4945f0620a6ee3dd5d0e6f47cc522eff03416a8422f411c85a18f347f7691bc` |
| Catalog CSV | `76e1d3bf9c7a463a88dbf1bc86506670d3af00720dad313730a3801d07524782` |
| Workbook | `f13cdc1cbdd7315616bb98c57cc5fc063c41953705afa89c835697d042295920` |
| Complete JSON report | `14547e1c714e2611076e4fc79c0c93d2793da01960f3a0654b98e5ed7ea6fa5d` |
| M77 proposal | `cf722824164e02b2ffeb08ffd479660747b553a687a6eb49403197d999792435` |

## Exact offline command

Run from the repository with its existing private evidence. The example uses a
fresh sibling output; it never overwrites the completed run.

```bash
.venv/bin/python -m app.m76 \
  --m74-dir var/m74-final \
  --m73-dir var/m73-final \
  --m73-digests-sha256 07be04f0c8e96dd6999841beef75a45e5afa3177d931cb0d3323e47df497b773 \
  --baseline-dir var/m70-offline-final \
  --baseline-report-sha256 228c29245ab8898fb4647aa5016b0e86b49ac6546ebef546480a65c941370a56 \
  --proposal var/m71-preparation/M71_manifest.json \
  --private /root/.intelligenceos-arbitrage-amazon \
  --checkpoint 260e03e15b79c77b96430d3416a57fefc65c374421489fe34937d92e41077dd4 \
  --sources /root/.intelligenceos-arbitrage-amazon/m72-catalog-pilot-output/M72_M70_sources.json \
  --summary /root/.intelligenceos-arbitrage-amazon/m72-catalog-pilot-output/M72_summary.json \
  --store var/m66-local/intelligence.sqlite3 \
  --m67-manifest var/m66-expanded-review/M66_review_manifest.json \
  --m67-sha256 8983bef70ce5cfd79d15b7611e4b5646784f37bfce1a88bd220286394303ee55 \
  --output var/m76-next-offline-review
```

`--checkpoint` is the original M72 checkpoint required by the reused M73 verifier;
the M75 terminal checkpoint is pinned independently in `m76_evidence.CHECKPOINT`.
Missing server-only evidence fails closed, without fabrication or relaxed validation.

## Verification

Baseline regression: **2,042 passed**. Targeted M76: **23 passed**. Existing M73/M74
validation: **58 passed**. Both documented sample modes (`app.orchestrator` and
`app.demo`) passed with sockets and DNS blocked.

New tests cover exact reconciliation, duplicate and overlapping ASINs, conflicts
and original provenance, no-overwrite/protected-path behavior, deterministic
Excel/CSV/JSON, evidence-manifest hashes, source drift without publishing a
completion manifest, empty/missing/partial/corrupted registries, corrupted source
hashes and M75 output hashes, bad checkpoint/completion/request accounting,
preflight drift, and rejection before import. Synthetic fixtures are confined to
temporary test directories. Real-output verification used the strict original
validators with credential/owner-artifact reads and network connections blocked.

Final full regression: **2,065 passed in 513.43 seconds**. No merge or deployment
was performed.
