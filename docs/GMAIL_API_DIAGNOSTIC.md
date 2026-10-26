# Gmail API stopped DEMO inspection — 2026-10-26

Read-only inspection found the API reservation marker at
`var/diagnostics/gmail-api-demo.attempted`, timestamp 18:27:38.397863 UTC,
mode 0600, owner root. Its expected reservation header and both existing
DEMO attachment hashes match. No API stage log was present. The SMTP stage
log describes a separate attempt and cannot establish this API attempt's result.

The last demonstrable completed work is message construction, private credential
read/validation and marker content writing. Marker fsync completion is not proven
by its existence. No historical evidence separates token refresh, response
validation, token rotation, serialization and submission. Gmail acceptance was
not recorded; absence of an acknowledgement does not prove non-delivery.

The token directory is root-owned 0700; the token is a regular, nonsymlink,
root-owned 0600 file. The required client_id, client_secret and refresh_token
fields are present as nonempty strings and scopes equals gmail.send only.
No values are recorded. Offline validation cannot establish expiry, revocation,
project/client status or Google's acceptance of the authorization.

Optional redacted observation in app.gmail_api now separates credential read,
validation, refresh, refresh response validation, optional rotation, serialization,
submission and acceptance validation. ops.gmail_stage_tracking writes allowlisted
stage/status/time, last completed stage, acceptance/submission flags and numeric
HTTP status/errno only. It never records provider bodies, URLs, headers, message
content, IDs, addresses or exception messages. HTTP success without an ID is not
reported as acceptance. No retries are added. Log writes are owner-only,
symlink-rejecting and flushed/fsynced. A failed submission remains ambiguous.

The local ignored demo helper is wired to this observer for a future separately
authorized attempt. Its existing-marker guard remains before token reads or
network work; instrumentation cannot reconstruct historical stages and does not
permit a retry. No stage log is fabricated for the historical attempt.

Next targeted diagnostic: the owner should inspect the intended sender's Gmail
Sent folder manually near 18:27:38 UTC for the fictional DEMO subject and exact
recipient. This requires no additional API permission. Finding a matching message
supports sending; absence alone does not establish a refresh failure. Existing
terminal output, if retained, may help, but do not share codes, URLs, credentials
or raw provider responses. A credential-free DNS/TLS probe to the token and send
hosts could test current connectivity separately; it cannot reconstruct this
attempt or validate the refresh token. No token-refresh diagnostic or resend is
authorized here. Preserve all attempt markers.
