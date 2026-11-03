"""Offline pinned Amazon-ledger + saved-receipt decision reporting. No acquisition clients."""
import argparse
import json
import sqlite3
import sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
from app.evidence_io import digest,offline,pinned,publication,json_write,safe
from app.sales_evidence import load_ledger
from app.opportunity_engine import evaluate,rank
from app.decision_history import database,record,trend
from app.decision_workbook import workbook
from app.observations import fingerprint
from app.m80_contract import implementation


def inputs(path:Path,sha:str):
    manifest=pinned(path,sha)
    if set(manifest) not in ({'schema','ledger','receipts'},{'schema','ledger','receipts','handoff'}) or manifest['schema']!=1 or type(manifest['schema']) is not int:
        raise ValueError('Exact decision manifest schema required')
    paths={str(path.resolve()):sha};data=[]
    def item(value):
        if not isinstance(value,dict) or set(value)!={'path','sha256'} or not isinstance(value['path'],str):raise ValueError('Exact input pin required')
        candidate=Path(value['path'])
        if not candidate.is_absolute():candidate=path.parent/candidate
        candidate=safe(candidate)
        if str(candidate) in paths:raise ValueError('Repeated input path')
        if digest(candidate)!=value['sha256']:raise ValueError('Evidence artifact pin mismatch')
        paths[str(candidate)]=value['sha256'];return candidate,value['sha256']
    ledger,ledger_sha=item(manifest['ledger'])
    handoff=None
    if 'handoff' in manifest:
        hp,hs=item(manifest['handoff']);handoff=pinned(hp,hs)
    if not isinstance(manifest['receipts'],list) or len(manifest['receipts'])>10000:raise ValueError('Bounded receipts required')
    for value in manifest['receipts']:
        receipt_path,receipt_sha=item(value);obj=pinned(receipt_path,receipt_sha)
        artifact=obj.get('artifact_path')
        if not isinstance(artifact,str) or not artifact:raise ValueError('Original independent receipt artifact required')
        artifact=Path(artifact)
        if not artifact.is_absolute():artifact=receipt_path.parent/artifact
        artifact=safe(artifact);expected=obj.get('artifact_sha256')
        if artifact==receipt_path or digest(artifact)!=expected:raise ValueError('Independent original artifact digest mismatch')
        if str(artifact) in paths and paths[str(artifact)]!=expected:raise ValueError('Conflicting artifact pin')
        paths[str(artifact)]=expected;data.append(obj)
    return ledger,ledger_sha,data,paths,handoff


