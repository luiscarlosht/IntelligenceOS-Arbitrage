# M89 DigitalOcean deployment preparation

Status: PREPARED, NOT DEPLOYED; live authentication NOT AUTHORIZED/NOT RUN.
Starting commit aca3660. purchase_authorized=false throughout.

Authoritative local ledger:
`var/m88-real-six-pilot/20261105T022741571627Z/amazon-http-attempt-ledger.json`.
SHA-256: `b7502888a36b97594e5c79b3f8c47312c1226d80355a03621284660b45da2f1b`.
12/49 used, 37 remaining: 11 COMPLETE and attempt 12 FAILED. Failed and
uncertain attempts remain charged. Older 11/49 handoffs are historical only.
No ledger or production credentials are committed with this milestone.

## Reviewed deployment constraints

Existing Ubuntu 24.04 layout is recorded in VM_V02_RELEASE.md. The existing
systemd offline service restricts address families to AF_UNIX and denies all IP
traffic. Preserve that service and timer. Use a separate root-owned release and
manual invocation as the existing dedicated application user. No inbound port,
new subscription, timer, automatic restart or new service is needed.

Operator must verify the existing host identity through its established SSH
known-host record, available disk/RAM, Ubuntu version, Python 3.12, system clock,
CA trust, service account and outbound DNS/443 policy. Never disable certificate
validation or SSH host-key validation. Host access and these checks were not
performed in the restricted preparation environment.

## Stage code and ledger (operator commands after deployment approval)

Run from this checkout on the source machine. Stop all Amazon executors and keep
them stopped until the destination is the sole accounting authority. The ledger
lock cannot coordinate independent machines. Never restore a pre-run ledger onto
an active destination; rollback code only, retaining the newest accounting.

```bash
umask 077
RELEASE=$(git rev-parse HEAD)
: "${DO_HOST:?Set the established DigitalOcean SSH destination}"
mkdir -m 700 /tmp/m89-transfer
python3.12 -m app.m89_deployment transfer-ledger \
  --ledger var/m88-real-six-pilot/20261105T022741571627Z/amazon-http-attempt-ledger.json \
  --destination /tmp/m89-transfer/ledger.json
git archive --format=tar.gz --output=/tmp/m89-transfer/release.tar.gz "$RELEASE"
sha256sum /tmp/m89-transfer/release.tar.gz
ssh -o StrictHostKeyChecking=yes "$DO_HOST" 'umask 077; mkdir -m 700 /root/m89-incoming'
scp -o StrictHostKeyChecking=yes /tmp/m89-transfer/release.tar.gz /tmp/m89-transfer/ledger.json "$DO_HOST":/root/m89-incoming/
```

Existing staging directories intentionally cause failure; inspect them, do not
overwrite. Compare archive SHA-256 on the destination with the source value
through the trusted operator session. Set RELEASE to the reviewed full commit
printed by `git rev-parse HEAD` above. Run as root on the VM:

```bash
: "${RELEASE:?Set reviewed full commit}"
sha256sum /root/m89-incoming/release.tar.gz
install -d -m 755 /opt/intelligenceos-arbitrage/releases
mkdir -m 755 "/opt/intelligenceos-arbitrage/releases/$RELEASE"
tar -xzf /root/m89-incoming/release.tar.gz -C "/opt/intelligenceos-arbitrage/releases/$RELEASE"
cd "/opt/intelligenceos-arbitrage/releases/$RELEASE"
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
install -d -o intelligenceos-arbitrage -g intelligenceos-arbitrage -m 700 /var/lib/intelligenceos-arbitrage/m89
# Use a fresh staging path, then exclusive, fsynced publication by the application.
test ! -e /var/lib/intelligenceos-arbitrage/m89/incoming-ledger.json
install -o intelligenceos-arbitrage -g intelligenceos-arbitrage -m 600 /root/m89-incoming/ledger.json /var/lib/intelligenceos-arbitrage/m89/incoming-ledger.json
runuser -u intelligenceos-arbitrage -- .venv/bin/python -m app.m89_deployment transfer-ledger \
  --ledger /var/lib/intelligenceos-arbitrage/m89/incoming-ledger.json \
  --destination /var/lib/intelligenceos-arbitrage/m89/ledger.json
install -d -o intelligenceos-arbitrage -g intelligenceos-arbitrage -m 700 /etc/intelligenceos-arbitrage/m89
```

Provision `/etc/intelligenceos-arbitrage/m89/live.env` from the existing protected
credential source via the approved secret transfer mechanism. Do not read or
print credentials in Codex/chat, shell arguments, terminal tracing or logs. Do
not rotate or regenerate them. File must be application-owned mode 0600, parent
0700, no symlinks/hardlinks, outside the release. Required format: four literal
`KEY=value` lines, no shell expansion, quoting, `export` or whitespace:
`LWA_CLIENT_ID`, `LWA_CLIENT_SECRET`, `LWA_REFRESH_TOKEN`, and
`PURCHASE_AUTHORIZED=false`. The command reads this protected environment file
directly; it does not source shell code or inherit unrelated credentials.

