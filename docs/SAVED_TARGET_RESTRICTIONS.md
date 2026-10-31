# Source-bound saved-target restriction screening

`ops.saved_target_restrictions` reuses `amazon_candidate_enrichment._execute`,
its Listings Restrictions parser, exclusive private report reservations, durable
pre-HTTP checkpoints, private seller entry and shared OperationPacer/cooldowns.
It is opt-in and never registered in orchestration, Sheets or browser workflows.

Legacy schema1 manifests retain the original one-to-ten distinct-brand policy.
Reviewed schema2 manifests support one to twenty unique US/New ASINs and stop
immediately after three successfully parsed no-restriction results. Failures,
invalid responses and approvals never count toward this goal. Remaining targets
stay in the persisted report as `not_attempted`, with the stop reason. No report
or reservation is deleted, released, retried or automatically resumed. Same-manifest
replay fails before seller prompting or credential access. A new manifest requires
explicit review, including prior attempts and reservations; do not rename outputs
to bypass a previous uncertain run.

One authentication plus at most one restriction check per target: maximum21 HTTP
attempts, no retries/redirects/pagination. Pricing, fees, catalog and retailer calls
are excluded. Authentication failure stops; individual restriction failures are
preserved while subsequent distinct checks may proceed within the request/deadline
limits. Shared quota cooldowns or the120-second deadline may leave fewer completed
checks. Reports checkpoint all selected target rows before prompting or HTTP.

Schema2 requires a hash-bound identity review for the exact ordered ASIN records.
Original target JSON is retained without field rewrites. Review records explain
product/pack support and preserve missing fields. Missing catalog brand fields may
use an explicitly sourced title/manufacturer label. Ambiguous identifier groups and
critical conflicting fields are rejected. Package-hierarchy or missing-theme warnings
require explicit review; they are not equivalent to a contradictory identity. Only
same-source arrays of included components/material may be reviewed as multi-values;
all values remain in the manifest, never pick a convenient value. No retailer exact
match, missing accessory, pack splitting or eligibility is inferred from this review.

Source target bytes, identity review, prior restriction evidence and named original
catalog/code files are hash-bound. `validate` performs read-only offline validation;
`run` additionally requires `--execute`. No credentials are needed for preparation.
At future execution the operator confirms the intended account using the existing
hidden prompt; the nonsecret account reference does not independently prove continuity.
Returned approval messages, reasons and links are retained without following them.
Listing permission is scoped to the checked account/ASIN/US/New and observation time;
FBA eligibility and sourcing-document acceptability remain separate and unknown.

Reports use the existing private Amazon directory:
`saved-target-restrictions-MANIFEST_SHA256-01.json`. This does not import target DBs,
change Sheets, alter the active browser or overwrite earlier reports. In a goal stop,
aggregate status is `stopped_listing_permission_goal`. Otherwise shared enrichment
status may be `partial` because pricing/fees deliberately remain `not_requested`.
The CLI prints individual restriction outcomes and the exact no-restriction ASINs.
A goal stop is a successful bounded run even though later targets remain unattempted;
failures still remain explicit in those earlier results.

Runtime manifests/reports stay private under ignored `var/`. Future SSH commands
require the exact reviewed code/evidence bytes already on that host; drift fails
before credentials. Preparation performs no deployment or live provider calls.

Offline tests inject synthetic transport/credentials into temporary private storage.
They cover1/4/10/20-target ceilings, all-restricted21-attempt exhaustion, early stop,
retained unattempted rows, failed/malformed checks, approval instructions/links,
unknown FBA/document eligibility, source/manifest/review drift and duplicate refusal.
