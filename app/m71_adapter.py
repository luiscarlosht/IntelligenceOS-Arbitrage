"""Bounded Catalog adapter with no enabled live transport or execution entry point."""
from copy import deepcopy
from datetime import datetime, timezone
import math
import re
import time
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import Request

from app.amazon_pacing import OperationPacer
from app.m65_intelligence import ASIN, US
from app.m71_manifest import AUTH_URL, HOST, PATH, DATA, validate
from app.observations import canonical, fingerprint


def parameters(query: dict | None=None,token: str | None=None,asins: list[str] | None=None) -> dict:
    params=dict(marketplaceIds=US,includedData=','.join(DATA),pageSize='20')
    if asins is not None:params.update(identifiersType='ASIN',identifiers=','.join(asins))
    elif query is not None:
        params['keywords']=query['keywords']
        if query['classification_ids']:params['classificationIds']=','.join(query['classification_ids'])
    else:raise ValueError('Exactly scoped query required')
    if token is not None:params['pageToken']=token
    return params


class CatalogTransport:
    """Private in-memory credentials only. send() is deliberately disabled in M71.

    A future authorized entry point must bind account/credentials, deadline,
    lock, current history and a fresh owner artifact before enabling TLS transport.
    """
    def __init__(self,credentials: dict):
        if (set(credentials)!={'client_id','client_secret','refresh_token'}
                or any(not isinstance(v,str) or not v or len(v)>8192 for v in credentials.values())):
            raise ValueError('Private credential contract required')
        self._credentials=dict(credentials);self._access=None

    def build(self,phase: str,params: dict) -> Request:
        if phase=='authentication':
            return Request(AUTH_URL,data=urlencode(dict(grant_type='refresh_token',**self._credentials)).encode(),
                           headers={'Content-Type':'application/x-www-form-urlencoded'},method='POST')
        if phase not in ('keyword','identifier') or not self._access:raise ValueError('Catalog scope/token missing')
        return Request('https://'+HOST+PATH+'?'+urlencode(params),headers={'x-amz-access-token':self._access},method='GET')

    def validate(self,request: Request,phase: str,params: dict):
        parsed=urlsplit(request.full_url)
        if parsed.scheme!='https' or parsed.port is not None or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('HTTPS exact endpoint allowlist required')
        if phase=='authentication':
            expected=dict(grant_type=['refresh_token'],**{k:[v] for k,v in self._credentials.items()})
            if (params or request.full_url!=AUTH_URL or request.get_method()!='POST' or not request.data
                    or parse_qs(request.data.decode(),keep_blank_values=True)!=expected):
                raise ValueError('Authentication endpoint/body outside frozen contract')
        elif (phase not in ('keyword','identifier') or parsed.netloc!=HOST or parsed.path!=PATH
                or request.get_method()!='GET' or request.data is not None or not self._access
                or parse_qs(parsed.query,keep_blank_values=True)!={k:[v] for k,v in params.items()}
                or dict(request.header_items()).get('X-amz-access-token')!=self._access):
            raise ValueError('Catalog endpoint/parameters outside frozen contract')
        if phase!='authentication':
            allowed={'marketplaceIds','includedData','pageSize','pageToken'}
            allowed|={'keywords','classificationIds'} if phase=='keyword' else {'identifiers','identifiersType'}
            if (set(params)-allowed or params.get('marketplaceIds')!=US or params.get('includedData')!=','.join(DATA)
                    or params.get('pageSize')!='20' or (phase=='keyword' and not params.get('keywords'))
                    or (phase=='identifier' and params.get('identifiersType')!='ASIN')):
                raise ValueError('Unsupported Catalog operation/filter')
            if phase=='identifier':
                batch=params.get('identifiers','').split(',')
                if not 1<=len(batch)<=20 or len(set(batch))!=len(batch) or any(not ASIN.fullmatch(a) for a in batch):
                    raise ValueError('Bounded distinct explicit ASIN batch required')

    def send(self,request: Request):
        raise PermissionError('M71_PREPARATION_ONLY: live transport disabled')

    def accept_authentication(self,body: dict):
        token=body.get('access_token');expiry=body.get('expires_in')
        if not isinstance(token,str) or not 1<=len(token)<=8192 or type(expiry) is not int or expiry<=0:
            raise ValueError('Ambiguous authentication response')
        self._access=token

    def secrets(self):return set(self._credentials.values())|({self._access} if self._access else set())

    def clear(self):self._access=None;self._credentials.clear()


