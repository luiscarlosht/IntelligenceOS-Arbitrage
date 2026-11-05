"""M88 normalized evidence and strict identity gate, using existing parsers."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from app.amazon_catalog import parse_catalog, marketplace_row
from app.amazon_candidates import parse_search
from app.m66_opportunity import exact_match
from app.normalization import identity
from app.m80_execution import scrub

US = 'ATVPDKIKX0DER'
DATA = 'summaries,identifiers,relationships,attributes,salesRanks'


def attribute(document: dict, name: str) -> str:
    rows = document.get('attributes', {}).get(name, [])
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError('Invalid scoped catalog attribute')
    values = {r['value'] for r in rows if isinstance(r,dict) and r.get('marketplace_id') == US
              and isinstance(r.get('value'),str) and r['value'].strip()}
    return next(iter(values)) if len(values) == 1 else ''


def product(document: dict, asin: str, secrets: tuple[str, ...]) -> dict:
    catalog = parse_catalog(document, expected_asin=asin, is_mock=False, secrets=secrets)
    listing = catalog.value
    summary = marketplace_row(document, 'summaries') or {}
    result = dict(asin=asin, title=listing.title, gtin=listing.gtin, brand=summary.get('brand',''),
        model=summary.get('modelNumber') or attribute(document,'model_number'),
        size=summary.get('size') or attribute(document,'size'), pack_quantity=listing.package_quantity,
        variation=listing.variation, url='https://www.amazon.com/dp/'+asin,
        source='Amazon SP-API Catalog Items 2022-04-01', source_reference='M88 catalog '+asin,
        observed_at=catalog.observed_at.isoformat(), confidence='MEDIUM', verified=True,
        mapping_issues=list(listing.mapping_issues), identifiers=[asdict(i) for i in listing.identifiers])
    return scrub(result, set(secrets))


def match(source: dict, amazon: dict, now: datetime) -> dict:
    retailer = {k: None if v == 'UNKNOWN' else v for k,v in source.items()}
    target = {k: None if v == 'UNKNOWN' else v for k,v in amazon.items()}
    result = exact_match(dict(asin=target['asin'], retailer_product=retailer, amazon_product=target), as_of=now)
    missing = list(result['missing'])
    for side,value in [('source',source),('amazon',amazon)]:
        if value.get('verified') is not True or value.get('confidence') not in ('HIGH','MEDIUM'):
            missing.append(side+'.verified_identity')
    for key in ('brand','model','size','variation'):
        if not isinstance(target.get(key),str) or not isinstance(retailer.get(key),str):
            missing.append(key+'.explicit_identity')
        elif identity(target[key]) != identity(retailer[key]):
            missing.append(key+'.mismatch')
    if amazon.get('mapping_issues'):
        missing.append('catalog.mapping_issues')
    return dict(exact=result['exact'] and not missing, missing=sorted(set(missing)),
                mismatches=result['mismatches'])


def search_result(document: dict, source: dict, secrets: tuple[str,...]) -> dict:
    search = parse_search(document, secrets=secrets)
    by_asin = {item['asin']:item for item in document['items']}
    candidates=[]
    for item in search['candidates']:
        observed=product(by_asin[item['asin']], item['asin'], secrets)
        candidates.append(dict(product=observed, identity=match(source,observed,datetime.now(timezone.utc))))
    exact=[c['product']['asin'] for c in candidates if c['identity']['exact']]
    return dict(candidates=candidates, total_results=search['total_results'], more_results=search['more_results'],
                selected_asin=exact[0] if len(exact)==1 and not search['more_results'] else None,
                status='EXACT_CANDIDATE' if len(exact)==1 and not search['more_results'] else 'UNRESOLVED')


def observation(value, asin: str, source: str, at: str, **extra) -> dict:
    return dict(value=value, asin=asin, condition='New', marketplace=US, source=source,
                source_reference='M88 '+asin+' '+source, observed_at=at, confidence='MEDIUM',
                verified=True, **extra)


def enrich(batch: dict, receipts: list[dict]) -> dict:
    result=deepcopy(batch)
    rows={r['source_candidate_id']:r for r in result['observations']}
    for receipt in receipts:
        candidate=receipt['candidate_id']
        if candidate not in rows: continue
        row=rows[candidate]; value=receipt['evidence']; phase=receipt['phase']
        retained = value
        if phase == 'search':
            retained = dict(status=value['status'], more_results=value['more_results'],
                candidates=[dict(asin=c['product']['asin'], title=c['product']['title'])
                            for c in value['candidates']], receipt_number=receipt['number'])
        row.setdefault('m88_evidence',{})[phase]=retained
        # Only independently rechecked detail evidence promotes a source pairing.
        if phase=='detail' and value['identity']['exact']:
            row['amazon']=dict(asin=value['product']['asin'],product=value['product'],
                               eligibility={'status':'UNKNOWN'},market={},financials={})
        if phase=='offers' and 'amazon' in row:
            amazon=row['amazon']; asin=amazon['asin']; at=receipt['observed_at']
            count=value['value']['offer_coverage']['requested_condition_offer_count'] if value['value'].get('offer_coverage') else None
            if count is not None:
                amazon['market']['competing_offers']=observation(count,asin,'New offer count',at,basis='new_offer_count')
            # A competing offer is only an assumed research sale-price scenario.
            price=value.get('fee_price')
            if price is not None:
                for mode in ('FBA','FBM'):
                    amazon['financials'][mode]={'base':dict(selling_price=observation(price,asin,
                        'Observed competing New listing price; achievable sale price unverified',at,
                        currency='USD',assumed=True))}
        if phase.startswith('fees_') and 'amazon' in row:
            mode=phase.split('_')[1]; amazon=row['amazon']; asin=amazon['asin']
            inputs=amazon['financials'].setdefault(mode,{}).setdefault('base',{})
            quote=value['quote']['value']
            for key in ('referral_fee','fulfillment_fee'):
                if quote.get(key) is not None:
                    inputs[key]=observation(quote[key],asin,'Amazon fee estimate',receipt['observed_at'],
                        currency='USD',mode=mode,price_basis=deepcopy(inputs.get('selling_price',{})))
    return result
