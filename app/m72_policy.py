"""Pinned ten-request pilot policy and read-only preflight. Never authorizes itself."""
from datetime import datetime, timezone, timedelta
import csv
from pathlib import Path
import re

from app.m65_intelligence import ASIN, US, CONDITION, read_json, sha256, observed
from app.m66_verification import ACCOUNT
from app.m67_policy import CONTEXT, private_json
from app.m67_state import secure, readonly
from app.m71_manifest import prepare, validate, implementation as m71_implementation
from app.observations import fingerprint

PROPOSAL_SHA256='b09cbea8033caa994b8a79c2451851b1cc91171548e73cadf1c1ebef35731103'
MANIFEST_SHA256='0161373a75c3a744c97bd20a0caefd7afb5527158794c15875ac1946963fa26c'
OPERATION='M72-US-CATALOG-FIRST9-ONCE'
REGISTRY='m72-catalog-pilot.sqlite3'
RESULTS='m72-catalog-pilot-output'
BUDGET=dict(authentication=1,keyword=9,total=10,identifier=0,pages=0,retries=0,refreshes=0,
            restrictions=0,pricing=0,fees=0,fba=0,listings=0,purchases=0,approvals=0)
TIMEOUT=120


def implementation() -> dict:
    root=Path(__file__).parent
    names=('m72.py','m72_policy.py','m72_registry.py','m72_transport.py','m72_execution.py',
           'm72_reporting.py','m67_policy.py','m67_state.py','amazon_pilot.py','amazon_diagnostics.py','ops_notifications.py')
    return dict(m71_implementation(),**{name:sha256(root/name) for name in names})


def load_baseline(path: Path) -> tuple[set[str],str]:
    if path.is_symlink() or any(p.is_symlink() for p in path.parents) or path.stat().st_size>16*1024*1024:
        raise ValueError('Bounded original M70 catalog CSV required')
    digest=sha256(path)
    with path.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        if not {'asin','identity_complete','eligibility','source_sha256'}<=set(reader.fieldnames or []):
            raise ValueError('M70 catalog export columns required')
        asins=set();count=0
        for row in reader:
            count+=1;a=row['asin']
            if count>10000 or not ASIN.fullmatch(a) or a in asins:raise ValueError('Distinct original M70 ASINs required')
            asins.add(a)
    if sha256(path)!=digest:raise ValueError('Baseline drift')
    return asins,digest


def account(private: Path) -> tuple[dict,str]:
    context,digest=private_json(private/CONTEXT)
    if (set(context)!={'account_reference','marketplace_id','condition','seller_id','credentials_sha256'}
            or context['account_reference']!=ACCOUNT or context['marketplace_id']!=US or context['condition']!=CONDITION
            or not isinstance(context['seller_id'],str) or not re.fullmatch('[A-Z0-9]{1,32}',context['seller_id'])
            or not re.fullmatch('[a-f0-9]{64}',context['credentials_sha256'])):
        raise ValueError('Original private account binding required')
    return context,digest


def cooldowns(private: Path) -> list[dict]:
    rows=[]
    for name in ('candidate-executions.sqlite3','m67-executions.sqlite3'):
        db=readonly(private/name)
        try:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='amazon_cooldowns'").fetchone():
                for operation,until,diagnostics in db.execute('SELECT operation,not_before_utc,diagnostics FROM amazon_cooldowns'):
                    if operation=='searchCatalogItems':
                        import json
                        if not observed(until):raise ValueError('Ambiguous saved cooldown')
                        data=json.loads(diagnostics)
                        rate=data.get('rate_limit')
                        if rate is not None:
                            from app.amazon_pacing import positive
                            if positive(rate) is None:raise ValueError('Ambiguous saved pacing rate')
                        rows.append(dict(until=until,rate=rate))
        finally:db.close()
    return sorted(rows,key=fingerprint)


def history_files(private: Path,store: Path,m67_manifest: Path) -> str:
    """Bind every original audit input, including additions, without copying its engine."""
    from app.m63_history import PATTERNS
    paths={p for pattern in PATTERNS for p in private.glob(pattern)}
    paths.update((private/'candidate-executions.sqlite3',private/'m67-executions.sqlite3',store,
                  m67_manifest,m67_manifest.parent/'M66_candidate_ranking.json'))
    if len(paths)>510:raise ValueError('Bounded immutable history inventory required')
    for path in (private/'candidate-executions.sqlite3',private/'m67-executions.sqlite3',store):
        db=readonly(path);db.close()
    values=[]
    for path in sorted(paths):
        # The original M63 authorization proof is required history, not a new
        # catalog source. Do not route it through M70's catalog-only name guard.
        if (path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_file()
                or path.stat().st_size>64*1024*1024
                or re.search(r'credential|account-context|token|\.env',path.name,re.I)):
            raise ValueError('Bounded original history file required; credential values forbidden')
        values.append(dict(path=str(path.absolute()),sha256=sha256(path)))
    return fingerprint(values)


