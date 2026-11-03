"""Offline conservative per-Amazon-selling-unit economics. No sourcing clients."""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlsplit
from app.normalization import gtin, identity, timestamp
from app.profitability import analyze

UNKNOWN='UNKNOWN'
COSTS=('walmart_shipping','sales_tax','preparation','inbound_shipping','packaging','other_cost',
       'referral_fee','fulfillment_fee','storage','transaction_cost')
IDENTITY=('brand','model','quantity','size','variation')
RISKS=('brand_resale','authenticity','invoice_acceptability','fba_eligibility')


def amount(value) -> Decimal:
    if isinstance(value,bool) or value in (None,'',UNKNOWN):raise ValueError('Explicit USD amount required')
    try:result=Decimal(str(value))
    except InvalidOperation:raise ValueError('Invalid amount') from None
    if not result.is_finite() or result<0 or result>Decimal('1000000000') or abs(result.as_tuple().exponent)>18:raise ValueError('Finite nonnegative amount required')
    return result


def known(value):return value not in (None,'',UNKNOWN)


def receipt(value:dict, now:datetime, kind:str, synthetic:bool, hours:int=24) -> None:
    if not isinstance(value,dict) or value.get('kind')!=kind or value.get('currency')!='USD':raise ValueError('Receipt scope required')
    if value.get('evidence_class')!=('SYNTHETIC' if synthetic else 'CURRENT_LIVE'):raise ValueError('Evidence class mismatch')
    observed=timestamp(value.get('observed_at',''))
    if observed is None or not now-timedelta(hours=hours)<=observed<=now:raise ValueError('Fresh receipt required')
    if not isinstance(value.get('source_reference'),str) or not value['source_reference'].strip():raise ValueError('Reviewable source reference required')
    if not re.fullmatch('[a-f0-9]{64}',str(value.get('artifact_sha256',''))):raise ValueError('Original artifact digest required')
    if value.get('owner_reviewed') is not True:raise ValueError('Independent owner review required')


