"""M77 manual CLI: offline validation, separate interactive authorization, explicit execution, recovery."""
import argparse
import getpass
import json
from pathlib import Path
import sys
import warnings

from app.m65 import write_json
from app.m70_sources import file_hash
from app.m73_evidence import document
from app.m77_policy import preflight, REGISTRY, completion
from app.m77_authorization import owner_authorization
from app.observations import fingerprint

PATH_INPUTS=('m74-dir','m73-dir','baseline-dir','proposal','private','sources','summary','store','m67-manifest')
DIGEST_INPUTS=('m73-digests-sha256','baseline-report-sha256','checkpoint','m67-sha256')


class Parser(argparse.ArgumentParser):
    def error(self,message):self.exit(2,'M77_BLOCKED: invalid arguments\n')


def review_output(path, args):
    protected=[args.m76_dir,args.m74_dir,args.m73_dir,args.baseline_dir,args.private,
               args.sources.parent,args.summary.parent,args.store.parent,args.m67_manifest.parent,args.proposal.parent]
    if (not path or path.is_symlink() or any(p.is_symlink() for p in path.parents)
            or any(path.resolve().is_relative_to(p.resolve()) for p in protected)):
        raise ValueError('Fresh review/recovery output outside all historical evidence required')


def main(argv=None) -> int:
    parser=Parser(description=__doc__,allow_abbrev=False)
    parser.add_argument('action',choices=('dry-run','authorize','execute','report'))
    parser.add_argument('--m76-dir',type=Path,required=True)
    for name in PATH_INPUTS:parser.add_argument('--'+name,type=Path,required=True)
    for name in DIGEST_INPUTS:parser.add_argument('--'+name,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--reviewed-preflight',type=Path);parser.add_argument('--preflight-sha256')
    parser.add_argument('--review-reference');parser.add_argument('--authorization',type=Path)
    parser.add_argument('--authorization-sha256');parser.add_argument('--execute-live',action='store_true')
    args=parser.parse_args(argv)
    evidence={n.replace('-','_'):getattr(args,n.replace('-','_')) for n in PATH_INPUTS+DIGEST_INPUTS}
    try:
        if args.execute_live and args.action!='execute':raise ValueError('Live flag outside explicit execution')
        if args.action in ('dry-run','authorize'):
            prepared=preflight(args.m76_dir,evidence);report=prepared.report
            if not args.output:raise ValueError('New output required')
            if args.action=='dry-run':
                review_output(args.output,args)
                write_json(args.output,report)
                result=dict(mode=report['mode'],preflight_file_sha256=file_hash(args.output),
                    preflight_sha256=fingerprint(report),implementation_digest=report['implementation_digest'],
                    budget=report['budget'],query_ids=[q['query_id'] for q in report['requests']],
                    execution_authorized=False,actual_requests=0)
            else:
                if not args.reviewed_preflight or not args.preflight_sha256 or not args.review_reference:
                    raise ValueError('Exact reviewed preflight required')
                if document(args.reviewed_preflight,args.preflight_sha256)!=report:raise ValueError('Reviewed/current preflight mismatch')
                import re
                if (args.output.parent.absolute()!=args.private.absolute()
                        or any(p.is_symlink() for p in args.output.parents)
                        or not re.fullmatch(r'm77-owner-authorization-[A-Za-z0-9._-]+\.json',args.output.name)
                        or args.output.exists() or args.output.is_symlink()):raise ValueError('New M77-only owner artifact path required')
                if not sys.stdin.isatty():raise ValueError('Interactive local terminal required')
                from app.m77_policy import account
                context,_=account(args.private)
                with warnings.catch_warnings():
                    warnings.simplefilter('error',getpass.GetPassWarning)
                    if getpass.getpass('Existing seller account ID (hidden): ')!=context['seller_id']:
                        raise ValueError('Owner account confirmation failed')
                print('Authorize only M77: ONE authentication + THIRTY-ONE first-page keywords; 32 maximum; NO REPLAY.')
                if input('Type AUTHORIZE M77 32 REQUESTS NO REPLAY: ')!='AUTHORIZE M77 32 REQUESTS NO REPLAY':
                    raise ValueError('Explicit owner acknowledgement required')
                prepared.guard()
                if (args.private/REGISTRY).exists() or (args.private/REGISTRY).is_symlink():raise ValueError('M77 already claimed')
                artifact=owner_authorization(report,args.review_reference)
                write_json(args.output,artifact)
                from app.m65_intelligence import sha256
                result=dict(mode=artifact['mode'],authorization_file_sha256=sha256(args.output),
                            expires_at=artifact['expires_at'],actual_requests=0)
        elif args.action=='execute':
            if not args.execute_live or not args.authorization or not args.authorization_sha256:
                raise ValueError('Fresh authorization and explicit live flag required')
            from app.m77_execution import execute
            result=execute(args.m76_dir,evidence,args.authorization,args.authorization_sha256,execute_live=True)
        else:
            review_output(args.output,args)
            from app.m77_registry import inspect
            from app.m77_reporting import export
            snapshot=inspect(args.private/REGISTRY)
            prepared=preflight(args.m76_dir,evidence,_recovery=True)
            if snapshot['binding']['preflight']!=prepared.report:raise ValueError('Recovery binding drift')
            manifest=prepared.manifest
            baseline=dict(catalog=[dict(asin=a) for a in prepared.baseline])
            result=export(snapshot,manifest,{p['asin'] for p in baseline['catalog']},args.output)
        print(json.dumps(result,sort_keys=True))
        return 2 if args.action=='execute' and result.get('status')!='COMPLETED_NO_REPLAY' else 0
    except (Exception,KeyboardInterrupt):
        print('M77_BLOCKED: missing owner authorization, immutable drift, prior claim, interruption or unsafe storage');return 2


if __name__=='__main__':raise SystemExit(main())