def preflight(proposal: Path,store: Path,private: Path,m67_manifest: Path,m67_digest: str,baseline: Path,*,
              _claimed: bool=False,_locked_report: dict | None=None) -> dict:
    secure(private,directory=True)
    if proposal.is_symlink() or any(p.is_symlink() for p in proposal.parents):raise ValueError('Original proposal required')
    doc,digest=read_json(proposal)
    if digest!=MANIFEST_SHA256 or doc.get('proposal_sha256')!=PROPOSAL_SHA256:raise ValueError('Original pinned M71 proposal required')
    validate(doc)
    history_binding=history_files(private,store,m67_manifest)
    if _locked_report is None:
        if doc!=prepare(private,store,m67_manifest,m67_digest):raise ValueError('Original code/history/configuration drift')
    else:
        # Original M69 readers acquire a shared account lock themselves. While
        # M72 owns that lock exclusively, verify their complete immutable input
        # inventory against the already validated report instead of nesting locks.
        from app.m70_plan import plan
        if (history_binding!=_locked_report['history_files_sha256']
                or doc['pacing']!=plan()['configured_limits']):raise ValueError('Locked history/pacing drift')
    if history_files(private,store,m67_manifest)!=history_binding:raise ValueError('History changed during validation')
    if len(doc['excluded_asins'])<97 or len(doc['checked_eligibility_asins'])!=40:raise ValueError('Historical safeguards missing')
    context,binding=account(private)
    secure(private/'credentials.json')  # Metadata only; no secret-value read in preflight.
    info=(private/'credentials.json').stat()
    credential_metadata=fingerprint(dict(device=info.st_dev,inode=info.st_ino,size=info.st_size,mtime_ns=info.st_mtime_ns,mode=info.st_mode,uid=info.st_uid))
    existing=private/REGISTRY
    if existing.exists() or existing.is_symlink():
        from app.m72_registry import inspect
        inspect(existing)  # Any existing operation, corruption or ambiguous file fails closed.
        if not _claimed:raise ValueError('Permanent pilot operation already claimed; replay forbidden')
    lock=private/'candidate-execution.lock'
    if lock.exists() or lock.is_symlink():secure(lock)
    if (private/RESULTS).exists() or (private/RESULTS).is_symlink():raise ValueError('Existing pilot output requires reconciliation')
    known,baseline_digest=load_baseline(baseline)
    saved_cooldowns=cooldowns(private)
    return dict(schema=1,mode='M72_OFFLINE_PREFLIGHT',operation_id=OPERATION,
        proposal_sha256=PROPOSAL_SHA256,manifest_file_sha256=MANIFEST_SHA256,
        account_reference=ACCOUNT,marketplace_id=US,account_binding_sha256=binding,
        credential_metadata_sha256=credential_metadata,credential_content_verification='DEFERRED_UNTIL_FRESH_AUTHORIZATION',
        history_evidence_sha256=doc['history_evidence_sha256'],excluded_asins_sha256=fingerprint(doc['excluded_asins']),
        history_files_sha256=history_binding,
        historical_exclusions=len(doc['excluded_asins']),checked_eligibility_asins=40,
        queries=doc['queries'][:9],budget=dict(BUDGET),pacing=doc['pacing'],saved_cooldowns=saved_cooldowns,
        baseline_file_sha256=baseline_digest,baseline_distinct_asins=len(known),
        implementation_sha256=implementation(),hard_timeout_seconds=TIMEOUT,socket_timeout_seconds=10,
        execution_authorized=False,actual_requests=0,actual_authentication=0,new_asin_reservations=0)


def check_authorization(auth: dict,report: dict,now: datetime | None=None) -> None:
    now=now or datetime.now(timezone.utc)
    fields={'schema','mode','approved','execution_permission','operation_id','proposal_sha256','manifest_file_sha256',
        'account_reference','marketplace_id','account_binding_sha256','preflight_sha256','implementation_sha256',
        'budget','query_ids','review_reference','reviewed_at','expires_at','no_retry','no_replay'}
    if (not isinstance(auth,dict) or set(auth)!=fields or type(auth['schema']) is not int or auth['schema']!=1
            or auth['mode']!='M72_EXPLICIT_OWNER_AUTHORIZATION' or auth['approved'] is not True
            or auth['execution_permission'] is not True or auth['no_retry'] is not True or auth['no_replay'] is not True
            or auth['operation_id']!=OPERATION or auth['proposal_sha256']!=PROPOSAL_SHA256
            or auth['manifest_file_sha256']!=MANIFEST_SHA256 or auth['account_reference']!=ACCOUNT
            or auth['marketplace_id']!=US or auth['account_binding_sha256']!=report['account_binding_sha256']
            or auth['preflight_sha256']!=fingerprint(report) or auth['implementation_sha256']!=implementation()
            or auth['budget']!=BUDGET or any(type(v) is not int for v in auth['budget'].values())
            or auth['query_ids']!=[q['id'] for q in report['queries']]
            or not isinstance(auth['review_reference'],str) or not re.fullmatch(r'manual:[A-Za-z0-9._-]{1,80}',auth['review_reference'])):
        raise ValueError('Fresh exact M72 account/code/proposal/budget owner authorization required')
    start=observed(auth['reviewed_at']);end=observed(auth['expires_at'])
    if not start or not end:raise ValueError('Aware owner authorization timestamps required')
    start=datetime.fromisoformat(start);end=datetime.fromisoformat(end)
    if not start<=now<end or not timedelta(0)<end-start<=timedelta(minutes=15):raise ValueError('Fresh fifteen-minute maximum authorization required')


def owner_authorization(report: dict,reference: str,*,now: datetime | None=None) -> dict:
    """Called only by the later explicit interactive authorization command."""
    now=now or datetime.now(timezone.utc)
    auth=dict(schema=1,mode='M72_EXPLICIT_OWNER_AUTHORIZATION',approved=True,execution_permission=True,
        operation_id=OPERATION,proposal_sha256=PROPOSAL_SHA256,manifest_file_sha256=MANIFEST_SHA256,
        account_reference=ACCOUNT,marketplace_id=US,account_binding_sha256=report['account_binding_sha256'],
        preflight_sha256=fingerprint(report),implementation_sha256=implementation(),budget=dict(BUDGET),
        query_ids=[q['id'] for q in report['queries']],review_reference=reference,reviewed_at=now.isoformat(),
        expires_at=(now+timedelta(minutes=15)).isoformat(),no_retry=True,no_replay=True)
    check_authorization(auth,report,now);return auth
