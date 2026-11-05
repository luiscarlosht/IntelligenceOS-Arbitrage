"""Manual DigitalOcean readiness and single-use authentication; no SP-API calls."""
import argparse
from importlib.metadata import version
import json
import os
from pathlib import Path
import socket
import ssl
import sys
from urllib.parse import urlencode
from urllib.request import Request, HTTPSHandler, HTTPRedirectHandler, ProxyHandler, build_opener

from app.m67_state import secure
from app.m88_state import ledger, lock, sha, stamp, write

BASELINE = 'b7502888a36b97594e5c79b3f8c47312c1226d80355a03621284660b45da2f1b'
HOSTS = ('api.amazon.com', 'sellingpartnerapi-na.amazon.com')
KEYS = {'LWA_CLIENT_ID', 'LWA_CLIENT_SECRET', 'LWA_REFRESH_TOKEN', 'PURCHASE_AUTHORIZED'}


def baseline(path: Path) -> dict:
    value = ledger(path)
    if value['attempts_used'] != 12 or sha(path) != BASELINE:
        raise ValueError('Authoritative 12-attempt baseline required; never reset')
    return value


def configuration(path: Path) -> dict:
    secure(path.parent, directory=True)
    secure(path)
    if path.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError('Configuration must be outside repository')
    if path.stat().st_size > 16384:
        raise ValueError('Bounded configuration required')
    values = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or key not in KEYS or key in values or not value or any(c.isspace() for c in value):
            raise ValueError('Invalid protected environment configuration')
        values[key] = value
    if set(values) != KEYS or values['PURCHASE_AUTHORIZED'] != 'false':
        raise ValueError('Complete configuration with purchase_authorized=false required')
    return values


def dependencies() -> None:
    if sys.version_info[:2] != (3, 12):
        raise ValueError('Python 3.12 required')
    for name, expected in (('openpyxl', '3.1.5'), ('pytest', '9.0.3')):
        if version(name) != expected:
            raise ValueError('Pinned dependencies required')
    ssl.create_default_context()  # Validate availability of trusted CA configuration.


def network() -> None:
    # DNS, TCP and verified TLS only. No HTTP bytes or authentication sent.
    context = ssl.create_default_context()
    for host in HOSTS:
        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        with socket.create_connection((host, 443), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=host):
                pass


def preflight(path: Path, env: Path, *, offline: bool = False) -> dict:
    dependencies()
    configuration(env)
    with lock(path.with_suffix('.lock')):
        baseline(path)
    if not offline:
        network()
    return dict(configuration='PASS', ledger='PASS', attempts_used=12, remaining=37,
                dns_tcp_tls='NOT_TESTED' if offline else 'PASS', purchase_authorized=False)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send(credentials: dict) -> bool:
    payload = urlencode(dict(grant_type='refresh_token', client_id=credentials['LWA_CLIENT_ID'],
                             client_secret=credentials['LWA_CLIENT_SECRET'],
                             refresh_token=credentials['LWA_REFRESH_TOKEN'])).encode()
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request('https://api.amazon.com/auth/o2/token', data=payload,
                      headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
    with opener.open(request, timeout=20) as response:
        raw = response.read(65537)
        if len(raw) > 65536:
            return False
        document = json.loads(raw)
        return response.status == 200 and isinstance(document.get('access_token'), str) and bool(document['access_token'])


def authenticate(path: Path, env: Path, *, opt_in: bool = False) -> None:
    if not opt_in:
        raise PermissionError('Explicit authentication-only opt-in required')
    dependencies()
    credentials = configuration(env)
    # Hold the existing M88 ledger lock for reservation, send and completion.
    with lock(path.with_suffix('.lock')):
        value = baseline(path)
        value['m89_authentication_only'] = 'CLAIMED_NO_REPLAY'
        value['attempts'].append(dict(number=13, phase='authentication', candidate_id=None,
            status='RESERVED', reserved_at=stamp(), operation='m89-authentication-only'))
        value['attempts_used'] = 13
        write(path, value, replace=True)  # Durable charge before any possible dispatch.
        try:
            success = send(credentials)  # Exactly one invocation; no retries or redirects.
        except BaseException:
            value['attempts'][-1].update(status='FAILED', completed_at=stamp(), outcome='UNKNOWN_NO_RETRY')
            write(path, value, replace=True)
            raise RuntimeError('Authentication stopped; attempt remains charged') from None
        finally:
            credentials.clear()
        value['attempts'][-1].update(status='COMPLETE' if success else 'FAILED',
                                     completed_at=stamp(), token_received=success)
        write(path, value, replace=True)
        if not success:
            raise RuntimeError('Authentication rejected; attempt remains charged')


def transfer(source: Path, destination: Path) -> None:
    secure(destination.parent, directory=True)
    with lock(source.with_suffix('.lock')):
        baseline(source)
        raw = source.read_bytes()
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        baseline(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('preflight', 'authentication-only', 'transfer-ledger'))
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--approve-one-authentication-attempt', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'transfer-ledger':
            if args.destination is None:
                parser.error('--destination required')
            transfer(args.ledger, args.destination)
            print('Ledger copied byte-for-byte; 12/49 used; purchase_authorized=false')
        else:
            if args.env_file is None:
                parser.error('--env-file required')
            if args.command == 'preflight':
                print(json.dumps(preflight(args.ledger, args.env_file, offline=args.offline), sort_keys=True))
            else:
                if args.offline:
                    parser.error('Authentication cannot use --offline')
                authenticate(args.ledger, args.env_file, opt_in=args.approve_one_authentication_attempt)
                print('Authentication complete; token discarded; 13/49 used; purchase_authorized=false')
    except Exception:
        print('M89 stopped; inspect protected ledger; no retry or automatic repair. No secret diagnostics emitted.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
