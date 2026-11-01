"""M72 explicit ten-request pilot: dry-run, owner authorization, execute or report."""
import argparse
import getpass
import json
from pathlib import Path

from app.m65 import write_json
from app.m65_intelligence import read_json,sha256
from app.m67_policy import private_json
from app.m72_policy import (preflight,account,owner_authorization,check_authorization,load_baseline,
    REGISTRY,MANIFEST_SHA256,PROPOSAL_SHA256)
from app.observations import fingerprint


class Parser(argparse.ArgumentParser):
    def error(self,message):self.exit(2,'M72_BLOCKED: invalid arguments\n')


def main(argv=None):
    p=Parser(description=__doc__)
    p.add_argument('action',choices=('dry-run','authorize','execute','report'))
    p.add_argument('--proposal',type=Path,required=True)
    p.add_argument('--store',type=Path,required=True)
    p.add_argument('--private',type=Path,default=Path.home()/'.intelligenceos-arbitrage-amazon')
    p.add_argument('--m67-manifest',type=Path,required=True);p.add_argument('--m67-sha256',required=True)
    p.add_argument('--baseline-catalog',type=Path,required=True)
    p.add_argument('--output',type=Path)
    p.add_argument('--reviewed-preflight',type=Path);p.add_argument('--preflight-sha256')
    p.add_argument('--review-reference')
    p.add_argument('--authorization',type=Path);p.add_argument('--authorization-sha256')
    p.add_argument('--execute-live',action='store_true')
    a=p.parse_args(argv)
    try:
        if a.execute_live and a.action!='execute':raise ValueError('Execution flag outside execute action')
        args=(a.proposal,a.store,a.private,a.m67_manifest,a.m67_sha256,a.baseline_catalog)
        if a.action in ('dry-run','authorize'):
            report=preflight(*args)
            if not a.output:raise ValueError('New explicit output path required')
            if a.action=='dry-run':
                if a.output.resolve().is_relative_to(a.private.resolve()):raise ValueError('Review reports outside protected history directory')
                write_json(a.output,report)
                result=dict(mode=report['mode'],preflight_sha256=fingerprint(report),preflight_file_sha256=sha256(a.output),
                    budget=report['budget'],query_ids=[q['id'] for q in report['queries']],execution_authorized=False,actual_requests=0)
            else:
                if not a.reviewed_preflight or not a.preflight_sha256 or not a.review_reference:raise ValueError('Exact reviewed preflight required')
                reviewed,digest=read_json(a.reviewed_preflight)
                if digest!=a.preflight_sha256 or reviewed!=report:raise ValueError('Reviewed/current preflight drift')
                if a.output.parent.resolve()!=a.private.resolve() or not a.output.name.startswith('m72-owner-authorization-') or a.output.exists():
                    raise ValueError('New dedicated private authorization filename required')
                import sys
                if not sys.stdin.isatty():raise ValueError('Local interactive owner authorization required')
                context,_=account(a.private)
                if getpass.getpass('Existing seller account ID (hidden): ')!=context['seller_id']:raise ValueError('Owner account confirmation failed')
                print('M72: authorize ONE authentication and NINE first-page keyword searches; TEN total maximum; NO REPLAY.')
                if input('Type AUTHORIZE M72 10 REQUESTS NO REPLAY: ')!='AUTHORIZE M72 10 REQUESTS NO REPLAY':raise ValueError('Explicit owner confirmation required')
                auth=owner_authorization(report,a.review_reference)
                # Revalidate after potentially slow human confirmation, before writing.
                if preflight(*args)!=report:raise ValueError('Preflight changed during confirmation')
                write_json(a.output,auth)
                result=dict(mode=auth['mode'],authorization_file_sha256=sha256(a.output),expires_at=auth['expires_at'],actual_requests=0)
        elif a.action=='execute':
            if not a.execute_live or not a.authorization or not a.authorization_sha256:raise ValueError('Separate fresh authorization and explicit execution flag required')
            from app.m72_execution import execute
            result=execute(*args,a.authorization,a.authorization_sha256,execution_flag=True)
        else:
            if not a.output:raise ValueError('New recovery report directory required')
            from app.m72_registry import inspect
            from app.m72_reporting import export
            doc,digest=read_json(a.proposal)
            if digest!=MANIFEST_SHA256 or doc['proposal_sha256']!=PROPOSAL_SHA256:raise ValueError('Pinned original proposal required')
            snapshot=inspect(a.private/REGISTRY);baseline,source=load_baseline(a.baseline_catalog)
            if source!=snapshot['binding']['preflight']['baseline_file_sha256']:raise ValueError('Original baseline required')
            if a.output.resolve().is_relative_to(a.private.resolve()):raise ValueError('Recovery exports outside protected history directory')
            result=export(snapshot,doc,baseline,a.output)
        print(json.dumps(result,sort_keys=True))
        return 2 if a.action=='execute' and result.get('status')!='COMPLETED_NO_REPLAY' else 0
    except (Exception,KeyboardInterrupt):
        print('M72_BLOCKED: missing authorization, drift, prior operation, interruption or unsafe evidence/storage');return 2


if __name__=='__main__':raise SystemExit(main())
