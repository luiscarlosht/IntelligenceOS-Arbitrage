# M80 — one-shot Top-20 Amazon sales research pilot

Status: **development and synthetic validation only; live acquisition NOT AUTHORIZED**.
M79/PR #74 found no retained BSR, current offers, Buy Box or positive current seller
permission for the 1,397-ASIN universe. Its Top-20 is an identity-coverage research
queue, not a demand shortlist. M80 freezes exactly those 20 records from an explicitly
reviewed M79 handoff digest. It does not initiate Walmart sourcing or authorize purchases.

No production credential values, live Amazon calls, server deployment, historical
writes, M77 replay, merge, service change or purchase are performed by development.
All demonstration observations are clearly synthetic. PR #74 was merged by the owner;
M80's review PR targets main without merging anything.

## Fixed scope and accounting

Operation: `M80-US-TOP20-SALES-ONCE`. US marketplace `ATVPDKIKX0DER`, condition
`new_new` (pricing `New`), customer `Consumer`. Fixed schedule:

| Slots | Operation | HTTP method/path | Maximum |
|---|---|---|---:|
| 1 | LWA token | POST api.amazon.com/auth/o2/token | 1 |
| 2–21 | Catalog details, one exact ASIN each | GET /catalog/2022-04-01/items/{asin} | 20 |
| 22 | New/Consumer item-offer batch | POST /batches/products/pricing/v0/itemOffers | 1 |
| 23–42 | Seller-specific listing restrictions | GET /listings/2021-08-01/restrictions | 20 |

Forty-two is the **maximum HTTP request count**, including one authentication and one
batch HTTP request containing exactly 20 distinct pricing subrequests. It is not 42
pricing subrequests. Catalog includedData is exactly
`salesRanks,summaries,identifiers,productTypes,classifications,relationships,attributes`.
Pricing members are GET `/products/pricing/v0/items/{asin}/offers` with `MarketplaceId`,
`ItemCondition=New`, `CustomerType=Consumer`. Restrictions bind `asin`, the privately
confirmed seller ID, `marketplaceIds`, and `conditionType=new_new`. The two POSTs are
authentication and read queries, not listing/inventory mutations. No searches, pagination,
substitution, order access, fees, approval applications, purchases or SKU writes exist.

`m80-plan.json` binds the exact ordered allowlist and requests, M79 file digest/targets,
account-file digest, canonical private root, protected evidence roots, current application
source hashes, pacing, budget and deadline. Unknown fields, changed code/targets,
synthetic-marked input, exclusions/conflicts, changed account/source or wrong marketplace
fail closed. No CLI ASIN, endpoint, method, rate, timeout or registry overrides exist.
The transport independently checks frozen definitions and exact URL/method/body/headers.

`preflight` is read-only. It creates no claim, owner permission, token or output. It
checks credential metadata only. `prepare` writes only a new plan. `authorize` writes
only a new M80-specific owner artifact after interactive review. `execute` alone can
acquire live evidence, and requires all of: explicit live flag, exact reviewed plan-file
SHA-256, a separate fresh owner authorization and its file SHA-256, hidden seller-ID
confirmation, exact acknowledgement, current source/account/code checks, absence of
any prior M80 claim/result and the nonblocking shared account lock. Old M77 artifacts
cannot satisfy the M80 schema. Hidden-input fallback is refused.

The owner artifact lasts at most ten minutes. The process has an independent 600-second
monotonic deadline plus Linux signal deadline; token expiry is checked with a five-second
margin and never refreshed. Production credential contents are first read only after
permission checks and the account lock. Their digest must match the reviewed binding.
Bindings and authorization/file contents are checked again before every possible send.
Credentials and tokens remain in memory only, are removed from transport references on
exit, and core dumps are disabled. This is not a promise of secure RAM zeroization.

All participants must use the original canonical private account root and its existing
`candidate-execution.lock`. Do not clone account state or run other account jobs during
the pilot. The trusted operator/root and approved code/runtime remain security assumptions;
the owner artifact is owner-only local authorization, not a digital signature or OS sandbox.