def run(manifest:Path,manifest_sha:str,output:Path,history:Path,as_of:datetime) -> dict:
    if as_of.tzinfo is None:raise ValueError('Aware as-of time required')
    manifest=safe(manifest);history=safe(history);output=safe(output)
    if history.is_relative_to('/mnt') or history.parent==output.parent or history.is_relative_to(output) or output.is_relative_to(history.parent):
        raise ValueError('Separate private local history required')
    ledger,ledger_sha,receipts,pins,handoff=inputs(manifest,manifest_sha)
    with offline(reads=[ledger]):
        amazon=load_ledger(ledger,ledger_sha,as_of)
    # Inherit all original source boundaries even when only their derived ledger is supplied.
    protected=[Path(p) for p in pins]
    archived={Path(p) for p in amazon['protected_roots']}
    if handoff is not None:archived.update(Path(p).parent for p in handoff.get('input_sha256',{}))
    if any(history.is_relative_to(p.parent) or p.is_relative_to(history.parent) for p in protected):raise ValueError('History must not overlap original evidence')
    if any(history.is_relative_to(p) or p.is_relative_to(history.parent) for p in archived):raise ValueError('History must not overlap archived source roots')
    code=implementation()
    with publication(output,protected,archived_roots=archived) as stage:
        with offline(reads=[ledger],writes=[stage,history.parent]):
            kind=amazon['source_kind'];synthetic=amazon['synthetic']
            universe=[]
            if handoff is not None:
                from app.m80_contract import source
                hp=next(Path(p) for p,h in pins.items() if h==amazon['handoff_sha256']) if amazon['handoff_sha256'] in pins.values() else None
                if hp is None:raise ValueError('Original handoff pin must match acquisition plan')
                source(hp,amazon['handoff_sha256'])
                observed={r['asin'] for r in amazon['rows']}
                if not observed<={r['asin'] for r in handoff['all_asins']}:raise ValueError('ASIN outside original historical universe')
                universe=[dict(asin=r['asin'],evidence_class='HISTORICAL_M79_IDENTITY_ONLY',
                    identity=r,current_bsr='UNKNOWN',current_price='UNKNOWN',current_new_offer_count='UNKNOWN',
                    current_listing_permission='UNKNOWN',monthly_unit_sales='UNKNOWN',purchase_authorized=False)
                    for r in handoff['all_asins'] if r['asin'] not in observed]
            by={}
            for receipt in receipts:
                key=(receipt.get('asin'),receipt.get('kind'))
                if key in by:raise ValueError('Ambiguous duplicate receipt')
                if receipt.get('asin') not in {r['asin'] for r in amazon['rows']}:raise ValueError('Out-of-scope receipt ASIN')
                by[key]=receipt
            opportunities=[]
            for row in amazon['rows']:
                keys=('WALMART_QUOTE','AMAZON_FBA_FEE_ESTIMATE','OWNER_RISK_REVIEW')
                opportunities.append(evaluate(row,*(by.get((row['asin'],k),{}) for k in keys),as_of,synthetic=synthetic))
            opportunities=rank(opportunities)
            with database(history) as db:
                observations=record(db,amazon)
                for row in amazon['rows']:row['price_history']=trend(observations,row,kind,as_of)
                research=sorted(amazon['rows'],key=lambda r:(not r['review_ready'],r['asin']))[:20]
                quality=[dict(asin=r['asin'],evidence_class=kind,review_ready=r['review_ready'],
                    missing_metrics=[k for k in ('new_offer_count','listing_permission','price_stability','estimated_monthly_unit_sales','fba_permission') if r[k]=='UNKNOWN'],
                    identity_issues=r['identity_issues'],economic_flags=next(x['flags'] for x in opportunities if x['asin']==r['asin'])) for r in amazon['rows']]
                weekly=[]
                for week in sorted({datetime.fromisoformat(v['observed_at']).date()-timedelta(days=datetime.fromisoformat(v['observed_at']).weekday())
                                    for item in observations if item['source_kind']==kind for v in item['provenance'].values()}):
                    samples=[item for item in observations if item['source_kind']==kind and any(
                        week<=datetime.fromisoformat(v['observed_at']).date()<week+timedelta(days=7) for v in item['provenance'].values())]
                    weekly.append(dict(week_start=str(week),evidence_class=kind,distinct_observed_asins=len({r['asin'] for r in samples}),
                        observed_snapshots=len(samples),realized_sales='UNKNOWN',realized_revenue='UNKNOWN',realized_profit='UNKNOWN'))
                report=dict(schema=1,mode='OFFLINE_DECISION_SUPPORT_PROPOSALS_ONLY',as_of=as_of.isoformat(),source_kind=kind,
                    synthetic=synthetic,purchase_authorized=False,walmart_sourcing_authorized=False,input_sha256=pins,
                    code_sha256=code,amazon=amazon,opportunities=opportunities,research_top20=research,history=observations,
                    weekly=weekly,data_quality=quality,historical_unobserved=universe,inventory_proposals=[dict(asin=r['asin'],status=r['status'],evidence_class=kind,
                        proposed_purchase_quantity='UNKNOWN',reason='Demand velocity, budget and owner purchase permission required',purchase_authorized=False)
                        for r in opportunities if r['status']=='REVIEW_PROPOSAL_ONLY'],
                    executive=dict(evidence_class=kind,asins=len(amazon['rows']),universe_asins=len(amazon['rows'])+len(universe),historical_unobserved=len(universe),research_candidates=len(research),
                        current_amazon_review_ready=sum(r['review_ready'] for r in amazon['rows']),
                        economic_review_proposals=sum(r['status']=='REVIEW_PROPOSAL_ONLY' for r in opportunities),
                        realized_sales='UNKNOWN',live_api_calls=0,purchases_authorized=0),
                    method=dict(demand='Exact US category ID/rank type pilot groups only; no global BSR score or monthly sales model.',
                        competition='Current reported New counts; partial returned details are not a full seller census.',
                        research='Review-ready first, ASIN tie order; category groups carry demand-relative priority; no cross-category BSR comparison.',
                        economics='Decimal, unrounded >=50% acquisition ROI and >=$5 profit. Excel formulas are audit aids; JSON decides gates.',
                        markup='Net-profit/acquisition percent, identical to acquisition ROI; margin=net-profit/selling-price.',
                        history='Separate append-only, idempotent, hash-chained local history. Synthetic/live classes never pooled.',
                        freshness='M80 ranks/restrictions 24h, New offers 6h; saved acquisition/fee/risk receipts 24h. Future timestamps rejected.',
                        pricing='Lowest observed current New landed price; fee estimate must match that exact selling price.',
                        trust='Owner-reviewed original ledger and receipt artifact pins. Local receipt assertions require independent human review.',
                        unknown='Missing evidence stays UNKNOWN/excluded. Listing permission is not FBA or purchase approval.',
                        forecasts='One BSR snapshot cannot establish velocity. No inventory quantity model or realized profit inferred.'))
                json_write(stage/'decision-report.json',report);workbook(report,stage/'decision-report.xlsx')
                json_write(stage/'research-shortlist.json',dict(schema=1,purpose='OWNER_RESEARCH_REVIEW_ONLY',evidence_class=kind,
                    purchase_authorized=False,sourcing_authorized=False,products=[dict(asin=r['asin'],**r['identity'],
                        prices=r['prices'],listing_permission=r['listing_permission'],provenance=r['provenance']) for r in research]))
                if implementation()!=code or any(digest(Path(p))!=sha for p,sha in pins.items()):raise ValueError('Input/code drift during report')
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','output','history'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--manifest-sha256',required=True);p.add_argument('--as-of',required=True)
    a=p.parse_args(argv)
    try:report=run(a.manifest,a.manifest_sha256,a.output,a.history,datetime.fromisoformat(a.as_of))
    except (ValueError,OSError,sqlite3.Error) as exc:
        print(json.dumps(dict(status='FAIL_CLOSED',error_type=type(exc).__name__)),file=sys.stderr);return 1
    print('OFFLINE_DECISION_COMPLETE: '+str(report['executive']['asins'])+' ASINs; '+report['source_kind']+'; 0 live requests; proposals only')
    return 0


if __name__=='__main__':raise SystemExit(main())
