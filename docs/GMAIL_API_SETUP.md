# Arbitrage Gmail API adapter — prepared, not enabled

This adapter is confined to IntelligenceOS-Arbitrage. SMTP remains the default
for existing hosts. No schedules, systemd units or production environment files
are changed by this milestone. No authorization or email has been performed.
The Gmail App Password is only an SMTP credential and cannot authenticate Gmail
API requests. Do not copy it, inspect shell profiles, or reuse another project's
credentials. Use a dedicated Arbitrage OAuth client and token file.

## Google Cloud and consent setup (owner action)

1. In Google Cloud Console, select/create a dedicated Arbitrage project, then
   APIs & Services → Library → Gmail API → Enable. This task does not purchase
   services or enable an API on your behalf.
2. In Google Auth Platform configure Branding (app name, support email and
   developer contact), Audience and Data Access. For a personal Gmail account
   choose External and add the sending account as a test user while Testing.
   Internal is available only to eligible Google Workspace organizations;
   Workspace administrators may additionally need to trust the client.
3. Request exactly `https://www.googleapis.com/auth/gmail.send`.
   It permits sending with attachments without reading mail, drafts or labels.
   Do not request `mail.google.com`, gmail.modify, gmail.compose, profile or
   additional scopes. Gmail send is a **sensitive**, not restricted, scope.
4. Clients → Create client → Desktop app, named Arbitrage local authorization.
   Download its JSON on your trusted workstation. Never upload it to chat,
   commit it, paste token responses or use OAuth Playground/shared clients.
5. The owner must review the consent screen and authorize the intended sending
   Gmail account. Set EMAIL_FROM to that account; aliases require separate Gmail
   send-as configuration and are not configured by this adapter.

External Testing authorizations and refresh tokens expire after **seven days**
for gmail.send. This makes Testing unsuitable for unattended long-term operation.
For unattended use, resolve the appropriate production publishing/verification
requirements, then perform fresh consent. Moving to Production is not a promise
of permanent tokens. Public external apps requesting sensitive scopes generally
require Google verification; personal-use/testing and internal exceptions may
apply but can retain warnings/user limits. Follow Google's console requirements;
do not bypass consent warnings or organizational policy. No paid Workspace
subscription is necessary just to use a personal Gmail account.

## Exact secure authorization steps (not executed)

Run on a trusted workstation with a local browser, Python 3.12, and this checkout.
Use a location outside the repository. The helper binds only 127.0.0.1 on an
ephemeral port, uses library OAuth state/PKCE protection, requests offline access
and explicit consent, and does not print authorization URLs or tokens. Do not
use a remote VM browser callback or deprecated out-of-band copy/paste flow.

```bash
umask 077
install -d -m 700 "$HOME/.config/arbitrage-gmail"
# Move the downloaded Desktop client JSON here using your local file manager:
# ~/.config/arbitrage-gmail/client.json
chmod 600 "$HOME/.config/arbitrage-gmail/client.json"
python3.12 -m venv .venv-gmail-auth
.venv-gmail-auth/bin/python -m pip install -r requirements-gmail-auth.txt
.venv-gmail-auth/bin/python -m ops.gmail_authorize \
  --client-file "$HOME/.config/arbitrage-gmail/client.json" \
  --token-file "$HOME/.config/arbitrage-gmail/token.json"
```

Choose the intended sender in the browser and approve only sending mail. This
command performs consent and writes tokens; **it never sends a message**. Existing
token destinations are refused; use a new private filename for reauthorization.
An App Password is never requested. Do not run with HTTP/OAuth debug logging.

For a later separately authorized deployment, transfer only token.json using
SCP/SFTP with verified host keys to a dedicated private directory owned by the
Arbitrage service user. Set directory mode 0700 and file mode 0600; exclude it
from Git, reports, general backups, diagnostics and shared home directories.
Storage is protected by Unix ownership/permissions, not application encryption;
use encrypted host storage/backups where needed. The runtime rejects symlink,
nonregular, foreign-owned and group/world-readable credential files. The directory
must be private for token rotation. Use a trusted directory path without symlink
ancestors. Do not put secrets into environment variables or command arguments.

Only after separate deployment/send approval, configure the Arbitrage service:

```text
ARBITRAGE_EMAIL_TRANSPORT=gmail_api
ARBITRAGE_GMAIL_TOKEN_FILE=/private/arbitrage-gmail/token.json
EMAIL_FROM=your-authorized-sender@gmail.com
EMAIL_TO=your-approved-recipient@example.com
```

Do not run the orchestrator with recipients until sending is authorized: it sends
on a report run. Do not modify cron/timers in this preparation. Keep SMTP variables
unset for a Gmail API deployment; SMTP hosts retain their existing configuration
with ARBITRAGE_EMAIL_TRANSPORT omitted or set to smtp. There is no automatic
fallback from Gmail API to SMTP, and no SMTP password is passed to Gmail.

## Unattended refresh and failure behavior

Each report delivery exchanges the stored refresh token at Google's fixed HTTPS
token endpoint, then submits MIME/base64url XLSX content at the fixed Gmail
users/me/messages/send endpoint. Default TLS verification and 30-second network
timeouts apply; redirects are refused. Short-lived access tokens stay in memory.
A returned replacement refresh token is saved atomically with mode 0600 before
submission. Files contain only client credentials, refresh token and send scope.
Normal refresh does not require a browser. Runtime has no new dependencies.

Refresh tokens can expire/revoke through Testing, user revocation, password
changes involving Gmail scopes, prolonged nonuse, token issuance limits or admin
policy. An invalid grant requires fresh interactive consent; refresh cannot
repair it. Errors suppress response bodies, tokens, addresses and original
exception tracebacks. The orchestrator records a failed run. There are no automatic
send retries or SMTP fallback: a timeout after submission has an unknown delivery
outcome, so check the sender's Sent folder manually before rerunning. A Gmail
message ID means accepted submission, not confirmed inbox delivery. Keep the
existing single-job execution model; concurrent credential rotation is not
supported. Gmail account/API sending quotas still apply.

## Validation and official references

Tests mock OAuth consent, refresh and submission; cover attachment bytes,
recipient headers, scope rejection, private files, token rotation, redirects and
redacted tracebacks. Existing mocked SMTP tests remain in place. Live OAuth,
account consent, service-user permissions and delivery are intentionally untested.

- [Gmail scopes and sensitivity](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Sending MIME messages and attachments](https://developers.google.com/workspace/gmail/api/guides/sending)
- [Desktop OAuth and offline refresh](https://developers.google.com/identity/protocols/oauth2/native-app)
- [Refresh expiration including seven-day Testing limit](https://developers.google.com/identity/protocols/oauth2#expiration)
- [OAuth verification exceptions](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)

Checked 2026-10-26. Consult the console and official policy before production use.
