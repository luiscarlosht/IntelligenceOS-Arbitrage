# Keepa pilot — committed preparation, LIVE DISABLED

The pilot implementation was pending in the working tree. It is retained for
review, with both `run_once` and `pilot_product_once` now guarded by the existing
false `LIVE_CALLS_ENABLED` code gate. `--run-once` stops before credential entry,
marker creation or network access. No environment variable can enable this gate.
Do not change it under this milestone. No account entitlement is verified.

Offline preparation only:

```bash
.venv/bin/python -m app.keepa_pilot --asin B002XQ1R06
```

This prints a bounded, secret-free request plan with `actual_requests=0`,
`tokens_consumed=0`, `live_execution_available=false`. It neither loads credentials
nor calls Keepa/Amazon. The dormant pilot supports historical response summaries,
allowlisted output, explicit unknown fees/eligibility, secure terminal-only entry
and a durable no-retry marker if a later reviewed change enables it. Those dormant
behaviors are tested with injected transports only; they are not authorization to
run a live pilot. Historical pricing is never current availability or an assured
resale price. Python memory erasure cannot be guaranteed.

A future live milestone needs verified included entitlement/license, explicit
request authorization, reviewed pricing/token bounds and secure local credential
setup. No new subscription, live test or deployment is part of this work.
See [existing adapter safeguards](KEEPA_PREPARATION.md) and the official
[request documentation](https://keepa.com/api-docs/request-basics.html).