## Durable, no-replay semantics

Only `m80-us-top20-once.sqlite3` is created. M77's registry and historical data are never
opened or changed by M80. SQLite uses FULL synchronous commits, rollback journals,
immutable UPDATE/DELETE triggers, unique attempts/responses and a validated event hash
chain. The claim and parent directory are fsynced before dispatch; each exact sequential
intent is committed **before** any possible send. There are no retries or resume paths.

An intent without a retained reply is uncertain and consumed even if interrupted before
sending. An HTTP/error/malformed reply may be retained as known failure evidence; an
empty uncertain list does not imply success. Only all 42 validated replies can complete.
A partial batch, member non-200, member Retry-After or mismatched echo/ASIN stops before
any restrictions call. Raw sanitized failed-batch evidence is preserved; normalized
pricing is conservatively unavailable if the whole batch cannot be validated.

Any existing ledger—including empty/corrupt files, dangling links or orphan SQLite
sidecars—blocks execution permanently. A claim left by SIGKILL is not replayable.
**Never delete, reset, replace or relocate this ledger to force another M80 run.** A
future attempt needs a separately reviewed operation and authorization contract.
Failures after claim leave evidence for read-only recovery; reports never resume requests.
Matching results are not silently overwritten. No automatic cleanup repairs ownership,
ACLs, credentials, private metadata or historical files.

## Pacing and transport

Local conservative caps: Catalog 1 rps, restrictions 1 rps, pricing batch 0.05 rps.
Only one batch is allowed. Lower observed limits reduce future rates with additional
50% headroom; hints cannot accelerate a cap. Invalid/ambiguous rates, throttles,
Retry-After, non-200 responses or insufficient time stop rather than retry/wait indefinitely.
The shared account must be idle; the operator must review current quotas/cooldowns first.

HTTPS certificate/hostname verification uses the system trust store. Proxy environment
settings, redirects, cookies and SDK refresh/retry machinery are not used. Each HTTP
operation has a ten-second socket timeout. Response bounds are 16 KiB for authentication,
1 MiB for a catalog item, 4 MiB for the offers batch and 128 KiB for restrictions; invalid
JSON, duplicate keys, nonfinite numbers or larger responses stop. At least 512 MiB free
storage is required before claim. HTTP status, safe request IDs/rate metadata, local UTC
observation time and sanitized body SHA-256 are retained. Secrets, seller IDs, owner
artifacts, cookies/authorization and approval links are removed from persisted bodies.
Authentication body/token and even token hashes are never retained.

## Typed evidence and conservative ranking

Frozen dataclasses represent Catalog, Rank, Offers, Price and Restrictions. Adapters
validate exact ASIN, US marketplace, requested condition, positive integer BSR, rank kind
and category ID. Optional metrics stay absent/UNKNOWN. Missing prices/shipping/counts
are never replaced with zero. Landed prices are either explicitly observed or a complete
observed USD listing+shipping sum; currencies are not converted. Explicit zero counts
cannot coexist with positive New prices. Ambiguous count groups cannot become a known
New count. NumberOfOffers and returned details are separate: returned offers may be only
a bounded low-price population, not all sellers. Fulfillment channel `Amazon` means the
fulfillment channel, not proof that Amazon retail is the seller. No unique-seller count
or Amazon-retail presence is invented. Buy Box absence among returned details is UNKNOWN.

Every batch response must correspond once to one exact allowlisted request. Optional
Consumer echo omission is accepted only for the frozen Consumer request; conflicting
customer/marketplace/condition/URI is refused. Internal Retry-After survives redaction.
Restrictions need an explicit array: a successful empty list becomes
`NO_LISTING_RESTRICTIONS_OBSERVED` for that exact seller, marketplace, New condition and
time. A nonempty list is restricted; missing/malformed evidence is never an approval.
FBA eligibility, authenticity, invoices, profitability and purchase permission remain
UNKNOWN/false. No brand-wide or cross-account permission is inferred.

