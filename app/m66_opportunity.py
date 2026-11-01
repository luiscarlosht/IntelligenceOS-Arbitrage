"""Strict identity and complete-cost decisions; never submits or purchases."""
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit

from app.m65_intelligence import ASIN, US, CONDITION, observed
from app.m66_verification import fresh
from app.marketplace import match_listings
from app.models import RetailProduct, MarketplaceListing
from app.normalization import gtin, identity, money
from app.profitability import analyze

DECISIONS=('REJECTED_RESTRICTION','REJECTED_IDENTITY_MISMATCH','REJECTED_PROFITABILITY',
           'REQUIRES_APPROVAL','NEEDS_SELLER_VERIFICATION','NEEDS_FBA_VERIFICATION',
           'NEEDS_RETAILER_MATCH','NEEDS_FEE_DATA','READY_FOR_PURCHASE_REVIEW')
COSTS=('amazon_sale_price','retailer_price','retailer_shipping','sales_tax','referral_fee','fba_fee',
       'inbound_shipping','preparation_cost','packaging_cost','storage_cost',
       'other_acquisition_cost','other_selling_cost')
PRODUCT_FIELDS=('brand','title','gtin','model','size','pack_quantity','variation','url','observed_at','source_reference')


def template(asin: str) -> dict:
    if not ASIN.fullmatch(asin):raise ValueError('ASIN required')
    return dict(schema=1,asin=asin,marketplace=US,condition=CONDITION,
        amazon_product={k:None for k in PRODUCT_FIELDS},retailer_product={k:None for k in PRODUCT_FIELDS},
        costs={k:dict(value=None,currency='USD',observed_at=None,source_reference=None,
                     asin=asin if k in ('amazon_sale_price','referral_fee','fba_fee') else None,
                     condition=CONDITION if k in ('amazon_sale_price','referral_fee','fba_fee') else None,
                     fulfillment='FBA' if k in ('referral_fee','fba_fee') else None,
                     sale_price_basis=None) for k in COSTS},
        inventory_units=None,purchase_authorized=False,
        estimates=dict(expected_net_profit=None,roi_percent=None,estimated_inventory_investment=None),
        cost_basis='All costs per complete matched selling unit; explicit zero allowed, missing never zero')


def exact_match(record: dict, *, as_of: datetime) -> dict:
    amazon=record.get('amazon_product') or {};retailer=record.get('retailer_product') or {}
    missing=[];mismatch=[]
    if not isinstance(amazon,dict) or not isinstance(retailer,dict):
        return dict(exact=False,missing=['product_evidence'],mismatches=[])
    values={}
    for side,product in (('amazon',amazon),('retailer',retailer)):
        for key in PRODUCT_FIELDS:
            if product.get(key) is None or product.get(key)=='':missing.append(side+'.'+key)
            elif key!='pack_quantity' and not isinstance(product.get(key),str):missing.append(side+'.'+key+'_type')
        date=product.get('observed_at')
        if not fresh(date,as_of):missing.append(side+'.fresh_observation')
        url=product.get('url')
        try:
            parsed=urlsplit(url) if isinstance(url,str) else None
            if not parsed or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
                missing.append(side+'.https_url')
        except ValueError:missing.append(side+'.https_url')
        if not isinstance(product.get('source_reference'),str) or not product.get('source_reference'):
            missing.append(side+'.source_reference')
        try:
            code=gtin(product.get('gtin'))
        except (ValueError,AttributeError):
            code='';mismatch.append(side+'.invalid_gtin')
        if not code:missing.append(side+'.valid_gtin')
        pack=product.get('pack_quantity')
        if type(pack) is not int or pack<=0:missing.append(side+'.positive_pack_quantity')
        values[side]=code
    if amazon.get('url') and amazon.get('url')!='https://www.amazon.com/dp/'+record['asin']:
        mismatch.append('amazon_asin_url')
    for field in ('brand','model','size','variation'):
        left,right=amazon.get(field),retailer.get(field)
        if left and right and (not isinstance(left,str) or not isinstance(right,str) or identity(left)!=identity(right)):
            mismatch.append(field)
    if values['amazon'] and values['retailer'] and values['amazon']!=values['retailer']:mismatch.append('gtin')
    if type(amazon.get('pack_quantity')) is int and type(retailer.get('pack_quantity')) is int and amazon['pack_quantity']!=retailer['pack_quantity']:
        mismatch.append('pack_quantity')
    if not missing and not mismatch:
        # Existing matcher is reused; M66 additionally requires GTIN, size and
        # both complete identity observations rather than model-only fallback.
        p=RetailProduct('supplied',retailer['title'],retailer['url'],values['retailer'],retailer['brand'],
            retailer['model'],retailer['pack_quantity'],None,'unknown',
            datetime.fromisoformat(observed(retailer['observed_at'])),retailer['source_reference'],variation=retailer['variation'])
        listing=MarketplaceListing(record['asin'],values['amazon'],amazon['brand'],amazon['model'],
            amazon['pack_quantity'],amazon['variation'],None,None)
        if not match_listings(p,(listing,)).exact:mismatch.append('existing_matcher_rejected')
    return dict(exact=not missing and not mismatch,missing=sorted(set(missing)),mismatches=sorted(set(mismatch)))