def evaluate(amazon:dict, quote:dict, fees:dict, risks:dict, now:datetime, *, synthetic:bool) -> dict:
    """Inputs must come from pinned source ledgers/receipts; asserted receipt trust is explicit."""
    if now.tzinfo is None:raise ValueError('Aware as-of time required')
    flags=[]; result=dict(asin=amazon.get('asin',UNKNOWN),evidence_class='SYNTHETIC' if synthetic else 'CURRENT_LIVE',
        status='EXCLUDED',flags=flags,purchase_authorized=False,sourcing_authorized=False,
        acquisition_cost=UNKNOWN,sale_price=UNKNOWN,net_profit=UNKNOWN,roi_percent=UNKNOWN,margin_percent=UNKNOWN,
        markup_percent=UNKNOWN,minimum_roi_percent='50',minimum_profit_usd='5',quantity_proposal=UNKNOWN,
        costs={k:UNKNOWN for k in COSTS},source_provenance=amazon.get('provenance',{}),
        estimated_monthly_unit_sales=UNKNOWN)
    try:
        expected='SYNTHETIC_TEST' if synthetic else 'AUTHORIZED_M80_OBSERVATION'
        if amazon.get('evidence_class')!=expected:raise ValueError('Amazon provenance class mismatch')
        if amazon.get('review_ready') is not True or amazon.get('identity_issues'):raise ValueError('Fresh Amazon identity/demand/listing evidence required')
        stamps=amazon.get('provenance',{})
        if '22' not in stamps or len(stamps)!=3:raise ValueError('Complete observation timestamp provenance required')
        for slot,value in stamps.items():
            observed=timestamp(value.get('observed_at',''))
            if observed is None or not now-timedelta(hours=6 if slot=='22' else 24)<=observed<=now:raise ValueError('Fresh Amazon observation required')
        if amazon.get('listing_permission')!='NO_LISTING_RESTRICTIONS_OBSERVED':raise ValueError('Listing restriction clearance required')
        for value,kind in ((quote,'WALMART_QUOTE'),(fees,'AMAZON_FBA_FEE_ESTIMATE'),(risks,'OWNER_RISK_REVIEW')):
            receipt(value,now,kind,synthetic)
            for key in ('asin','marketplace','account_binding_sha256','condition'):
                if not known(amazon.get(key)) or value.get(key)!=amazon[key]:raise ValueError('Receipt account/ASIN/condition mismatch')
        url=urlsplit(quote.get('source_reference',''))
        if url.scheme!='https' or url.hostname not in ('www.walmart.com','walmart.com') or url.username or url.password or url.port not in (None,443):
            raise ValueError('Saved Walmart HTTPS product quote required')
        if quote.get('identity_verified') is not True:raise ValueError('Independent identity review required')
        prior=amazon.get('identity',{});a=risks.get('verified_amazon_identity');q=quote.get('identity',{})
        if not isinstance(a,dict):raise ValueError('Independent exact Amazon identity review required')
        for key in ('gtin',*IDENTITY):
            if known(prior.get(key)) and a.get(key)!=prior[key]:raise ValueError('Reviewed Amazon identity contradicts frozen '+key)
        observed_identity=amazon.get('catalog_identity',{})
        for key in ('brand','model','quantity'):
            if not known(observed_identity.get(key)) or observed_identity[key]!=a.get(key):raise ValueError('Current catalog '+key+' verification required')
        av=gtin(a.get('gtin') if known(a.get('gtin')) else '')
        current=amazon.get('current_gtins',[])
        if not av or current!=[av] or gtin(q.get('gtin',''))!=av:raise ValueError('Exact current checksum-valid GTIN required')
        for key in IDENTITY:
            if not known(a.get(key)) or not known(q.get(key)):raise ValueError('Missing exact '+key)
            if key=='quantity':
                if type(a[key]) is not int or a[key]<1 or type(q[key]) is not int or a[key]!=q[key]:raise ValueError('Pack quantity mismatch')
            elif not isinstance(a[key],str) or not isinstance(q[key],str) or identity(a[key])!=identity(q[key]):raise ValueError('Exact '+key+' mismatch')
        # Exact variation validation is independently documented; no inferred pack conversion.
        if quote.get('variation_verified') is not True:raise ValueError('Variation verification required')
        prices=[amount(p['landed_usd']) for p in amazon.get('prices',[]) if p.get('basis')=='lowest_observed' and known(p.get('landed_usd'))]
        if not prices or min(prices)<=0:raise ValueError('Current New landed offer price required')
        sale=min(prices)
        if amount(fees.get('sale_price'))!=sale or fees.get('fulfillment')!='FBA':raise ValueError('Fee estimate must match conservative selling price and FBA')
        if fees.get('quantity')!=a['quantity'] or type(fees.get('quantity')) is not int:raise ValueError('Fee package scope mismatch')
        for key in RISKS:
            if risks.get(key)!='VERIFIED_FOR_EXACT_ACCOUNT_AND_PRODUCT':raise ValueError('Unresolved risk: '+key)
        purchase=amount(quote.get('purchase_price'))
        if purchase<=0:raise ValueError('Positive purchase price required')
        costs={k:amount((fees if k in ('referral_fee','fulfillment_fee','storage','transaction_cost') else quote).get(k)) for k in COSTS}
        legacy={k:v for k,v in costs.items() if k!='walmart_shipping'}
        legacy['other_cost']+=costs['walmart_shipping']
        economics=analyze(purchase,sale,legacy)
        result.update(purchase_price=str(purchase),sale_price=str(sale),acquisition_cost=str(economics.acquisition_cost),
            costs={k:str(v) for k,v in costs.items()},net_profit=str(economics.net_profit),roi_percent=str(economics.roi),
            margin_percent=str(economics.net_profit/sale*100),markup_percent=str(economics.net_profit/economics.acquisition_cost*100),
            receipt_sha256={k:v['artifact_sha256'] for k,v in (('quote',quote),('fees',fees),('risks',risks))},identity=a)
        if economics.roi<Decimal('50'):flags.append('BELOW_50_PERCENT_ACQUISITION_ROI')
        if economics.net_profit<Decimal('5'):flags.append('BELOW_5_USD_NET_PROFIT')
        if not flags:result['status']='REVIEW_PROPOSAL_ONLY'
    except (ValueError,TypeError,KeyError,AttributeError,InvalidOperation) as exc:flags.append(str(exc))
    return result


def rank(rows:list[dict]) -> list[dict]:
    return sorted(rows,key=lambda r:(r['status']!='REVIEW_PROPOSAL_ONLY',
        -Decimal(r['roi_percent']) if r['roi_percent']!=UNKNOWN else Decimal('Infinity'),r['asin']))
