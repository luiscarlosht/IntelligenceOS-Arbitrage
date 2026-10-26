"""Private stage evidence for the historical operator-only SMTP DEMO helper."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat


class StageTracker:
    def __init__(self, path: Path):
        self.path = path
        self.accepted = False
        self.submission_started = False

    def call(self, stage, operation, *args, **kwargs):
        if stage not in ('connection_banner', 'ehlo', 'verified_starttls',
                         'ehlo_after_tls', 'authentication', 'mail_from', 'rcpt_to', 'message_data'):
            raise ValueError('Unknown SMTP stage')
        if stage == 'message_data':
            self.submission_started = True
        self.emit(stage, 'started')
        try:
            result = operation(*args, **kwargs)
        except BaseException:
            self.emit(stage, 'failed')
            raise
        if stage == 'message_data' and result[0] == 250:
            self.accepted = True
        self.emit(stage, 'completed')
        return result

    def emit(self, stage, status):
        record = dict(utc=datetime.now(timezone.utc).isoformat(), stage=stage, status=status,
                      smtp_acceptance_observed=self.accepted, submission_started=self.submission_started)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        with os.fdopen(fd, 'a') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                raise ValueError('Stage log must be private and regular')
            stream.write(json.dumps(record) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
