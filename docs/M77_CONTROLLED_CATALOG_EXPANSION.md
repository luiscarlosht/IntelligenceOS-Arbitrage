# M77 — Controlled Catalog Discovery Expansion

M77 adds a separate, manual, one-shot executor on M76 merge `3bff577`.
Development, tests and sample runs are offline. No live authorization is generated
and no Amazon or authentication requests are made during implementation.

The reviewed baseline is 777 distinct real observed ASINs, with 223 remaining to
1,000. Discovery cannot guarantee 223 new ASINs. Maximum capacity is 620 raw
observations; duplicates, sparse pages, exclusions and rejected records reduce yield.

## Reviewed definitions and correction to M76 rationale

All 31 ranked definitions q020–q050 were individually reviewed against the original
proposal and frozen in [the request manifest](M77_REQUEST_MANIFEST.json). M77 uses
all 31, extending the proposal's hypothetical 23-query selection through a new,
separately authorized scope. No old request allowance or authorization carries over.

The immutable M76 rationale says “Unobserved M75 intent first.” **Every one of these
31 candidates has one observed M75 page under its exact intent label**, and 20
observed incremental M75 ASINs in that label. Consequently their ordering follows
original review order, q020 through q050. The candidates are unused phrases;
their intent labels are not unobserved intents. Labels are not a harmonized taxonomy
or evidence of marketplace absence. Historical M76 reports and their rationale
strings are preserved exactly. The earlier 20-new-ASIN/page yield is descriptive,
not a prediction of M77 yield.

## Pinned evidence and preflight

The original M76 evidence manifest must hash to
`0e8c1840d7f9860c36422baa5d828bfc9d29493bac77d2c80af71daf0b67577b`;
its M77 proposal must hash to
`cf722824164e02b2ffeb08ffd479660747b553a687a6eb49403197d999792435`.
M75's terminal event-chain checkpoint is
`27003995ccec549ea0d61e3b9597b24eab39fcba6ffb7e547ac64ed67dfb8454`.
A checkpoint is not the SQLite file digest.

Preflight validates the exact original M76 output inventory, every output digest,
digest report and all original implementation hashes. Additional M77 modules are
separately bound by the current implementation map. It reuses the original M76
validator for the complete M73/M74/M75 chain: original reports, M70/M72 sources,
history, exclusions, account binding, immutable registry, completed 21-slot request
accounting, all 20 pages and exact M75 export reproduction. It reconstructs M76
in memory and requires the exact original report, source coverage and proposal.
Missing evidence, unknown request accounting, partial completion or drift blocks.

Preflight reads credential **metadata** and existing account-context evidence only;
credential content verification is deferred until fresh authorization has passed.
It creates no registry, reservation, authorization or network request. Review output
and recovery paths must be outside all historical evidence directories.

## Exact offline dry-run

Run from the repository using its private original evidence and a fresh output
filename. The wrapper installs a process-wide audit hook rejecting socket events,
credential-value reads and owner-authorization artifact reads. It accepts only
`dry-run` options. This command is safe to run for review and is not authorization.

```bash
.venv/bin/python -m ops.m77_offline \
  --m76-dir var/m76-validated \
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
  --output var/m77-dry-run.json
```

`--checkpoint` binds the original M72 operation; M75's checkpoint is independently
pinned. Do not replace original paths with regenerated or invented evidence.
The preflight contains the exact current implementation map and its canonical
SHA-256, evidence map/digest, account binding, request definitions and budget.
See [validation and implementation hashes](M77_SAFETY_AUDIT.md).

## Future owner authorization contract

This milestone does not authorize execution. A future owner must review a fresh
preflight in a local interactive terminal. `app.m77 authorize` takes the same
evidence options plus `--reviewed-preflight`, its exact file `--preflight-sha256`,
`--review-reference manual:<reference>` and a fresh private
`--output /root/.intelligenceos-arbitrage-amazon/m77-owner-authorization-<reference>.json`.
It verifies current/reviewed preflight equality, requires hidden seller-ID confirmation
without terminal fallback, then the exact acknowledgement:
`AUTHORIZE M77 32 REQUESTS NO REPLAY`.

