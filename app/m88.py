"""Explicit one-shot, read-only M88 SP-API pilot. Preparation never reads secrets."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import time
import tempfile
from urllib.parse import urlencode
from urllib.request import Request

from app import amazon_pilot as pilot
from app.amazon_details import parse_pricing, parse_fees
from app.amazon_diagnostics import AmazonFailure, failure_metadata
from app.amazon_pacing import OperationPacer
from app.evidence_io import offline, safe, publication
from app.m80_execution import scrub
from app.m88_evidence import DATA, US, product, match, search_result, enrich
from app.m88_state import Journal, ledger, lock, read, sha, stamp, write
from app.m67_state import secure
from app.product_analysis import comparison, workbook
from app.provider_contracts import SellerContext
from app.walmart_evidence import normalize


class Stop(Exception):
    """Fixed-category executor failure; exception values are never printed."""


def implementation() -> dict:
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(__file__).parent.glob('*.py'))}


def readiness(private: Path) -> dict:
    if private.resolve().is_relative_to(Path(__file__).resolve().parent.parent):
        raise ValueError('Research credentials must remain outside the repository')
    secure(private, directory=True)
    credential=private/'credentials.json'; secure(credential)
    info=credential.stat()
    return dict(status='METADATA_READY_VALUES_UNREAD',file_size=info.st_size,
                inode=info.st_ino,mtime_ns=info.st_mtime_ns,uid=info.st_uid,mode=stat.S_IMODE(info.st_mode),
                entitlement_status='UNVERIFIED_UNTIL_AUTHORIZED_REQUEST')


def source(path: Path, expected: str) -> dict:
    if sha(path)!=expected: raise ValueError('M88 source digest mismatch')
    batch=read(path); manifest=normalize(batch)
    if (batch.get('name')!='m88-real-six-pilot' or batch.get('batch_kind')!='NEW_PILOT'
            or batch.get('purchase_authorized') is not False or any('amazon' in r for r in batch['observations'])):
        raise ValueError('Authentic source-only M88 new cohort required')
    for row in batch['observations']:
        p=row['walmart_product']; observed=datetime.fromisoformat(p['observed_at'].replace('Z','+00:00'))
        if not timedelta(0)<=datetime.now(timezone.utc)-observed<=timedelta(hours=24):
            raise ValueError('Fresh source observations required')
        if any(not isinstance(p.get(key),str) or not 1<=len(p[key])<=512 or not all(c.isprintable() for c in p[key])
               for key in ('title','pack_description')):
            raise ValueError('Bounded authentic search evidence required')
        from urllib.parse import urlsplit
        url=urlsplit(p['url'])
        if (url.scheme!='https' or url.netloc!='www.walmart.com' or not url.path.startswith('/ip/')
                or url.path.split('/')[-1]!=p['walmart_item_id'] or url.query or url.fragment):
            raise ValueError('Walmart URL identity mismatch')
    if sha(path)!=expected: raise ValueError('Source drift')
    return batch


def definitions(batch: dict) -> list[dict]:
    rows=batch['observations']
    result=[dict(phase='authentication',candidate_id=None,method='POST',host='api.amazon.com',path='/auth/o2/token')]
    for row in rows:
        p=row['walmart_product']
        result.append(dict(phase='search',candidate_id=row['source_candidate_id'],method='GET',
            host='sellingpartnerapi-na.amazon.com',path='/catalog/2022-04-01/items',
            query=dict(marketplaceIds=US,keywords=p['title']+' '+p['pack_description'],keywordsLocale='en_US',
                       includedData=DATA,pageSize=10)))
    for row in rows:
        for phase,path,method in [('detail','/catalog/2022-04-01/items/{exact_candidate_asin}','GET'),
            ('offers','/products/pricing/v0/items/{exact_asin}/offers','GET'),
            ('fees_FBA','/products/fees/v0/items/{exact_asin}/feesEstimate','POST'),
            ('fees_FBM','/products/fees/v0/items/{exact_asin}/feesEstimate','POST')]:
            result.append(dict(phase=phase,candidate_id=row['source_candidate_id'],method=method,
                host='sellingpartnerapi-na.amazon.com',path_template=path,conditional=True))
    return result


def prepare(input_path: Path, expected: str, preview: Path, ledger_path: Path, private: Path,
            output: Path, account: Path | None = None) -> dict:
    input_path=safe(input_path); ledger_path=safe(ledger_path); preview=safe(preview)
    batch=source(input_path,expected); prior=read(preview)
    if (prior.get('name')!='m88-real-six-pilot' or prior.get('maximum_http_attempts')!=31
            or prior.get('absolute_ceiling')!=49): raise ValueError('Saved conditional 31-attempt preview required')
    accounting=ledger(ledger_path)
    if accounting.get('m88_operation') is not None: raise PermissionError('M88 already claimed; recover only')
    credential_status=readiness(private)
    if account:
        secure(account)
        if not account.resolve().is_relative_to(private.resolve()): raise ValueError('Private account context required')
    plan=dict(schema='m88-read-only-plan-v1',cohort='m88-real-six-pilot',marketplace=US,condition='New',
        source_path=str(input_path),source_sha256=expected,preview_path=str(preview),preview_sha256=sha(preview),
        ledger_path=str(ledger_path),ledger_baseline_sha256=sha(ledger_path),ledger_baseline_used=accounting['attempts_used'],
        private_root=str(private.resolve()),credential_readiness=credential_status,
        account_path=str(account.resolve()) if account else None,account_sha256=sha(account) if account else None,
        fee_account_status='BOUND_CONTEXT_TO_VALIDATE_AT_EXECUTION' if account else 'UNBOUND_FEES_SKIP',
        requests=definitions(batch),maximum_http_attempts=31,cumulative_ceiling=49,
        retries=0,refreshes=0,pagination=0,deadline_seconds=600,per_request_timeout_seconds=10,
        rates=dict(catalog_max_per_second=1,offers_max_per_second=.25,fees_max_per_second=.5),
        matching='Verified source and Amazon brand, model, GTIN, variant, size, pack; exactly one candidate on complete first page; no title-only match',
        fee_basis='Observed buy-box New listing price with explicit zero buyer shipping; hypothetical base only, never confirmed sale price',
        implementation_sha256=implementation(),purchase_authorized=False)
    with publication(output,[input_path,preview,ledger_path]) as stage:
        write(stage/'plan.json',plan)
        write(stage/'readiness.json',dict(credential_status,fee_account_status=plan['fee_account_status'],
            remaining_cumulative_attempts=49-accounting['attempts_used'],purchase_authorized=False))
    return plan


def check(plan: dict) -> dict:
    if plan.get('implementation_sha256')!=implementation(): raise ValueError('Implementation drift')
    batch=source(Path(plan['source_path']),plan['source_sha256'])
    if (plan['requests']!=definitions(batch) or plan.get('maximum_http_attempts')!=31
            or plan.get('cumulative_ceiling')!=49 or plan.get('purchase_authorized') is not False
            or any(plan.get(k)!=0 for k in ('retries','refreshes','pagination'))
            or plan.get('schema')!='m88-read-only-plan-v1' or plan.get('marketplace')!=US
            or plan.get('condition')!='New' or plan.get('deadline_seconds')!=600):
        raise ValueError('Frozen M88 endpoint scope required')
    if sha(Path(plan['preview_path']))!=plan['preview_sha256']: raise ValueError('Conditional preview drift')
    if readiness(Path(plan['private_root']))!=plan['credential_readiness']: raise ValueError('Credential metadata drift')
    if plan['account_path'] and sha(Path(plan['account_path']))!=plan['account_sha256']:
        raise ValueError('Account context drift')
    return batch


def report(plan: dict, operation: Path, output: Path) -> dict:
    """Report-only recovery: no token/credential access, no refund or replay."""
    batch=read(Path(plan['source_path']))
    if sha(Path(plan['source_path']))!=plan['source_sha256']: raise ValueError('Source drift')
    accounting=ledger(Path(plan['ledger_path'])); plan_sha=sha(operation/'plan.json')
    receipts=[]; uncertain=[]
    for attempt in accounting['attempts']:
        if attempt.get('plan_sha256')!=plan_sha: continue
        if attempt['status']=='COMPLETE':
            path=operation/('receipt-'+str(attempt['number'])+'.json')
            if sha(path)!=attempt['receipt_sha256']: raise ValueError('Evidence receipt integrity failure')
            receipt=read(path)
            if (receipt['number']!=attempt['number'] or receipt['phase']!=attempt['phase']
                    or receipt['candidate_id']!=attempt['candidate_id']): raise ValueError('Receipt scope mismatch')
            receipts.append(receipt)
        elif attempt['status']=='RESERVED': uncertain.append(attempt['number'])
    enriched=enrich(batch,receipts); manifest=normalize(enriched)
    manifest['source_inventory'] = list(manifest['source_inventory']) + [
        dict(path=str(operation/f"receipt-{r['number']}.json"),
             sha256=sha(operation/f"receipt-{r['number']}.json"), role='M88 normalized API receipt')
        for r in receipts]
    manifest['recovery_blockers']=['New authentic M88 cohort; identity/market/cost gaps remain explicit']
    assessed=comparison(manifest,datetime.now(timezone.utc))
    assessed.update(cohort='m88-real-six-pilot',batch_kind='NEW_PILOT',delivery_context=batch.get('delivery_context'),
                    amazon_http_attempts=accounting['attempts_used'],purchase_authorized=False)
    with publication(output,[Path(plan['source_path']),operation,Path(plan['ledger_path'])]) as stage:
        with offline(writes=[stage]):
            write(stage/'enriched-batch.json',enriched)
            write(stage/'normalized.json',manifest)
            write(stage/'comparison.json',assessed)
            previous_tempdir=tempfile.tempdir
            try:
                tempfile.tempdir=str(stage)
                workbook(assessed,stage/'comparison.xlsx')
            finally:
                tempfile.tempdir=previous_tempdir
            write(stage/'missing-data-report.json',dict(purchase_authorized=False,unknown_outcome_attempts=uncertain,
                unknown_outcomes_remain_charged=True,records=[dict(candidate_id=r['candidate_id'],
                missing_information=r['missing_information']) for r in assessed['records']]))
            searches=[r for r in receipts if r['phase']=='search']
            summary=dict(cohort='m88-real-six-pilot',source_products=6,searches_completed=len(searches),
                candidate_asins_by_source={r['candidate_id']:[c['product']['asin'] for c in r['evidence']['candidates']] for r in searches},
                exact_matches=sum(r['phase']=='detail' and r['evidence']['identity']['exact'] for r in receipts),
                attempts_used=accounting['attempts_used'],ceiling=49,unknown_outcome_attempts=uncertain,
                failed_attempts=[a['number'] for a in accounting['attempts'] if a['status']=='FAILED'],
                financial_assessments={r['candidate_id']:r['financial_assessment'] for r in assessed['records']},
                purchase_authorized=False)
            write(stage/'execution-report.json',summary)
            from app.m78_reporting import write as bytes_write
            bytes_write(stage/'executive-summary.md',(
                '# M88 read-only evidence pilot\n\n'+
                f"Six source observations; {len(searches)} searches completed; {summary['exact_matches']} exact matches. "
                f"Cumulative Amazon attempts: {accounting['attempts_used']}/49.\n\n"+
                'Source URLs, prices, timestamps, package descriptions and Sacramento context are retained. '
                'Missing source identities cannot be filled from Amazon candidates. Ambiguous or partial searches stay unresolved. '
                'Demand, historical series and seller eligibility remain unknown. Observed competing prices are hypothetical sale-price bases only; '
                'fees are estimates, merchant fulfillment and other missing costs are never zero. No confirmed profit or purchase approval.\n\n'+
                f"Failed attempts: {summary['failed_attempts']}; uncertain attempts: {uncertain}. "
                'All remain charged. Recovery never dispatches, retries or refreshes tokens. purchase_authorized=false.\n').encode())
    return summary


def execute(plan_path: Path, expected: str, *, transport=pilot._request_json) -> None:
    """One approved command, at most 31 HTTP calls; no inherited provider selector."""
    if sha(plan_path)!=expected: raise ValueError('Reviewed plan digest required')
    plan=read(plan_path); operation=plan_path.parent; private=Path(plan['private_root'])
    batch=check(plan); journal=Journal(Path(plan['ledger_path']),expected)
    with ExitStack() as stack:
        stack.enter_context(lock(private/'candidate-execution.lock'))
        stack.enter_context(lock(Path(plan['ledger_path']).with_suffix('.lock')))
        journal.start()
        if sha(Path(plan['ledger_path']))!=plan['ledger_baseline_sha256']:
            raise ValueError('Cumulative ledger drift; do not reset')
        if (operation/'execution-status.json').exists(): raise PermissionError('Operation already started; recover only')
        write(operation/'execution-status.json',dict(status='STARTING',purchase_authorized=False))
        pacer=OperationPacer(headroom=.5)
        expiry=time.monotonic()+600; token_expiry=expiry
        credentials={}; token=None; seller=None
        prior_handler=signal.signal(signal.SIGALRM,pilot.deadline); signal.alarm(600)
        def boundary():
            check(plan)
            if time.monotonic()>=min(expiry,token_expiry): raise TimeoutError('M88 deadline')
        def call(phase: str, candidate_id: str | None, request: Request, parser):
            boundary()
            number=journal.reserve(phase,candidate_id)
            try:
                document=pacer.call(request,transport)
                try:
                    value=parser(document)
                except Exception:
                    raise AmazonFailure('M88 response rejected',reason='response_validation_failed',
                        http_status=getattr(document,'http_status',None)) from None
                safe_value=scrub(value,set(credentials.values())|({token} if token else set())|({seller} if seller else set()))
                receipt=dict(number=number,phase=phase,candidate_id=candidate_id,observed_at=stamp(),evidence=safe_value)
                # Token material must NEVER enter receipts or operational output.
                if phase=='authentication': receipt['evidence']={'token_received':True}
                write(operation/f'receipt-{number}.json',receipt)
                journal.finish(number,'COMPLETE',receipt_sha256=sha(operation/f'receipt-{number}.json'))
                return value
            except BaseException as error:
                journal.finish(number,'FAILED',failure=failure_metadata(error))
                raise
        try:
            directory=os.open(private,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try: credentials=pilot.load_credentials(directory)
            finally: os.close(directory)
            if plan['account_path']:
                context=read(Path(plan['account_path']))
                if context.get('credentials_sha256')!=sha(private/'credentials.json'):
                    raise ValueError('Research account credential binding mismatch')
                seller=context.get('seller_id')
                if not isinstance(seller,str) or not re.fullmatch('[A-Z0-9]{1,32}',seller): raise ValueError('Private seller context required')
            auth_request=Request('https://api.amazon.com/auth/o2/token',data=urlencode(dict(grant_type='refresh_token',**credentials)).encode(),
                                 headers={'Content-Type':'application/x-www-form-urlencoded'})
            def accept_auth(document):
                nonlocal token, token_expiry
                access=document.get('access_token'); seconds=document.get('expires_in')
                if (str(document.get('token_type','')).lower()!='bearer' or not isinstance(access,str)
                        or not 1<=len(access)<=2048 or not access.isascii()
                        or any(c.isspace() or not c.isprintable() for c in access)
                        or type(seconds) is not int or seconds<=10): raise ValueError('Invalid token response')
                token=access; token_expiry=min(expiry,time.monotonic()+seconds-10)
                return {'token_received':True}
            call('authentication',None,auth_request,accept_auth)
            for definition in plan['requests'][1:7]:
                candidate=definition['candidate_id']; row=next(r for r in batch['observations'] if r['source_candidate_id']==candidate)
                result=call('search',candidate,pilot.amazon_request(token,definition['path'],definition['query']),
                            lambda doc:search_result(doc,row['walmart_product'],tuple(credentials.values())+(token,)))
                asin=result['selected_asin']
                if not asin: continue
                detail=call('detail',candidate,pilot.amazon_request(token,'/catalog/2022-04-01/items/'+asin,dict(marketplaceIds=US,includedData=DATA)),
                    lambda doc: detail_result(doc,asin,row['walmart_product'],tuple(credentials.values())+(token,)))
                if not detail['identity']['exact']: continue
                offers=call('offers',candidate,pilot.amazon_request(token,'/products/pricing/v0/items/'+asin+'/offers',
                    dict(MarketplaceId=US,ItemCondition='New',CustomerType='Consumer')),
                    lambda doc: offer_result(doc,asin))
                price=offers['fee_price']
                if price is None or seller is None: continue
                for mode in ('FBA','FBM'):
                    identifier=candidate+':'+mode+':base'
                    body={'FeesEstimateRequest':dict(MarketplaceId=US,IsAmazonFulfilled=mode=='FBA',Identifier=identifier,
                          PriceToEstimateFees=dict(ListingPrice=dict(CurrencyCode='USD',Amount=price),Shipping=dict(CurrencyCode='USD',Amount='0')))}
                    call('fees_'+mode,candidate,pilot.amazon_request(token,'/products/fees/v0/items/'+asin+'/feesEstimate',body=body),
                         lambda doc:parse_fees(doc,SellerContext(seller,US),Decimal(price),identifier,is_mock=False,expected_asin=asin,fulfillment=mode))
            write(operation/'execution-status.json',dict(status='COMPLETED',purchase_authorized=False),replace=True)
        except BaseException:
            write(operation/'execution-status.json',dict(status='STOPPED_NO_RETRY',purchase_authorized=False),replace=True)
            raise Stop('M88 stopped; use report-only recovery') from None
        finally:
            credentials.clear(); token=None; seller=None
            signal.alarm(0); signal.signal(signal.SIGALRM,prior_handler)


def detail_result(document: dict, asin: str, retailer: dict, secrets: tuple) -> dict:
    item=product(document,asin,secrets)
    return dict(product=item,identity=match(retailer,item,datetime.now(timezone.utc)))


def offer_result(document: dict, asin: str) -> dict:
    from dataclasses import asdict
    evidence=parse_pricing(document,is_mock=False,expected_asin=asin)
    prices=[p for p in evidence.value.prices if p.basis=='buy_box_observed'
            and p.listing_price is not None and p.listing_price>0 and p.shipping==Decimal('0')]
    eligible=not evidence.value.exclude_from_profitability_ranking
    price=str(prices[0].listing_price) if eligible and len(prices)==1 else None
    return dict(asdict(evidence),fee_price=price,fee_price_assumed=True,buyer_shipping_scenario='0')


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','execute','recover'))
    parser.add_argument('--source',type=Path); parser.add_argument('--source-sha256')
    parser.add_argument('--preview',type=Path); parser.add_argument('--ledger',type=Path)
    parser.add_argument('--private',type=Path,default=pilot.DIRECTORY)
    parser.add_argument('--account-context',type=Path)
    parser.add_argument('--output',type=Path); parser.add_argument('--plan',type=Path); parser.add_argument('--plan-sha256')
    args=parser.parse_args()
    try:
        if args.action=='prepare':
            if not all((args.source,args.source_sha256,args.preview,args.ledger,args.output)): parser.error('Prepare requires source/digest, preview, ledger and output')
            prepare(args.source,args.source_sha256,args.preview,args.ledger,args.private,args.output,args.account_context)
            print('M88 plan prepared; credential values unread; zero HTTP attempts.')
        else:
            if not args.plan or not args.plan_sha256: parser.error('Reviewed plan/digest required')
            if sha(args.plan)!=args.plan_sha256: raise ValueError('Plan digest mismatch')
            if args.action=='execute': execute(args.plan,args.plan_sha256)
            else:
                if not args.output: parser.error('Recover requires fresh output')
                plan=read(args.plan)
                with lock(Path(plan['ledger_path']).with_suffix('.lock')):
                    report(plan,args.plan.parent,args.output)
            print('M88 action complete; purchase_authorized=false.')
    except (Exception,KeyboardInterrupt) as error:
        print('M88 stopped; category='+type(error).__name__+'; no automatic retry.')
        return 1
    return 0


if __name__=='__main__': raise SystemExit(main())
