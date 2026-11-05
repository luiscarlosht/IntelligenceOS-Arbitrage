# M90 read-only SP-API validation preparation

Prepared from reviewed M89 `6a09b7a503906fa3fd96eae1ea9472d15859865f`.
Development and testing only. Zero live Amazon HTTP requests, zero LWA attempts,
no deployment, no purchases. `purchase_authorized=false`.

## Exact proposed request

```http
GET /catalog/2022-04-01/items/B001BE12BA?marketplaceIds=ATVPDKIKX0DER&includedData=summaries HTTP/1.1
Host: sellingpartnerapi-na.amazon.com
x-amz-access-token: <in-memory seller-authorized LWA access token>
User-Agent: IntelligenceOS-Arbitrage/M90
Accept: application/json
Accept-Encoding: identity
```

No body, sellerId query, pagination, authentication, refresh, follow-up, fees,
pricing, restrictions, listings, inventory, orders or commerce operations.
US marketplace `ATVPDKIKX0DER` is proposed; operator must confirm this account's
US participation rather than infer it from the ASIN or successful LWA response.

Sources checked 2026-11-05:

- [getCatalogItem reference](https://developer-docs.amazon/sp-api/reference/getcatalogitem):
  Catalog Items v2022-04-01 GET, required ASIN and marketplaceIds; explicitly
  select summaries instead of requesting unnecessary datasets.
- [Official OpenAPI model](https://github.com/amzn/selling-partner-api-models/blob/main/models/catalog-items-api-model/catalogItems_2022-04-01.json):
  success is an Item object, not a payload wrapper: `asin`, optional datasets
  including `summaries` (ItemSummaries array of ItemSummaryByMarketplace objects, with
  marketplaceId required and itemName optional in the Amazon schema).
  M90 conservatively requires matching ASIN, exactly one US summary, and a
  nonempty itemName. Additional fields are ignored. Missing summary is a charged
  validation failure, not proof of seller eligibility or catalog absence.
  Error responses use an errors array with code/message/optional details; M90
  rejects every non-200 without persisting untrusted error bodies.
- [Catalog roles](https://developer-docs.amazon/sp-api/docs/catalog-items-api):
  Product Listing is required. Developer profile approval, that role on the
  application, and authorization of that application by this seller must be
  confirmed. A role name that permits writes does not authorize this executor
  to perform writes. No restricted data token is proposed for catalog summaries.
- [Amazon signing announcement](https://developer-docs.amazon/sp-api/lang-ja_JP/changelog/sp-api-will-no-longer-require-aws-iam-or-aws-signature-version-4):
  SP-API has not required AWS IAM or SigV4 since October 2, 2023. Use the LWA
  access-token header; do not add AWS credentials or signing machinery.

A 200 establishes only success for this operation at that time. LWA authentication
alone establishes neither Product Listing permission nor seller eligibility.
401/403 remain possible; 429/5xx must consume the attempt without retry.

## Continuation and safety contract

The sole authoritative ledger remains
`/var/lib/intelligenceos-arbitrage/m89/ledger.json`. Never transfer the older local
12-attempt ledger over it. M90 development did not inspect or modify the host.
The supplied authoritative state is 13/49 used, 36 remaining, successful M89
LWA attempt 13; its exact production SHA-256 has **not** been supplied or verified.

Under the ledger lock, M90 checks the complete pinned file hash, cumulative schema,
all numbered attempts, successful attempt 13's authentication operation, token
receipt boolean, timezone-aware ordered timestamps and M89 no-replay claim. It
reconstructs the entire preceding 12-attempt document and compares its canonical
hash against reviewed M89's `b7502888a36b97594e5c79b3f8c47312c1226d80355a03621284660b45da2f1b`.
This pins every historical field, including the charged attempt-12 failure; it
never substitutes a synthetic history. If serialization or metadata differs,
stop for review rather than weakening validation or repairing history.

Execution holds the existing shared `candidate-execution.lock` and M89's
`ledger.lock` through reservation, send and completion. Operator must identify
the actual shared account lock path; creating a different same-named lock does
not coordinate existing executors. Quiesce every older executor on all machines.
All Amazon operations must use the same sole ledger and locks.

Before dispatch, atomic replacement plus file and parent-directory fsync appends
attempt 14, status RESERVED, phase catalog_read_only, ASIN B001BE12BA, operation
m90-one-get, baseline digest and timestamp. Count becomes **14/49, 35 remaining**.
No historical entries are removed or rewritten. Completion sets COMPLETE and
persists only a fixed, redacted structural result. Errors, timeouts, interrupts
and uncertain outcomes remain charged (FAILED); SIGKILL can leave RESERVED.
There is no retry, refund, repair, reset or resume command. Any post-dispatch
storage failure requires manual audit while retaining the reserved charge.

One direct HTTPS connection uses trusted TLS and hostname verification, no proxy,
no redirect handling, no automatic retry, 10-second socket timeout and a 20-second
absolute SIGALRM deadline. Response reads stop at 262145 bytes; more than 262144
is rejected. Exact method and URL are allowlisted before connection. No response
strings, credentials, access tokens, token hashes or exception strings are saved.
Core dumps are disabled before credential reads. Use a dedicated manual process
without an existing alarm or thread-based invocation.

## Token and seller prerequisites — unresolved blockers

M89 discarded attempt 13's token, and its ledger has no recoverable token.
The protected source `/etc/intelligenceos-arbitrage/m89/live.env` contains client
ID, client secret, refresh token and PURCHASE_AUTHORIZED=false. M90 reuses its
existing strict parser/security checks; it never authenticates with these values,
changes that source, or copies its secrets. Preflight does not read credentials.
A refresh token is **not** a valid SP-API access token.

A fresh access token for the same app/seller must already be available through
a separately reviewed trusted in-memory broker, passed in an inherited pipe FD
>=3, ASCII 1–2048 bytes, no newline. No token in shell arguments, environment,
files, reports, logs or chat. M90 contains no such broker. Do not run LWA to
satisfy this prerequisite under the present authorization. If no usable token
exists, a new scope must authorize and account for authentication, changing the
expected attempt numbering; that requires a new review, not a workaround.

Operator must supply a protected 0600, service-owned JSON context file in a
0700 directory, outside the release, with actual verified values:
`seller_id` (not yet supplied), `marketplace_id` = ATVPDKIKX0DER,
`product_listing_role_confirmed`, `application_authorized_for_seller`,
`us_marketplace_participation_confirmed`, `token_matches_protected_source`
(all true only with supporting account evidence), and `token_expires_at`
(timezone-aware ISO timestamp, at least 60 seconds in the future). These are
operator attestations, not remote permission verification; no values have been
invented or populated by development. Confirm the app identity and token/seller
binding in the trusted broker. Context contains no token or secret.

## Safe DigitalOcean procedure — later, after review

1. Review and approve the M90 commit and exact GET scope separately from staging.
   Verify the established SSH host key, application user, Python 3.12, CA trust,
   clock, outbound HTTPS and disk capacity. No host checks were performed here.
2. Quiesce all manual Amazon executors. Read the protected production ledger's
   metadata/hash using the trusted operator session; review the full 13-attempt
   history without exposing secrets. Securely retain an audit copy. Do not restore,
   copy over, truncate, reinitialize, or relocate the authoritative ledger.
3. Stage a hash-verified `git archive` of the reviewed M90 commit into a NEW
   `/opt/intelligenceos-arbitrage/releases/<M90_COMMIT>` directory and create a
   separate venv with reviewed pinned requirements. Run `pip check` and offline
   regressions. Installation/import has no execution hook. Do not change `/current`,
   old release files, systemd units/timers, firewall, M89 configuration or services.
4. As the existing application user, run only M90's offline preflight from the
   new release. It validates the ledger under lock, opens no sockets, reads no
   credentials, and reserves no attempt. Do not use M89's network preflight.

```bash
.venv/bin/python -B -m app.m90 preflight \
  --ledger /var/lib/intelligenceos-arbitrage/m89/ledger.json \
  --ledger-sha256 "$REVIEWED_M89_13_SHA256"
```

5. Resolve token, seller context and shared lock prerequisites. Disable shell
   tracing, core dumps and credential logging. Obtain explicit owner approval
   naming commit, ledger hash, account, ASIN, US marketplace and exactly attempt
   14, with no LWA authentication. Installation/preflight approval is insufficient.
6. Only then, from the trusted broker's service-user child process with token
   already written to inherited anonymous pipe FD 3, the proposed single-request
   command is below. Variables are paths/digests only. This is deliberately a
   conditional command, not a working token-generation recipe.

```bash
.venv/bin/python -B -m app.m90 execute \
  --ledger /var/lib/intelligenceos-arbitrage/m89/ledger.json \
  --ledger-sha256 "$REVIEWED_M89_13_SHA256" \
  --env-file /etc/intelligenceos-arbitrage/m89/live.env \
  --account-lock "$EXISTING_AMAZON_PRIVATE_ROOT/candidate-execution.lock" \
  --seller-context "$PROTECTED_M90_CONTEXT" --token-fd 3 \
  --approval APPROVE_M90_ONE_GET_ATTEMPT_14
```

7. Inspect the authoritative ledger once and securely archive its new hash and
   record. Count must be 14/49 even on rejection, timeout or uncertainty. No rerun.
   Roll back code only if needed; retain all newest ledger history. No services or
   timers are activated. Any unexpected state is a stop-and-review condition.

## Remaining risks and validation limits

- Production ledger/hash, seller ID, app identity/role consent, US participation,
  real shared lock path, fresh token/broker and token expiry/binding are unverified.
- Protected-source validation checks shape/security, not remote validity.
- Local locks do not protect copied ledgers on other hosts; sole-writer custody
  and prohibition on restoring old backups remain operational requirements.
- A privileged operator can bypass code, forge attestations or roll back state;
  file hashes are review bindings, not external signatures or monotonic storage.
- A hard kill or disk failure can leave a charged uncertain reservation. Never
  infer that a request was not dispatched from lack of a completion record.
- Real connectivity, Amazon permissions, response content and rate limits have
  not been tested. Catalog success provides no profitability, fee, selling
  eligibility, inventory or purchase authorization evidence.

Offline tests use synthetic ledgers and mocked HTTP. The synthetic baseline hash
is injected only in tests; the production constant remains M89's reviewed hash.
Tests cover success, 401/403/429/5xx, redirects, timeouts, catchable and uncatchable
crashes, replay, history corruption, malformed/oversized responses, reservation
failure, approval gate, bounded token pipe, and fixed transport method/path.

## Local preparation evidence

- Python 3.12.3; `pip check` passed.
- Focused final regression: 55 passed (35 M90 tests plus 20 M89 tests),
  using `/tmp/arbitrage-ci-fix-py312/bin/python -m pytest -q tests/test_m90.py
  tests/test_m89_deployment.py tests/test_m89_continue.py tests/test_m89.py`.
- Both README sample workflows passed: default `app.orchestrator` and discovery
  mode (`ARBITRAGE_MODE=discovery`). Outputs remain ignored runtime artifacts.
- Read-only inspection confirmed the local historical ledger is 12/49:
  11 COMPLETE, 1 FAILED. Its raw and canonical hashes both match reviewed M89's
  baseline. This confirms the reconstruction encoding, not production state.
- Production's 13-attempt ledger was not accessed. No production credentials
  were read. No remote host, service, timer, symlink or deployed file was changed.
- Full baseline regression, started before adding M90 tests: **2,982 passed,
  9 skipped in 732.70 seconds**, using `python -m pytest -q` in the same Python
  3.12 environment. M90 adds 35 independently passing tests; the focused 55-test
  run also rechecks 20 M89 tests against the final implementation.
- `git diff --check` passed. No live or DigitalOcean validation is implied.
