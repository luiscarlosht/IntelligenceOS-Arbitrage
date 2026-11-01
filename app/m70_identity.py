"""Observed catalog identity, conservative enrichment and exact local matching."""
from collections import defaultdict
from datetime import datetime, timezone
import re

from app.m65_intelligence import ASIN, US, observed, safe_text
from app.normalization import gtin, identity
from app.observations import canonical, fingerprint

FIELDS=('brand','title','product_type','category','gtin','model','size','variation','pack_quantity','condition')
CORE=('brand','title','gtin','model','size','variation','pack_quantity')
MATCH=('brand','gtin','model','size','variation','pack_quantity','condition')


def field_value(field: str,value):
    if value is None or value=='':return None
    if field=='pack_quantity':
        if type(value) is int and value>0:return value
        if isinstance(value,str) and re.fullmatch('[1-9][0-9]*',value.strip()):return int(value)
        raise ValueError('Explicit positive pack count required')
    if field=='variation' and isinstance(value,dict):
        if not value:return None
        if any(not isinstance(k,str) or not isinstance(v,str) for k,v in value.items()):raise ValueError('Observed variation dimensions required')
        value=canonical(value)
    if not isinstance(value,str) or len(value)>512:raise ValueError('Bounded observed text required')
    if '[REDACTED]' in value:return None
    value=value.strip()
    if value.upper() in ('','UNKNOWN','UNVERIFIED','N/A'):return None
    if field=='gtin':return gtin(value)
    if field=='condition':
        if value.casefold() in ('new','new_new'):return 'new_new'
        if value.casefold() in ('used','used_like_new','used_very_good','used_good','used_acceptable','refurbished_refurbished','collectible_like_new'):
            return value.casefold()
        raise ValueError('Unsupported condition evidence')
    if any(not c.isprintable() for c in value):raise ValueError('Printable observed text required')
    return value


def key(field: str,value):
    return value if field in ('gtin','pack_quantity') else identity(value)


def observation(mapped: dict, *, role: str, reference: str, source_hash: str, source_class: str,
                observed_at: str, secrets=frozenset()) -> dict:
    asin=mapped.get('asin')
    if (role not in ('amazon','retailer') or (role=='amazon' and not isinstance(asin,str))
            or (asin is not None and (not isinstance(asin,str) or not ASIN.fullmatch(asin)))):
        raise ValueError('Explicit valid ASIN required for Amazon observations')
    date=observed(observed_at)
    if not date or datetime.fromisoformat(date)>datetime.now(timezone.utc):raise ValueError('Original aware observation timestamp required')
    if mapped.get('marketplace',US)!=US:raise ValueError('US source scope required')
    if mapped.get('is_mock') is True or mapped.get('is_synthetic') is True:raise ValueError('Synthetic records cannot be imported as real sources')
    inferred=mapped.get('inferred_fields',[]);generated=mapped.get('generated_fields',[])
    if not isinstance(inferred,list) or not isinstance(generated,list) or set(inferred+generated)-set(FIELDS)-{'asin','upc'}:
        raise ValueError('Explicit inference flags required')
    if 'asin' in inferred+generated or mapped.get('is_generated') is True:raise ValueError('Generated/inferred ASIN forbidden')
    def sanitized(value):
        if isinstance(value,str):
            for secret in secrets:
                if secret:value=value.replace(secret,'[REDACTED]')
        elif isinstance(value,dict):value={k:sanitized(v) for k,v in value.items()}
        return value
    fields={};issues={};evidence={}
    for field in FIELDS:
        candidates=mapped.get(field)
        if not isinstance(candidates,list):candidates=[candidates]
        values=[];states=[]
        if field in inferred or (field=='gtin' and 'upc' in inferred):states=['INFERRED_UNVERIFIED']
        elif field in generated or (field=='gtin' and 'upc' in generated):states=['GENERATED_UNVERIFIED']
        else:
            for candidate in candidates:
                candidate=sanitized(candidate)
                try:value=field_value(field,candidate)
                except (ValueError,TypeError,AttributeError):states.append('INVALID');continue
                if value is not None:values.append(value)
        unique={canonical(key(field,v)):v for v in sorted(values,key=canonical,reverse=True)}
        fields[field]=[unique[k] for k in sorted(unique)]
        status='CONFLICT' if len(unique)>1 else 'SOURCE_OBSERVED' if unique else states[0] if states else 'MISSING'
        evidence[field]=dict(source_reference=reference,observed_at=date,status=status)
        if states:issues[field]=sorted(set(states))
    upcs=[]
    for value in mapped.get('upc_values',[]):
        if isinstance(value,str) and re.fullmatch('[0-9]{12}',value):
            try:
                if gtin(value) in fields['gtin'] and 'gtin' not in inferred+generated and 'upc' not in inferred+generated:upcs.append(value)
            except ValueError:pass
    return dict(asin=asin,role=role,marketplace=US,fields=fields,field_evidence=evidence,
        issues=issues,upc_values=sorted(set(upcs)),observed_at=date,source_reference=reference,
        source_sha256=source_hash,source_class=source_class,review_blocks=sorted(set(mapped.get('review_blocks',[]))))


