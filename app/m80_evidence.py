"""Typed US/New/Consumer observations. No sales-volume model or purchase approval."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal
from app.m65_intelligence import US
from app.observations import fingerprint
from app.normalization import gtin
from app.m65_intelligence import ASIN


@dataclass(frozen=True)
class Rank:
    kind: Literal['display_group', 'classification']
    category_id: str
    title: str
    rank: int


@dataclass(frozen=True)
class Catalog:
    asin: str
    ranks: tuple[Rank, ...]
    variation_parent: bool | None
    brand: str | None
    model: str | None
    quantity: int | None
    gtins: tuple[str, ...] = ()
    parent_asins: tuple[str, ...] = ()


@dataclass(frozen=True)
class Price:
    basis: Literal['lowest_observed', 'buy_box_observed']
    landed_usd: str | None
    fulfillment: str | None


@dataclass(frozen=True)
class Offers:
    asin: str
    total_count: int | None
    new_count: int | None
    prices: tuple[Price, ...]
    returned_offers: int | None
    buy_box_winner_observed: bool | None


@dataclass(frozen=True)
class Restrictions:
    asin: str
    status: Literal['NO_LISTING_RESTRICTIONS_OBSERVED', 'RESTRICTED', 'UNKNOWN']
    reason_codes: tuple[str, ...]
    fba_permission: str = 'UNKNOWN'
    purchase_authorized: bool = False


def integer(value, minimum=0) -> int:
    if type(value) is not int or value < minimum: raise ValueError('Explicit bounded integer required')
    return value


def text(value) -> str:
    if not isinstance(value,str) or not value or len(value)>512 or any(not c.isprintable() for c in value):
        raise ValueError('Bounded observed text required')
    return value


def money(value: dict | None) -> Decimal | None:
    if value is None: return None
    if not isinstance(value,dict) or value.get('CurrencyCode') != 'USD' or isinstance(value.get('Amount'),bool):
        raise ValueError('Explicit USD amount required')
    try: result=Decimal(str(value['Amount']))
    except (InvalidOperation, KeyError): raise ValueError('Invalid amount') from None
    if not result.is_finite() or result < 0: raise ValueError('Invalid amount')
    return result


def catalog(body: dict, asin: str) -> Catalog:
    if body.get('asin') != asin or body.get('errors'): raise ValueError('Catalog ASIN/status mismatch')
    ranks=[]; seen=set()
    datasets=body.get('salesRanks', [])
    if not isinstance(datasets,list): raise ValueError('Rank dataset must be an array')
    for scoped in datasets:
        if scoped.get('marketplaceId') != US: raise ValueError('Rank marketplace mismatch')
        for key,kind,id_key in (('displayGroupRanks','display_group','websiteDisplayGroup'),
                                ('classificationRanks','classification','classificationId')):
            values=scoped.get(key,[])
            if not isinstance(values,list): raise ValueError('Rank list required')
            for row in values:
                identifier=text(row.get(id_key)); number=integer(row.get('rank'),1)
                marker=(kind,identifier)
                if marker in seen: raise ValueError('Ambiguous duplicate category rank')
                seen.add(marker); ranks.append(Rank(kind,identifier,text(row.get('title')),number))
    summaries=body.get('summaries',[])
    if not isinstance(summaries,list) or len(summaries)>1 or any(s.get('marketplaceId')!=US for s in summaries):
        raise ValueError('Unambiguous US summary required')
    summary=summaries[0] if summaries else {}
    classification=summary.get('itemClassification')
    quantity=summary.get('packageQuantity')
    if classification is not None and classification not in ('BASE_PRODUCT','VARIATION_CHILD','VARIATION_PARENT'):
        raise ValueError('Explicit known item classification required')
    if quantity is not None: integer(quantity,1)
    for key in ('brand','modelNumber'):
        if summary.get(key) is not None: text(summary[key])
    identifiers=set(); parents=set()
    for scoped in body.get('identifiers',[]):
        if scoped.get('marketplaceId')!=US: raise ValueError('Identifier marketplace mismatch')
        for item in scoped.get('identifiers',[]):
            if item.get('identifierType') in ('UPC','EAN','GTIN'):
                value=gtin(item.get('identifier'))
                if not value: raise ValueError('Explicit valid GTIN required')
                identifiers.add(value)
    for scoped in body.get('relationships',[]):
        if scoped.get('marketplaceId')!=US: raise ValueError('Relationship marketplace mismatch')
        for relation in scoped.get('relationships',[]):
            for parent in relation.get('parentAsins',[]):
                if not isinstance(parent,str) or not ASIN.fullmatch(parent): raise ValueError('Valid variation parent ASIN required')
                parents.add(parent)
    return Catalog(asin,tuple(ranks), None if classification is None else classification=='VARIATION_PARENT',
                   summary.get('brand'),summary.get('modelNumber'),quantity,tuple(sorted(identifiers)),tuple(sorted(parents)))


def offers(body: dict, asin: str) -> Offers:
    if body.get('errors'): raise ValueError('Pricing error envelope')
    payload=body.get('payload')
    if not isinstance(payload,dict) or payload.get('ASIN')!=asin or payload.get('status') not in ('Success','NoBuyableOffers'):
        raise ValueError('Bound successful pricing ASIN required')
    identifier=payload.get('Identifier',{})
    if (not isinstance(identifier,dict) or identifier.get('MarketplaceId')!=US
            or identifier.get('ASIN',asin)!=asin or identifier.get('ItemCondition')!='New'):
        raise ValueError('US/New pricing identifier required')
    summary=payload.get('Summary',{})
    if not isinstance(summary,dict): raise ValueError('Summary object required')
    total=summary.get('TotalOfferCount')
    if total is not None: integer(total)
    groups=summary.get('NumberOfOffers')
    new=None
    if groups is not None:
        if not isinstance(groups,list): raise ValueError('Count groups array required')
        seen=set(); subtotal=0; new=0
        for row in groups:
            integer(row.get('OfferCount'))
            condition=row.get('condition'); channel=row.get('fulfillmentChannel')
            if not isinstance(condition,str) or channel not in ('Amazon','Merchant'):
                new=None; continue  # Optional scope labels cannot be inferred.
            if condition.casefold() not in ('new','used','collectible','refurbished','club'): raise ValueError('Unknown condition count label')
            key=(condition.casefold(),channel)
            if key in seen: raise ValueError('Duplicate count group')
            seen.add(key); count=integer(row.get('OfferCount')); subtotal+=count
            if condition.casefold()=='new' and new is not None: new+=count
        if total is not None and subtotal>total: raise ValueError('Inconsistent offer counts')
        if not groups or total is None or subtotal!=total: new=0 if total==0 and groups==[] else None
    prices=[]
    for key,basis in (('LowestPrices','lowest_observed'),('BuyBoxPrices','buy_box_observed')):
        values=summary.get(key,[])
        if not isinstance(values,list): raise ValueError('Price list required')
        for row in values:
            if not isinstance(row.get('condition'),str): raise ValueError('Price condition required')
            if row['condition'].casefold()!='new': continue
            if row.get('offerType','B2C')!='B2C': raise ValueError('Consumer pricing required')
            listing=money(row.get('ListingPrice')); shipping=money(row.get('Shipping')); landed=money(row.get('LandedPrice'))
            if landed is None and listing is not None and shipping is not None: landed=listing+shipping
            if landed is not None and listing is not None and shipping is not None and landed!=listing+shipping:
                raise ValueError('Inconsistent landed price')
            channel=row.get('fulfillmentChannel')
            if channel is not None and channel not in ('Amazon','Merchant'): raise ValueError('Unknown fulfillment label')
            prices.append(Price(basis,str(landed) if landed is not None and landed>0 else None,channel))
    detail=payload.get('Offers')
    winner=None
    if detail is not None:
        if not isinstance(detail,list) or len(detail)>20 or (total is not None and len(detail)>total):
            raise ValueError('Bounded returned offer details required')
        for row in detail:
            if 'IsBuyBoxWinner' in row:
                if type(row['IsBuyBoxWinner']) is not bool: raise ValueError('Boolean Buy Box flag required')
                if row['IsBuyBoxWinner']: winner=True
        if total==0 and detail: raise ValueError('Zero-count contradiction')
    if (total==0 or new==0) and prices: raise ValueError('Zero-count pricing contradiction')
    if payload['status']=='NoBuyableOffers' and (total!=0 or detail!=[] or prices):
        raise ValueError('Explicit no-offer response inconsistent')
    return Offers(asin,total,new,tuple(prices),len(detail) if detail is not None else None,winner)


def batch(body: dict, requests: list[dict]) -> dict[str, Offers]:
    responses=body.get('responses')
    if not isinstance(responses,list) or len(responses)!=20: raise ValueError('All 20 batch responses required')
    expected={r['uri']:r for r in requests}; result={}
    for response in responses:
        request=response.get('request')
        if not isinstance(request,dict): raise ValueError('Batch request echo required')
        uri=request.get('uri'); wanted=expected.get(uri)
        if (wanted is None or set(request)-set(wanted)-{'headers'} or request.get('headers',{})!={}
                or any(request.get(k)!=v for k,v in wanted.items() if k!='CustomerType')
                or request.get('CustomerType','Consumer')!='Consumer'):
            raise ValueError('Batch request echo mismatch')
        asin=uri.split('/')[-2]
        headers=response.get('headers',{})
        if (uri not in expected or asin in result or type(response.get('status',{}).get('statusCode')) is not int or response.get('status',{}).get('statusCode')!=200
                or not isinstance(headers,dict) or any(k.casefold()=='retry-after' for k in headers)):
            raise ValueError('Batch member failure/duplicate/throttle')
        result[asin]=offers(response.get('body',{}),asin)
    if set(result)!={r['uri'].split('/')[-2] for r in requests}: raise ValueError('Incomplete batch')
    return result


def restrictions(body: dict, asin: str) -> Restrictions:
    values=body.get('restrictions')
    if body.get('errors') or not isinstance(values,list): raise ValueError('Explicit restrictions array required')
    codes=[]
    for row in values:
        if row.get('asin')!=asin or row.get('marketplaceId')!=US or row.get('conditionType','new_new')!='new_new':
            raise ValueError('Restrictions ASIN/marketplace/condition mismatch')
        for reason in row.get('reasons',[]): codes.append(text(reason.get('reasonCode')))
    return Restrictions(asin,'RESTRICTED' if values else 'NO_LISTING_RESTRICTIONS_OBSERVED',tuple(sorted(set(codes))))


def validate_response(definition: dict, body: dict) -> None:
    if definition['phase']=='catalog': catalog(body,definition['asin'])
    elif definition['phase']=='offers_batch': batch(body,definition['body']['requests'])
    elif definition['phase']=='restrictions': restrictions(body,definition['asin'])


def fresh(value: dict, now: datetime, hours: int) -> bool:
    try: observed=datetime.fromisoformat(value['observed_at'])
    except (ValueError,KeyError,TypeError): return False
    return bool(observed.tzinfo and now-timedelta(hours=hours)<=observed<=now)


def analyze(snapshot: dict, now: datetime) -> dict:
    if now.tzinfo is None: raise ValueError('Aware as-of time required')
    plan=snapshot['binding']['plan']; replies=snapshot['responses']; rows=[]; groups={}
    pricing={}; pricing_frame=replies.get(22)
    if pricing_frame and pricing_frame['http_status']==200 and fresh(pricing_frame,now,6):
        try: pricing=batch(pricing_frame['body'],plan['requests'][21]['body']['requests'])
        except (ValueError,TypeError,KeyError,AttributeError): pass
    for i,asin in enumerate(plan['asins']):
        ranks=[]; identity_issues=[]; observed_catalog=None; permission=None
        c=replies.get(i+2); r=replies.get(i+23)
        if c and c['http_status']==200 and fresh(c,now,24):
            try: observed_catalog=catalog(c['body'],asin); ranks=list(observed_catalog.ranks)
            except (ValueError,TypeError,KeyError,AttributeError): pass
        if r and r['http_status']==200 and fresh(r,now,24):
            try: permission=restrictions(r['body'],asin)
            except (ValueError,TypeError,KeyError,AttributeError): pass
        offer=pricing.get(asin)
        if observed_catalog and observed_catalog.variation_parent: identity_issues.append('VARIATION_PARENT')
        target=plan['targets'][i]
        if observed_catalog:
            for old, current in (('brand',observed_catalog.brand),('model',observed_catalog.model),('quantity',observed_catalog.quantity)):
                prior=target.get(old,target.get('pack_quantity') if old=='quantity' else None)
                if prior not in (None,'UNKNOWN') and current is not None and str(prior).strip().casefold()!=str(current).strip().casefold():
                    identity_issues.append('CHANGED_'+old.upper())
        if observed_catalog and observed_catalog.gtins:
            old_gtin=target.get('gtin')
            if old_gtin not in (None,'UNKNOWN') and gtin(old_gtin) not in observed_catalog.gtins: identity_issues.append('CHANGED_GTIN')
            if len(observed_catalog.gtins)>1: identity_issues.append('MULTIPLE_CURRENT_GTINS_REVIEW')
        row=dict(asin=asin, evidence_class='SYNTHETIC_TEST' if snapshot['binding'].get('synthetic') else 'AUTHORIZED_M80_OBSERVATION', marketplace=US, account_binding_sha256=plan['account_sha256'], condition='new_new',
            identity={key:target.get(key,'UNKNOWN') for key in ('brand','title','gtin','upc_values','model','quantity','size','variation')},
            provenance={str(s):{'observed_at':replies[s]['observed_at'],'source_sha256':replies[s]['source_sha256']} for s in (i+2,22,i+23) if s in replies}, ranks=[asdict(rank) for rank in ranks], category_relative_ranks=[],
            listing_permission=permission.status if permission else 'UNKNOWN',
            restriction_reasons=list(permission.reason_codes) if permission else [],
            total_offer_count=offer.total_count if offer and offer.total_count is not None else 'UNKNOWN',
            current_gtins=list(observed_catalog.gtins) if observed_catalog else [],
            variation_parent_asins=list(observed_catalog.parent_asins) if observed_catalog else [],
            returned_offer_count=offer.returned_offers if offer and offer.returned_offers is not None else 'UNKNOWN',
            offer_detail_coverage='UNKNOWN' if not offer or offer.returned_offers is None or offer.new_count is None else
                'COMPLETE_REPORTED_NEW' if offer.returned_offers==offer.new_count else 'PARTIAL_OR_FILTERED_REPORTED',
            confidence='SUPPORTED_OBSERVATIONS_ONLY' if ranks or offer or permission else 'UNKNOWN',
            new_offer_count=offer.new_count if offer and offer.new_count is not None else 'UNKNOWN',
            prices=[asdict(p) for p in offer.prices] if offer else [],
            buy_box_observed=True if offer and (offer.buy_box_winner_observed or any(p.basis=='buy_box_observed' and p.landed_usd for p in offer.prices)) else 'UNKNOWN',
            price_stability='UNKNOWN', estimated_monthly_unit_sales='UNKNOWN', sales_estimate_confidence='UNKNOWN',
            fba_permission='UNKNOWN', identity_issues=identity_issues, sourcing_allowed=False, purchase_authorized=False,
            source_slots=[n for n in (i+2,22,i+23) if n in replies])
        row['review_ready'] = bool(snapshot['status']=='COMPLETED_NO_REPLAY' and ranks and offer
            and offer.new_count is not None and any(p.landed_usd for p in offer.prices)
            and observed_catalog and observed_catalog.variation_parent is False
            and permission and permission.status=='NO_LISTING_RESTRICTIONS_OBSERVED' and not identity_issues)
        for rank in ranks: groups.setdefault((rank.kind,rank.category_id),[]).append((rank.rank,row))
        rows.append(row)
    ordered=[]
    for key,items in sorted(groups.items()):
        items.sort(key=lambda pair:(pair[0],pair[1]['new_offer_count'] if type(pair[1]['new_offer_count']) is int else float('inf'),pair[1]['asin']))
        positions={number:i+1 for i,number in enumerate(sorted({number for number,_ in items}))}
        for number,row in items: row['category_relative_ranks'].append(dict(kind=key[0],category_id=key[1],rank_within_pilot=positions[number]))
        ordered.append(dict(kind=key[0],category_id=key[1],review_priority=[row['asin'] for _,row in items if row['review_ready']]))
    return dict(mode='M80_SALES_REVIEW_NOT_PURCHASE_APPROVAL', status=snapshot['status'], as_of=now.isoformat(),
        synthetic=snapshot['binding'].get('synthetic',False), rows=rows, category_groups=ordered,
        requests_consumed=snapshot['requests_consumed'], uncertain_slots=snapshot['uncertain_slots'],
        limitations=['Ranks comparable only within exact marketplace/category ID/rank type and this selected pilot.',
            'No monthly-sales calibration; one snapshot cannot establish stability, total market sales or all-seller coverage.',
            'No listing restrictions observed is account/time/condition scoped, not FBA, sourcing or purchase approval.'],
        purchase_authorized=False, walmart_sourcing_authorized=False, checkpoint_sha256=snapshot['checkpoint_sha256'])
