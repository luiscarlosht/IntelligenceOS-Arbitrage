"""Explicit-owner-only M80 read operations. No retries, redirects or credential access on import."""
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import ssl
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler
from app.ops_notifications import NoRedirect
from app.observations import canonical, fingerprint
from app.m67_state import secure
from app.m80_contract import (ACCOUNT, LEDGER, PLAN, OPERATION, RATES, account, read, unique,
                              check_inputs, check_permission, validate)
from app.m80_evidence import validate_response
from app.m80_journal import Journal, inspect

LIMITS={'authentication':16384,'catalog':1024*1024,'offers_batch':4*1024*1024,'restrictions':128*1024}
USER_AGENT='IntelligenceOS-M80/1.0 (Language=Python/3.12)'


def scrub(value, secrets: set[str]):
    if isinstance(value,dict):
        result={}
        for key,item in value.items():
            if key.casefold()=='headers':
                result[key]=({k:scrub(v,secrets) for k,v in item.items() if k.casefold() in
                             ('retry-after','x-amzn-ratelimit-limit','x-amzn-requestid')} if isinstance(item,dict) else scrub(item,secrets))
            elif not re.search('token|secret|credential|authorization|cookie|seller.?id|account|password|links',key,re.I):
                result[key]=scrub(item,secrets)
        return result
    if isinstance(value,list): return [scrub(v,secrets) for v in value]
    if isinstance(value,str):
        for secret in sorted(secrets,key=len,reverse=True):
            if secret: value=value.replace(secret,'[REDACTED]')
    return value


class Transport:
    def __init__(self, credentials:dict, seller_id:str, plan:dict):
        validate(plan)
        self.allowed=deepcopy(plan['requests'])
        if (set(credentials)!={'client_id','client_secret','refresh_token'} or any(not isinstance(v,str) or not v
                or len(v)>8192 for v in credentials.values())): raise ValueError('Bound private credential contract required')
        self.credentials=dict(credentials); self.seller=seller_id; self.token=None

    def secrets(self) -> set[str]: return set(self.credentials.values())|{self.seller}|({self.token} if self.token else set())
    def clear(self) -> None: self.credentials.clear(); self.token=None; self.seller=''

    def build(self, definition:dict) -> Request:
        if definition not in self.allowed: raise ValueError('Unallowlisted request definition')
        headers={'User-Agent':USER_AGENT}
        query=deepcopy(definition['query']); data=None
        if definition['phase']=='authentication':
            data=urlencode(dict(grant_type='refresh_token',**self.credentials)).encode()
            headers['Content-Type']='application/x-www-form-urlencoded'
        else:
            if not self.token: raise ValueError('Token required')
            headers['x-amz-access-token']=self.token
            if 'sellerId' in query: query['sellerId']=self.seller
            if definition['body'] is not None:
                data=canonical(definition['body']).encode(); headers['Content-Type']='application/json'
        url='https://'+definition['host']+definition['path']+('?' + urlencode(query) if query else '')
        return Request(url,data=data,headers=headers,method=definition['method'])

    def validate(self, request:Request, definition:dict) -> None:
        expected=self.build(definition)
        if (request.full_url!=expected.full_url or request.get_method()!=expected.get_method()
                or request.data!=expected.data or dict(request.header_items())!=dict(expected.header_items())
                or request.unredirected_hdrs): raise ValueError('Request escaped frozen contract')

    def accept_authentication(self, body:dict) -> int:
        token=body.get('access_token'); seconds=body.get('expires_in')
        if (str(body.get('token_type','')).casefold()!='bearer' or not isinstance(token,str) or not 1<=len(token)<=8192
                or not token.isascii() or any(c.isspace() or not c.isprintable() for c in token)
                or type(seconds) is not int or seconds<=5): raise ValueError('Bound bearer token and expiry required')
        self.token=token
        return seconds

    def send(self, request:Request, definition:dict) -> dict:
        self.validate(request,definition)
        opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
        try: response=opener.open(request,timeout=10)
        except HTTPError as error: response=error
        with response:
            status=response.status; headers=dict(response.headers or {}); raw=response.read(LIMITS[definition['phase']]+1)
        if len(raw)>LIMITS[definition['phase']]: raise ValueError('Response exceeds bound')
        if status!=200: return dict(status=status,headers=headers,body={})
        body=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite response')))
        if not isinstance(body,dict): raise ValueError('JSON object required')
        return dict(status=status,headers=headers,body=body)