The review report retains identity from M79, current scoped observations, original
sanitized bodies, per-field source slots/times/hashes and account-binding digest.
Observed brand/model/quantity changes or variation parents block review priority.
Missing item classification does not become verified non-parent identity.

Demand comparisons use only matching `(rank kind, exact category ID, marketplace)`
within this selected pilot. Lower BSR is ordered first; known New offer counts break
rank ties, then ASIN provides deterministic ordering. Equal BSR keeps equal demand rank.
Categories are not pooled into a global demand score; selected-pilot rank is not a
market share, percentile or unit-sales estimate. Review priority requires complete pilot
accounting, fresh BSR/restrictions (24 hours), scoped no-restrictions status, known New
count and positive observed landed price (six hours), and no detected identity block.
Optional missing Buy Box data is still explicitly UNKNOWN. These are policy freshness
thresholds for locally observed responses, not guarantees about Amazon's internal updates.

One snapshot cannot establish price stability. Monthly sales, calibration confidence and
price stability remain UNKNOWN. No BSR-to-units constants/model is fitted. Every row,
report and completion has sourcing and purchase permissions false. `review_ready` means
ready for human sales-evidence review, never Walmart sourcing or buying.

## Offline development and demonstration

```sh
.venv/bin/python -m pytest -q tests/test_m80.py tests/test_m79.py
.venv/bin/python -B -m app.m80_demo --output var/m80-synthetic-demo-final
```

Use a fresh output path. The demo installs a process audit hook denying Python socket
and subprocess operations, uses injected fixture transport and a simulated clock, and
opens no production credential or owner files. It accounts for all 42 synthetic slots,
returns 20 synthetic products in two rank groups, two restricted records and one variation
parent. Seventeen records meet synthetic review rules; none permits sourcing or purchases.
Output `m80-results/` contains `M80_report.json`, `M80_evidence.json`,
`M80_sales_review.xlsx`, and hashed `M80_completion.json`. All outputs label synthetic
evidence, including a marker on each product row. No synthetic data is represented as real.

Production and recovery use the same typed adapters and report exporter. Output is private
0700/0600, exclusive, formula-safe and byte-deterministic for the same evidence/as-of. New
reports cannot be written into protected evidence roots or old private subdirectories;
only the designated fresh `m80-results` or an external fresh review directory is allowed.
A directory without completion is incomplete. Audit hooks are defense in depth, not an
OS-enforced network sandbox or protection from malicious same-user/native code.

## Exact first-live-pilot steps — OWNER ONLY, NOT RUN BY DEVELOPMENT

These steps are a runbook, **not current execution authorization**. First review this PR,
its exact code revision, M79's original handoff/completion, exact 20 ASINs, seller binding,
quotas/cooldowns, cost policy and evidence-retention location. Authorize the new 42-request
read-only scope explicitly. Use an approved Linux owner-controlled execution workspace
with Python 3.12 and reviewed dependencies. If code/evidence/account metadata placement
requires DigitalOcean filesystem changes, stop for separate approval; this PR does not
authorize deployment or credential copying. Do not provide credential values in chat.

1. Select the original canonical private account directory outside /mnt, with its existing owner-only
   `credentials.json` and `candidate-execution.lock`; confirm other account jobs are idle.
   Do not clone or relocate account authority to evade an existing claim. Paths below
   are owner-reviewed placeholders, not inferred host locations:

```sh
PRIVATE=/path/to/approved-original-private-account-directory
HANDOFF=/path/to/original/M79_walmart_handoff.json
```

2. Under explicit owner preparation approval, create a **new** 0600 `m80-account.json`
   in that 0700 directory. It must contain exactly:

```json
{
  "schema": 1,
  "operation_id": "M80-US-TOP20-SALES-ONCE",
  "seller_id": "OWNER_CONFIRMED_SELLER_ID",
  "marketplace_id": "ATVPDKIKX0DER",
  "condition": "new_new",
  "credentials_sha256": "ORIGINAL_REVIEWED_CREDENTIAL_FILE_SHA256"
}
```

   The seller/credential digest may be copied locally from the already approved account
   context after review, without reading credential contents during M80 preparation.
   Do not invent them, change credentials, strip ACLs, or silently chmod existing files.
   Extended ACLs, wrong modes/ownership, symlinks or hardlinks on private inputs fail.

