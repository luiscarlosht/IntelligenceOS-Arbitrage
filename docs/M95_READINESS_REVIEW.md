# M95 offline readiness review — 2026-11-07

Branch: `milestone/m95-eligibility-discovery`. No live request, production credentials access,
production claim, purchase, listing, inventory change or deployment was performed.

## M94 historical-audit failure

The original `test_exact_manifest_validates_offline` failed at its call to
`m94.validate(...)` (original test line 19), before its assertions. The unchanged
production guard at `ops/m94_restrictions.py:47` compares the reviewed
`historical_audit_sha256` with `audit_digest(historical)` and raises
`ValueError('Historical audit changed; re-review required')` when unequal.

Read-only diagnostics of the preserved operator evidence:

| Audit view | SHA-256 |
| --- | --- |
| Reviewed M94 audit | `a6660d4298818626edafa6a2fa5acd382f78e6621032f22fa8cd40965a4f4340` |
| Current reader | `feee9d1156ff138e8e902ae6dbd02f062aa066e7802ce1b57db8fd541bf33456` |
| Only M95 patterns removed, in memory | `feee9d1156ff138e8e902ae6dbd02f062aa066e7802ce1b57db8fd541bf33456` |
| Older committed reader, which omits M94 files | `a6660d4298818626edafa6a2fa5acd382f78e6621032f22fa8cd40965a4f4340` |

There are zero M95 production evidence files. The difference from the older reader
is exactly two M94 files: `m94-eligibility-8004c4bba07fa40b0636324424b0b5cf8b65498fb7305fe4b4945b443ddc9598-01.json`
(SHA-256 `f30c57240de666e30fbb00c9690c6b1b229717a739ce6380120ec419102b2845`)
and `m94-eligibility-authorization-01.json`
(SHA-256 `dab2053ec25297f8a2ce1a35064841a6d9acede2a10cdb6e1e3265fb2b3b4502`).
They add the five executed M94 ASINs to exclusions: B000255NH8, B0002AR73G,
B00061SL0Y, B000AQSCE0 and B000NP2SBG. Removing only those entries and ASINs from
an in-memory diagnostic projection recovers the reviewed digest exactly. That
projection was never used for validation or written back.

M94 reader support was already an unstaged change before M95 started. The previous
session reproduced this failure before implementing M95. Comparing only with Git
HEAD would misattribute that existing change to M95. Adding M95 discovery changes
the audit when M95 evidence exists, but did not cause this failure.

The validator correctly rejects the completed proposal. The test incorrectly
expected a pre-execution proposal to remain valid after execution. Its happy path
now uses synthetic source files, a private temporary history and a matching
synthetic reviewed fingerprint. Real hashing, audit, cohort, request and exclusion
checks remain enabled. A separate test adds a synthetic permanent claim and asserts
the exact historical-drift rejection. Two tests distinguish absent M95 evidence
from actual new M95 evidence. No historical evidence, production fingerprint,
completed eligibility result or production integrity check was changed.

## Official Amazon semantics and state separation