class Pacer:
    def __init__(self, monotonic=time.monotonic, sleep=time.sleep):
        self.monotonic=monotonic; self.sleep=sleep; self.rates=dict(RATES); self.next={}
    def acquire(self, phase:str, deadline:float) -> None:
        if phase=='authentication': return
        wait=max(0,self.next.get(phase,0)-self.monotonic())
        if self.monotonic()+wait>=deadline: raise TimeoutError
        if wait: self.sleep(wait)
        self.next[phase]=self.monotonic()+1/self.rates[phase]
    def observe(self, phase:str, headers:dict) -> None:
        if any(str(k).casefold()=='retry-after' for k in headers): raise ValueError('Stop on Retry-After; never retry')
        rates=[v for k,v in headers.items() if str(k).casefold()=='x-amzn-ratelimit-limit']
        if len(rates)>1: raise ValueError('Ambiguous usage limit')
        if rates and phase in self.rates:
            rate=float(rates[0])
            if not math.isfinite(rate) or rate<=0 or not math.isfinite(1/rate): raise ValueError('Invalid usage rate')
            self.rates[phase]=min(self.rates[phase],rate/2)
            self.next[phase]=max(self.next.get(phase,0),self.monotonic()+1/self.rates[phase])


def run_claimed(journal:Journal, transport, plan:dict, *, before_request, pacer:Pacer,
                monotonic=time.monotonic, utcnow=lambda:datetime.now(timezone.utc)) -> None:
    """Injection seam for synthetic tests; CLI never injects transports or gates."""
    try:
        validate(plan)
        plan=deepcopy(plan)
        journal.start()
    except BaseException:
        transport.clear(); raise
    deadline=monotonic()+600; token_deadline=None
    def boundary():
        before_request()
        if monotonic()>=deadline or token_deadline is not None and monotonic()>=token_deadline: raise TimeoutError
    try:
        for definition in plan['requests']:
            boundary(); pacer.acquire(definition['phase'],min(deadline,token_deadline or deadline)); boundary()
            request=transport.build(definition); transport.validate(request,definition)
            journal.consume(definition)  # FULL synchronous intent commits BEFORE possible send.
            boundary()
            reply=transport.send(request,definition)
            if (not isinstance(reply,dict) or set(reply)!={'status','headers','body'} or type(reply['status']) is not int
                    or not isinstance(reply['headers'],dict) or not isinstance(reply['body'],dict)):
                raise ValueError('Response envelope required')
            slot=definition['slot']; raw=reply['body']
            if len(canonical(raw).encode())>LIMITS[definition['phase']]: raise ValueError('Response phase bound exceeded')
            if slot==1:
                # Never retain auth body, token or token hash, even on failure.
                retained={'authenticated':False}
                if reply['status']==200:
                    seconds=transport.accept_authentication(raw)
                    token_deadline=monotonic()+seconds-5
                    retained={'authenticated':True,'expires_in':seconds}
            else: retained=scrub(raw,transport.secrets())
            safe_headers={str(k).lower():str(v) for k,v in reply['headers'].items()
                          if str(k).lower() in ('x-amzn-ratelimit-limit','retry-after','x-amzn-requestid')}
            safe_headers={k:scrub(v,transport.secrets()) for k,v in safe_headers.items()}
            frame=dict(http_status=reply['status'],headers=safe_headers,body=retained,
                       observed_at=utcnow().isoformat(),source_sha256=fingerprint(retained))
            journal.response(slot,frame)  # Preserve failure evidence; no next request follows failure.
            pacer.observe(definition['phase'],reply['headers'])
            if reply['status']!=200: raise ValueError('Non-200; no retry')
            boundary()
            if slot!=1: validate_response(definition,retained)
        journal.finish(True)
    except BaseException:
        journal.finish(False)
    finally: transport.clear()


