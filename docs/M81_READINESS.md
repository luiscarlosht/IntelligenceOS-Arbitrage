# M81 offline readiness and archived evidence import

Main M80 merge `ea64e1de3156918155c2e570ee0aa80453846eed` was reviewed. PR #75 push run 41623448822 and pull-request run 41623457745 both passed; each ran 2,456 tests. The original M79 handoff contains 1,397 distinct ASINs; its 20-product research scope is an identity-coverage shortlist, not demonstrated demand. No current live observations exist in that handoff. Historical restrictions cannot establish current eligibility.

`app.sales_evidence.readiness(handoff, reviewed_sha256, fresh_output)` checks the pinned original M79 handoff through the M80 source validator and emits an owner checklist. It reads no account context or credential values, authorizes nothing, and must write outside historical evidence. Review the original handoff hash independently; generating a new hash is not independent authentication.

## First live pilot: owner authorization checklist

Follow the exact commands and schema in [M80 pilot](M80_AMAZON_RESEARCH_PILOT.md). Before issuing permission:

1. Review the original M79 handoff SHA, exact twenty ASINs, exclusion checks, account/US marketplace binding and current implementation file pins. Parent ASINs, identity conflicts and permanent exclusions must not enter the scope.
2. Owner confirms Selling Partner permissions: Catalog Items read access, Product Pricing read access, Listings Restrictions read access, supported US marketplace and seller identity. Confirm provider quotas and retention/security approval without disclosing credentials in chat. No new paid integration is authorized.
3. Inspect the generated plan offline: exactly 42 maximum HTTP attempts: one token request, twenty Catalog Items calls, one batch offers call (twenty members), twenty Listings Restrictions calls. There are no automatic retries. Provider rate/cooldown limits can stop the pilot early; a failed or uncertain request consumes its claim.
4. Review fresh canonical account metadata, local private workspace, request/response retention and exact paths. Generate a fresh interactive owner permission using the M80 command; the permission binds account, source, plan, code, nonce and expiry. A checklist or merged PR does not grant live permission.
5. Separately authorize the first live execution explicitly. No DigitalOcean modifications are part of that authorization. Execute once under the reviewed code. Never delete/reset the claim database, replay M77 or resume an ambiguous request.
6. Pin the completed original ledger SHA for read-only downstream import. Preserve failed/partial evidence too; incomplete or stale data produces UNKNOWN or exclusion, never invented sales.

## Changes and invariants

Live M80 validation still requires the current exact implementation map. Historical import accepts a recorded well-formed implementation map, validates plan semantics, journal chain and response bodies, and requires an independently reviewed original ledger SHA. This distinguishes archived code provenance from permission to execute old code. Historical mode is available only on read-only inspection/reporting, never live authorization or execution. The journal does not cryptographically prove an Amazon signature; its trust root remains the owner-reviewed local acquisition and file digest.

Duplicate HTTP control headers now fail before interpreting rate limits. Catalog adapters retain checksum-valid GTINs and variation parent links. Conflicting current GTINs exclude review readiness. Listing permission remains distinct from FBA permission and purchasing.

Offline publication uses a new private directory, no-replace rename, explicit input pins and no credential paths. Python audit guards reject sockets/processes and writes outside owned output; this is application defense, not an OS security boundary against native code or a malicious same-user process. Deployment requires separate kernel isolation and approval.

Remaining blockers: owner approval for live acquisition, exact account/role/quota review, fresh signed permission and actual current observations. Deployment and purchases remain unauthorized. Synthetic reports cannot clear those blockers.
