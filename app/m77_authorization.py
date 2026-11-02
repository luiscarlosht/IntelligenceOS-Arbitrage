"""Fresh M77-only owner permission. No old approval can authorize this operation."""
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import re

from app.m65_intelligence import observed
from app.m77_policy import BUDGET, OPERATION
from app.m77_policy import implementation
from app.observations import fingerprint

FIELDS={'schema','mode','approved','execution_permission','operation_id','preflight_sha256',
        'implementation_sha256','evidence_sha256','account_binding_sha256','account_reference','marketplace_id',
        'manifest_sha256','manifest_file_sha256','completion_file_sha256','contract_file_sha256',
        'request_definitions_sha256','budget','review_reference','issued_at','expires_at','no_retry','no_replay'}


def bindings(report: dict) -> dict:
    return {k:deepcopy(report[k]) for k in ('operation_id','implementation_sha256','evidence_sha256',
        'account_binding_sha256','account_reference','marketplace_id','manifest_sha256','manifest_file_sha256',
        'completion_file_sha256','contract_file_sha256','budget')} | dict(
            preflight_sha256=fingerprint(report),request_definitions_sha256=fingerprint(report['requests']))


def check(auth: dict,report: dict,now: datetime | None=None) -> None:
    now=now or datetime.now(timezone.utc)
    if (not isinstance(auth,dict) or set(auth)!=FIELDS or type(auth['schema']) is not int or auth['schema']!=1
            or auth['mode']!='M77_EXPLICIT_OWNER_AUTHORIZATION' or auth['approved'] is not True
            or auth['execution_permission'] is not True or auth['no_retry'] is not True or auth['no_replay'] is not True
            or auth['operation_id']!=OPERATION or any(auth[k]!=v for k,v in bindings(report).items())
            or auth['implementation_sha256']!=implementation() or auth['budget']!=BUDGET
            or any(type(v) is not int for v in auth['budget'].values())
            or not isinstance(auth['review_reference'],str)
            or not re.fullmatch(r'manual:[A-Za-z0-9._-]{1,80}',auth['review_reference'])):
        raise ValueError('Exact separate M77 owner permission required')
    start=observed(auth['issued_at']);end=observed(auth['expires_at'])
    if not start or not end:raise ValueError('Aware owner authorization timestamps required')
    start=datetime.fromisoformat(start);end=datetime.fromisoformat(end)
    if not start<=now<end or not timedelta(0)<end-start<=timedelta(seconds=600):
        raise ValueError('Fresh maximum ten-minute authorization required')


def owner_authorization(report: dict,reference: str,*,now: datetime | None=None) -> dict:
    now=now or datetime.now(timezone.utc)
    auth=dict(schema=1,mode='M77_EXPLICIT_OWNER_AUTHORIZATION',approved=True,execution_permission=True,
        **bindings(report),review_reference=reference,issued_at=now.isoformat(),
        expires_at=(now+timedelta(seconds=600)).isoformat(),no_retry=True,no_replay=True)
    check(auth,report,now);return auth
