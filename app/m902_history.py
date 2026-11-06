"""Pure historical ledger verification. Standard library only; no I/O or transport."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re

BASELINE_12 = 'b7502888a36b97594e5c79b3f8c47312c1226d80355a03621284660b45da2f1b'
BASELINE_13 = 'c79e2a7788c3b99ee75a17dc3150b9e2a609818ad2de3cce82f082e36c9b79f1'
MAX_LEDGER = 8*1024*1024


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Invalid historical JSON')
        value[key] = item
    return value


def canonical_hash(value: dict) -> str:
    return hashlib.sha256((json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     indent=2, default=str)+'\n').encode()).hexdigest()


def validate_snapshot(raw: bytes, expected: str, prior_expected: str = BASELINE_12) -> dict:
    """Pin every byte and reconstruct the complete reviewed twelve-attempt prefix."""
    if (type(raw) is not bytes or len(raw) > MAX_LEDGER
            or type(expected) is not str or not re.fullmatch('[0-9a-f]{64}', expected)
            or hashlib.sha256(raw).hexdigest() != expected):
        raise ValueError('Historical baseline mismatch')
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid historical JSON')))
    if type(value) is not dict:
        raise ValueError('Historical object required')
    attempts = value.get('attempts')
    if (value.get('pilot') != 'm88-real-six-pilot'
            or type(value.get('ceiling')) is not int or value['ceiling'] != 49
            or value.get('purchase_authorized') is not False
            or value.get('includes_authentication_and_retries') is not True
            or type(value.get('attempts_used')) is not int or value['attempts_used'] != 13
            or type(attempts) is not list or len(attempts) != 13
            or value.get('m89_authentication_only') != 'CLAIMED_NO_REPLAY'):
        raise ValueError('Historical accounting mismatch')
    for number, attempt in enumerate(attempts, 1):
        if (type(attempt) is not dict or type(attempt.get('number')) is not int
                or attempt['number'] != number or attempt.get('status') not in ('COMPLETE', 'FAILED')):
            raise ValueError('Historical attempt mismatch')
    last = attempts[-1]
    if (last.get('phase') != 'authentication' or last.get('candidate_id') is not None
            or last.get('operation') != 'm89-authentication-only' or last['status'] != 'COMPLETE'
            or last.get('token_received') is not True):
        raise ValueError('Completed historical authentication required')
    times = []
    for key in ('reserved_at', 'completed_at'):
        if type(last.get(key)) is not str:
            raise ValueError('Historical timestamp required')
        at = datetime.fromisoformat(last[key])
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError('Aware historical timestamp required')
        times.append(at)
    if times[1] < times[0]:
        raise ValueError('Historical chronology mismatch')
    prior = deepcopy(value)
    prior.pop('m89_authentication_only')
    prior['attempts'].pop()
    prior['attempts_used'] = 12
    if canonical_hash(prior) != prior_expected:
        raise ValueError('Historical prefix mismatch')
    return value
