# PR: Prepare Arbitrage send-only Gmail API delivery over HTTPS

Gmail report delivery can now be selected explicitly with
ARBITRAGE_EMAIL_TRANSPORT=gmail_api. Existing SMTP behavior remains the default.
The adapter sends the existing MIME XLSX attachment using only gmail.send,
refreshes credentials over verified HTTPS, refuses redirects, and suppresses
provider exceptions and payloads. No automatic send retry or SMTP fallback occurs.

A separate local-browser authorization helper requests offline consent with
state/PKCE protection and writes owner-only credentials. It never sends email.
The runbook documents Google Cloud setup, consent/verification requirements,
secure transfer, refresh/revocation behavior and Testing's seven-day token limit.

Validation: 305 tests passed locally, including mocked attachment submission,
refresh/rotation, consent, broad-scope rejection, file permissions and redacted
tracebacks. Legacy and discovery sample runs passed with a cleared environment
and no recipients. CI and live authorization/delivery have not been run.

Risks/remaining acceptance: owner consent, production publishing requirements,
service-user filesystem permissions and live sending remain operator actions.
Unix permissions protect stored credentials; application encryption is not used.
A submission timeout has an unknown delivery outcome and needs manual review.
Existing local SMTP diagnostic/demo work is excluded. No production schedule,
service deployment, paid service or unrelated project access is included.

Base intended: main. Head: milestone/gmail-api-adapter. Draft PR; do not merge or
deploy as part of preparation. Git push failed due to DNS, and the GitHub connector
could not locate the existing local parent commit. Publish the branch from a
network-enabled checkout before opening the PR; review its complete diff against
main because it also descends from the prior SMTP diagnostic milestone.

```bash
git push -u origin milestone/gmail-api-adapter
gh pr create --draft --base main --head milestone/gmail-api-adapter \
  --title "Prepare Arbitrage send-only Gmail API delivery over HTTPS" \
  --body-file docs/GMAIL_API_PR.md
```
