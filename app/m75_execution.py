"""Separate authorization-gated M75 execution. No automatic live invocation."""
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import re
import signal
import time

from app.amazon_pacing import OperationPacer
from app.m65_intelligence import private_values
from app.m67_policy import private_json
from app.m67_state import secure
from app.m71_adapter import validate_page, clean_product
from app.m74_plan import OPERATION
from app.m75_authorization import check
from app.m75_policy import preflight, REGISTRY, RESULTS, TIMEOUT, account, requests
from app.m75_registry import Registry, inspect
from app.m75_transport import Transport
from app.observations import fingerprint


def run_claimed(registry,transport,report,*,before_request,pacer,deadline,monotonic=time.monotonic):
    try:registry.start()  # A second entry cannot change a stopped or started run.
    except BaseException:
        transport.clear();raise
    token_deadline=None
    def boundary():
        before_request()
        if monotonic()>=deadline or (token_deadline is not None and monotonic()>=token_deadline):raise TimeoutError
    try:
        for slot in range(1,22):
            boundary()
            if slot>1:pacer.acquire('searchCatalogItems',deadline)
            boundary()
            request=transport.build_slot(slot);transport.validate_slot(request,slot)
            registry.consume(slot)  # Committed intent precedes every possible dispatch.
            boundary()  # Expiry/drift here burns the slot without sending.
            reply=transport.send_slot(request,slot)
            if not isinstance(reply,dict) or set(reply)!={'status','headers','body'}:raise ValueError('Explicit response envelope required')
            status=reply['status'];headers=reply['headers'];body=reply['body']
            if type(status) is not int or not isinstance(headers,dict) or not isinstance(body,dict):raise ValueError('Ambiguous response')
            if slot>1:pacer.observe('searchCatalogItems',status,headers)
            if status!=200 or any(str(k).casefold()=='retry-after' for k in headers):raise ValueError('Stop on error/throttle')
            if monotonic()>=deadline:raise TimeoutError
            page=None
            if slot==1:
                transport.accept_authentication(body);token_deadline=monotonic()+body['expires_in']
            else:
                items,token=validate_page(body,prior_tokens=set())
                secrets=transport.secrets()|private_values(body)
                if token:
                    for secret in sorted(secrets,key=len,reverse=True):
                        if secret:token=token.replace(secret,'[REDACTED]')
                page=dict(query_reference=requests()[slot-2]['query_id'],page_index=0,page_token=None,
                    pagination=dict(nextToken=token) if token else {},marketplace_id=report['marketplace_id'],
                    http_status=200,observed_at=datetime.now(timezone.utc).isoformat(),
                    items=[clean_product(i,secrets) for i in items],
                    operation_id=OPERATION,manifest_sha256=report['manifest_sha256'],
                    request_definition_sha256=fingerprint(requests()[slot-2]),request_slot=slot,
                    response_sha256=fingerprint(body))
            registry.response(slot,page,fingerprint(body))
        registry.finish(True)
    except BaseException:
        registry.finish(False)
    finally:transport.clear()


def authorization_file(path: Path,private: Path):
    if (path.parent.absolute()!=private.absolute() or any(p.is_symlink() for p in path.parents)
            or not re.fullmatch(r'm75-owner-authorization-[A-Za-z0-9._-]+\.json',path.name)):
        raise ValueError('Separate private M75 owner artifact required')
    return private_json(path)


def execute(m74_dir: Path,evidence: dict,authorization: Path,authorization_sha256: str,*,execute_live: bool):
    if execute_live is not True:raise ValueError('Explicit --execute-live required')
    prepared=preflight(m74_dir,evidence);report=prepared.report;private=evidence['private']
    auth,digest=authorization_file(authorization,private)
    if digest!=authorization_sha256:raise ValueError('Exact authorization file digest required')
    check(auth,report)
    secure(private/'candidate-execution.lock')
    lock=os.open(private/'candidate-execution.lock',os.O_RDWR|os.O_NOFOLLOW)
    registry=transport=None;handlers={};timer=False
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        prepared.guard();check(auth,report)
        current_auth,current_auth_digest=authorization_file(authorization,private)
        if current_auth!=auth or current_auth_digest!=digest:raise ValueError('Owner artifact drift before credential access')
        if (private/REGISTRY).exists() or (private/REGISTRY).is_symlink():raise ValueError('No replay')
        context,binding=account(private)
        credentials,credential_digest=private_json(private/'credentials.json')
        if credential_digest!=context['credentials_sha256'] or binding!=report['account_binding_sha256']:
            raise ValueError('Original credential/account binding required')
        transport=Transport(credentials,seller_id=context['seller_id'])
        if signal.getsignal(signal.SIGALRM)!=signal.SIG_DFL or signal.getitimer(signal.ITIMER_REAL)[0]:
            raise ValueError('Exclusive hard deadline unavailable')
        import resource
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        rate=min(1.,float(report['pacing']['search_rps_cap'])*float(report['pacing']['headroom']))
        pacer=OperationPacer(rates={'searchCatalogItems':rate/float(report['pacing']['headroom'])},headroom=report['pacing']['headroom'])
        for saved in report['saved_cooldowns']:
            pacer.restore_cooldown('searchCatalogItems',saved['until'])
            if saved['rate'] is not None:pacer.rates['searchCatalogItems']=min(pacer.rates['searchCatalogItems'],float(saved['rate']))
        def interrupted(_signal,_frame):raise KeyboardInterrupt
        for number in (signal.SIGALRM,signal.SIGTERM,signal.SIGHUP):handlers[number]=signal.signal(number,interrupted)
        signal.setitimer(signal.ITIMER_REAL,TIMEOUT);timer=True
        registry=Registry(private/REGISTRY,dict(operation_id=OPERATION,preflight=report,authorization_sha256=digest))
        def boundary():
            check(auth,report)
            now,current=authorization_file(authorization,private)
            if current!=digest or now!=auth:raise ValueError('Owner artifact drift')
            prepared.guard()
            if inspect(private/REGISTRY)['binding']['preflight']!=report:raise ValueError('Registry binding drift')
            current_credentials,current_digest=private_json(private/'credentials.json')
            if current_digest!=credential_digest or current_credentials!=credentials:raise ValueError('Credential drift')
            check(auth,report)
        run_claimed(registry,transport,report,before_request=boundary,pacer=pacer,deadline=time.monotonic()+TIMEOUT)
        signal.setitimer(signal.ITIMER_REAL,0);timer=False
        registry.close();registry=None
        from app.m75_reporting import export
        return export(inspect(private/REGISTRY),prepared.manifest,prepared.baseline,private/RESULTS)
    finally:
        if timer:signal.setitimer(signal.ITIMER_REAL,0)
        for number,handler in handlers.items():signal.signal(number,handler)
        if transport is not None:transport.clear()
        if registry is not None:registry.close()
        os.close(lock)
