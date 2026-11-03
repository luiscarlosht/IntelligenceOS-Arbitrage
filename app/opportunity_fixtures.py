"""Fictional complete receipts for boundary tests and offline demonstrations."""
from copy import deepcopy
from datetime import datetime,timezone
from app.opportunity_engine import COSTS,RISKS

NOW=datetime(2026,11,3,1,tzinfo=timezone.utc)


def case():
    identity=dict(brand='Fictional',model='Model-1',quantity=1,size='Standard',variation='Blue',gtin='00036000291452')
    a=dict(asin='B800000000',marketplace='ATVPDKIKX0DER',account_binding_sha256='0'*64,condition='new_new',
        evidence_class='SYNTHETIC_TEST',review_ready=True,identity_issues=[],listing_permission='NO_LISTING_RESTRICTIONS_OBSERVED',
        identity=identity,current_gtins=[identity['gtin']],prices=[dict(basis='lowest_observed',landed_usd='30')],catalog_identity={k:identity[k] for k in ('brand','model','quantity')},
        provenance={str(k):dict(observed_at=NOW.isoformat(),source_sha256='2'*64) for k in (2,22,23)})
    common={k:a[k] for k in ('asin','marketplace','account_binding_sha256','condition')}
    common.update(currency='USD',evidence_class='SYNTHETIC',observed_at=NOW.isoformat(),owner_reviewed=True,
                  artifact_sha256='1'*64,source_reference='offline independently reviewed synthetic artifact')
    q=dict(deepcopy(common),kind='WALMART_QUOTE',source_reference='https://www.walmart.com/ip/SYNTHETIC',
        availability='IN_STOCK',product_condition='NEW',seller='Fictional fixture seller',fulfillment='Fictional fixture fulfillment',
        identity_verified=True,variation_verified=True,identity=deepcopy(identity),purchase_price='10',
        **{k:'0' for k in COSTS[:6]})
    f=dict(common,kind='AMAZON_FBA_FEE_ESTIMATE',sale_price='30',fulfillment='FBA',quantity=1,
           referral_fee='4.50',fulfillment_fee='3',storage='0.10',transaction_cost='0')
    r=dict(common,kind='OWNER_RISK_REVIEW',verified_amazon_identity=deepcopy(identity),**{k:'VERIFIED_FOR_EXACT_ACCOUNT_AND_PRODUCT' for k in RISKS})
    return a,q,f,r