def economics(record: dict, *, as_of: datetime) -> dict:
    missing=[];values={}
    inputs=record.get('costs') or {}
    if not isinstance(inputs,dict):inputs={}
    for key in COSTS:
        field=inputs.get(key)
        if not isinstance(field,dict):missing.append(key);continue
        try:
            value=money(field.get('value'))
        except (ValueError,TypeError):value=None
        if (value is None or field.get('currency')!='USD' or not isinstance(field.get('source_reference'),str) or not field.get('source_reference')
                or not fresh(field.get('observed_at'),as_of)):
            missing.append(key)
        else:values[key]=value
    units=record.get('inventory_units')
    if type(units) is not int or units<=0:missing.append('positive_inventory_units')
    for key in ('amazon_sale_price','referral_fee','fba_fee'):
        field=inputs.get(key) or {}
        if not isinstance(field,dict):continue
        if field.get('asin')!=record.get('asin') or field.get('condition')!=CONDITION:
            missing.append(key+'.asin_condition_scope')
        if key in ('referral_fee','fba_fee'):
            try:basis=money(field.get('sale_price_basis'))
            except (ValueError,TypeError):basis=None
            if field.get('fulfillment')!='FBA' or basis is None or basis!=values.get('amazon_sale_price'):
                missing.append(key+'.fba_sale_price_scenario')
    if missing:
        return dict(complete=False,missing=sorted(set(missing)),net_profit=None,expected_net_profit=None,roi_percent=None,
                    estimated_inventory_investment=None,passes=None)
    purchase=values['retailer_price']+values['retailer_shipping']
    if purchase<=0 or values['amazon_sale_price']<=0:
        return dict(complete=False,missing=['positive_purchase_and_sale_price'],net_profit=None,expected_net_profit=None,roi_percent=None,
                    estimated_inventory_investment=None,passes=None)
    mapped=dict(inbound_shipping=values['inbound_shipping'],preparation=values['preparation_cost'],
        packaging=values['packaging_cost'],sales_tax=values['sales_tax'],other_cost=values['other_acquisition_cost'],
        fulfillment_fee=values['fba_fee'],storage=values['storage_cost'],
        transaction_cost=values['other_selling_cost'],referral_fee=values['referral_fee'])
    e=analyze(purchase,values['amazon_sale_price'],mapped)
    investment=e.acquisition_cost*units
    acquisition=values['retailer_price']+values['retailer_shipping']+values['sales_tax']
    other=sum((values[k] for k in ('preparation_cost','packaging_cost','storage_cost','other_acquisition_cost','other_selling_cost')),Decimal('0'))
    assert e.net_profit==values['amazon_sale_price']-values['referral_fee']-values['fba_fee']-acquisition-values['inbound_shipping']-other
    return dict(complete=True,missing=[],net_profit=str(e.net_profit),expected_net_profit=str(e.net_profit),roi_percent=str(e.roi),
        acquisition_cost=str(acquisition),amazon_fees=str(values['referral_fee']+values['fba_fee']),
        inbound_shipping=str(values['inbound_shipping']),other_costs=str(other),
        total_invested_cost_per_unit=str(e.acquisition_cost),estimated_inventory_investment=str(investment),
        inventory_units=units,passes=e.roi>=50 and e.net_profit>=5 and investment<=500,
        cost_basis='ROI denominator: retailer price + retailer shipping + tax + inbound + prep + packaging + other acquisition; Amazon fees/storage/other selling charges deducted once from proceeds')


