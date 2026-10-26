"""Arbitrage-only Gmail transport. No SMTP credentials or automatic send retries."""
import base64
import json
import os
import stat
import tempfile
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler

SCOPE = 'https://www.googleapis.com/auth/gmail.send'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
SEND_URL = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'


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
    with build_opener(NoRedirect()).open(Request(url, data=body, headers=headers), timeout=30) as response:
        return json.loads(response.read(1024 * 1024))


def send_message(message, token_file: Path) -> None:
    """Refresh on each job; keep short-lived access tokens in memory only."""
    from urllib.parse import urlencode
    failed = False
    try:
        data = read_private(token_file)
        if data.get('scopes') != [SCOPE] or not all(data.get(k) for k in ('client_id', 'client_secret', 'refresh_token')):
            raise GmailError('Invalid Gmail authorization')
        token = post(TOKEN_URL, urlencode({
            'grant_type': 'refresh_token', 'client_id': data['client_id'],
            'client_secret': data['client_secret'], 'refresh_token': data['refresh_token'],
        }).encode(), {'Content-Type': 'application/x-www-form-urlencoded'})
        if token.get('scope') and set(token['scope'].split()) != {SCOPE}:
            raise GmailError('Unexpected Gmail scopes')
        access = token['access_token']
        if not isinstance(access, str) or not access:
            raise GmailError('Invalid Gmail access token')
        if token.get('refresh_token'):
            data['refresh_token'] = token['refresh_token']
            write_private(token_file, data)
        result = post(SEND_URL, json.dumps({'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}).encode(),
                      {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + access})
        if not result.get('id'):
            raise GmailError('Missing Gmail submission acknowledgement')
    except Exception:
        failed = True
    # Raise outside the handler so even formatted tracebacks omit provider errors.
    if failed:
        raise GmailError('Gmail API delivery failed; authorization or submission requires operator review')
