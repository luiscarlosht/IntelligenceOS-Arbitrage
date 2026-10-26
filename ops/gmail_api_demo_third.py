"""Explicit third DEMO attempt; independent marker, no retries or schedules."""
import argparse
from email.message import EmailMessage
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.gmail_api import send_message
from ops.gmail_stage_tracking import StageTracker

TOKEN_FILE = Path('/root/.config/arbitrage-gmail/token.json')
MARKER = ROOT / 'var/diagnostics/gmail-api-demo-3.attempted'
STAGES = ROOT / 'var/diagnostics/gmail-api-demo-3.stages.jsonl'
RECIPIENT = 'luiscarloshernandez@hotmail.com'
TOTAL_TIMEOUT = 90


def build_message(sender):
    if not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@gmail\.com', sender):
        raise ValueError('Authorized primary Gmail sender required')
    message = EmailMessage()
    message['From'] = sender
    message['To'] = RECIPIENT
    message['Subject'] = 'Arbitrage fictional DEMO — Gmail API attempt 3'
    message.set_content('Fictional DEMO fixtures only. No live opportunities or purchase approval. '
                        'Explicit third Gmail API test; no automatic retry.')
    for name, maintype, subtype in (
        ('DEMO.xlsx', 'application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
        ('DEMO.md', 'text', 'markdown'),
    ):
        path = ROOT / 'var/demo' / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Both existing DEMO attachments required')
        message.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=name)
    return message


def execute(sender, *, tracker=None):
    # Never inspect or change previous attempt/refresh markers. This is attempt 3.
    fd = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write('Gmail API DEMO attempt 3 reserved; not a delivery receipt.\n')
        stream.flush()
        os.fsync(stream.fileno())
    tracker = tracker if tracker is not None else StageTracker(STAGES)
    try:
        tracker('message_construction', 'started')
        message = build_message(sender)
        # Persist only filenames/hashes, never content or addresses.
        with os.fdopen(os.open(MARKER, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW), 'a') as stream:
            for part in message.iter_attachments():
                stream.write(part.get_filename() + ' sha256=' +
                    hashlib.sha256(part.get_payload(decode=True)).hexdigest() + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        tracker('message_construction', 'completed')
    except Exception:
        tracker('message_construction', 'failed', error_category='validation')
        raise
    send_message(message, TOKEN_FILE, observe=tracker)
    return tracker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sender', required=True)
    parser.add_argument('--send', action='store_true', required=True)
    args = parser.parse_args()
    tracker = StageTracker(STAGES)
    output = dict(attempt=3, acceptance_observed=False, automatic_retry=False)
    previous = None
    installed = False
    def deadline(*_):
        raise TimeoutError()
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        previous = signal.signal(signal.SIGALRM, deadline)
        installed = True
        signal.alarm(TOTAL_TIMEOUT)
        execute(args.sender, tracker=tracker)
    except (Exception, KeyboardInterrupt):
        pass
    finally:
        if installed:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
    output.update(acceptance_observed=tracker.acceptance_observed,
        last_completed_stage=tracker.last_completed,
        submission_started=tracker.submission_started)
    print(json.dumps(output))
    return 0 if output['acceptance_observed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