def clean_product(item: dict,secrets: set[str]) -> dict:
    allowed={'asin','summaries','identifiers','relationships','attributes','productTypes','classifications','dimensions','salesRanks'}
    def scrub(value):
        if isinstance(value,dict):
            return {k:scrub(v) for k,v in value.items() if isinstance(k,str) and not re.search(
                'seller|token|secret|credential|authorization|account|cookie|password',k,re.I)}
        if isinstance(value,list):return [scrub(v) for v in value]
        if isinstance(value,str):
            for secret in sorted(secrets,key=len,reverse=True):
                if secret:value=value.replace(secret,'[REDACTED]')
        return value
    return scrub({k:v for k,v in item.items() if k in allowed})


def validate_page(body: dict,*,prior_tokens: set[str],asins: list[str] | None=None) -> tuple[list[dict],str | None]:
    if not isinstance(body,dict):raise ValueError('Structured response required')
    items=body.get('items');pagination=body.get('pagination',{})
    if (not isinstance(items,list) or len(items)>20 or not isinstance(pagination,dict)
            or len(canonical(body).encode())>8*1024*1024):raise ValueError('Bounded Catalog response required')
    token=pagination.get('nextToken')
    if token is not None and (not isinstance(token,str) or not 1<=len(token)<=4096 or token in prior_tokens
                               or any(not c.isprintable() for c in token)):
        raise ValueError('Repeated or malformed pagination cursor')
    for item in items:
        if not isinstance(item,dict) or not isinstance(item.get('asin'),str) or not ASIN.fullmatch(item['asin']):
            raise ValueError('Only observed valid ASINs accepted')
        if asins is not None and item['asin'] not in asins:raise ValueError('Identifier enrichment cannot discover new ASINs')
        for name in ('summaries','identifiers','relationships','productTypes','classifications','dimensions'):
            for scoped in item.get(name,[]):
                if not isinstance(scoped,dict) or scoped.get('marketplaceId')!=US:raise ValueError('US response scope required')
    if asins is not None and token is not None:raise ValueError('Identifier batch continuation needs a separately reviewed budget; stop')
    return items,token


