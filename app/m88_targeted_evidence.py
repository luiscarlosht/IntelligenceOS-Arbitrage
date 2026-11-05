"""Evidence ranking and allowlisted Catalog details for the M88 continuation."""
from dataclasses import asdict
from datetime import datetime,timezone
import math
import re
from app.amazon_catalog import parse_catalog
from app.m88_evidence import product,match,US
from app.m80_execution import scrub
from app.m88_reconcile import equality,known

DATA='summaries,identifiers,relationships,attributes,dimensions'
ATTRIBUTES=('brand','manufacturer','model_number','part_number','externally_assigned_product_identifier',
    'item_form','color','size','style','item_package_quantity','number_of_items','unit_count',
    'included_components','is_bundle','material','product_description','bullet_point',
    'item_dimensions','item_package_dimensions','item_weight','item_package_weight')
STRUCTURE={'value','unit','marketplace_id','language_tag','type','height','length','width','weight',
           'item','package','quantity','count','size','size_system','size_class','color'}


def ranking(reconciliation: dict) -> list[dict]:
    result=[]
    for row in reconciliation['records']:
        if row['classification']!='NEEDS_REVIEW':continue
        comparison=row['comparisons']; p=row['amazon_product']
        score=100*comparison['upc']['overlap']+20*(comparison['brand']['status']=='MATCH')
        score+=10*(comparison['model']['status']=='MATCH')
        score+=5*(len(comparison['upc']['amazon_identifiers']['distinct_canonical_gtins'])==1)
        if row['walmart_item_id']=='13952053139':
            # This is a recorded size/style clue, not proof that Count means cells.
            score+=15 if re.search(r'\b8\s+Count\s*\(Pack of 1\)',p.get('size',''),re.I) else 0
            if 'Pack of 2' in p.get('size',''):score-=15
        score-=3*len(row['source_exceptions'])
        result.append(dict(walmart_item_id=row['walmart_item_id'],asin=row['asin'],score=score,
            evidence_basis=dict(barcode_overlap=comparison['upc']['overlap'],brand=comparison['brand']['status'],
                                model=comparison['model']['status'],amazon_size=p.get('size')),
            minimum_amazon_fields=['GTIN applicability to sellable package','manufacturer model and part_number; no inferred alias',
                'brand, item_form/formulation, selected color/size/style','number_of_items, item_package_quantity, unit_count and package relationships'],
            source_fields_still_unresolved=row['source_exceptions'],prior_gaps=row['remaining_gaps'],
            verified_exact_match=False))
    result.sort(key=lambda r:(-r['score'],r['walmart_item_id'],r['asin']))
    for i,row in enumerate(result,1):row['rank']=i
    return result


def targets(ranked: list[dict]) -> list[dict]:
    selected=[]
    for item in ('17011265','13952053139','721324153'):
        candidates=[r for r in ranked if r['walmart_item_id']==item]
        if not candidates:raise ValueError('Prioritized unresolved source missing')
        selected.append(candidates[0])
    return sorted(selected,key=lambda r:r['rank'])


def value(item,depth: int=0):
    """Bounded typed attributes, retaining units/scope; no arbitrary response keys."""
    if depth>7:raise ValueError('Catalog attribute nesting exceeds bound')
    if item is None or type(item) in (bool,int):return item
    if isinstance(item,float):
        if not math.isfinite(item):raise ValueError('Nonfinite catalog value')
        return str(item)
    if isinstance(item,str):
        # Abort rather than silently truncate identity evidence.
        if len(item)>16000:raise ValueError('Catalog evidence string exceeds bound')
        return ''.join(c for c in item if c.isprintable() or c in '\n\t')
    if isinstance(item,list):
        if len(item)>100:raise ValueError('Catalog evidence list exceeds bound')
        return [value(v,depth+1) for v in item]
    if isinstance(item,dict):return {k:value(v,depth+1) for k,v in item.items() if k in STRUCTURE}
    raise ValueError('Invalid catalog evidence type')


def scoped_values(attributes: dict,key: str) -> list[str]:
    rows=attributes.get(key,[])
    return sorted({row['value'] for row in rows if isinstance(row,dict) and row.get('marketplace_id')==US
                   and isinstance(row.get('value'),str) and row['value'].strip()})


def catalog_detail(document: dict,asin: str,source: dict,secrets: tuple[str,...]) -> dict:
    base=product(document,asin,secrets)
    parsed=parse_catalog(document,expected_asin=asin,is_mock=False,secrets=secrets)
    attrs=document.get('attributes',{})
    if not isinstance(attrs,dict):raise ValueError('Catalog attributes object required')
    retained={key:value(attrs[key]) for key in ATTRIBUTES if key in attrs}
    if any(not isinstance(v,list) for v in retained.values()):raise ValueError('Catalog attribute arrays required')
    mpns=scoped_values(retained,'part_number')
    base.update(manufacturer=parsed.value.manufacturer,
        manufacturer_part_number=mpns[0] if len(mpns)==1 else 'UNKNOWN',manufacturer_part_number_alternatives=mpns,
        retained_attributes=retained,relationships=[asdict(r) for r in parsed.value.relationships])
    dimensions=document.get('dimensions',[])
    if not isinstance(dimensions,list) or len(dimensions)>10:raise ValueError('Invalid dimensions')
    base['dimensions']=[value(row) for row in dimensions if isinstance(row,dict) and row.get('marketplaceId')==US]
    # marketplaceId is the dataset scope; restore it explicitly, never infer it.
    for row in base['dimensions']:row['marketplaceId']=US
    gate=match(source,base,datetime.now(timezone.utc))
    gate['missing']=sorted(set(gate['missing']+(['source.conflicting_observations'] if source.get('conflicting_observations') else [])))
    gate['exact']=gate['exact'] and not source.get('conflicting_observations')
    mpn_status=equality(source.get('mpn'),base['manufacturer_part_number'])
    if mpn_status=='DIFFERENT_LABELS':
        gate['missing']=sorted(set(gate['missing']+['manufacturer_part_number.mismatch']))
        gate['exact']=False
    compared=dict(
        gtin=dict(walmart=source.get('gtin'),amazon=base['gtin'],amazon_identifiers=base['identifiers']),
        manufacturer_model=dict(walmart=source.get('model'),amazon=base['model'],status=equality(source.get('model'),base['model'])),
        manufacturer_part_number=dict(walmart=source.get('mpn','UNKNOWN'),amazon=base['manufacturer_part_number'],status=mpn_status),
        brand=dict(walmart=source.get('brand'),amazon=base['brand'],status=equality(source.get('brand'),base['brand'])),
        formulation=dict(walmart_description=source.get('pack_description'),amazon_item_form=retained.get('item_form',[]),status='UNRESOLVED_UNLESS_INDEPENDENTLY_SCOPED'),
        size=dict(walmart_structured_size=source.get('size'),amazon_size=base['size'],amazon_unit_count=retained.get('unit_count',[]),status='NO_UNIT_OR_PACKAGE_EQUIVALENCE_INFERRED'),
        quantity_packaging=dict(walmart_count=source.get('pack_quantity'),walmart_basis=source.get('pack_quantity_basis','UNKNOWN'),
            amazon_package_quantity=base['pack_quantity'],amazon_number_of_items=retained.get('number_of_items',[]),
            amazon_item_package_quantity=retained.get('item_package_quantity',[]),relationships=base['relationships'],equivalence='UNKNOWN'),
        independent_human_signoff=source.get('independent_human_signoff',False))
    return scrub(dict(product=base,identity=gate,comparisons=compared,retention='Allowlisted normalized attributes; no raw payload or source-field upgrades'),set(secrets))