The resulting M77-only artifact binds the exact code map, preflight, evidence,
account, marketplace, M76 manifest/proposal, request-definition hash and budget.
Its validity is at most ten minutes. M72/M75 artifacts cannot authorize M77.
`app.m77 execute` requires all original evidence options, the new artifact path,
its exact `--authorization-sha256` and explicit `--execute-live`. No CLI default
executes, authorizes or creates the artifact. Help/import does not load the executor.
Do not run authorize or execute as part of development or validation.

## Runtime controls and permanent failure semantics

The fixed scope is one LWA POST followed by exactly 31 US Catalog Items GET
first pages, in reviewed order, with `pageSize=20` and the frozen includedData.
The manifest enumerates every endpoint and parameter. There is no pagination,
substitution, retry, refresh, resume, other endpoint or ASIN reservation. A short
or empty valid page consumes its sole slot. Cursors are retained as redacted
partial-window evidence and never dispatched.

Execution uses the existing global `candidate-execution.lock` with exclusive
nonblocking flock, validates all bindings again under lock, and only then reads
credential values. Their content digest must match the original account binding;
metadata equality cannot conceal content drift. Core dumps are disabled. The new
permanent registry is `m77-catalog-discovery.sqlite3`, distinct from M72/M75.
Exclusive creation and directory fsync precede use. SQLite FULL synchronous commits
durably record each sequential request intent before dispatch. Immutable-table
triggers and the event hash chain reject mutation, duplicate attempts/responses,
out-of-order slots and false completion. Every accounted-but-unanswered slot is
uncertain and remains consumed.

Before dispatch, execution rechecks authorization validity/file digest, code,
account, evidence, credential contents and registry binding. It uses conservative
frozen pacing, saved cooldowns and lower observed rates. Throttles, Retry-After,
non-200 replies, malformed pages and transport errors stop permanently; there is
no retry. Verified TLS, no proxy/redirects, ten-second socket bounds and bounded
responses reuse the reviewed transport primitive. A 180-second process alarm and
monotonic checks bound the operation; deadline exhaustion may stop before all
31 pages. Authentication expiry never triggers refresh. Signals and errors preserve
partial evidence. SIGKILL can leave an incomplete or uncertain registry.

**Any existing M77 registry, including an empty/corrupt file, permanently blocks
execution. Never delete, reset, replace or resume it.** Read-only recovery can
explain a valid partial journal; an unreadable/corrupt journal blocks recovery
and requires evidence preservation and investigation. A future discovery attempt
would require a different reviewed milestone and authorization contract.

## Private output and recovery contract

Normal execution exports into the new owner-only private directory
`m77-catalog-expansion-output`; directories are 0700 and files 0600. Historical
sources, registries, checkpoints and M76 catalog records are never rewritten.

| File | Contract |
| --- | --- |
| `M77_catalog_pages.json` | Saved cleaned observed products, exact query/slot/marketplace provenance, response and definition digests, timestamps, first-page and cursor coverage |
| `M77_M70_sources.json` | Existing schema-1 `amazon_catalog_pages` adapter, relative page path, exact page SHA-256 and explicit permission reference; consumable by M70/M76-style consolidation |
| `M77_summary.json` | Completion/no-replay status, consumed and uncertain slots, page and raw counts, overlap against original 777-ASIN M76 baseline, exclusions, quality/conflicts and checkpoint |
| `M77_output_digests.json` | Exact SHA-256 inventory of the three primary outputs |

Only explicit observed ASINs and attributes are retained. Existing identity merge
contracts preserve conflicting observed alternatives and original field provenance.
An output does not replace the M76 catalog or resolve its conflicts. Missing
attributes remain missing; seller eligibility, retailer matching, pricing, fees
and economics remain UNKNOWN or disabled. Purchase authorization is false.
No credentials, tokens, raw error messages or authorization contents are exported.

For read-only recovery use `app.m77 report` with the same evidence options and a
fresh `--output` directory outside historical evidence. It validates the complete
original chain and exact journal preflight binding, reads no credential values or
owner artifacts, and exports already journaled responses. It never sends, claims,
resumes or modifies the registry. Unanswered responses cannot be reconstructed.
Recovery exports partial pages and uncertain slots without declaring success.