def rehearse(manifest: dict,journal,transport: CatalogTransport,*,monotonic=time.monotonic,
             sleep=time.sleep,before_request=lambda:None,maximum_seconds: float=900) -> dict:
    """Internal injection seam. No CLI, credential loading, live send or ASIN reservation.

    Tests inject synthetic replies; future production authorization must be reviewed
    separately. A started journal is never reusable, even after an uncertain send.
    """
    validate(manifest)
    manifest=deepcopy(manifest)
    if journal.digest!=manifest['proposal_sha256']:raise ValueError('Exact journal/manifest binding required')
    if not math.isfinite(maximum_seconds) or not 0<maximum_seconds<=900:raise ValueError('Finite bounded deadline required')
    journal.start()  # outside try: re-entry cannot mutate a terminal run
    deadline=monotonic()+maximum_seconds
    pacing=manifest['pacing']
    pacer=OperationPacer(rates={'searchCatalogItems':pacing['search_rps_cap']},headroom=pacing['headroom'],
                         monotonic=monotonic,sleep=sleep)
    excluded=set(manifest['excluded_asins']);seen=set();pages=[];duplicates=0;excluded_observations=0
    state={q['id']:dict(token=None,tokens=set(),ended=False) for q in manifest['queries']}
    active_phase='authentication'
    def dispatch(phase,params,query=None,index=0,asins=None,prior_tokens=None):
        nonlocal active_phase,duplicates,excluded_observations
        active_phase=phase
        before_request()
        operation=None if phase=='authentication' else 'searchCatalogItems'
        if operation:pacer.acquire(operation,deadline)
        before_request()
        if monotonic()>=deadline:raise TimeoutError
        request=transport.build(phase,params)
        transport.validate(request,phase,params)
        slot=journal.consume(phase,fingerprint(dict(phase=phase,params=params)))
        # Durable slot is committed before any potentially interruptible send.
        reply=transport.send(request)
        if not isinstance(reply,dict) or set(reply)!={'status','headers','body'}:raise ValueError('Explicit HTTP envelope required')
        status=reply['status'];headers=reply['headers'];body=reply['body']
        if not isinstance(headers,dict) or type(status) is not int:raise ValueError('Explicit status/headers required')
        if operation:pacer.observe(operation,status,headers)
        if status!=200 or any(str(k).casefold()=='retry-after' for k in headers):raise ValueError('Stop on failure/throttle; no retry')
        if monotonic()>=deadline:raise TimeoutError
        if phase=='authentication':
            transport.accept_authentication(body);journal.response(slot,None,fingerprint(body));return None
        items,token=validate_page(body,prior_tokens=prior_tokens or set(),asins=asins)
        date=datetime.now(timezone.utc).isoformat()
        page=dict(query_reference=query,page_index=index,page_token=params.get('pageToken'),
                  pagination=dict(nextToken=token) if token else {},marketplace_id=US,http_status=200,
                  observed_at=date,items=[clean_product(i,transport.secrets()) for i in items],
                  manifest_sha256=manifest['proposal_sha256'],response_sha256=fingerprint(body),request_slot=slot)
        journal.response(slot,page,fingerprint(body));pages.append(page)
        for item in items:
            a=item['asin']
            if a in excluded:excluded_observations+=1
            elif a in seen:duplicates+=1
            elif phase=='keyword':seen.add(a)
        return token
    try:
        dispatch('authentication',{})
        for page_index in range(4):
            for query in manifest['queries']:
                current=state[query['id']]
                if current['ended']:continue
                if len(seen)>=1000:break
                token=dispatch('keyword',parameters(query,current['token']),query['id'],page_index,
                               prior_tokens=current['tokens'])
                if token:current['tokens'].add(token)
                current['token']=token;current['ended']=token is None
            if len(seen)>=1000:break
        targets=sorted(seen)[:1000]
        for start in range(0,len(targets),20):
            batch=targets[start:start+20]
            if set(batch)&excluded:raise ValueError('Permanent exclusions cannot be explicitly queried')
            dispatch('identifier',parameters(asins=batch),f'identifier-{start//20:03}',asins=batch)
        journal.finish('COMPLETE');status='COMPLETED_NO_REPLAY'
    except BaseException:
        # Failure text, token, credentials, headers and raw bodies never reach logs.
        journal.finish('STOP');status='STOPPED_NO_REPLAY'
    finally:transport.clear()
    return dict(status=status,phase=active_phase,requests_consumed=journal.count(),
        distinct_unclaimed_asins=len(seen),duplicate_observations=duplicates,
        excluded_observations=excluded_observations,seen_asins_sha256=fingerprint(sorted(seen)),
        pages=pages,execution_authorized=False,eligibility='UNKNOWN',new_asin_reservations=0)


def save_catalog(result: dict,output):
    """Private M70-compatible saved-page handoff, including partial runs.

    This helper performs local writes only. Synthetic tests must never be presented
    as real discovery evidence. No CLI invokes rehearsal or this handoff in M71.
    """
    from app.m65 import write_json
    from app.m65_intelligence import sha256
    if output.is_symlink() or any(p.is_symlink() for p in output.parents):raise ValueError('Dedicated private export required')
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    pages=output/'M71_catalog_pages.json'
    write_json(pages,dict(mode='M71_SAVED_CATALOG_PAGES',pages=result['pages'],
        status=result['status'],execution_authorized=False,eligibility='UNKNOWN'))
    write_json(output/'M71_M70_sources.json',dict(schema=1,sources=[dict(path=pages.name,sha256=sha256(pages),
        adapter='amazon_catalog_pages',permission_reference='local:M71-reviewed-catalog-export',marketplace=US)]))
    summary={k:v for k,v in result.items() if k!='pages'}
    write_json(output/'M71_discovery_summary.json',summary)
