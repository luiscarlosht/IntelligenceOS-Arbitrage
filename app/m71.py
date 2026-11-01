"""M71 preparation-only CLI: freeze/preview a proposal; no execute action."""
import argparse
import json
import os
from pathlib import Path
from app.m65 import write_json
from app.m65_intelligence import read_json, sha256
from app.m71_manifest import prepare, validate, preview


class Parser(argparse.ArgumentParser):
    def error(self,message):self.exit(2,'M71_BLOCKED_OFFLINE: invalid arguments\n')


def export(doc: dict,output: Path):
    validate(doc)
    if output.is_symlink() or any(p.is_symlink() for p in output.parents):raise ValueError('New nonsymlink output required')
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    write_json(output/'M71_manifest.json',doc)
    fd=os.open(output/'M71_request_preview.md',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(preview(doc));stream.flush();os.fsync(stream.fileno())
    write_json(output/'M71_manifest.sha256.json',dict(file_sha256=sha256(output/'M71_manifest.json'),
        proposal_sha256=doc['proposal_sha256'],execution_authorized=False))


def main(argv=None):
    p=Parser(description=__doc__);p.add_argument('action',choices=('prepare','validate'))
    p.add_argument('--store',type=Path,required=True)
    p.add_argument('--history-dir',type=Path,default=Path.home()/'.intelligenceos-arbitrage-amazon')
    p.add_argument('--m67-manifest',type=Path,required=True);p.add_argument('--m67-sha256',required=True)
    p.add_argument('--output',type=Path);p.add_argument('--manifest',type=Path);p.add_argument('--sha256')
    args=p.parse_args(argv)
    try:
        expected=prepare(args.history_dir,args.store,args.m67_manifest,args.m67_sha256)
        if args.action=='prepare':
            if not args.output or args.output.resolve().is_relative_to(args.history_dir.resolve()):raise ValueError('Dedicated output directory required')
            export(expected,args.output)
        else:
            if not args.manifest or not args.sha256:raise ValueError('Exact frozen file digest required')
            doc,digest=read_json(args.manifest)
            if digest!=args.sha256 or doc!=expected:raise ValueError('Current source/code/history/configuration drift')
            validate(doc)
        print(json.dumps(dict(mode=expected['mode'],proposal_sha256=expected['proposal_sha256'],
            keyword_queries=50,category_intents=10,keyword_request_ceiling=200,identifier_request_ceiling=50,
            authentication_ceiling=1,total_ceiling=251,excluded_asins=len(expected['excluded_asins']),
            actual_authentication=0,actual_amazon_requests=0,actual_retailer_requests=0,new_asin_reservations=0,
            execution_authorized=False),sort_keys=True));return 0
    except (Exception,KeyboardInterrupt):
        print('M71_BLOCKED_OFFLINE: invalid evidence, drift, budget or storage failure');return 2


if __name__=='__main__':raise SystemExit(main())
