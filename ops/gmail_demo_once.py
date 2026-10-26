"""One authorized Gmail DEMO submission; no retry or scheduled integration."""
from __future__ import annotations
import argparse
from email.message import EmailMessage
import json
import os
from pathlib import Path
import resource
import signal
import smtplib
import ssl
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ops.smtp_auth_diagnostic import load_bashrc_configuration

from ops.smtp_stage_tracking import StageTracker
MARKER = ROOT / 'var/diagnostics/gmail-demo.attempted'
STAGES = ROOT / 'var/diagnostics/gmail-demo.stages.jsonl'
RECIPIENT = 'luiscarloshernandez@hotmail.com'


def build_message(username, run=lambda name, function, *args, **kwargs: function(*args, **kwargs)):
    message = EmailMessage()
    message['From'] = username
    message['To'] = RECIPIENT
    message['Subject'] = 'Arbitrage fictional DEMO data — one-time Gmail test'
    message.set_content('Fictional DEMO data only. These attachments contain illustrative fixtures, '
                        'not live opportunities or purchase recommendations. One-time Gmail test.')
    for name, maintype, subtype in (
        ('DEMO.xlsx', 'application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
        ('DEMO.md', 'text', 'markdown')):
        path = ROOT / 'var/demo' / name
        if run('attachment_stat_' + name, path.is_file):
            message.add_attachment(run('attachment_read_' + name, path.read_bytes), maintype=maintype, subtype=subtype, filename=name)
    return message


def send_once():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if MARKER.exists() or MARKER.is_symlink():
        print('Stopped: Gmail attempt already reserved; no retry permitted.')
        return 1
    tracker = StageTracker(STAGES)
    last = 'preflight'
    operation_name = 'preflight'
    def run(name, function, *args, **kwargs):
        nonlocal operation_name
        operation_name = name
        return function(*args, **kwargs)
    client = None
    key = ''
    def deadline(*_):
        raise TimeoutError()
    previous = signal.signal(signal.SIGALRM, deadline)
    signal.alarm(120)  # Bounds DNS and the entire attempt, including operations.
    try:
        username, key = run('credential_parse', load_bashrc_configuration, Path('/root/.bashrc'))
        message = build_message(username, run)
        context = run('tls_context', ssl.create_default_context)
        fd = run('attempt_marker_create', os.open, MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        operation_name = 'attempt_marker_write'
        with os.fdopen(fd, 'w') as stream:
            stream.write('One authorized Gmail DEMO attempt; no retries. Not a delivery receipt.\n')
            stream.flush()
            run('attempt_marker_fsync', os.fsync, stream.fileno())
        def call(stage, operation, *args, **kwargs):
            nonlocal last
            result = run(stage, tracker.call, stage, operation, *args, **kwargs)
            last = stage
            return result
        # Reuse the existing tracker, with explicit stages and no implicit QUIT.
        client = run('smtp_initialize', smtplib.SMTP, timeout=15, local_hostname='arbitrage.local')
        for stage, operation, args in [
            ('connection_banner', client.connect, ('smtp.gmail.com', 587)),
            ('ehlo', client.ehlo, ()),
        ]:
            code, _ = call(stage, operation, *args)
            if code != (220 if stage == 'connection_banner' else 250):
                raise smtplib.SMTPException()
        call('verified_starttls', client.starttls, context=context)
        if call('ehlo_after_tls', client.ehlo)[0] != 250:
            raise smtplib.SMTPException()
        # One AUTH mechanism, no login fallback or reconnect.
        client.user, client.password = username, key
        if 'PLAIN' not in client.esmtp_features.get('auth', '').split():
            raise smtplib.SMTPNotSupportedError()
        call('authentication', client.auth, 'PLAIN', client.auth_plain)
        client.password = key = ''
        if call('mail_from', client.mail, username)[0] != 250:
            raise smtplib.SMTPException()
        if call('rcpt_to', client.rcpt, RECIPIENT)[0] not in (250, 251):
            raise smtplib.SMTPException()
        payload = run('message_serialize', message.as_bytes)
        tracker.submission_started = True
        code, _ = call('message_data', client.data, payload)
        if code != 250:
            raise smtplib.SMTPException()
        print('SMTP accepted one DEMO message for ' + RECIPIENT + '. Inbox delivery unverified.')
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps(dict(status='stopped', error_type=type(error).__name__,
                              last_completed_stage=last, operation=operation_name,
                              errno=safe_errno(error),
                              attempt_marker_exists=MARKER.exists() or MARKER.is_symlink(),
                              smtp_acceptance_observed=tracker.accepted,
                              submission_ambiguous=tracker.submission_started and not tracker.accepted,
                              automatic_retry=False)))
        return 1
    finally:
        key = ''
        if client is not None:
            client.password = ''
            try:
                client.close()
            except Exception as error:
                print(json.dumps(dict(status='cleanup_failed', operation='socket_close',
                                      error_type=type(error).__name__, errno=safe_errno(error))))
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def safe_errno(error):
    value = getattr(error, 'errno', None)
    return value if type(value) is int else None


def diagnose():
    """Read-only local checks and bounded DNS; never creates SMTP or markers."""
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    failed = False
    def check(name, function):
        nonlocal failed
        try:
            detail = function()
            print(json.dumps(dict(operation=name, status='ok', detail=detail)))
        except Exception as error:
            failed = True
            print(json.dumps(dict(operation=name, status='failed',
                                  error_type=type(error).__name__, errno=safe_errno(error))))
    def credentials():
        username, key = load_bashrc_configuration(Path('/root/.bashrc'))
        key = ''
        return 'literal parsing passed; values omitted'
    check('credential_parse', credentials)
    for name in ('DEMO.xlsx', 'DEMO.md'):
        def attachment(name=name):
            path = ROOT / 'var/demo' / name
            if not path.is_file():
                return 'absent; sender would omit'
            return dict(readable=True, bytes=len(path.read_bytes()))
        check('attachment_read_' + name, attachment)
    check('attempt_marker_inspect', lambda: dict(
        exists=MARKER.exists(), symlink=MARKER.is_symlink(),
        action='preserved; no write or retry'))
    check('tls_context', lambda: dict(
        verify_mode=int(ssl.create_default_context().verify_mode),
        check_hostname=ssl.create_default_context().check_hostname))
    def deadline(*_):
        raise TimeoutError()
    previous = signal.signal(signal.SIGALRM, deadline)
    signal.alarm(10)
    try:
        check('dns_resolution', lambda: dict(address_count=len(socket.getaddrinfo(
            'smtp.gmail.com', 587, type=socket.SOCK_STREAM))))
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    print('No SMTP connection, authentication or submission. DNS deadline=10s; '
          'sender socket timeout=15s; sender whole-attempt deadline=120s.')
    return int(failed)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--send', action='store_true')
    mode.add_argument('--diagnose', action='store_true', help='Read-only checks and DNS; never SMTP')
    args = parser.parse_args()
    raise SystemExit(diagnose() if args.diagnose else send_once())