def preflight(private:Path, plan_sha:str) -> dict:
    if private.resolve().is_relative_to('/mnt'): raise ValueError('M80 execution state must stay outside deployment volumes')
    plan,sha=read(private/PLAN)
    if sha!=plan_sha or plan.get('private_root')!=str(private.resolve()): raise ValueError('Exact reviewed plan file required')
    check_inputs(plan)
    if (any(Path(str(private/LEDGER)+suffix).exists() or Path(str(private/LEDGER)+suffix).is_symlink() for suffix in ('','-journal','-wal','-shm'))
            or (private/'m80-results').exists() or (private/'m80-results').is_symlink()):
        raise ValueError('Existing M80 claim/results permanently blocks execution')
    if shutil.disk_usage(private).free<512*1024*1024: raise ValueError('512 MiB free reserve required')
    return plan


def execute(private:Path, plan_sha:str, authorization:Path, auth_sha:str, *, execute_live:bool) -> dict:
    if execute_live is not True: raise PermissionError('Explicit --execute-live and separate owner authorization required')
    plan=preflight(private,plan_sha)
    if authorization.parent.resolve()!=private.resolve() or not re.fullmatch(r'm80-owner-authorization-[A-Za-z0-9._-]+\.json',authorization.name):
        raise ValueError('Separate M80 private owner artifact required')
    auth,sha=read(authorization)
    if sha!=auth_sha: raise ValueError('Exact owner artifact file digest required')
    check_permission(auth,plan,datetime.now(timezone.utc))
    lock_fd=os.open(private/'candidate-execution.lock',os.O_RDWR|os.O_NOFOLLOW)
    journal=transport=None; handlers={}; timer=False
    try:
        fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        preflight(private,plan_sha)
        def boundary():
            check_permission(auth,plan,datetime.now(timezone.utc)); check_inputs(plan)
            current,current_sha=read(authorization)
            _,current_plan_sha=read(private/PLAN)
            if current!=auth or current_sha!=auth_sha or current_plan_sha!=plan_sha: raise ValueError('Authorization/plan drift')
            if journal is not None and inspect(private/LEDGER)['binding']!=dict(plan=plan,authorization_sha256=auth_sha,synthetic=False): raise ValueError('Ledger binding drift')
            if transport is not None:
                _,current_credentials_sha=read(private/'credentials.json')
                if current_credentials_sha!=context['credentials_sha256']: raise ValueError('Credential drift')
        boundary()
        context,binding_sha=account(private)
        credentials,credential_sha=read(private/'credentials.json')  # First secret-value read is AFTER all gates/lock.
        if credential_sha!=context['credentials_sha256'] or binding_sha!=plan['account_sha256']: raise ValueError('Credential/account binding mismatch')
        if signal.getsignal(signal.SIGALRM)!=signal.SIG_DFL or signal.getitimer(signal.ITIMER_REAL)[0]: raise ValueError('Exclusive deadline required')
        import resource
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        def interrupted(_number,_frame): raise KeyboardInterrupt
        for number in (signal.SIGALRM,signal.SIGTERM,signal.SIGHUP): handlers[number]=signal.signal(number,interrupted)
        signal.setitimer(signal.ITIMER_REAL,600); timer=True
        journal=Journal(private/LEDGER,dict(plan=plan,authorization_sha256=auth_sha,synthetic=False))
        transport=Transport(credentials,context['seller_id'],plan)
        run_claimed(journal,transport,plan,before_request=boundary,pacer=Pacer())
        signal.setitimer(signal.ITIMER_REAL,0); timer=False
        journal.close(); journal=None
        return inspect(private/LEDGER)
    finally:
        if timer: signal.setitimer(signal.ITIMER_REAL,0)
        for number,handler in handlers.items(): signal.signal(number,handler)
        if transport is not None: transport.clear()
        if journal is not None: journal.close()
        os.close(lock_fd)
