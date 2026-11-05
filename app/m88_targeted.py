"""One-shot targeted Catalog verification, appending to the original M88 ledger."""
import argparse
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from decimal import Decimal
import os
from pathlib import Path
import re
import signal
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import Request

from app import amazon_pilot as pilot
from app.amazon_details import parse_fees
from app.amazon_diagnostics import AmazonFailure,failure_metadata
from app.amazon_pacing import OperationPacer
from app.evidence_io import offline,publication,safe
from app.m80_execution import scrub
from app.m88 import implementation,readiness,offer_result,Stop
from app.m88_evidence import US,enrich
from app.m88_state import ledger,lock,read,sha,stamp,write
from app.m88_targeted_evidence import DATA,ranking,targets,catalog_detail
from app.m88_targeted_state import CLAIM,LIMIT,TargetedJournal,prefix_sha
from app.product_analysis import comparison,workbook
from app.provider_contracts import SellerContext
from app.walmart_evidence import normalize


def definitions(selected: list[dict]) -> list[dict]:
    result=[dict(phase='authentication',candidate_id=None,method='POST',host='api.amazon.com',path='/auth/o2/token')]
    for target in selected:
        common=dict(candidate_id=target['candidate_id'],asin=target['asin'],host='sellingpartnerapi-na.amazon.com')
        result.append(dict(common,phase='detail',method='GET',path='/catalog/2022-04-01/items/'+target['asin'],
            query=dict(marketplaceIds=US,includedData=DATA,locale='en_US')))
        result.append(dict(common,phase='offers',method='GET',path='/products/pricing/v0/items/'+target['asin']+'/offers',
            query=dict(MarketplaceId=US,ItemCondition='New',CustomerType='Consumer'),requires='strict exact identity'))
        for mode in ('FBA','FBM'):
            result.append(dict(common,phase='fees_'+mode,method='POST',path='/products/fees/v0/items/'+target['asin']+'/feesEstimate',
                requires='exact identity, bound seller context, supported New buy-box base price and explicit zero buyer shipping',
                body_template=dict(MarketplaceId=US,IsAmazonFulfilled=mode=='FBA',condition='New',scenario='base')))
    return result


def prepare(reconciliation: Path,expected: str,private: Path,output: Path,account: Path | None=None) -> dict:
    reconciliation=safe(reconciliation)
    if sha(reconciliation)!=expected:raise ValueError('Pinned reconciliation required')
    prior=read(reconciliation); ranked=ranking(prior)
    if len(ranked)!=26 or prior.get('cohort')!='m88-real-six-pilot':raise ValueError('Original 26 unresolved M88 pairs required')
    batch_path=safe(reconciliation.parent/'enriched-batch.json');batch=read(batch_path)
    normalize(batch)
    source_ids={r['walmart_product']['walmart_item_id']:r['source_candidate_id'] for r in batch['observations']}
    selected=[dict(t,candidate_id=source_ids[t['walmart_item_id']]) for t in targets(ranked)]
    ledger_entries=[v for v in prior['source_inventory'] if Path(v['path']).name=='amazon-http-attempt-ledger.json']
    if len(ledger_entries)!=1:raise ValueError('One authoritative original ledger required')
    ledger_path=safe(Path(ledger_entries[0]['path']));data=ledger(ledger_path)
    if (data['attempts_used']!=7 or data.get(CLAIM) is not None or any(a['status']!='COMPLETE' for a in data['attempts'])
            or not isinstance(data.get('m88_operation'),str)):raise PermissionError('Original completed 7/49 with no targeted claim required')
    inventory=list(prior['source_inventory'])+[dict(path=str(reconciliation),sha256=expected),dict(path=str(batch_path),sha256=sha(batch_path))]
    for item in inventory:
        if sha(Path(item['path']))!=item['sha256']:raise ValueError('Original reconciliation evidence drift')
    if account:
        if not account.resolve().is_relative_to(private.resolve()):raise ValueError('Private account context required')
        read(account)
    plan=dict(schema='m88-targeted-verification-v1',cohort='m88-real-six-pilot',marketplace=US,condition='New',
        private_root=str(private.resolve()),credential_readiness=readiness(private),
        account_path=str(account.resolve()) if account else None,account_sha256=sha(account) if account else None,
        fee_account_status='BOUND_TO_VALIDATE' if account else 'UNBOUND_FEES_SKIP',
        source_path=str(batch_path),reconciliation_path=str(reconciliation),source_inventory=inventory,
        ledger_path=str(ledger_path),baseline_ledger_sha256=sha(ledger_path),baseline_attempts=7,
        original_operation_sha256=data['m88_operation'],original_attempts_sha256=prefix_sha(data['attempts']),
        targets=selected,requests=definitions(selected),maximum_new_attempts=LIMIT,expected_initial_attempts=4,
        cumulative_ceiling=49,maximum_cumulative_attempts=20,retries=0,refreshes=0,pagination=0,
        deadline_seconds=600,per_request_timeout_seconds=10,
        implementation_sha256=implementation(),purchase_authorized=False)
    with publication(output,[reconciliation,batch_path,ledger_path]) as stage:
        write(stage/'ranking.json',dict(ranked_candidates=ranked,selected=selected,ranking_is_not_exact_identity=True,purchase_authorized=False))
        write(stage/'plan.json',plan)
    return plan