The source ledger and transfer copy remain protected audit backups. Destination
preflight verifies its exact pinned hash and every prior record before any auth.
If staging fails, inspect rather than rerun installation over existing state.
Keep the existing `/current` symlink and offline release unchanged.

## Preflight

From the reviewed release directory on the VM:

```bash
runuser -u intelligenceos-arbitrage -- .venv/bin/python -m app.m89_deployment preflight \
  --ledger /var/lib/intelligenceos-arbitrage/m89/ledger.json \
  --env-file /etc/intelligenceos-arbitrage/m89/live.env --offline
runuser -u intelligenceos-arbitrage -- .venv/bin/python -m app.m89_deployment preflight \
  --ledger /var/lib/intelligenceos-arbitrage/m89/ledger.json \
  --env-file /etc/intelligenceos-arbitrage/m89/live.env
```

Offline mode checks Python/dependency versions, CA context, protected configuration
and authoritative ledger. It reports DNS/TCP/TLS NOT_TESTED. Full mode additionally
resolves api.amazon.com and sellingpartnerapi-na.amazon.com, opens TCP 443 and
performs certificate-verified TLS with SNI, then closes. It sends no HTTP, never
contacts an authentication URL and consumes no Amazon API attempt. A successful
TLS handshake does not establish credential validity, seller permissions or API
availability. Run `pip check` separately as above for dependency consistency.

## Authentication only — DO NOT RUN until separately approved

Operator approval must explicitly name the reviewed release, authoritative ledger
hash, account configuration, one authentication attempt and remaining budget.
Approval for installation/preflight does not authorize authentication or SP-API.

```bash
runuser -u intelligenceos-arbitrage -- .venv/bin/python -m app.m89_deployment authentication-only \
  --ledger /var/lib/intelligenceos-arbitrage/m89/ledger.json \
  --env-file /etc/intelligenceos-arbitrage/m89/live.env \
  --approve-one-authentication-attempt
```

Exactly one POST to `https://api.amazon.com/auth/o2/token`, standard refresh-token
fields, verified TLS, proxy disabled, redirects disabled, 20-second transport
timeout, bounded response, no retries. This follows
[Amazon's connection procedure](https://developer-docs.amazon/sp-api/docs/connecting-to-the-selling-partner-api).
The token is discarded, never printed or persisted. No Catalog, offers, fees,
purchases, listings or settings requests exist in this module.

The existing ledger lock is held through execution. Attempt 13 is durably reserved
and fsynced before dispatch, leaving 36. Success, rejection, timeout, interruption
and uncertain sends all remain charged. A hard kill can leave RESERVED; report it
as uncertain, never replay/refund it. The command refuses any subsequent execution
because the exact 12-attempt baseline no longer matches. Completion preserves all
prior records and operation bindings. No reset, repair or retry command exists.
Durability failure after dispatch requires operator investigation; retain the
reserved charge. After execution securely archive the newest ledger and reconcile
its hash/count back to the source before any further separately approved work.

## Readiness report and remaining blockers

- Offline implementation and synthetic regression validation prepared. No live
  Amazon API calls or authentication executed during M89 preparation.
- Source authoritative ledger verified 12/49 with all prior attempts intact.
  Destination ledger transfer/install has NOT been performed.
- DigitalOcean SSH destination/host identity and current host configuration need
  operator verification. Server deployment and real DNS/TCP/TLS remain NOT_TESTED.
- Protected credential provisioning and account binding must be verified by the
  authorized operator without changing credentials. Credential validity UNKNOWN.
- Operator must approve reviewed release deployment/sole-writer cutover, then
  independently approve the one-attempt authentication command. Further SP-API
  operations require a new reviewed scope; purchases remain unauthorized.
- No automatic fallback to another ledger, credential source, endpoint or proxy.
  Restoring an old ledger or running copied ledgers concurrently breaks accounting
  and is prohibited by this operational procedure.

## Preparation validation evidence

- Python 3.12.3; local test environment openpyxl 3.1.5 and pytest 8.3.5.
  `pip check` passed, but strict M89 dependency preflight correctly refused the
  pytest mismatch against requirements.txt (9.0.3). Install the reviewed pinned
  requirements on the target before claiming a passing preflight.
- 11 M89 regression tests passed using synthetic credentials/ledgers and mocked
  transports. They cover single dispatch, refusal of replay/redirects, accounting
  before dispatch, failure/interruption charging, baseline tampering, locking,
  dependency gates, TLS-only readiness and byte-identical exclusive transfer.
- Actual authoritative ledger copied locally to a protected temporary directory
  and hash-verified; source remained unchanged at 12/49. No credentials read.
- Legacy and discovery sample modes succeeded; `git diff --check` passed.
- Full repository regression results are recorded in the implementation handoff.
  No host, Docker or live API validation is implied by these offline checks.