3. Take `HANDOFF_SHA256` from the independently reviewed original M79 completion entry
   for the handoff, verify transfer bytes, then prepare an exclusive plan:

```sh
.venv/bin/python -B -m app.m80 prepare --private "$PRIVATE" \
  --handoff "$HANDOFF" --handoff-sha256 "$HANDOFF_SHA256"
```

   Record the printed **plan_file_sha256** as `PLAN_SHA256`; inspect the complete new
   `m80-plan.json`, all 20 ASINs and 42 definitions. No claim, permission or live call is
   created. The plan pins all current app source files, so a later code change requires
   a new review/plan before claim; code must remain fixed during execution.

4. Run and review read-only preflight:

```sh
.venv/bin/python -B -m app.m80 preflight --private "$PRIVATE" --plan-sha256 "$PLAN_SHA256"
```

   Confirm the operator's seller authorization and Product Listing role. Current mappings
   permit Product Listing for Catalog/restrictions and either Product Listing or Pricing
   for this v0 offers batch. Verify granted application access and usage plan before
   approval. No PII/RDT operations are requested. No zero-cost assumption is made.

5. Only after explicit approval, in the owner's interactive local terminal, issue the
   separate fresh authorization. Confirm the seller ID through hidden input, then type
   exactly `AUTHORIZE M80 42 REQUESTS TOP20 NO RETRY NO REPLAY`:

```sh
.venv/bin/python -B -m app.m80 authorize --private "$PRIVATE" \
  --plan-sha256 "$PLAN_SHA256" --review-reference manual:M80-first20 \
  --output "$PRIVATE/m80-owner-authorization-first20.json"
sha256sum "$PRIVATE/m80-owner-authorization-first20.json"
```

   Record the file digest as `AUTH_SHA256`. This still makes **zero requests** and reads
   no credential values. If authorization expires before claim, a fresh interactive
   artifact with a new filename is needed. After any claim there is no M80 restart.

6. On the same approved workspace, within the authorization window, the owner may run
   this **single explicitly approved command**. Do not run it as part of this development:

```sh
.venv/bin/python -B -m app.m80 execute --private "$PRIVATE" --plan-sha256 "$PLAN_SHA256" \
  --authorization "$PRIVATE/m80-owner-authorization-first20.json" \
  --authorization-sha256 "$AUTH_SHA256" --execute-live
```

   Preserve stdout/exit status and private results/ledger. A stop is not permission to
   retry. The maximum is 42 HTTP calls, with 20 pricing subrequests; token expiry or any
   failure can consume fewer. The hard deadline is ten minutes, not a completion promise.

7. For a stopped/interrupted or completed operation, use only read-only evidence recovery
   to a new external report directory. It reads the M80 ledger, never credentials, sends
   nothing and never resumes. Use an explicit aware as-of time:

```sh
.venv/bin/python -B -m app.m80 report --private "$PRIVATE" \
  --as-of YYYY-MM-DDTHH:MM:SSZ --output /path/to/new/m80-owner-review
```

   Retain the original ledger and its checkpoint, source/plan/authorization digests,
   sanitized evidence, runtime/tool revision and report/completion hashes. Review missing
   and stale metrics. Actual source data and report conclusions cannot be claimed until
   this separately authorized acquisition succeeds. Walmart sourcing, longitudinal price
   collection, further pilots, FBA/fee checks and purchases all require separate review.

Official schemas and current scope references:
[Catalog](https://developer-docs.amazon/sp-api/lang-en_US/reference/getcatalogitem),
[offers batch](https://developer-docs.amazon/sp-api/reference/getitemoffersbatch),
[listing restrictions](https://developer-docs.amazon/sp-api/lang-en_en/docs/get-listings-restrictions),
[role mappings](https://developer-docs.amazon/sp-api/docs/role-mappings).