def check(plan: dict) -> dict:
    if (plan.get('schema')!='m88-targeted-verification-v1' or plan.get('implementation_sha256')!=implementation()
            or plan.get('requests')!=definitions(plan['targets']) or plan.get('maximum_new_attempts')!=13
            or plan.get('baseline_attempts')!=7 or plan.get('cumulative_ceiling')!=49
            or plan.get('purchase_authorized') is not False or any(plan.get(k)!=0 for k in ('retries','refreshes','pagination'))):
        raise ValueError('Frozen targeted endpoint/code/budget contract required')
    if readiness(Path(plan['private_root']))!=plan['credential_readiness']:raise ValueError('Research credential metadata drift')
    for item in plan['source_inventory']:
        if item['path']!=plan['ledger_path'] and sha(Path(item['path']))!=item['sha256']:raise ValueError('Targeted input drift')
    if plan['account_path'] and sha(Path(plan['account_path']))!=plan['account_sha256']:raise ValueError('Account context drift')
    batch=read(Path(plan['source_path']))
    ids={r['walmart_product']['walmart_item_id']:r['source_candidate_id'] for r in batch['observations']}
    expected_targets=[dict(t,candidate_id=ids[t['walmart_item_id']])
        for t in targets(ranking(read(Path(plan['reconciliation_path']))))]
    if plan['targets']!=expected_targets:raise ValueError('Target selection drift outside ranked unresolved evidence')
    for row in batch['observations']:
        at=datetime.fromisoformat(row['walmart_product']['observed_at'].replace('Z','+00:00'))
        if not timedelta(0)<=datetime.now(timezone.utc)-at<=timedelta(hours=24):raise ValueError('Fresh source identity required')
    return batch