Reviewed Amazon's [official use-case guide](https://github.com/amzn/selling-partner-api-docs/blob/main/guides/en-US/use-case-guides/listings-restrictions-api-use-case-guide/listings-restrictions-api-use-case-guide_2021-08-01.md)
and [official OpenAPI model](https://github.com/amzn/selling-partner-api-models/blob/main/models/listings-restrictions-api-model/listingsRestrictions_2021-08-01.json).
`getListingsRestrictions` requires ASIN, sellerId and marketplaceIds; conditionType
filters the applicable restrictions and `new_new` means New. An explicit empty
array means no restrictions for the requested condition/marketplace. An omitted
or null array is invalid. Restrictions may omit conditionType; such rows still
apply and are not ignored. Wrong-marketplace/condition responses fail validation.

| State | Interpretation |
| --- | --- |
| APPROVAL_REQUIRED | Approval is needed before listing; a path-forward link may allow removal of the restriction. Approval is not already granted. |
| NOT_ELIGIBLE | Cannot create the listing; the API documents no path-forward link to remove this restriction. This is not a permanent forecast. |
| OTHER_RESTRICTED | Other nonempty restriction rows, including unknown codes and ASIN_NOT_FOUND (ASIN absent in that marketplace). |
| NO_RESTRICTIONS_REPORTED | Explicit valid empty array in the requested seller/marketplace/New scope. |
| UNRESTRICTED_VERIFIED | Reserved for independent exact seller/ASIN/marketplace/New permission and validated provenance/parser semantics. Conservative-v1 never emits it, even for an injected true boolean. |
| UNKNOWN | Missing, malformed, failed, interrupted or unattempted evidence. |

NOT_ELIGIBLE takes precedence if both negative codes appear. The new classifier
also returns UNKNOWN for malformed envelopes or typed fields. Historical M94
classifications remain unchanged. No state authorizes purchases/listings or proves
FBA eligibility, product identity or Walmart profitability.

The guide describes using an absence-of-restrictions result before creating an
offer-only listing. That supports treating it as a useful discovery lead. The
OpenAPI shape has no separate affirmative listing_permission field: the legacy
parser derives a boolean from the array. Keeping that separate from independently
verified permission is this pilot's conservative policy, not a claim that Amazon
requires a second API operation or that an empty array is meaningless.

## Early stopping decision

No rule change. Threshold remains one successful parsed response with zero rows
and affirmative permission. Tests cover actual empty arrays continuing, restricted
and malformed responses continuing, and a synthetic affirmative parser stopping
after authentication plus one check. The latter is a future-parser contract test,
not evidence of a real affirmative API field.

Stopping at the first valid NO_RESTRICTIONS_REPORTED result would be reasonable for
finding one research lead: it saves requests but sacrifices cohort coverage and
does not meet the original independent-permission goal. It requires explicit review
of the changed goal/stop reason and regression tests; it must not promote the
classification. The existing rule is retained, so conservative-v1 may use all 11
requests even when it receives empty arrays.

## Complete Git and reproducibility review

The exact intended commit scope, including existing untracked dependencies:

```text
app/amazon_candidate_enrichment.py
app/m63_history.py
docs/ARCHITECTURE.md
docs/ROADMAP.md
docs/M95_ELIGIBILITY_DISCOVERY.md
docs/M95_READINESS_REVIEW.md
ops/m94_restrictions.py
ops/m95_diversified_queue.py
ops/m95_eligibility.py
ops/m95_manifest.py
ops/m95_restrictions.py
tests/conftest.py
tests/fixtures/m94_reviewed_proposal.json
tests/fixtures/m95_reviewed_proposal.json
tests/test_m94_restrictions.py
tests/test_m95_execution.py
tests/test_m95_restrictions.py
```

The M94 adapter is unchanged but must be included because it was already untracked.
M95 imports it and the untracked manifest/eligibility modules; omitting them breaks
a fresh checkout. Reviewed proposal fixtures contain no secrets or grants and retain
the original reviewed SHA-256 values. Tests copy them to temporary paths and isolate
historical-source discovery. M95 defaults now resolve its path at call time to
support that isolation; normal production paths/digests remain unchanged.

Preserve but exclude the existing `m94_offline_queue.py` (older standalone generator
with top-level side effects), `m94_offline_queue.py.pre-m94-fix` and
`ops/m95_manifest.py.bak` (backups). None is imported by M95. Do not use `git add .`.
Credentials, private reports/claims, environment files, databases, generated
workbooks, caches and ignored `var/` files are not commit inputs. Runtime validation
still intentionally requires the reviewed proposal and preserved operator histories;
a reproducible test checkout is not permission to fabricate those histories.

## Final validation and readiness

Python 3.12.3, command `.venv/bin/python -m pytest -q`:
**3,764 passed, 9 skipped, zero failures in 775.58 seconds (12:55)**.
The full output is retained locally at `/tmp/m95-review-full-pytest.txt`.
The M94/M95/shared-engine focused command passed **85 tests**. The same 85 tests
passed in `/tmp/m95-reproducible-checkout`, assembled from tracked files plus the
exact commit scope above, without `.git`, `.venv`, ignored `var/`, backups or
operator evidence. It uses the existing interpreter/dependencies, not copied
production data. Both documented sample modes passed with output/database paths
in `/tmp`. Exact reviewed M95 offline validation, `git diff --check`, and a
reverse dry-run check of the complete review patch passed.

The reviewed M94 report and authorization fingerprints were checked again and are
unchanged. Production M95 report/claim count remains zero. No files were staged,
committed, published or deployed. A complete review patch (including the untracked
commit inputs) is at `/tmp/m95-reviewed-working-tree.patch`.

Offline code/test commit readiness: ready, provided all 17 intended files are
included and the three unrelated generator/backup files are excluded. This review
changed 12 paths relative to the prior M95 work: the two M95 adapter/classifier
modules, three M94/M95 test modules, conftest, two proposal fixtures, and four docs
(this review, the execution guide, ARCHITECTURE and ROADMAP). The other five commit
inputs are existing engine/history changes and unchanged untracked dependencies.

Live business-goal readiness remains limited: conservative-v1 cannot independently
verify unrestricted permission or stop on an actual empty array. A separately
reviewed independent-evidence policy or a narrower research-lead stopping goal is
needed to change that. Any live pilot also requires separate explicit authorization
and preserved operator evidence; passing tests is not live or purchase approval.
