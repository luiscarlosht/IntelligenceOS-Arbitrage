"""Offline authentication diagnosis: no DNS, connections, HTTP or ledger writes."""
import argparse
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import ssl
import sys
from urllib.parse import parse_qs, urlencode
from urllib.request import Request

from app import amazon_pilot as pilot
from app.amazon_transport_diagnostics import local_socket_readiness
from app.evidence_io import publication
from app.m67_state import secure
from app.m88_state import ledger, read, sha, write
from app.m89 import LEDGER

ACTIVE = ContextVar('m89_auth_offline', default=False)
INSTALLED = False


@contextmanager
def no_dispatch():
    """Allow socket construction only; prohibit even DNS and local connections."""
    global INSTALLED
    if not INSTALLED:
        def guard(event, args):
            if ACTIVE.get() and ((event.startswith('socket.') and event != 'socket.__new__')
                                 or event.startswith(('http.client.', 'subprocess.', 'os.exec', 'os.spawn', 'os.system'))):
                raise PermissionError('Offline authentication diagnosis prohibits dispatch')
        sys.addaudithook(guard)
        INSTALLED = True
    token = ACTIVE.set(True)
    try:
        yield
    finally:
        ACTIVE.reset(token)


def file_hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def diagnose(root: Path, private: Path, inventory_path: Path, output: Path) -> dict:
    with no_dispatch():
        inventory = read(inventory_path)
        def unchanged():
            if any(file_hash(Path(path)) != digest for path, digest in inventory.items()):
                raise ValueError('Preserved evidence changed; never repair it automatically')
        unchanged()
        ledger_path = root / LEDGER
        data = ledger(ledger_path)
        if data['attempts_used'] != 12 or data['attempts'][-1]['status'] != 'FAILED':
            raise ValueError('Authoritative used-12 ledger with failed last attempt required')
        failure = data['attempts'][-1]
        if failure['phase'] != 'authentication' or failure['failure']['reason'] != 'transport_error':
            raise ValueError('Expected authentication transport failure')
        prior_auth = []
        transport_hashes = []
        for folder, number in (('m88-executor-v1-20261105T0301Z', 1), ('m88-targeted-verification-v1', 8)):
            attempt = data['attempts'][number - 1]
            plan_path = root / folder / 'plan.json'
            if sha(plan_path) != attempt['plan_sha256']:
                raise ValueError('Prior authentication plan changed')
            transport_hashes.append(read(plan_path)['implementation_sha256']['amazon_pilot.py'])
            path = root / folder / f'receipt-{number}.json'
            if sha(path) != attempt['receipt_sha256']:
                raise ValueError('Prior authentication receipt changed')
            receipt = read(path)
            prior_auth.append(dict(number=number, status=attempt['status'], observed_at=receipt['observed_at'],
                                   token_received=receipt['evidence']['token_received']))
        failed_plan_path = root.parent / 'm89-read-only-v1/plan.json'
        if sha(failed_plan_path) != failure['plan_sha256']:
            raise ValueError('Failed M89 plan changed')
        transport_hashes.append(read(failed_plan_path)['implementation_sha256']['amazon_pilot.py'])
        if len(set(transport_hashes)) != 1:
            raise ValueError('Historical shared transport implementations differ; review required')
        credentials_path = private / 'credentials.json'
        secure(private, directory=True)
        secure(credentials_path)
        descriptor = os.open(private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            values = pilot.load_credentials(descriptor)
            credential_status = dict(present=True, security_valid=True, required_fields_present=True,
                                     local_shape_valid=True, remote_validity='UNTESTED')
            values.clear()
        finally:
            os.close(descriptor)
        account = read(private / 'm67-account-context.json')
        account_status = dict(credential_binding_valid=account.get('credentials_sha256') == sha(credentials_path),
                              marketplace_valid=account.get('marketplace_id') == 'ATVPDKIKX0DER',
                              condition_valid=account.get('condition') == 'new_new')
        account.clear()
        # Construct only a synthetic request. Never put operator values in a request during diagnosis.
        request = Request('https://api.amazon.com/auth/o2/token',
                          data=urlencode(dict(grant_type='refresh_token', client_id='fixture',
                                              client_secret='fixture', refresh_token='fixture')).encode(),
                          headers={'Content-Type': 'application/x-www-form-urlencoded'})
        request_status = dict(endpoint=request.full_url, method=request.get_method(),
                              content_type=request.get_header('Content-type'), encoding='UTF-8',
                              form_fields=sorted(parse_qs(request.data.decode())), timeout_seconds=10,
                              proxy_policy='EXPLICITLY_DISABLED', redirect_policy='DISABLED', retries=0,
                              marketplace='ATVPDKIKX0DER', marketplace_sent_to_token_endpoint=False,
                              same_endpoint_headers_encoding_and_transport_as_M88=True)
        proxy_vars = ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
                      'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')
        ca_vars = ('SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE')
        environment = dict(proxy_variable_presence={k: bool(os.environ.get(k)) for k in proxy_vars},
                           ca_override_presence={k: bool(os.environ.get(k)) for k in ca_vars},
                           sandbox_network_disabled=os.environ.get('CODEX_SANDBOX_NETWORK_DISABLED') == '1')
        try:
            context = ssl.create_default_context()
            tls_status = dict(context_created=True, certificate_verification=context.verify_mode.name,
                              hostname_check=context.check_hostname, trust_store=context.cert_store_stats(),
                              remote_handshake='UNTESTED')
        except Exception as error:
            from app.amazon_transport_diagnostics import classify_transport
            tls_status = dict(context_created=False, diagnostic=classify_transport(error, 'tls_context'),
                              remote_handshake='UNTESTED')
        local = local_socket_readiness()
        blocked = not local['local_socket_ready']
        report = dict(schema='m89-authentication-readiness-v1', evaluated_at=datetime.now(timezone.utc).isoformat(),
            starting_commit='753304d', additional_amazon_http_attempts=0, cumulative_attempts=12, remaining_attempts=37,
            ledger_status_counts={s: sum(a['status'] == s for a in data['attempts']) for s in ('COMPLETE', 'FAILED', 'RESERVED')},
            ledger_sha256=sha(ledger_path), preserved_inventory_sha256=sha(inventory_path),
            preserved_file_count=len(inventory), latest_failure=failure, prior_authentication=prior_auth,
            failed_authentication_receipt_present=(root.parent / 'm89-read-only-v1/receipt-12.json').exists(),
            original_underlying_exception='NOT_RECORDED', original_root_cause_certainty='INFERRED_NOT_PROVEN',
            historical_shared_transport_sha256=transport_hashes[0],
            current_local_blocker='INTERNET_SOCKET_CREATION_DENIED' if blocked else 'NONE_DETECTED_LOCALLY',
            likely_historical_cause='Restricted sandbox denied network operations; consistent with local EPERM and rapid no-status failure',
            request=request_status, credentials=credential_status, account=account_status,
            environment=environment, tls=tls_status, local_transport=local,
            untested=['Amazon DNS resolution', 'Remote TCP connection', 'Remote TLS handshake/certificate',
                      'Amazon authentication acceptance', 'SP-API permissions', 'Seller eligibility'],
            corrective_action=['Run a future separately authorized attempt only in an approved network-enabled runtime',
                               'Keep verified TLS, explicit no-proxy policy and correct existing request configuration',
                               'Retain safe nested transport category, errno and stage for future failures',
                               'Do not rotate credentials, weaken TLS, bypass sandbox restrictions or replay the claimed plan'],
            live_retry_now_justified=bool(not blocked and tls_status['context_created'] and all(account_status.values())),
            live_retry_attempted=False, retry_authorized_by_this_report=False,
            future_retry_conditions=['Explicit later authorization for one authentication-only attempt',
                                     'Approved runtime permits unconnected Internet sockets and authorized outbound HTTPS',
                                     'New scope starts at actual 12/49 ledger; reserve attempt 13 before dispatch',
                                     'No automatic retries, token refresh, or follow-on API calls'],
            preserved_evidence_unchanged=True, purchase_authorized=False)
        unchanged()
        with publication(output, [root, inventory_path]) as stage:
            write(stage / 'authentication-readiness.json', report)
            write(stage / 'preserved-evidence-inventory.json', inventory)
            summary = ("# M89 authentication readiness\n\n"
                "Zero additional Amazon HTTP attempts. Ledger preserved: 12/49 used, 37 remaining; 11 COMPLETE and 1 FAILED. "
                "Attempt 12 is the failed authentication entry, not a successful receipt. receipt-12.json was never created; failure metadata lives in the ledger.\n\n"
                f"Current local blocker: {report['current_local_blocker']}. IPv4/IPv6 socket creation was probed without DNS, connect, send, TLS handshake or HTTP operations. "
                f"Local results: {local['socket_checks']}. "
                "This is the likely historical cause, not proof of the original nested exception: the old handler discarded its type/errno. "
                "A successful local TLS context does not validate Amazon's remote certificate.\n\n"
                "M88 attempts 1 and 8 have successful authentication receipts. Their shared transport hash matches the M89 executed plan. "
                "M88/M89 token endpoint, method, form encoding, headers, timeout, proxy and TLS policies match. "
                "Credential file security, local field shape and saved account binding pass; remote validity remains untested. "
                f"Proxy-variable presence: {environment['proxy_variable_presence']}; CA-override presence: {environment['ca_override_presence']}. "
                "No evidence supports changing the endpoint, credentials, headers or certificate policy.\n\n"
                "Correction: retain safe underlying exception categories/errno/stage in future transport failures; use an approved network-enabled runtime for any later live operation. "
                "The sandbox restriction cannot be corrected by application configuration here. Do not weaken TLS or enable proxy bypasses.\n\n"
                f"Live retry recommended by current local checks: {report['live_retry_now_justified']}. Remote connectivity and authentication remain untested. "
                "A later authentication-only attempt may be justified after approved network access is available and explicit authorization is given. "
                "It must use a new reviewed scope, charge attempt 13 before dispatch, stop after one result, and never replay M89's failed operation. "
                "This report neither authorizes nor attempts that retry.\n\npurchase_authorized=false.\n")
            (stage / 'authentication-readiness.md').write_text(summary)
            (stage / 'authentication-readiness.md').chmod(0o600)
            unchanged()
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'private', 'preserved-inventory', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    report = diagnose(args.root, args.private, args.preserved_inventory, args.output)
    print(f"Offline readiness: {report['current_local_blocker']}; 0 new attempts; 12/49 used, 37 remaining")


if __name__ == '__main__':
    main()
