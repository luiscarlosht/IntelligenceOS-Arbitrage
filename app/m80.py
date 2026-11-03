"""M80 prepare/preflight/authorize/execute/report. No live default or implicit permission."""
import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
from pathlib import Path
import sys
import warnings
from io import BytesIO
import zipfile
from openpyxl import Workbook
from app.m80_contract import (PLAN, LEDGER, ACK, prepare, read, write, permission, account, check_inputs)
from app.m80_execution import preflight, execute
from app.m80_journal import inspect
from app.m80_evidence import analyze
from app.m79 import MemoryExcelWriter
from app.m78_reporting import cell


def export(snapshot:dict, output:Path, now:datetime) -> dict:
    if (output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents)
            or output.resolve().is_relative_to('/mnt')): raise ValueError('New local nonsymlink report path required')
    plan=snapshot['binding']['plan']
    dest=output.resolve(); private=Path(plan['private_root'])
    if (any(dest.is_relative_to(root) for root in plan['protected_roots'])
            or dest.is_relative_to(private) and dest!=private/'m80-results'):
        raise ValueError('Report cannot mutate historical/private input directories')
    report=analyze(snapshot,now)
    output.mkdir(mode=0o700)
    write(output/'M80_report.json',report)
    write(output/'M80_evidence.json',snapshot)
    wb=Workbook(); wb.remove(wb.active)
    wb.properties.created=wb.properties.modified=datetime(2000,1,1)
    for name,rows in {'Products':report['rows'],'Category_Priority':report['category_groups'],
                      'Limitations':[{'limitation':v} for v in report['limitations']]}.items():
        ws=wb.create_sheet(name); keys=sorted({k for row in rows for k in row}) or ['status']; ws.append(keys)
        for row in rows: ws.append([cell(row.get(k,'UNKNOWN')) for k in keys])
        ws.freeze_panes='B2'; ws.auto_filter.ref=ws.dimensions
    raw=BytesIO(); MemoryExcelWriter(wb,zipfile.ZipFile(raw,'w',zipfile.ZIP_DEFLATED)).save()
    result=BytesIO()
    with zipfile.ZipFile(raw) as src,zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(src.namelist()):
            info=zipfile.ZipInfo(name,(2000,1,1,0,0,0)); info.compress_type=zipfile.ZIP_DEFLATED; info.external_attr=0o600<<16
            dst.writestr(info,src.read(name))
    from app.m78_reporting import write as bytes_write
    bytes_write(output/'M80_sales_review.xlsx',result.getvalue())
    write(output/'M80_completion.json',dict(status=snapshot['status'],synthetic=report['synthetic'],
        checkpoint_sha256=snapshot['checkpoint_sha256'],
        output_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()},
        purchase_authorized=False,walmart_sourcing_authorized=False))
    return report


def authorize(private:Path, plan_sha:str, reference:str, output:Path) -> None:
    plan=preflight(private,plan_sha)
    if not sys.stdin.isatty() or not sys.stdout.isatty(): raise PermissionError('Interactive owner terminal required')
    if (output.parent.resolve()!=private.resolve() or not output.name.startswith('m80-owner-authorization-')
            or output.suffix!='.json'): raise ValueError('Separate private M80 authorization filename required')
    context,_=account(private)
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        if getpass.getpass('Confirm seller ID privately: ')!=context['seller_id']: raise PermissionError('Seller confirmation failed')
    if input(ACK+'\n')!=ACK: raise PermissionError('Exact new authorization acknowledgement required')
    # Repeat all read-only checks after the human review; no credentials read.
    if preflight(private,plan_sha)!=plan: raise ValueError('Plan drift during review')
    write(output,permission(plan,reference,datetime.now(timezone.utc)))


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    sub=p.add_subparsers(dest='action',required=True)
    create=sub.add_parser('prepare'); create.add_argument('--private',type=Path,required=True)
    create.add_argument('--handoff',type=Path,required=True); create.add_argument('--handoff-sha256',required=True)
    check=sub.add_parser('preflight'); auth=sub.add_parser('authorize'); live=sub.add_parser('execute')
    for parser in (check,auth,live):
        parser.add_argument('--private',type=Path,required=True); parser.add_argument('--plan-sha256',required=True)
    auth.add_argument('--review-reference',required=True); auth.add_argument('--output',type=Path,required=True)
    live.add_argument('--authorization',type=Path,required=True); live.add_argument('--authorization-sha256',required=True)
    live.add_argument('--execute-live',action='store_true')
    recovery=sub.add_parser('report'); recovery.add_argument('--private',type=Path,required=True)
    recovery.add_argument('--output',type=Path,required=True); recovery.add_argument('--as-of',required=True)
    args=p.parse_args(argv)
    try:
        if args.action=='prepare':
            plan=prepare(args.handoff,args.handoff_sha256,args.private); write(args.private/PLAN,plan)
            print(json.dumps({'mode':'M80_PREPARATION_ONLY','plan_file_sha256':hashlib.sha256((args.private/PLAN).read_bytes()).hexdigest(),'maximum_requests':42}))
        elif args.action=='preflight':
            plan=preflight(args.private,args.plan_sha256)
            print(json.dumps({'mode':'M80_READ_ONLY_PREFLIGHT','asins':plan['asins'],'budget':plan['budget'],
                              'plan_sha256':args.plan_sha256,'execution_authorized':False}))
        elif args.action=='authorize':
            authorize(args.private,args.plan_sha256,args.review_reference,args.output)
            print('M80 separate owner artifact created; no request made')
        elif args.action=='execute':
            snapshot=execute(args.private,args.plan_sha256,args.authorization,args.authorization_sha256,execute_live=args.execute_live)
            export(snapshot,args.private/'m80-results',datetime.now(timezone.utc))
            print(json.dumps({'status':snapshot['status'],'requests_consumed':snapshot['requests_consumed']}))
            return 0 if snapshot['status']=='COMPLETED_NO_REPLAY' else 2
        else:
            snapshot=inspect(args.private/LEDGER)
            export(snapshot,args.output,datetime.fromisoformat(args.as_of.replace('Z','+00:00')))
            print('M80 read-only evidence recovery; no credentials, requests or resume')
        return 0
    except (Exception,KeyboardInterrupt):
        print('M80_BLOCKED: authorization, contract, accounting, evidence or storage failure; no automatic retry')
        return 2


if __name__=='__main__': raise SystemExit(main())
