"""Operator-only SendGrid authentication check. Never submits a message."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shlex
import resource
import smtplib
import ssl
import sys


CREDENTIAL_VARIABLES = (
    'SMTP_APP_PASSWORD', 'SMTP_PASSWORD', 'EMAIL_SMTP_PASS', 'EMAIL_SMTP_PASSWORD',
)
ENV_PATH = Path('/root/.weinstein_env')


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


class AmbiguousCredential(Exception):
    def __init__(self, names: list[str]):
        self.names = names


def load_credential(variable: str | None = None) -> str:
    """Parse only approved credential assignments as data; never source or expand."""
    if variable is not None and variable not in CREDENTIAL_VARIABLES:
        raise ValueError()
    values: dict[str, str] = {}
    with ENV_PATH.open() as stream:
        for line in stream:
            match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$', line)
            if not match or match[1] not in CREDENTIAL_VARIABLES:
                continue
            name, raw = match[1], match[2]
            if name in values:
                raise ValueError()  # Duplicate credential assignments need review.
            words = shlex.split(raw, comments=True)
            if len(words) > 1:
                raise ValueError()
            value = words[0] if words else ''
            # Reject shell references/substitutions instead of guessing their meaning.
            if any(character in value for character in ('$', '`')):
                raise ValueError()
            values[name] = value
    present = [name for name in CREDENTIAL_VARIABLES if values.get(name)]
    if variable is None:
        if len(present) > 1:
            raise AmbiguousCredential(present)
        if len(present) != 1:
            raise ValueError()
        variable = present[0]
    key = values.get(variable, '')
    if not key or any(character.isspace() for character in key):
        raise ValueError()
    return key


def main(variable: str | None = None) -> int:
    stage = 'terminal'
    client = None
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            print('Stopped: run directly in an interactive SSH terminal.')
            return 1
        stage = 'credential_file'
        key = load_credential(variable)
        stage = 'tls_context'
        context = ssl.create_default_context()
        stage = 'connect'
        client = TrackedSMTP('smtp.sendgrid.net', 2525, timeout=30)
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
        client.login('apikey', key)
        key = ''
        print('Authentication succeeded. No email submitted; delivery not tested.')
        return 0
    except AmbiguousCredential as error:
        print('Stopped: ambiguous credential; nonempty variables present: ' + ', '.join(error.names))
        print('Select the confirmed variable explicitly with --credential-variable NAME.')
        return 1
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
    parser.add_argument('--credential-variable', choices=CREDENTIAL_VARIABLES)
    arguments = parser.parse_args()
    raise SystemExit(main(arguments.credential_variable))
