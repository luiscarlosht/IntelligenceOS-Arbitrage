# Corrected candidate-review email: separate interactive SSH attempt

The separately authorized helper is
`ops/gmail_corrected_candidate_review_ssh_once.py`. It does not import or invoke
the earlier candidate-review helper. It pins the corrected workbook, not the
original, to SHA-256:

`23138171a64294d9e3353a5cfecd32d303030ca181ff59dbc8cbd0fac396dd47`

Offline verification checks the saved successful real 21-request report, all ten
Candidate Comparison rows against their saved eBay/Amazon evidence, LIVE source
and catalog summary labels, zero false MOCK labels, zero exact matches, ten
ambiguous candidates, unknown economics and missing versus explicit-zero shipping.
No credentials are read by `--check`; no network operation is performed.

The sole recipient is `luiscarloshernandez@hotmail.com`. The exact subject is
“Corrected — eBay/Amazon proof-of-concept candidate review.” The message summarizes
10 ambiguous candidates, zero confirmed matches and profitability unknown, and
explicitly says it is not a purchase recommendation. Its sole attachment is the
verified corrected workbook as `Corrected-eBay-Amazon-Candidate-Review.xlsx`.
No private configuration or credentials are attached or included in the body.

Fresh, owner-only, exclusive attempt records use:

- `var/diagnostics/gmail-ebay-candidate-review-corrected-ssh-1.attempted`
- `var/diagnostics/gmail-ebay-candidate-review-corrected-ssh-1.stages.jsonl`
- `var/diagnostics/gmail-ebay-candidate-review-corrected-ssh-1.outcome.json`

Previous original/corrected reports, helpers and all previous attempt records
remain unchanged. Existing fresh-attempt records block reuse. At most one OAuth
refresh and one Gmail submission use the existing Gmail API integration; there
are no retries, SMTP fallback or schedule changes. Acceptance is not proof of
inbox delivery. An uncertain submission must not be automatically repeated.
The 90-second whole-command and existing 30-second socket timeouts remain.

Run exactly this in your direct interactive SSH terminal, not through Codex:

```sh
env PYTHONPATH=/root/IntelligenceOS-Arbitrage \
  /root/IntelligenceOS-Arbitrage/.venv/bin/python \
  /root/IntelligenceOS-Arbitrage/ops/gmail_corrected_candidate_review_ssh_once.py --send
```

`--send` requires an interactive terminal and has not been executed in preparation.
To verify offline instead, replace `--send` with `--check`; this reserves nothing
and leaves all send records untouched. The explicit PYTHONPATH permits direct
script imports from any current directory.
