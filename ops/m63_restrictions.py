"""Offline validation by default. Run ONLY after review of the exact M63 cohort.

Discovery never imports this executor. No Catalog/Pricing/Fees/retailer requests.
"""
import argparse
import csv
import fcntl
import json
import os
from pathlib import Path

from app import amazon_candidate_enrichment as engine
from app import amazon_pilot as pilot
from app.amazon_catalog import MARKETPLACE
from app.amazon_diagnostics import ResponseDocument
from app.m63_history import ASIN, audit, sha256
from app.observations import fingerprint


def validate(path: Path, digest: str, private: Path = pilot.DIRECTORY) -> dict:
    if path.is_symlink() or sha256(path)!=digest:
        raise ValueError('Exact reviewed manifest hash required')
    m=json.loads(path.read_bytes())
    asins=m['asins']
    if (m['mode']!='M63_LISTINGS_RESTRICTIONS_PROPOSAL' or m['execution_authorized'] is not False
            or m['marketplace_id']!=MARKETPLACE or m['condition']!='new_new'
            or not 1<=len(asins)<=20 or len(asins)!=len(set(asins))
            or any(not ASIN.fullmatch(a) for a in asins)):
        raise ValueError('Invalid M63 scope')
    history=audit(private)
    if fingerprint(history)!=m['history_sha256'] or set(asins)&set(history['excluded_asins']):
        raise ValueError('Historical attempt audit changed or ASIN previously attempted')
    source=path.parent/'M63_amazon_candidates_100.csv'
    if source.is_symlink() or sha256(source)!=m['candidates_csv_sha256']:
        raise ValueError('Candidate CSV changed')
    with source.open(encoding='utf-8-sig',newline='') as stream:
        rows=list(csv.DictReader(stream))
    by_asin={r['asin']:r for r in rows}
    if len(rows)!=len(by_asin):
        raise ValueError('Duplicate discovery candidates')
    expected_budget=dict(restrictions=len(asins),distinct_asins=len(asins),maximum_distinct_asins=20,
        authentication=1,retries=0,catalog=0,pricing=0,fees=0,retailer=0)
    if m['budget']!=expected_budget or len(m['requests'])!=len(asins):
        raise ValueError('M63 request ceiling changed')
    for asin,spec in zip(asins,m['requests'],strict=True):
        row=by_asin[asin]
        params=dict(asin=asin,marketplaceIds=MARKETPLACE,conditionType='new_new',reasonLocale='en_US',sellerId='[private runtime value]')
        if (spec['method']!='GET' or spec['path']!='/listings/2021-08-01/restrictions'
                or spec['params']!=params or spec['candidate_id']!='amazon-us:'+asin
                or spec['brand']!=row['brand'] or spec['category']!=row['category']):
            raise ValueError('M63 request/candidate mismatch')
    return m


def run(path: Path,digest: str,maximum: int,*,private: Path=pilot.DIRECTORY,**dependencies):
    """One-shot permanent authorization reservation, even on uncertain failure.

    The operator reviews the exact manifest before invoking the explicit CLI.
    Existing engine privately prompts for account continuity; no seller ID in CLI.
    """
    m=validate(path,digest,private)
    if type(maximum) is not int or maximum!=len(m['asins']) or maximum>20:
        raise ValueError('Exact reviewed ASIN limit required')
    directory=pilot.private_directory(private)
    lock=None
    try:
        lock=os.open('candidate-execution.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600,dir_fd=directory)
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        validate(path,digest,private)
        fd=pilot.create_file(directory,'m63-eligibility-authorization-01.json')
        with os.fdopen(fd,'w') as stream:
            stream.write(json.dumps(dict(manifest_sha256=digest,asins=m['asins'],maximum_checks=maximum,state='claimed_no_replay'))+'\n')
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)
    # Only allowlisted restriction codes persist. Messages/links can echo private
    # seller identifiers and are excluded before the shared parser checkpoints.
    raw_transport=dependencies.pop('transport',None) or pilot._request_json
    def safe_transport(request):
        reply=raw_transport(request)
        if request.full_url.startswith('https://api.amazon.com/auth/o2/token'):
            return reply
        rows=reply.get('restrictions')
        if reply.get('errors') or not isinstance(rows,list):
            raise ValueError('Invalid restriction response')
        clean=[]
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('reasons',[]),list):
                raise ValueError('Invalid restriction row')
            reasons=[]
            for reason in row.get('reasons',[]):
                if not isinstance(reason,dict):
                    raise ValueError('Invalid restriction reason')
                code=reason.get('reasonCode')
                reasons.append(dict(reasonCode=code if code in ('APPROVAL_REQUIRED','ASIN_NOT_FOUND','NOT_ELIGIBLE') else 'OTHER'))
            clean.append(dict(marketplaceId=row.get('marketplaceId'),conditionType=row.get('conditionType'),reasons=reasons))
        result=ResponseDocument(dict(restrictions=clean),getattr(reply,'http_status',200))
        result.rate_headers=getattr(reply,'rate_headers',{})
        return result
    internal=dict(deadline_seconds=120,budget=dict(maximum_requests=maximum+1),requests=[dict(asin=a,
        seller_reference=m['account_reference'],pricing={},restrictions=dict(path=s['path'],params=s['params']))
        for a,s in zip(m['asins'],m['requests'],strict=True)])
    rows=[dict(asin=a,target_id='amazon-us:'+a,marketplace_id=MARKETPLACE,condition='new_new',
               seller_reference=m['account_reference'],pricing=dict(status='not_requested',data=None),
               fees=dict(status='not_requested',data=None),restrictions=dict(status='not_attempted',data=None)) for a in m['asins']]
    return engine._execute(internal,private,operations={a:('restrictions',) for a in m['asins']},
                           request_limit=maximum+1,stem='m63-eligibility-'+digest+'-01',
                           initial_report=dict(rows=rows,source_bound_manifest=m),transport=safe_transport,**dependencies)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('validate','run'))
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--sha256',required=True)
    p.add_argument('--max-checks',type=int,required=True)
    p.add_argument('--execute-reviewed',action='store_true')
    args=p.parse_args()
    if (args.action=='run')!=args.execute_reviewed:
        p.error('run requires --execute-reviewed after exact-cohort review')
    try:
        m=validate(args.manifest,args.sha256)
        if args.max_checks!=len(m['asins']):
            raise ValueError('Exact ASIN limit required')
        if args.action=='run':
            r=run(args.manifest,args.sha256,args.max_checks)
            print(json.dumps(dict(status=r['status'],attempts=len(r['attempts']))))
        else:
            print(json.dumps(dict(status='validated_offline',asins=m['asins'],live_requests=0)))
        return 0
    except (Exception,KeyboardInterrupt):
        print('M63 restrictions stopped without replay. Inspect private evidence.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
