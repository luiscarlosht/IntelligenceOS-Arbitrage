"""Operator-only Gmail authentication check. Never submits a message."""
from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import re
import shlex
import resource
import smtplib
import ssl
import sys
import warnings


ENV_PATH = Path(__file__).resolve().parents[1] / 'ops' / 'arbitrage-gmail.env'


# Only these public protocol labels may reach output. Never echo arbitrary EHLO
# tokens: a malformed response could contain a credential or encoded payload.
AUTH_LABELS = ('CRAM-MD5', 'PLAIN', 'LOGIN', 'XOAUTH2', 'OAUTHBEARER', 'EXTERNAL', 'GSSAPI', 'NTLM', 'DIGEST-MD5', 'SCRAM-SHA-1', 'SCRAM-SHA-256')
STAGE_LABELS = ('connect', 'ehlo', 'starttls', 'ehlo_after_tls', 'authenticate')


def report_auth_mechanisms(features: dict[str, str]) -> None:
    tokens = features.get('auth', '').split()
    known = [name for name in AUTH_LABELS if name in tokens]
    unknown_count = sum(token not in AUTH_LABELS for token in tokens)
    print('Advertised AUTH mechanisms: ' + (', '.join(known) or 'none recognized')
          + f'; unrecognized_count={unknown_count}')


class TemporaryAuthenticationError(smtplib.SMTPException):
    """Stop login fallback without retaining a raw server reply."""

    def __init__(self, code: int):
        self.smtp_code = code
        super().__init__('Temporary SMTP authentication failure')


class TrackedSMTP(smtplib.SMTP):
    """Record only fixed labels and numeric codes, never SMTP wire contents."""

    def __init__(self, *args, **kwargs):
        self.diagnostic_stage = 'connect'
        super().__init__(*args, **kwargs)

    def getreply(self):
        stage = self.diagnostic_stage if self.diagnostic_stage in STAGE_LABELS else 'unknown'
        try:
            code, reply = super().getreply()
        except smtplib.SMTPServerDisconnected:
            print(f'SMTP response: stage={stage}; code=unavailable; disconnected=True')
            raise
        safe_code = code if type(code) is int and 100 <= code <= 599 else 'unavailable'
        print(f'SMTP response: stage={stage}; code={safe_code}')
        return code, reply

    def auth(self, mechanism, authobject, *, initial_response_ok=True):
        safe_mechanism = mechanism if mechanism in AUTH_LABELS else 'unrecognized'
        print(f'Authentication mechanism attempted: {safe_mechanism}')
        try:
            return super().auth(mechanism, authobject, initial_response_ok=initial_response_ok)
        except smtplib.SMTPAuthenticationError as error:
            if 400 <= error.smtp_code <= 499:
                # login catches SMTPAuthenticationError and tries another mechanism.
                # A different exception type stops it immediately on temporary failure.
                raise TemporaryAuthenticationError(error.smtp_code) from None
            raise


def load_configuration(path: Path) -> str:
    """Read isolated literal settings, without shell expansion or inherited env."""
    values: dict[str, str] = {}
    allowed = {'SMTP_HOST', 'SMTP_PORT', 'SMTP_SECURITY', 'SMTP_USER', 'EMAIL_TO'}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'([A-Z_]+)=(.*)', line)
        if not match or match[1] not in allowed or match[1] in values:
            raise ValueError()
        words = shlex.split(match[2], comments=True)
        if len(words) > 1 or any(c in match[2] for c in ('$', '`', ';')):
            raise ValueError()
        values[match[1]] = words[0] if words else ''
    if (values.get('SMTP_HOST'), values.get('SMTP_PORT'), values.get('SMTP_SECURITY')) != (
            'smtp.gmail.com', '587', 'starttls') or values.get('EMAIL_TO'):
        raise ValueError()
    username = values.get('SMTP_USER') or input('Full Gmail address for Arbitrage: ').strip()
    if not re.fullmatch(r'[A-Za-z0-9._%+\-]+@gmail\.com', username, re.IGNORECASE):
        raise ValueError()
    return username