def decide(record: dict, verification: dict, *, as_of: datetime) -> dict:
    asin=record.get('asin')
    if (not isinstance(asin,str) or not ASIN.fullmatch(asin) or verification.get('asin')!=asin
            or record.get('marketplace')!=US or record.get('condition')!=CONDITION
            or verification.get('marketplace')!=US or verification.get('condition')!=CONDITION):
        raise ValueError('Exact ASIN/US/New decision scope required')
    # Reusing an old verified aggregate cannot turn stale evidence into READY.
    aggregate_fresh=fresh(verification.get('evaluated_at'),as_of)
    listing_expiry=observed(verification.get('listing_valid_until'))
    fba_expiry=observed(verification.get('fba_valid_until'))
    result=dict(asin=asin,decision='NEEDS_SELLER_VERIFICATION',reasons=[],identity=None,economics=None,
                purchase_authorized=False,listing_submission_authorized=False)
    if record.get('is_mock') is True or record.get('is_synthetic') is True:
        result['reasons']=['SIMULATED_INPUT_IS_NOT_VERIFIED_OPPORTUNITY']
        return result
    sc=set(verification.get('seller_central_states',[]))
    restriction_codes=set(verification.get('manual_restriction_codes',[]))
    if verification.get('conflict_requires_review') or 'BRAND_VALIDATION_BLOCKED' in sc:
        result['reasons']=['CONFLICT_OR_BRAND_VALIDATION_REQUIRES_REVIEW']
    elif (verification.get('api_state') in ('NOT_ELIGIBLE','OTHER_RESTRICTED') or 'NEW_LISTINGS_NOT_ACCEPTED' in sc
          or restriction_codes&{'PRODUCT_RESTRICTED','CATEGORY_RESTRICTED'}):
        result.update(decision='REJECTED_RESTRICTION',reasons=['REPORTED_SELLING_RESTRICTION'])
    elif verification.get('api_state')=='APPROVAL_REQUIRED' or 'APPROVAL_APPLICATION_REQUIRED' in sc:
        result.update(decision='REQUIRES_APPROVAL',reasons=['OBSERVED_APPROVAL_PATHWAY'])
    elif (not aggregate_fresh or verification.get('listing_permission_verified') is not True
          or not listing_expiry or as_of>datetime.fromisoformat(listing_expiry)):
        result['reasons']=['FRESH_API_AND_EXISTING_ASIN_OFFER_VERIFICATION_REQUIRED']
    elif (verification.get('fba_conflict_requires_review') or verification.get('fba_state')=='FBA_UNKNOWN'
          or (verification.get('fba_state')=='FBA_ELIGIBLE' and (not fba_expiry or as_of>datetime.fromisoformat(fba_expiry)))):
        result.update(decision='NEEDS_FBA_VERIFICATION',reasons=['INDEPENDENT_FBA_EVIDENCE_REQUIRED'])
    elif verification.get('fba_state')=='FBA_INELIGIBLE':
        result.update(decision='REJECTED_RESTRICTION',reasons=['FBA_INELIGIBLE'])
    elif verification.get('fba_state')!='FBA_ELIGIBLE':
        result.update(decision='NEEDS_FBA_VERIFICATION',reasons=['INDEPENDENT_FBA_EVIDENCE_REQUIRED'])
    else:
        match=exact_match(record,as_of=as_of);result['identity']=match
        if match['mismatches']:result.update(decision='REJECTED_IDENTITY_MISMATCH',reasons=match['mismatches'])
        elif not match['exact']:result.update(decision='NEEDS_RETAILER_MATCH',reasons=match['missing'])
        else:
            costs=economics(record,as_of=as_of);result['economics']=costs
            if not costs['complete']:result.update(decision='NEEDS_FEE_DATA',reasons=costs['missing'])
            elif not costs['passes']:result.update(decision='REJECTED_PROFITABILITY',reasons=['ROI_PROFIT_OR_INVENTORY_BUDGET_FAILED'])
            else:result.update(decision='READY_FOR_PURCHASE_REVIEW',reasons=['ALL_EVIDENCE_GATES_PASS_REVIEW_ONLY'])
    return result
