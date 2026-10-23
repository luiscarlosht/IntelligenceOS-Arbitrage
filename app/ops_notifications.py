"""Opt-in HTTPS heartbeat and failure notifications. Never logs URLs or credentials."""
import json
import math
from pathlib import Path
import ssl
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Notification redirects forbidden')


def validate_config(config: dict) -> None:
    if config.get('enabled') is not True:
        raise ValueError('Notifications are not enabled')
    hosts = config.get('allowed_hosts')
    if not isinstance(hosts, list) or not hosts or not all(isinstance(h, str) for h in hosts):
        raise ValueError('Explicit destination hosts required')
    if not config.get('heartbeat_url'):
        raise ValueError('External heartbeat destination required')
    for key in ('heartbeat_url', 'notification_url'):
        value = config.get(key)
        if not value:
            continue
        if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError('Invalid destination characters')
        url = urlsplit(value)
        if (url.scheme != 'https' or not url.hostname or url.hostname not in hosts
                or url.username or url.password or url.query or url.fragment
                or url.port not in (None, 443) or not url.path.strip('/')):
            raise ValueError('Invalid HTTPS destination')
    token = config.get('notification_token', '')
    if not isinstance(token, str) or '\r' in token or '\n' in token:
        raise ValueError('Invalid notification token')


def post(url: str, body: bytes, token: str = '') -> None:
    headers = {'Content-Type': 'text/plain; charset=utf-8', 'User-Agent': 'IntelligenceOS-ops/1'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(url, data=body, headers=headers, method='POST')
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(request, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise ValueError('Notification delivery failed')
        # Do not retain, log or parse endpoint response bodies.
        response.read(1024)


def deliver(config: dict, failed: bool, now: float, state: dict, send=post) -> dict:
    """Heartbeat every run; alert on transition or each six-hour failure reminder.

    State is updated only after successful acknowledgement. Failure of one endpoint
    does not suppress the other. A receiver acknowledgement is not human receipt.
    """
    validate_config(config)
    if (not isinstance(state, dict) or (state and
            (type(state.get('failed')) is not bool or type(state.get('sent_at')) not in (int, float)
             or not math.isfinite(state['sent_at']) or state['sent_at'] < 0))):
        raise ValueError('Invalid notification delivery state')
    errors = []
    try:
        send(config['heartbeat_url'].rstrip('/') + ('/fail' if failed else ''), b'')
    except Exception:
        errors.append('heartbeat_delivery_failed')
    previous = state.get('failed')
    last_sent = state.get('sent_at', 0)
    due = ((failed and (previous is not True or now - last_sent >= 21600 or now < last_sent))
           or (not failed and previous is True))
    updated = dict(state)
    if config.get('notification_url') and due:
        try:
            send(config['notification_url'],
                 b'IntelligenceOS operations check FAILED; inspect restricted journal.' if failed
                 else b'IntelligenceOS operations check recovered.', config.get('notification_token', ''))
            updated = {'failed': failed, 'sent_at': now}
        except Exception:
            errors.append('failure_notification_delivery_failed')
    if errors:
        # Preserve delivered alert state while reporting retryable transport failures.
        return {'state': updated, 'issues': errors}
    return {'state': updated, 'issues': []}


def read_config(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('Notification credential file must be private')
    config = json.loads(path.read_text())
    validate_config(config)
    return config
