"""Authorized local source adapters and bounded pagination; no HTTP capability."""
import csv
import hashlib
from itertools import islice
import json
from pathlib import Path
import re

from app.amazon_catalog import marketplace_row
from app.sp_catalog_targets import parse_target_item, stamp
from app.m65_intelligence import US, private_values
from app.m70_identity import FIELDS, observation
from app.observations import canonical, fingerprint
from app.provider_runtime import ProviderFailure

ADAPTERS={'m63_json','m63_csv','amazon_catalog_pages','amazon_catalog_items',
          'local_csv','local_json','retailer_csv','retailer_json'}
MAX_BYTES=64*1024*1024


def file_hash(path: Path) -> str:
    if (path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_file()
            or path.stat().st_size>MAX_BYTES or re.search(r'credential|authorization|account-context|token|\.env',path.name,re.I)):
        raise ValueError('Bounded nonsymlink catalog evidence required; private credentials forbidden')
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(65536),b''):digest.update(block)
    return digest.hexdigest()


def strict_json(path: Path):
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValueError('Duplicate JSON key')
            result[k]=v
        return result
    return json.loads(path.read_bytes(),object_pairs_hook=unique,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def source_manifest(path: Path) -> tuple[list[dict],str]:
    digest=file_hash(path);doc=strict_json(path)
    if not isinstance(doc,dict) or set(doc)!={'schema','sources'} or type(doc['schema']) is not int or doc['schema']!=1:
        raise ValueError('Explicit local source manifest schema required')
    if not isinstance(doc['sources'],list) or not 1<=len(doc['sources'])<=100:raise ValueError('One to 100 source exports required')
    entries=[];interpretations={}
    required={'path','sha256','adapter','permission_reference','marketplace'}
    for entry in doc['sources']:
        if (not isinstance(entry,dict) or not required<=set(entry) or set(entry)-required-{'observed_at'}
                or entry['adapter'] not in ADAPTERS or entry['marketplace']!=US or not re.fullmatch('[a-f0-9]{64}',entry['sha256'])
                or not re.fullmatch(r'(?:local|manual):[A-Za-z0-9._-]{1,100}',entry['permission_reference'])):
            raise ValueError('Source path/hash/adapter and nonsecret permission reference required')
        p=Path(entry['path']);p=p if p.is_absolute() else path.parent/p
        if file_hash(p)!=entry['sha256']:raise ValueError('Source file digest mismatch')
        role='retailer' if entry['adapter'].startswith('retailer_') else 'amazon'
        key=(entry['sha256'],role)
        if key in interpretations and interpretations[key]!=entry['adapter']:raise ValueError('Ambiguous source adapter assignment')
        interpretations[key]=entry['adapter']
        entries.append(dict(entry,path=p))
    if file_hash(path)!=digest:raise ValueError('Source manifest changed')
    return sorted(entries,key=lambda e:(e['sha256'],e['adapter'],str(e['path']))),digest


def decoded(value,default):
    if value is None or value=='':return default
    return json.loads(value) if isinstance(value,str) else value


def flags(row: dict) -> tuple[list,list]:
    inferred=decoded(row.get('inferred_fields',row.get('inferred_fields_json')),[])
    generated=decoded(row.get('generated_fields',row.get('generated_fields_json')),[])
    if not isinstance(inferred,list) or not isinstance(generated,list):raise ValueError('Field inference flags must be arrays')
    states=decoded(row.get('field_status',row.get('field_status_json')),{} )
    if not isinstance(states,dict):raise ValueError('Field status object required')
    for field,state in states.items():
        if 'INFERRED' in str(state).upper():inferred.append(field)
        if 'GENERATED' in str(state).upper():generated.append(field)
    return inferred,generated


def local_record(row: dict) -> dict:
    if not isinstance(row,dict):raise ValueError('Structured product record required')
    cat=row.get('catalog') or row
    if not isinstance(cat,dict):raise ValueError('Structured catalog identity required')
    if row.get('asin') and cat.get('asin') and row['asin']!=cat['asin']:raise ValueError('Conflicting ASIN placement')
    if row.get('amazon_url') and row['amazon_url']!='https://www.amazon.com/dp/'+str(row.get('asin')):
        raise ValueError('Explicit US ASIN URL required')
    summary=row.get('summary_fields') or {}
    variation=cat.get('variation')
    if 'variation_json' in row:
        v=decoded(row['variation_json'],{});variation=v.get('summary')
    if isinstance(variation,str) and variation.startswith('{'):variation=decoded(variation,{})
    size=cat.get('size') or row.get('size') or summary.get('size')
    if not size and isinstance(variation,dict):size=variation.get('size')
    pack=cat.get('package_quantity',cat.get('pack_quantity'))
    if 'pack_information_json' in row:pack=decoded(row['pack_information_json'],{}).get('package_quantity')
    ids=decoded(row.get('identifiers_json'),cat.get('identifiers',[]))
    if not isinstance(ids,list):raise ValueError('Structured identifier list required')
    values=[];upcs=[]
    for candidate in ids:
        if not isinstance(candidate,dict):raise ValueError('Structured identifier required')
        kind=candidate.get('kind') or candidate.get('identifier_type') or candidate.get('identifierType')
        value=candidate.get('value') or candidate.get('identifier')
        if kind in ('UPC','EAN','GTIN'):
            values.append(value)
            if kind=='UPC':upcs.append(value)
    for field in ('gtin','upc'):
        value=cat.get(field) or row.get(field)
        if value is not None and value!='':values.append(value)
        if field=='upc' and value:upcs.append(value)
    inferred,generated=flags(row)
    if cat is not row:
        nested_inferred,nested_generated=flags(cat)
        inferred=sorted(set(inferred+nested_inferred))
        generated=sorted(set(generated+nested_generated))
    issues=decoded(row.get('mapping_issues_json'),cat.get('mapping_issues',[]))
    blocks=[]
    if cat.get('item_classification')=='VARIATION_PARENT' or any('variation parent' in str(i).lower() for i in issues):blocks.append('VARIATION_PARENT')
    declared=decoded(row.get('identity_conflicts',row.get('identity_conflicts_json')),[])
    states=decoded(row.get('field_status',row.get('field_status_json')),{} )
    if declared or any(str(v).upper()=='CONFLICT' for v in states.values()):blocks.append('DECLARED_IDENTITY_CONFLICT')
    return dict(asin=row.get('asin',cat.get('asin')),marketplace=row.get('marketplace',row.get('marketplace_id')),
        brand=row.get('brand') or cat.get('brand') or summary.get('brand'),title=cat.get('title') or row.get('title'),
        product_type=row.get('product_type') or cat.get('product_type'),category=row.get('category') or cat.get('category'),
        gtin=values,upc_values=upcs,model=cat.get('model') or row.get('model'),size=size,variation=variation,
        pack_quantity=pack,condition=row.get('condition') or cat.get('condition'),
        inferred_fields=inferred,generated_fields=generated,is_generated=row.get('is_generated'),
        is_mock=row.get('is_mock') or cat.get('is_mock'),is_synthetic=row.get('is_synthetic') or cat.get('is_synthetic'),review_blocks=blocks)


def raw_record(item: dict,date: str,secrets: set[str]) -> dict:
    snapshot=parse_target_item(item,observed_at=stamp(date),provenance='local:saved-catalog-export',secrets=secrets,is_mock=False)
    mapped=local_record(snapshot)
    summary=marketplace_row(item,'summaries') or {}
    types=marketplace_row(item,'productTypes') or {}
    mapped['product_type']=types.get('productType')
    browse=summary.get('browseClassification') or {}
    mapped['category']=browse.get('displayName')
    mapped['inferred_fields'],mapped['generated_fields']=flags(item)
    for field in ('is_mock','is_synthetic','is_generated'):
        if field in item:mapped[field]=item[field]
    if 'marketplace' in item or 'marketplace_id' in item:mapped['marketplace']=item.get('marketplace',item.get('marketplace_id'))
    # Structured attributes are used only as explicit observed values. Unit
    # count, title text and package hierarchy never imply selling-pack quantity.
    attrs=item.get('attributes') or {}
    for field,attribute in (('model','model_number'),('size','size'),('pack_quantity','item_package_quantity')):
        values=[v.get('value') for v in attrs.get(attribute,[]) if isinstance(v,dict) and v.get('marketplace_id')==US]
        if values:mapped[field]=([mapped[field]] if mapped[field] is not None else [])+values
    return mapped


def local_pages(path: Path,adapter: str,page_size: int):
    if adapter.endswith('_csv'):
        with path.open(encoding='utf-8-sig',newline='') as stream:
            reader=csv.DictReader(stream);index=0
            if adapter=='m63_csv' and not {'asin','identifiers_json','pack_information_json','variation_json'}<=set(reader.fieldnames or []):
                raise ValueError('Original M63 CSV schema required')
            while chunk:=list(islice(reader,page_size)):
                yield index,chunk,None,False,set()
                index+=1
        return
    doc=strict_json(path)
    secrets=private_values(doc)
    if isinstance(doc,dict) and (doc.get('is_mock') is True or doc.get('is_synthetic') is True):raise ValueError('Real saved sources required')
    if adapter=='m63_json' and (not isinstance(doc,dict) or doc.get('mode') not in ('M63_CATALOG_DISCOVERY','M63_SAVED_CATALOG_OFFLINE')):
        raise ValueError('Original M63 saved Catalog report required')
    if adapter=='amazon_catalog_pages':
        if not isinstance(doc,dict) or not isinstance(doc.get('pages'),list):raise ValueError('Explicit saved pages required')
        groups={}
        for page in doc['pages']:
            if not isinstance(page,dict) or page.get('marketplace_id')!=US or page.get('http_status')!=200:
                raise ValueError('Successful scoped saved Catalog pages required')
            q=page.get('query_reference');idx=page.get('page_index')
            if not isinstance(q,str) or type(idx) is not int or idx<0:raise ValueError('Explicit page/query identity required')
            groups.setdefault(q,[]).append(page)
        count=0
        for query,pages in sorted(groups.items()):
            expected_token=None;tokens=set();items_seen=0
            for expected,page in enumerate(sorted(pages,key=lambda p:p['page_index'])):
                if page['page_index']!=expected or page.get('page_token')!=expected_token:raise ValueError('Broken local pagination chain')
                items=page.get('items')
                if not isinstance(items,list) or len(items)>20:raise ValueError('Catalog service page size maximum is 20')
                pagination=page.get('pagination') or {}
                if not isinstance(pagination,dict):raise ValueError('Malformed pagination')
                token=pagination.get('nextToken')
                if token is not None and (not isinstance(token,str) or not token or token in tokens):raise ValueError('Invalid/repeated page token')
                if token is not None:tokens.add(token)
                if expected<len(pages)-1 and token is None:raise ValueError('Unexpected page after terminal cursor')
                items_seen+=len(items)
                if expected>=1000 or items_seen>1000:raise ValueError('Catalog query paging window or bounded page count exceeded')
                yield count,items,page.get('observed_at'),bool(expected==len(pages)-1 and token),secrets
                expected_token=token;count+=1
        return
    if isinstance(doc,dict):
        if adapter=='m63_json':rows=doc.get('candidates',[])
        elif adapter=='amazon_catalog_items' and 'asin' in doc:rows=[doc]
        elif 'records' in doc or 'items' in doc:rows=doc.get('records',doc.get('items'))
        elif adapter in ('local_json','retailer_json') and ('asin' in doc or 'gtin' in doc or 'upc' in doc):rows=[doc]
        else:raise ValueError('Recognized product export shape required')
        if isinstance(rows,dict):rows=[rows[k] for k in sorted(rows)]
        date=doc.get('observed_at')
    else:rows=doc;date=None
    if not isinstance(rows,list):raise ValueError('Local product list required')
    for index in range(0,len(rows),page_size):yield index//page_size,rows[index:index+page_size],date,False,secrets


def ingest(manifest_path: Path,*,page_size: int=200,maximum_observations: int=100000,maximum_asins: int=10000) -> tuple[list[dict],dict]:
    if (type(page_size) is not int or not 1<=page_size<=1000 or type(maximum_observations) is not int or not 1<=maximum_observations<=100000
            or type(maximum_asins) is not int or not 1<=maximum_asins<=10000):raise ValueError('Explicit bounded local import sizes required')
    entries,manifest_sha=source_manifest(manifest_path)
    observations=[];coverage=[];seen_files=set();seen_asins=set();duplicate_sources=0;total=0
    for entry in entries:
        digest=entry['sha256'];adapter=entry['adapter'];path=entry['path']
        role='retailer' if adapter.startswith('retailer_') else 'amazon'
        file_key=(digest,role)
        if file_key in seen_files:duplicate_sources+=1;continue
        seen_files.add(file_key)
        count=accepted=pages=partial=0;rejections=[]
        for page,rows,date,incomplete,global_secrets in local_pages(path,adapter,page_size):
            pages+=1;partial+=int(incomplete)
            for index,row in enumerate(rows):
                total+=1;count+=1
                if total>maximum_observations:raise ValueError('Local observation budget exhausted; split legitimate exports explicitly')
                ref=f'sha256:{digest}:page:{page}:row:{index}'
                try:
                    secrets=private_values(row)|global_secrets
                    timestamp=(row.get('observed_at') if isinstance(row,dict) else None) or date or entry.get('observed_at')
                    raw=adapter in ('amazon_catalog_items','amazon_catalog_pages')
                    mapped=raw_record(row,timestamp,secrets) if raw else local_record(row)
                    if mapped.get('marketplace') is None:mapped['marketplace']=entry['marketplace']
                    obs=observation(mapped,role=role,reference=ref,source_hash=digest,source_class=adapter,
                                    observed_at=timestamp,secrets=secrets)
                    observations.append(obs);accepted+=1
                    if role=='amazon':seen_asins.add(obs['asin'])
                except (ValueError,TypeError,KeyError,AttributeError,ProviderFailure):
                    rejections.append(dict(source_reference=ref,reason='INVALID_OR_UNSUPPORTED_PRODUCT_RECORD'))
                if len(seen_asins)>maximum_asins:raise ValueError('Distinct ASIN memory bound exceeded')
        if file_hash(path)!=digest:raise ValueError('Source changed during ingestion')
        coverage.append(dict(source_sha256=digest,adapter=adapter,role=role,permission_reference=entry['permission_reference'],
            rows=count,accepted=accepted,rejected=count-accepted,local_pages=pages,
            partial_query_windows=partial,rejections=rejections))
    if file_hash(manifest_path)!=manifest_sha:raise ValueError('Source manifest drift')
    return observations,dict(schema=1,source_manifest_sha256=manifest_sha,sources=coverage,
        total_rows=total,accepted_observations=len(observations),duplicate_source_files=duplicate_sources,
        local_page_size=page_size,maximum_asins=maximum_asins,maximum_observations=maximum_observations,
        retailer_network_requests=0,amazon_requests=0)
