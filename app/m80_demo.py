"""Explicit synthetic 42-slot demonstration. No credentials files or live network."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import sys
from app.m80_contract import OPERATION, BUDGET, RATES, definitions, implementation
from app.m80_execution import Transport, Pacer, run_claimed
from app.m80_journal import Journal, inspect
from app.m80 import export


class Clock:
    def __init__(self): self.seconds=0.0
    def monotonic(self): return self.seconds
    def sleep(self,seconds): self.seconds+=seconds
    def utcnow(self): return datetime(2026,11,3,tzinfo=timezone.utc)+timedelta(seconds=self.seconds)


def plan(root:Path) -> dict:
    asins=[f'B8{i:08d}' for i in range(20)]
    targets=[dict(asin=a,marketplace='ATVPDKIKX0DER',brand='Synthetic brand',model=f'M-{i}',quantity=1,title=f'SYNTHETIC product {i}',
                  gtin='UNKNOWN',upc_values=[],size='UNKNOWN',variation='UNKNOWN',
                  identity_conflicts=[],permanently_excluded=False,sourcing_allowed=False) for i,a in enumerate(asins)]
    return dict(schema=1,operation_id=OPERATION,marketplace_id='ATVPDKIKX0DER',condition='new_new',
        private_root=str(root.resolve()),handoff_path=str(root.resolve().parent/'synthetic-source/M79_walmart_handoff.json'),
        protected_roots=[str(root.resolve().parent/'synthetic-source')],
        handoff_sha256='0'*64,account_sha256='0'*64,asins=asins,targets=targets,requests=definitions(asins),
        budget=deepcopy(BUDGET),rates=deepcopy(RATES),maximum_seconds=600,
        implementation_sha256=implementation(),purchase_authorized=False,walmart_sourcing_authorized=False)


def replies(contract:dict) -> dict[int,dict]:
    us=contract['marketplace_id']; result={1:dict(access_token='SYNTHETIC-NOT-A-REAL-TOKEN',token_type='bearer',expires_in=3600)}
    batch=[]
    for i,a in enumerate(contract['asins']):
        result[i+2]=dict(asin=a,summaries=[dict(marketplaceId=us,brand='Synthetic brand',modelNumber=f'M-{i}',packageQuantity=1,
            itemClassification='VARIATION_PARENT' if i==5 else 'BASE_PRODUCT')],
            salesRanks=[dict(marketplaceId=us,displayGroupRanks=[dict(websiteDisplayGroup=f'synthetic-category-{i%2}',
                title='SYNTHETIC category',rank=1000+50*i)])])
        price={'CurrencyCode':'USD','Amount':10+i}
        payload=dict(ASIN=a,status='Success',Identifier=dict(ASIN=a,MarketplaceId=us,ItemCondition='New'),
            Summary=dict(TotalOfferCount=i%5+1,NumberOfOffers=[dict(condition='new',fulfillmentChannel='Amazon',OfferCount=i%5+1)],
                LowestPrices=[dict(condition='new',fulfillmentChannel='Amazon',LandedPrice=price)],
                BuyBoxPrices=[dict(condition='new',LandedPrice=price)]),Offers=[dict(IsBuyBoxWinner=True)])
        batch.append(dict(request=deepcopy(contract['requests'][21]['body']['requests'][i]),
                          status={'statusCode':200},headers={},body={'payload':payload}))
        result[i+23]={'restrictions':[dict(asin=a,marketplaceId=us,conditionType='new_new',reasons=[dict(reasonCode='APPROVAL_REQUIRED')])] if i in (3,7) else []}
    result[22]={'responses':batch}
    return result


class SyntheticTransport(Transport):
    def __init__(self, contract:dict):
        super().__init__({'client_id':'SYNTHETIC-CLIENT-ID','client_secret':'SYNTHETIC-CLIENT-SECRET',
                          'refresh_token':'SYNTHETIC-REFRESH-TOKEN'},'SYNTHETICSELLER',contract)
        self.fixtures=replies(contract); self.calls=[]
    def send(self,request,definition):
        self.validate(request,definition); self.calls.append(definition['slot'])
        return dict(status=200,headers={},body=deepcopy(self.fixtures[definition['slot']]))


def demonstrate(output:Path) -> dict:
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents) or output.resolve().is_relative_to('/mnt'):
        raise ValueError('New local synthetic output required')
    output.mkdir(mode=0o700)
    contract=plan(output); clock=Clock(); transport=SyntheticTransport(contract)
    journal=Journal(output/'synthetic-m80.sqlite3',{'plan':contract,'authorization_sha256':'0'*64,'synthetic':True})
    run_claimed(journal,transport,contract,before_request=lambda:None,pacer=Pacer(clock.monotonic,clock.sleep),
                monotonic=clock.monotonic,utcnow=clock.utcnow)
    journal.close()
    snapshot=inspect(output/'synthetic-m80.sqlite3')
    report=export(snapshot,output/'m80-results',clock.utcnow())
    if snapshot['status']!='COMPLETED_NO_REPLAY' or len(transport.calls)!=42: raise ValueError('Synthetic demonstration failed')
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--output',type=Path,required=True); args=p.parse_args(argv)
    def guard(event,arguments):
        if event.startswith(('socket.','subprocess.')): raise PermissionError('Synthetic demonstration forbids networking/processes')
    sys.addaudithook(guard)
    report=demonstrate(args.output)
    print(f"M80_SYNTHETIC_ONLY: {report['requests_consumed']} accounted fixture requests; 0 live requests; {len(report['rows'])} ASINs; no sourcing/purchases")


if __name__=='__main__': main()
