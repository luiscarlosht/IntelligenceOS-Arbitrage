"""Local fictional M80-to-decision workbook demonstration. Never a sourcing agent."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
from app.m80_demo import plan,Clock,SyntheticTransport
from app.m80_journal import Journal
from app.m80_execution import run_claimed,Pacer
from app.opportunity_fixtures import case,NOW
from app.observations import canonical
from app.evidence_io import digest,json_write,safe
from app.decision_pipeline import run


def demonstrate_decisions(root:Path):
    root=safe(root)
    if root.exists() or root.is_relative_to('/mnt') or not root.parent.is_dir():raise ValueError('Fresh local synthetic root required')
    root.mkdir(mode=0o700)
    acquisition=root/'synthetic-acquisition';acquisition.mkdir(mode=0o700)
    contract=plan(acquisition);sample,q,f,r=case()
    contract['targets'][0].update(sample['identity'])
    # Original fictional plan/response fixture is enriched only inside this NEW synthetic acquisition.
    sample['identity']['title']=contract['targets'][0]['title']
    sample['identity']['upc_values']=[]
    r['verified_amazon_identity']=sample['identity']
    transport=SyntheticTransport(contract)
    transport.fixtures[2]['summaries'][0].update(brand=sample['identity']['brand'],modelNumber=sample['identity']['model'])
    transport.fixtures[2]['identifiers']=[dict(marketplaceId=contract['marketplace_id'],identifiers=[dict(identifierType='UPC',identifier='036000291452')])]
    universe=root/'synthetic-source';universe.mkdir(mode=0o700)
    handoff=universe/'M79_walmart_handoff.json'
    historical=[dict(asin=f'B9{i:08d}',marketplace=contract['marketplace_id'],title='SYNTHETIC historical identity only',sourcing_allowed=False)
                for i in range(1377)]
    old=root/'synthetic-old';old.mkdir(mode=0o700)
    prior=old/'original.json';json_write(prior,dict(evidence_class='SYNTHETIC',historical_only=True))
    contract['protected_roots'].append(str(old.resolve()))
    json_write(handoff,dict(ready_for_walmart_sourcing=False,priority20=contract['targets'],all_asins=contract['targets']+historical,
                           input_sha256={str(prior):digest(prior)}))
    contract['handoff_sha256']=digest(handoff)
    clock=Clock();journal=Journal(acquisition/'synthetic-m80.sqlite3',dict(plan=contract,authorization_sha256='0'*64,synthetic=True))
    run_claimed(journal,transport,contract,before_request=lambda:None,pacer=Pacer(clock.monotonic,clock.sleep),monotonic=clock.monotonic,utcnow=clock.utcnow)
    journal.close()
    sources=root/'inputs';sources.mkdir(mode=0o700);state=root/'own-state';state.mkdir(mode=0o700)
    ledger=root/'synthetic-acquisition/synthetic-m80.sqlite3'
    manifest=sources/'manifest.json'
    pins=[]
    q.update(identity=sample['identity'],purchase_price='1')
    f.update(sale_price='10',referral_fee='1',fulfillment_fee='1',storage='0',transaction_cost='0')
    for i,receipt in enumerate((q,f,r)):
        # Explicit fictional source artifacts: only demonstrate pinning, never live trust.
        artifact=sources/f'synthetic-original-{i}.txt';artifact.write_text('SYNTHETIC ONLY '+canonical(receipt));artifact.chmod(0o600)
        receipt.update(artifact_path=artifact.name,artifact_sha256=digest(artifact))
        path=sources/f'receipt-{i}.json';json_write(path,receipt);pins.append(dict(path=path.name,sha256=digest(path)))
    json_write(manifest,dict(schema=1,handoff=dict(path=str(handoff),sha256=digest(handoff)),ledger=dict(path=str(ledger),sha256=digest(ledger)),receipts=pins))
    report=run(manifest,digest(manifest),root/'report',state/'observations.sqlite3',datetime(2026,11,3,1,tzinfo=timezone.utc))
    if report['executive']['economic_review_proposals']!=1:raise ValueError('Only the fully fictional, completely evidenced example may pass review gates')
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args(argv)
    report=demonstrate_decisions(args.output)
    print('SYNTHETIC_DECISION_DEMO: 20 ASINs, 1 fictional review proposal, 19 excluded without complete receipts, workbook complete, 0 live requests')


if __name__=='__main__':main()
