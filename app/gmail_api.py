"""Arbitrage-only Gmail transport. No SMTP credentials or automatic send retries."""
import base64
import json
import os
import stat
import tempfile
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

SCOPE = 'https://www.googleapis.com/auth/gmail.send'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
SEND_URL = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'


GOOGLE_REASONS = frozenset((
    'accessNotConfigured', 'serviceDisabled', 'SERVICE_DISABLED',
    'forbidden', 'insufficientPermissions', 'ACCESS_TOKEN_SCOPE_INSUFFICIENT',
    'authError', 'UNAUTHENTICATED', 'PERMISSION_DENIED', 'invalid_grant',
    'invalid_client', 'unauthorized_client', 'invalid_request',
    'rateLimitExceeded', 'userRateLimitExceeded', 'dailyLimitExceeded',
    'quotaExceeded', 'RESOURCE_EXHAUSTED', 'backendError', 'internalError',
    'badRequest', 'INVALID_ARGUMENT', 'FAILED_PRECONDITION',
))


def safe_google_reasons(error):
    """Read a bounded error body; return only known public identifiers."""
    try:
        raw = error.read(16385)
        if len(raw) > 16384:
            return []
        payload = json.loads(raw)
        value = payload.get('error')
        candidates = []
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, dict):
            candidates.append(value.get('status'))
            for key in ('errors', 'details'):
                items = value.get(key, [])
                if isinstance(items, list):
                    candidates.extend(item.get('reason') for item in items if isinstance(item, dict))
        return sorted({item for item in candidates if isinstance(item, str) and item in GOOGLE_REASONS})
    except Exception:
        return []


class GmailError(RuntimeError):
    """Safe operational error; never includes provider payloads or credentials."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_private(path: Path) -> dict:
    """Reject symlinks, foreign ownership and group/world access before reading."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise GmailError('Gmail credential file must be owner-only and regular')
        return json.load(stream)


def write_private(path: Path, data: dict) -> None:
    """Atomic 0600 credential publication in an existing private directory."""
    parent = path.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise GmailError('Gmail credential directory must be owner-only')
    fd, name = tempfile.mkstemp(dir=parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def post(url: str, body: bytes, headers: dict) -> dict:
    # Default TLS certificate verification; prohibit bearer-bearing redirects.
    with build_opener(ProxyHandler({}), NoRedirect()).open(
        Request(url, data=body, headers=headers, method='POST'), timeout=30
    ) as response:
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise GmailError('Oversized Gmail response')
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise GmailError('Invalid Gmail response')
        return data


def send_message(message, token_file: Path, *, observe=None) -> None:
    """Refresh on each job; keep short-lived access tokens in memory only."""
    from urllib.parse import urlencode
    failed = False
    stage = 'credential_read'
    def event(status, **details):
        if observe is not None:
            observe(stage, status, **details)
    def advance(name):
        nonlocal stage
        event('completed')
        stage = name
        event('started')
    try:
        event('started')
        data = read_private(token_file)
        advance('credential_validation')
        if data.get('scopes') != [SCOPE] or not all(isinstance(data.get(k), str) and data[k] for k in ('client_id', 'client_secret', 'refresh_token')):
            raise GmailError('Invalid Gmail authorization')
        advance('token_refresh')
        token = post(TOKEN_URL, urlencode({
            'grant_type': 'refresh_token', 'client_id': data['client_id'],
            'client_secret': data['client_secret'], 'refresh_token': data['refresh_token'],
        }).encode(), {'Content-Type': 'application/x-www-form-urlencoded'})
        advance('refresh_response_validation')
        if 'error' in token:
            raise GmailError('Unexpected OAuth error response')
        if 'scope' in token and (not isinstance(token['scope'], str) or set(token['scope'].split()) != {SCOPE}):
            raise GmailError('Unexpected Gmail scopes')
        # Reject an explicitly incompatible token type before constructing a header.
        if 'token_type' in token and (not isinstance(token['token_type'], str) or token['token_type'].lower() != 'bearer'):
            raise GmailError('Unexpected Gmail token type')
        access = token['access_token']
        if not isinstance(access, str) or not access:
            raise GmailError('Invalid Gmail access token')
        if token.get('refresh_token'):
            if not isinstance(token['refresh_token'], str):
                raise GmailError('Invalid replacement refresh token')
            advance('token_rotation')
            data['refresh_token'] = token['refresh_token']
            write_private(token_file, data)
        advance('message_serialization')
        payload = json.dumps({'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}).encode()
        advance('message_submission')
        result = post(SEND_URL, payload,
                      {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + access})
        advance('acceptance_validation')
        if not isinstance(result.get('id'), str) or not result['id']:
            raise GmailError('Missing Gmail submission acknowledgement')
        event('completed', acceptance_observed=True)
    except Exception as error:
        failed = True
        # Read bounded structured reasons only; never log provider text.
        from urllib.error import HTTPError, URLError
        kind = ('http' if isinstance(error, HTTPError) else
                'network' if isinstance(error, (URLError, OSError)) else
                'validation' if isinstance(error, (GmailError, KeyError, ValueError, TypeError)) else 'other')
        details = {'error_category': kind}
        if isinstance(error, HTTPError) and type(error.code) is int:
            details['http_status'] = error.code
            details['google_reasons'] = safe_google_reasons(error)
        if isinstance(error, OSError) and type(error.errno) is int:
            details['errno'] = error.errno
        try:
            event('failed', **details)
        except Exception:
            pass  # A diagnostic-write failure must not expose provider errors.
    # Raise outside the handler so even formatted tracebacks omit provider errors.
    if failed:
        raise GmailError('Gmail API delivery failed; authorization or submission requires operator review')
