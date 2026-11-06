"""One-shot Catalog validation. Import and preflight never dispatch or authenticate."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import resource
import signal
import ssl
import stat

from app.m67_state import secure
from app.m88_state import ledger, lock, read, sha, stamp, write, validate_ledger
from app.m89_deployment import BASELINE, configuration

ASIN = 'B001BE12BA'
MARKETPLACE = 'ATVPDKIKX0DER'
HOST = 'sellingpartnerapi-na.amazon.com'
TARGET = '/catalog/2022-04-01/items/B001BE12BA?marketplaceIds=ATVPDKIKX0DER&includedData=summaries'
URL = 'https://' + HOST + TARGET
APPROVAL = 'APPROVE_M90_ONE_GET_ATTEMPT_14'
MAX_RESPONSE = 262144


def canonical_hash(value: dict) -> str:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + '\n').encode()
    return hashlib.sha256(raw).hexdigest()


def history(path: Path, expected: str) -> dict:
    """Pin ALL bytes, then prove continuation from the reviewed 12-attempt ledger."""
    # Retain the legacy path security check; validate one immutable snapshot.
    secure(path)
    if path.stat().st_size > 8*1024*1024:
        raise ValueError('Bounded ledger required')
    return history_bytes(path.read_bytes(), expected)


def history_bytes(raw: bytes, expected: str) -> dict:
    """Compatibility seam for the shared pure, network-free history validator."""
    from app.m902_history import validate_snapshot
    return validate_snapshot(raw, expected, BASELINE)


def preflight(path: Path, expected: str) -> dict:
    with lock(path.with_suffix('.lock')):
        history(path, expected)
    return dict(method='GET', url=URL, attempts_used=13, remaining=36,
                purchase_authorized=False, network='NOT_TESTED',
                blocker='Fresh in-memory seller-authorized LWA access token required; no authentication provided')


def parse_response(raw: bytes) -> dict:
    if len(raw) > MAX_RESPONSE:
        raise ValueError('Oversized response')
    # Reuse duplicate-key and nonfinite rejection from the private state reader.
    from app.m80_contract import unique
    doc = json.loads(raw, object_pairs_hook=unique,
                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    if not isinstance(doc, dict) or doc.get('asin') != ASIN:
        raise ValueError('Catalog Item ASIN mismatch')
    summaries = doc.get('summaries')
    if (not isinstance(summaries, list) or len(summaries) != 1
            or not isinstance(summaries[0], dict) or summaries[0].get('marketplaceId') != MARKETPLACE
            or not isinstance(summaries[0].get('itemName'), str) or not summaries[0]['itemName']):
        raise ValueError('Requested marketplace summary missing or invalid')
    # Never persist response strings: they could echo sensitive inputs or contain untrusted data.
    return dict(asin=ASIN, marketplace_id=MARKETPLACE, summary_present=True,
                seller_eligibility='UNKNOWN', profitability='UNKNOWN', purchase_authorized=False)


def send(token: str, *, url: str = URL, method: str = 'GET') -> tuple[int, bytes]:
    if url != URL or method != 'GET':
        raise PermissionError('Only the exact approved GET is permitted')
    connection = http.client.HTTPSConnection(HOST, timeout=10, context=ssl.create_default_context())
    try:
        # http.client performs one request, has no redirects, proxy environment, or retry loop.
        connection.request('GET', TARGET, headers={'x-amz-access-token': token,
                           'User-Agent': 'IntelligenceOS-Arbitrage/M90', 'Accept': 'application/json',
                           'Accept-Encoding': 'identity'})
        with connection.getresponse() as response:
            return response.status, response.read(MAX_RESPONSE + 1)
    finally:
        connection.close()


def token_from_pipe(fd: int) -> str:
    if (fd < 3 or not stat.S_ISFIFO(os.fstat(fd).st_mode)
            or not os.readlink(f'/proc/self/fd/{fd}').startswith('pipe:[')):
        raise ValueError('Dedicated anonymous token pipe required')
    # Nonblocking: a missing broker cannot hang before reservation.
    os.set_blocking(fd, False)
    raw = os.read(fd, 2049)
    if not 1 <= len(raw) <= 2048:
        raise ValueError('Bounded access token required')
    token = raw.decode('ascii')
    if any(c.isspace() or not c.isprintable() for c in token):
        raise ValueError('Invalid token shape')
    return token


def seller_context(path: Path) -> None:
    """Operator evidence is a prerequisite, not proof of remote authorization."""
    secure(path.parent, directory=True)
    if path.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError('Seller context must be outside repository')
    context = read(path)
    if (context.get('marketplace_id') != MARKETPLACE
            or not isinstance(context.get('seller_id'), str)
            or not re.fullmatch('[A-Z0-9]{1,32}', context['seller_id'])
            or context.get('product_listing_role_confirmed') is not True
            or context.get('application_authorized_for_seller') is not True
            or context.get('us_marketplace_participation_confirmed') is not True
            or context.get('token_matches_protected_source') is not True):
        raise ValueError('Confirmed seller, marketplace, application and token binding required')
    expires = datetime.fromisoformat(context['token_expires_at'])
    if expires.tzinfo is None or (expires - datetime.now(timezone.utc)).total_seconds() < 60:
        raise ValueError('Fresh access token with at least 60 seconds remaining required')


def execute(path: Path, expected: str, env: Path, account_lock: Path, token_fd: int, context: Path,
            *, approval: str = '', transport=send) -> dict:
    if approval != APPROVAL:
        raise PermissionError('Explicit one-request approval required')
    if account_lock.name != 'candidate-execution.lock':
        raise ValueError('Existing shared Amazon account lock required')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    with lock(account_lock), lock(path.with_suffix('.lock')):
        value = history(path, expected)
        seller_context(context)
        # Existing protected source is validated, never printed or used to authenticate.
        credentials = configuration(env)
        credentials.clear()
        token = token_from_pipe(token_fd)
        value['m90_one_request'] = dict(baseline_sha256=expected, url=URL, method='GET')
        value['attempts_used'] = 14
        value['attempts'].append(dict(number=14, phase='catalog_read_only', candidate_id=ASIN,
            status='RESERVED', reserved_at=stamp(), operation='m90-one-get', baseline_sha256=expected))
        write(path, value, replace=True)  # fsync file + parent before ANY possible dispatch.
        attempt = value['attempts'][-1]
        old_handler = signal.getsignal(signal.SIGALRM)
        def deadline(signum, frame):
            raise TimeoutError('M90 absolute deadline')
        try:
            signal.signal(signal.SIGALRM, deadline)
            signal.alarm(20)
            status, raw = transport(token)
            if type(status) is int and 100 <= status <= 599:
                attempt['http_status'] = status
            if type(status) is not int or status != 200:
                raise ValueError('Non-200 response; stop without retry')
            result = parse_response(raw)
            attempt.update(status='COMPLETE', completed_at=stamp(), http_status=200, result=result)
        except BaseException:
            attempt.update(status='FAILED', completed_at=stamp(), outcome='FAILED_OR_UNCERTAIN_NO_RETRY')
            write(path, value, replace=True)
            raise RuntimeError('M90 stopped; attempt charged; no retry') from None
        finally:
            token = None
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        write(path, value, replace=True)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('preflight', 'execute'))
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--ledger-sha256', required=True)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--account-lock', type=Path)
    parser.add_argument('--token-fd', type=int)
    parser.add_argument('--seller-context', type=Path)
    parser.add_argument('--approval', default='')
    args = parser.parse_args()
    try:
        if args.command == 'preflight':
            result = preflight(args.ledger, args.ledger_sha256)
        else:
            if args.env_file is None or args.account_lock is None or args.token_fd is None or args.seller_context is None:
                parser.error('execute requires protected env, existing account lock, and token pipe')
            if args.ledger != Path('/var/lib/intelligenceos-arbitrage/m89/ledger.json'):
                raise ValueError('Use the sole authoritative production ledger')
            result = execute(args.ledger, args.ledger_sha256, args.env_file, args.account_lock,
                             args.token_fd, args.seller_context, approval=args.approval)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print('M90 blocked or stopped. Inspect protected ledger; never retry or reset.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
