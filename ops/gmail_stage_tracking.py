"""Owner-only, allowlisted Gmail API stage evidence; never provider payloads."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat

from app.gmail_api import GOOGLE_REASONS

STAGES = frozenset(('message_construction', 'credential_read', 'credential_validation', 'token_refresh',
    'refresh_response_validation', 'token_rotation', 'message_serialization',
    'message_submission', 'acceptance_validation'))


class StageTracker:
    def __init__(self, path: Path):
        self.path = path
        self.last_completed = None
        self.acceptance_observed = False
        self.submission_started = False

    def __call__(self, stage, status, **details):
        if stage not in STAGES or status not in ('started', 'completed', 'failed'):
            raise ValueError('Invalid diagnostic event')
        if status == 'completed':
            self.last_completed = stage
        if stage == 'message_submission' and status == 'started':
            self.submission_started = True
        if stage == 'acceptance_validation' and status == 'completed' and details.get('acceptance_observed') is True:
            self.acceptance_observed = True
        record = dict(time=datetime.now(timezone.utc).isoformat(), stage=stage,
            status=status, last_completed_stage=self.last_completed,
            acceptance_observed=self.acceptance_observed,
            submission_started=self.submission_started)
        for key in ('http_status', 'errno'):
            if type(details.get(key)) is int:
                record[key] = details[key]
        if details.get('error_category') in ('http', 'network', 'validation', 'other'):
            record['error_category'] = details['error_category']
        reasons = details.get('google_reasons')
        if isinstance(reasons, list):
            record['google_reasons'] = sorted({r for r in reasons if isinstance(r, str) and r in GOOGLE_REASONS})
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        with os.fdopen(fd, 'a') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('Diagnostic file must be private and regular')
            stream.write(json.dumps(record) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
