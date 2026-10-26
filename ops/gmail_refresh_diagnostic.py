"""One reserved OAuth refresh only. No email, mailbox access or token writes."""
import json
import os
from pathlib import Path
import resource
import signal
import stat
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.gmail_api import NoRedirect, SCOPE, TOKEN_URL, read_private

TOKEN_FILE = Path('/root/.config/arbitrage-gmail/token.json')
RESERVATION = TOKEN_FILE.parent / 'refresh-diagnostic.attempted'
OAUTH_ERRORS = frozenset(('invalid_request', 'invalid_client', 'invalid_grant',
    'unauthorized_client', 'unsupported_grant_type', 'invalid_scope',
    'access_denied', 'temporarily_unavailable', 'server_error'))
SOCKET_TIMEOUT = 15
TOTAL_TIMEOUT = 40
MAX_BODY = 65536


def result(success=False, http_status=None, oauth_error=None):
    return dict(success=success, http_status=http_status, oauth_error=oauth_error)


def parse_response(response, status):
    body = response.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        return result(http_status=status)
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError):
        return result(http_status=status)
    if not isinstance(data, dict):
        return result(http_status=status)
    error = data.get('error')
    recognized = error if isinstance(error, str) and error in OAUTH_ERRORS else None
    success = (status == 200 and 'error' not in data and
        isinstance(data.get('access_token'), str) and bool(data['access_token']) and
        isinstance(data.get('token_type'), str) and data['token_type'].lower() == 'bearer' and
        ('scope' not in data or isinstance(data['scope'], str) and set(data['scope'].split()) == {SCOPE}))
    return result(success=success, http_status=status, oauth_error=recognized)


def run():
    """One POST at most; private reservation prevents repeated invocations."""
    status = None
    try:
        for ancestor in TOKEN_FILE.parents:
            if ancestor.is_symlink():
                return result()
        parent = TOKEN_FILE.parent.stat()
        if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700:
            return result()
        data = read_private(TOKEN_FILE)
        if data.get('scopes') != [SCOPE] or not all(
            isinstance(data.get(key), str) and data[key]
            for key in ('client_id', 'client_secret', 'refresh_token')
        ):
            return result()
        body = urlencode(dict(grant_type='refresh_token', client_id=data['client_id'],
            client_secret=data['client_secret'], refresh_token=data['refresh_token'])).encode()
        opener = build_opener(ProxyHandler({}), NoRedirect())
        request = Request(TOKEN_URL, data=body,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
        fd = os.open(RESERVATION, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write('One refresh diagnostic reserved; no automatic retry.\n')
            stream.flush()
            os.fsync(stream.fileno())
        try:
            response = opener.open(request, timeout=SOCKET_TIMEOUT)
        except HTTPError as error:
            response = error
        with response:
            code = response.code
            status = code if type(code) is int and 100 <= code <= 599 else None
            return parse_response(response, status)
    except (Exception, KeyboardInterrupt):
        return result(http_status=status)


def main():
    output = result()
    previous = None
    installed = False
    def deadline(*_):
        raise TimeoutError()
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        previous = signal.signal(signal.SIGALRM, deadline)
        installed = True
        signal.alarm(TOTAL_TIMEOUT)
        output = run()
    except (Exception, KeyboardInterrupt):
        pass
    finally:
        if installed:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
    print(json.dumps(output))
    return 0 if output['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