def execute(plan_path: Path,expected: str,*,transport=pilot._request_json) -> None:
    if sha(plan_path)!=expected:raise ValueError('Reviewed targeted plan digest required')
    plan=read(plan_path);batch=check(plan);private=Path(plan['private_root']);operation=plan_path.parent
    journal=TargetedJournal(Path(plan['ledger_path']),expected,plan)
    with ExitStack() as stack:
        stack.enter_context(lock(private/'candidate-execution.lock'))
        stack.enter_context(lock(Path(plan['ledger_path']).with_suffix('.lock')))
        journal.start()
        if sha(Path(plan['ledger_path']))!=plan['baseline_ledger_sha256']:raise ValueError('Ledger drift; no reset permitted')
        write(operation/'execution-status.json',dict(status='STARTING',purchase_authorized=False))
        pacer=OperationPacer(headroom=.5);expires=time.monotonic()+600;token_expires=expires
        credentials={};token=None;seller=None
        previous=signal.signal(signal.SIGALRM,pilot.deadline);signal.alarm(600)
        def call(phase,candidate,request,parser):
            check(plan)
            if time.monotonic()>=min(expires,token_expires):raise TimeoutError('Targeted deadline')
            # Every call is generated from the fixed phase/source/ASIN registry.
            number=journal.reserve(phase,candidate)
            try:
                document=pacer.call(request,transport)
                try:value=parser(document)
                except Exception:
                    raise AmazonFailure('Targeted response rejected',reason='response_validation_failed',http_status=getattr(document,'http_status',None)) from None
                evidence=scrub(value,set(credentials.values())|({token} if token else set())|({seller} if seller else set()))
                if phase=='authentication':evidence={'token_received':True}
                write(operation/f'receipt-{number}.json',dict(number=number,phase=phase,candidate_id=candidate,observed_at=stamp(),evidence=evidence))
                journal.finish(number,'COMPLETE',receipt_sha256=sha(operation/f'receipt-{number}.json'))
                return value
            except BaseException as error:
                journal.finish(number,'FAILED',failure=failure_metadata(error));raise
        try:
            directory=os.open(private,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:credentials=pilot.load_credentials(directory)
            finally:os.close(directory)
            if plan['account_path']:
                context=read(Path(plan['account_path']))
                if context.get('credentials_sha256')!=sha(private/'credentials.json'):raise ValueError('Account/credential binding mismatch')
                seller=context.get('seller_id')
                if not isinstance(seller,str) or not re.fullmatch('[A-Z0-9]{1,32}',seller):raise ValueError('Explicit private seller context required')
            def accept_auth(doc):
                nonlocal token,token_expires
                access=doc.get('access_token');seconds=doc.get('expires_in')
                if (str(doc.get('token_type','')).lower()!='bearer' or not isinstance(access,str) or not 1<=len(access)<=2048
                        or not access.isascii() or any(c.isspace() or not c.isprintable() for c in access)
                        or type(seconds) is not int or seconds<=10):raise ValueError('Invalid bearer response')
                token=access;token_expires=min(expires,time.monotonic()+seconds-10)
                return {'token_received':True}
            call('authentication',None,Request('https://api.amazon.com/auth/o2/token',data=urlencode(dict(grant_type='refresh_token',**credentials)).encode(),
                headers={'Content-Type':'application/x-www-form-urlencoded'}),accept_auth)
            for target in plan['targets']:
                candidate=target['candidate_id'];asin=target['asin']
                row=next(r for r in batch['observations'] if r['source_candidate_id']==candidate)
                source=dict(row['walmart_product'],conflicting_observations=row.get('conflicting_observations',[]))
                definition=next(r for r in plan['requests'] if r['phase']=='detail' and r['candidate_id']==candidate)
                detail=call('detail',candidate,pilot.amazon_request(token,definition['path'],definition['query']),
                    lambda doc:catalog_detail(doc,asin,source,tuple(credentials.values())+(token,)))
                if not detail['identity']['exact']:continue
                definition=next(r for r in plan['requests'] if r['phase']=='offers' and r['candidate_id']==candidate)
                offers=call('offers',candidate,pilot.amazon_request(token,definition['path'],definition['query']),lambda doc:offer_result(doc,asin))
                price=offers['fee_price']
                if price is None or seller is None:continue
                for mode in ('FBA','FBM'):
                    identifier=candidate+':'+mode+':base'
                    body={'FeesEstimateRequest':dict(MarketplaceId=US,IsAmazonFulfilled=mode=='FBA',Identifier=identifier,
                        PriceToEstimateFees=dict(ListingPrice=dict(CurrencyCode='USD',Amount=price),Shipping=dict(CurrencyCode='USD',Amount='0')))}
                    call('fees_'+mode,candidate,pilot.amazon_request(token,'/products/fees/v0/items/'+asin+'/feesEstimate',body=body),
                        lambda doc:parse_fees(doc,SellerContext(seller,US),Decimal(price),identifier,is_mock=False,expected_asin=asin,fulfillment=mode))
            write(operation/'execution-status.json',dict(status='COMPLETED',purchase_authorized=False),replace=True)
        except BaseException:
            write(operation/'execution-status.json',dict(status='STOPPED_NO_RETRY',purchase_authorized=False),replace=True)
            raise Stop('Targeted verification stopped; report-only recovery') from None
        finally:
            credentials.clear();token=None;seller=None
            signal.alarm(0);signal.signal(signal.SIGALRM,previous)


def recover(plan_path: Path,expected: str,output: Path) -> dict:
    if sha(plan_path)!=expected:raise ValueError('Pinned targeted plan required')
    plan=read(plan_path);operation=plan_path.parent
    journal=TargetedJournal(Path(plan['ledger_path']),expected,plan)
    with lock(Path(plan['ledger_path']).with_suffix('.lock')):
        data=journal.history();batch=read(Path(plan['source_path']));receipts=[];uncertain=[]
        for item in plan['source_inventory']:
            if item['path']!=plan['ledger_path'] and sha(Path(item['path']))!=item['sha256']:raise ValueError('Recovery input drift')
        for attempt in data['attempts'][7:]:
            if attempt.get('plan_sha256')!=expected:raise ValueError('Unrelated continuation')
            if attempt['status']=='COMPLETE':
                path=operation/f"receipt-{attempt['number']}.json"
                if sha(path)!=attempt['receipt_sha256']:raise ValueError('Receipt integrity failure')
                receipt=read(path)
                if any(receipt[k]!=attempt[k] for k in ('number','phase','candidate_id')):raise ValueError('Receipt binding drift')
                receipts.append(receipt)
            elif attempt['status']=='RESERVED':uncertain.append(attempt['number'])
        compact=[]
        for receipt in receipts:
            item=deepcopy(receipt)
            if item['phase']=='detail':
                detail=item['evidence'];product=detail['product']
                product.pop('retained_attributes',None);product.pop('dimensions',None)
                detail['receipt_reference']=str(operation/f"receipt-{item['number']}.json")
            compact.append(item)
        enriched=enrich(batch,compact)
        enriched.pop('batch_id',None)
        inventory=[dict(item,role='Historical baseline ledger hash in reviewed plan') if item['path']==plan['ledger_path'] else item
                   for item in plan['source_inventory']]
        inventory.extend([dict(path=str(plan_path),sha256=expected,role='Executed targeted plan'),
                          dict(path=plan['ledger_path'],sha256=sha(Path(plan['ledger_path'])),role='Current authoritative cumulative ledger')])
        manifest=normalize(enriched);manifest['source_inventory']=inventory+[
            dict(path=str(operation/f"receipt-{r['number']}.json"),sha256=sha(operation/f"receipt-{r['number']}.json")) for r in receipts]
        manifest['recovery_blockers']=['Source identity conflicts, screenshot references and agent/human review distinctions retained; no source identity inferred from Amazon.']
        assessed=comparison(manifest,datetime.now(timezone.utc))
        details=[r for r in receipts if r['phase']=='detail']
        summary=dict(cohort='m88-real-six-pilot',verified_matches=sum(r['evidence']['identity']['exact'] for r in details),
            targeted_details_completed=len(details),new_attempts=len(data['attempts'])-7,cumulative_attempts=data['attempts_used'],ceiling=49,
            attempts_by_phase=dict(Counter(a['phase'] for a in data['attempts'][7:])),
            failed_attempts=[a['number'] for a in data['attempts'][7:] if a['status']=='FAILED'],unknown_outcomes=uncertain,
            supported_profitability_products=sum(r['financial_assessment']!='INSUFFICIENT_DATA' for r in assessed['records']),
            original_operation_sha256=plan['original_operation_sha256'],targeted_plan_sha256=expected,
            authoritative_ledger_path=plan['ledger_path'],authoritative_ledger_sha256=sha(Path(plan['ledger_path'])),purchase_authorized=False)
        assessed.update(targeted_verification=summary,delivery_context=batch.get('delivery_context'))
        with publication(output,[operation,Path(plan['source_path']),Path(plan['ledger_path'])]) as stage:
            previous=tempfile.tempdir
            try:
                tempfile.tempdir=str(stage)
                with offline(writes=[stage]):
                    write(stage/'enriched-batch.json',enriched);write(stage/'normalized.json',manifest)
                    write(stage/'targeted-evidence.json',dict(summary,details=details))
                    write(stage/'execution-report.json',summary);write(stage/'comparison.json',assessed)
                    workbook(assessed,stage/'comparison.xlsx')
                    write(stage/'missing-data-report.json',dict(targets=[dict(candidate_id=r['candidate_id'],identity=r['evidence']['identity']) for r in details],
                        source_exceptions={r['source_candidate_id']:r.get('identity_exceptions',[]) for r in batch['observations']},
                        financial_gaps={r['candidate_id']:r['missing_information'] for r in assessed['records']},
                        unknown_outcomes=uncertain,purchase_authorized=False))
                    from app.m78_reporting import write as bytes_write
                    text=('# M88 targeted Catalog verification\n\n'+f"{summary['targeted_details_completed']} Catalog details; {summary['verified_matches']} verified exact matches. "
                        f"New attempts {summary['new_attempts']}; cumulative {summary['cumulative_attempts']}/49.\n\n"+
                        f"Attempts by phase: {summary['attempts_by_phase']}. Supported profitability products: {summary['supported_profitability_products']}/6.\n\n"+
                        'Independent Amazon attributes, manufacturer part numbers, identifiers, units and package relationships are retained in normalized receipts. '
                        'No model aliases, quantity equivalence, formulation, source corrections or human approval are inferred. '
                        'Original source conflicts, screenshot references, prices and timestamps remain intact. '
                        'Offers/fees require strict exact identity; missing costs/fees/quotes remain unknown. Unresolved products remain INSUFFICIENT_DATA.\n\n'+
                        f"Failed attempts: {summary['failed_attempts']}; uncertain outcomes: {uncertain}. All remain charged, without replay or retries. purchase_authorized=false.\n")
                    bytes_write(stage/'executive-summary.md',text.encode())
            finally:tempfile.tempdir=previous
        return summary


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('prepare','execute','recover'))
    parser.add_argument('--reconciliation',type=Path);parser.add_argument('--sha256');parser.add_argument('--private',type=Path,default=pilot.DIRECTORY)
    parser.add_argument('--account-context',type=Path);parser.add_argument('--output',type=Path);parser.add_argument('--plan',type=Path);parser.add_argument('--plan-sha256')
    args=parser.parse_args()
    try:
        if args.action=='prepare':
            if not all((args.reconciliation,args.sha256,args.output)):parser.error('Prepare requires reconciliation, SHA256 and fresh output')
            prepare(args.reconciliation,args.sha256,args.private,args.output,args.account_context)
            print('Targeted plan prepared; zero new HTTP attempts; credential values unread.')
        else:
            if not args.plan or not args.plan_sha256:parser.error('Pinned plan required')
            if args.action=='execute':execute(args.plan,args.plan_sha256)
            else:
                if not args.output:parser.error('Fresh report output required')
                recover(args.plan,args.plan_sha256,args.output)
            print('Targeted action complete; purchase_authorized=false.')
    except (Exception,KeyboardInterrupt) as error:
        print('Targeted M88 stopped; category='+type(error).__name__+'; no automatic retry.')
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
