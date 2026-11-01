"""Explicitly authorized one-shot M72 execution. Import and dry-run never dispatch."""
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import signal
import time

from app.amazon_pacing import OperationPacer
from app.m65_intelligence import read_json, sha256, private_values
from app.m67_policy import private_json
from app.m67_state import secure
from app.m71_adapter import validate_page, clean_product
from app.m72_policy import (preflight,check_authorization,account,load_baseline,BUDGET,
    REGISTRY,RESULTS,TIMEOUT,OPERATION,PROPOSAL_SHA256)
from app.m72_registry import Registry,inspect
from app.m72_transport import PilotTransport
from app.m72_reporting import export
from app.observations import fingerprint


def run_claimed(registry: Registry,transport: PilotTransport,proposal: dict,report: dict,*,
                before_request,pacer,deadline: float,monotonic=time.monotonic) -> None:
    """Internal injection seam for a freshly claimed operation; no resume path."""
    if registry.count()!=0:raise ValueError('Fresh operation only; no replay')
    token_deadline=None
    try:
        for slot in range(1,11):
            before_request()
            if slot>1:pacer.acquire('searchCatalogItems',deadline)
            before_request()
            if monotonic()>=deadline or (token_deadline is not None and monotonic()>=token_deadline):raise TimeoutError
            request=transport.build_slot(slot);transport.validate_slot(request,slot)
            # Persist exact intent before dispatch; authentication also consumes a slot.
            phase,params=transport.scope(slot)
            registry.consume(slot,fingerprint(dict(slot=slot,phase=phase,parameters=params)))
            try:reply=transport.send_slot(request,slot)
            except BaseException as error:
                if slot>1:
                    from app.amazon_diagnostics import AmazonFailure
                    if isinstance(error,AmazonFailure):pacer.observe('searchCatalogItems',error.http_status,getattr(error,'rate_headers',{}))
                raise
            if not isinstance(reply,dict) or set(reply)!={'status','headers','body'}:raise ValueError('Explicit HTTP envelope required')
            status=reply['status'];headers=reply['headers'];body=reply['body']
            if type(status) is not int or not isinstance(headers,dict) or not isinstance(body,dict):raise ValueError('Uncertain response')
            if slot>1:pacer.observe('searchCatalogItems',status,headers)
            if status!=200 or any(str(k).casefold()=='retry-after' for k in headers):raise ValueError('Stop on failure/throttle')
            if monotonic()>=deadline:raise TimeoutError
            page=None
            if slot==1:
                transport.accept_authentication(body)
                token_deadline=monotonic()+body['expires_in']
            else:
                items,token=validate_page(body,prior_tokens=set())
                # Save a continuation cursor as evidence only; never follow it.
                query=report['queries'][slot-2]
                page=dict(query_reference=query['id'],page_index=0,page_token=None,
                    pagination=dict(nextToken=token) if token else {},marketplace_id=report['marketplace_id'],
                    http_status=200,observed_at=datetime.now(timezone.utc).isoformat(),
                    items=[clean_product(i,transport.secrets()|private_values(body)) for i in items],
                    proposal_sha256=PROPOSAL_SHA256,operation_id=OPERATION,
                    request_slot=slot,response_sha256=fingerprint(body))
            registry.response(slot,page,fingerprint(body))
            # A late expiry/history drift stops before the next request, but the
            # successful bounded response is already durably recoverable.
        registry.finish(True)
    except BaseException:
        registry.finish(False)  # If storage fails, the permanent CLAIM still burns the operation.
    finally:transport.clear()


def execute(proposal: Path,store: Path,private: Path,m67_manifest: Path,m67_digest: str,baseline: Path,
            authorization: Path,authorization_digest: str,*,execution_flag: bool) -> dict:
    if execution_flag is not True:raise ValueError('Explicit --execute-live required')
    args=(proposal,store,private,m67_manifest,m67_digest,baseline)
    initial=preflight(*args)
    auth,auth_sha=private_json(authorization)
    if auth_sha!=authorization_digest:raise ValueError('Exact private authorization file required')
    check_authorization(auth,initial)
    lock_path=private/'candidate-execution.lock'
    if lock_path.exists():secure(lock_path)
    lock=os.open(lock_path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    registry=None;transport=None
    old_handlers={};timer_installed=False
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        report=preflight(*args,_locked_report=initial)
        if report!=initial:raise ValueError('Preflight changed while acquiring account lock')
        check_authorization(auth,report)
        context,binding=account(private)
        credentials,credentials_sha=private_json(private/'credentials.json')
        if credentials_sha!=context['credentials_sha256'] or binding!=report['account_binding_sha256']:
            raise ValueError('Credentials/account binding drift')
        transport=PilotTransport(credentials,seller_id=context['seller_id'])
        # Refuse an already-used signal timer. Execution is a bounded main-thread CLI.
        if signal.getsignal(signal.SIGALRM)!=signal.SIG_DFL or signal.getitimer(signal.ITIMER_REAL)[0]:
            raise ValueError('Exclusive execution deadline unavailable')
        import resource
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        pacer=OperationPacer(rates={'searchCatalogItems':report['pacing']['search_rps_cap']},headroom=report['pacing']['headroom'])
        for cooldown in report['saved_cooldowns']:
            pacer.restore_cooldown('searchCatalogItems',cooldown['until'])
            if cooldown['rate'] is not None:pacer.rates['searchCatalogItems']=min(pacer.rates['searchCatalogItems'],float(cooldown['rate']))
        def interrupted(_signal,_frame):raise KeyboardInterrupt
        for number in (signal.SIGALRM,signal.SIGTERM,signal.SIGHUP):
            old_handlers[number]=signal.signal(number,interrupted)
        signal.setitimer(signal.ITIMER_REAL,TIMEOUT);timer_installed=True
        registry=Registry(private/REGISTRY,dict(operation_id=OPERATION,preflight=report,
            authorization_sha256=auth_sha,account_binding_sha256=binding))
        def before_request():
            check_authorization(auth,report)
            now_auth,now_sha=private_json(authorization)
            if now_sha!=auth_sha or now_auth!=auth:raise ValueError('Authorization file drift')
            if preflight(*args,_claimed=True,_locked_report=report)!=report:raise ValueError('Current code/history/configuration drift')
            current,source=private_json(private/'credentials.json')
            if source!=credentials_sha or current!=credentials:raise ValueError('Current credentials drift')
        run_claimed(registry,transport,read_json(proposal)[0],report,before_request=before_request,
                    pacer=pacer,deadline=time.monotonic()+TIMEOUT)
        # Stop the hard dispatch timer before offline export. The journal remains
        # recoverable if export is interrupted; reporting never permits replay.
        signal.setitimer(signal.ITIMER_REAL,0);timer_installed=False
        registry.close();registry=None
        return export(inspect(private/REGISTRY),read_json(proposal)[0],load_baseline(baseline)[0],private/RESULTS)
    finally:
        if timer_installed:signal.setitimer(signal.ITIMER_REAL,0)
        for number,handler in old_handlers.items():signal.signal(number,handler)
        if transport is not None:transport.clear()
        if registry is not None:registry.close()
        os.close(lock)