def merge(observations: list[dict]) -> dict:
    if not observations:raise ValueError('Observed records required')
    observations=sorted(observations,key=lambda r:r['source_reference'])
    asins={r['asin'] for r in observations};roles={r['role'] for r in observations}
    if len(asins)!=1 or len(roles)!=1:raise ValueError('One exact ASIN and role per identity')
    result={};states={};provenance={};conflicts=[];alternatives={}
    for field in FIELDS:
        values={}
        provenance[field]=[]
        for obs in observations:
            for value in obs['fields'][field]:values.setdefault(canonical(key(field,value)),[]).append(value)
            provenance[field].append(obs['field_evidence'][field])
        alternatives[field]=[min(values[k],key=canonical) for k in sorted(values)]
        if len(values)>1:
            result[field]=None;states[field]='CONFLICT';conflicts.append(field)
        elif values:
            result[field]=alternatives[field][0];states[field]='SOURCE_OBSERVED'
        else:
            result[field]=None
            unsupported={e['status'] for e in provenance[field]}-{'MISSING'}
            states[field]=sorted(unsupported)[0] if unsupported else 'MISSING'
    missing=[f for f in FIELDS if result[f] is None]
    blocks=sorted({b for o in observations for b in o['review_blocks']})
    complete=not missing and not conflicts and not blocks
    return dict(asin=next(iter(asins)),role=next(iter(roles)),marketplace=US,**result,
        upc_values=sorted({u for o in observations for u in o['upc_values']}),field_status=states,
        field_provenance=provenance,observed_alternatives=alternatives,missing_fields=missing,
        identity_conflicts=conflicts,review_blocks=blocks,identity_complete=complete,
        catalog_identity_complete=all(result[f] is not None for f in FIELDS if f!='condition') and not conflicts and not blocks,
        m69_core_complete=all(result[f] is not None for f in CORE) and not conflicts and not blocks,
        identity_verified=False,identity_confidence_percent=(len(FIELDS)-len(missing))*10,
        confidence_interpretation='Observed field coverage, not probability, verification or selling permission',
        observed_at=min(o['observed_at'] for o in observations),last_observed_at=max(o['observed_at'] for o in observations),
        source_references=[o['source_reference'] for o in observations],
        source_sha256=sorted({o['source_sha256'] for o in observations}),
        source_classes=sorted({o['source_class'] for o in observations}),
        unsupported_observations=sorted({field for o in observations for field in o['issues']}),
        eligibility='UNKNOWN',fba_state='FBA_UNKNOWN',purchase_authorized=False)


def match_key(product: dict):
    if product['identity_conflicts'] or product['review_blocks'] or any(product.get(f) is None for f in MATCH):return None
    return tuple(key(f,product[f]) for f in MATCH)


def exact_match(amazon: dict,retailer: dict) -> dict:
    missing=[f for f in MATCH if amazon.get(f) is None or retailer.get(f) is None]
    mismatches=[f for f in MATCH if f not in missing and key(f,amazon[f])!=key(f,retailer[f])]
    if retailer.get('asin') and retailer['asin']!=amazon.get('asin'):mismatches.append('asin')
    unknown=bool(amazon['identity_conflicts'] or retailer['identity_conflicts'] or amazon['review_blocks'] or retailer['review_blocks']
                 or set(amazon['source_sha256'])&set(retailer['source_sha256']))
    status='MISMATCH' if mismatches else 'UNKNOWN' if missing or unknown else 'EXACT_IDENTITY_OBSERVED'
    return dict(status=status,missing_fields=missing,mismatches=mismatches,
                eligibility='UNKNOWN',selling_permission_confirmed=False,purchase_authorized=False)