def load_bashrc_configuration(path: Path) -> tuple[str, str]:
    """Parse only approved assignment literals; never execute shell contents."""
    values: dict[str, str] = {}
    with path.open() as source:
        for line in source:
            match = re.match(
                r'^\s*(?:export\s+)?((?:SMTP_|EMAIL_)[A-Za-z0-9_]+)=(.*)$',
                line.rstrip('\n'))
            if not match:
                continue
            name, literal = match.groups()
            if name in values or any(c in literal for c in ('$', '`', ';', '&', '|', '<', '>', '\\')):
                raise ValueError()
            words = shlex.split(literal, comments=True)
            if len(words) > 1:
                raise ValueError()
            values[name] = words[0] if words else ''
    # Missing transport settings use these fixed Gmail-only defaults.
    for name, expected in (('SMTP_HOST', 'smtp.gmail.com'), ('SMTP_PORT', '587'),
                           ('SMTP_SECURITY', 'starttls')):
        if values.get(name, expected) != expected:
            raise ValueError()
    def select(names: tuple[str, str]) -> str:
        present = [values[name] for name in names if name in values]
        if len(present) != 1 or not present[0]:
            raise ValueError()  # Alias pairs are ambiguous even if identical.
        return present[0]
    username = select(('SMTP_USER', 'SMTP_USERNAME'))
    key = select(('SMTP_PASSWORD', 'SMTP_APP_PASSWORD')).replace(' ', '')
    if not re.fullmatch(r'[A-Za-z0-9._%+\-]+@gmail\.com', username, re.IGNORECASE):
        raise ValueError()
    if not re.fullmatch(r'[A-Za-z]{16}', key):
        raise ValueError()  # Shape is not proof of Google provenance.
    return username, key


def load_credential() -> str:
    """New Google App Password only; never reuse inherited provider secrets."""
    if getpass.getpass is not getpass.unix_getpass:
        raise ValueError()  # Require a platform with hidden terminal entry.
    # unix_getpass opens /dev/tty with unbuffered FileIO; buffered r+
    # requires seeking and fails on terminals before the prompt is displayed.
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        key = getpass.getpass('Separate Arbitrage Google App Password (hidden): ')
    key = key.replace(' ', '')
    if not re.fullmatch(r'[a-zA-Z]{16}', key):
        raise ValueError()
    return key


def main(config_path: Path = ENV_PATH, *, bashrc_path: Path | None = None) -> int:
    stage = 'terminal'
    client = None
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            print('Stopped: run directly in an interactive SSH terminal.')
            return 1
        stage = 'configuration'
        if bashrc_path is not None:
            username, key = load_bashrc_configuration(bashrc_path)
        else:
            username = load_configuration(config_path)
            stage = 'hidden_credential_entry'
            key = load_credential()
        stage = 'tls_context'
        context = ssl.create_default_context()
        stage = 'connect'
        client = TrackedSMTP('smtp.gmail.com', 587, timeout=30)
        stage = 'ehlo'
        client.diagnostic_stage = stage
        code, _ = client.ehlo()
        if code != 250:
            raise smtplib.SMTPException()
        stage = 'starttls'
        client.diagnostic_stage = stage
        client.starttls(context=context)
        stage = 'ehlo_after_tls'
        client.diagnostic_stage = stage
        code, _ = client.ehlo()
        if code != 250:
            raise smtplib.SMTPException()
        report_auth_mechanisms(client.esmtp_features)
        stage = 'authenticate'
        client.diagnostic_stage = stage
        client.login(username, key)
        key = ''
        print('Authentication succeeded. No email submitted; delivery not tested.')
        return 0
    except (Exception, KeyboardInterrupt) as error:
        # Provider replies and exception text may contain secrets: never print them.
        print(f'Stopped: stage={stage}; error_type={type(error).__name__}. No email submitted.')
        return 1
    finally:
        if client is not None:
            # Close the socket without another SMTP operation or an implicit retry.
            try:
                client.close()
            except Exception:
                pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument('--config', type=Path, default=ENV_PATH)
    sources.add_argument('--bashrc', type=Path, help='Parse SMTP_/EMAIL_ literals without executing shell code')
    arguments = parser.parse_args()
    raise SystemExit(main(arguments.config, bashrc_path=arguments.bashrc))
