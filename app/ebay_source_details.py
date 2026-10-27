"""Offline source-detail planning and schema-profile import; no HTTP or credentials."""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from app.amazon_candidates import source_plan
from app.config import Config
from app.discovery import screen
from app.models import Match
from app.normalization import gtin, integer, money, timestamp, identity
from app.observations import ObservationStore, canonical, normalized, fingerprint
from app.provider_contracts import Evidence
from app.reporting import write_report

FIELDS = ('brand', 'manufacturer', 'model', 'mpn', 'upc', 'ean', 'gtin', 'item_specifics',
          'package_contents', 'package_quantity', 'component_count', 'variation', 'condition',
          'shipping_cost', 'shipping_currency', 'shipping_conditions', 'destination_zip',
          'seller', 'source_observed_at')
LABEL = 'OFFLINE EBAY SOURCE DETAILS — no verified Amazon match or purchase approval'


def read_json(path: Path):
    if path.stat().st_size > 4*1024*1024:
        raise ValueError('Evidence exceeds four MiB')
    return json.loads(path.read_text(), parse_float=Decimal,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def at_path(document: dict, path):
    if path is None:
        return None
    if not isinstance(path, list) or not path or any(not isinstance(x, str) for x in path):
        raise ValueError('Profile paths must be explicit string arrays')
    value = document
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value if value not in ('', [], {}) else None


def mapping_profile(path: Path | None):
    if path is None:
        return None
    profile = read_json(path)
    if (profile.get('schema_verified') is not True or not profile.get('evidence_reference')
            or not isinstance(profile.get('paths'), dict) or set(profile['paths']) != set(FIELDS)):
        raise ValueError('Verified complete mapping profile with nonsecret schema reference required')
    if profile['paths'].get('package_quantity') is not None and profile.get('package_quantity_means_retail_packages') is not True:
        raise ValueError('Retail-package quantity semantics must be verified separately from piece count')
    return profile


def normalize_detail(content: dict, profile: dict) -> dict:
    """Map explicit reviewed paths only; synthetic tests do not verify vendor schema."""
    if profile.get('schema_verified') is not True:
        raise ValueError('Unverified provider schema')
    values = {key: at_path(content, profile['paths'].get(key)) for key in FIELDS}
    invalid, normalized_ids = [], []
    for key, value in values.items():
        if value is None:
            continue
        try:
            if key in ('package_quantity', 'component_count'):
                value = integer(value)
                if not value:
                    raise ValueError('Positive count required')
            elif key == 'shipping_cost':
                value = money(value)
            elif key == 'source_observed_at':
                value = timestamp(value)
            elif key in ('item_specifics', 'variation'):
                if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                      for k,v in value.items()):
                    raise ValueError('String-valued specifics required')
            elif key == 'package_contents':
                if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v.strip() for v in value):
                    raise ValueError('Explicit component array required')
            elif not isinstance(value, str):
                raise ValueError('Text required')
            if key in ('upc', 'ean', 'gtin'):
                if key == 'upc' and len(value) != 12:
                    raise ValueError('UPC length')
                if key == 'ean' and len(value) not in (8,13):
                    raise ValueError('EAN length')
                valid = gtin(value)
                if valid:
                    normalized_ids.append(valid)
            values[key] = value
        except (ValueError, TypeError):
            invalid.append(key)
            # Retain the supplied value separately, but never normalize invalid identity.
            values[key] = None
    return dict(fields=normalized(values), invalid_fields=invalid,
                supplied_identifiers={k: at_path(content, profile['paths'].get(k)) for k in ('upc','ean','gtin')},
                normalized_gtins=sorted(set(normalized_ids)),
                identifier_contradiction=len(set(normalized_ids))>1,
                missing_fields=[k for k,v in values.items() if v is None],
                schema_reference=profile['evidence_reference'])


def saved_records(paths: tuple[Path, ...], profile: dict | None, wanted: set[str]) -> tuple[dict, list]:
    """Existing successful detail evidence wins over requesting another job."""
    records, inventory = {}, []
    for path in paths:
        document = read_json(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        used = 0
        if document.get('status') == 'finished':
            for result in document.get('results', []):
                query = result.get('query', {})
                item_id = str(query.get('value', ''))
                if (query.get('source'),query.get('country'),query.get('topic'),query.get('key')) != ('ebay','us','product','id'):
                    continue
                if item_id not in wanted or result.get('success') is not True or profile is None:
                    continue
                content = result.get('content')
                if not isinstance(content, dict):
                    continue
                url = content.get('url')
                if url:
                    parsed = urlsplit(url)
                    match = re.search(r'/itm/(?:[^/]+/)?([0-9]+)(?:/|$)',parsed.path)
                    if parsed.hostname not in ('ebay.com','www.ebay.com') or not match or match[1]!=item_id:
                        raise ValueError('Returned source identity mismatch')
                record = normalize_detail(content, profile)
                if not any(v is not None for v in record['fields'].values()):
                    continue
                record.update(export=str(path.resolve()), export_sha256=digest, job_id=document.get('job_id'),
                              ebay_item_id=item_id, query={k:query.get(k) for k in ('source','country','topic','key','value')})
                # Keep conflicts from multiple supplied exports explicit instead of last-write-wins.
                if item_id in records and records[item_id]['fields'] != record['fields']:
                    raise ValueError('Conflicting saved detail exports require explicit selection')
                records[item_id] = record
                used += 1
        inventory.append(dict(path=str(path.resolve()), sha256=digest, reusable_detail_rows=used))
    return records, inventory


def prepare_plan(source: Path, saved: tuple[Path, ...] = (), profile_path: Path | None = None):
    bound, products = source_plan(source)
    ids = [p.source_context.get('retailer_item_id') for p in products]
    if any(not isinstance(i,str) or not re.fullmatch(r'[0-9]{12}',i) for i in ids):
        raise ValueError('Known eBay listing IDs required')
    profile = mapping_profile(profile_path)
    records, inventory = saved_records(saved,profile,set(ids))
    pending = list(dict.fromkeys(i for i in ids if i not in records))
    proposal = dict(source='ebay',country='us',topic='product',key='id',values='\n'.join(pending)) if pending else None
    plan = dict(schema=1, source=bound['source'], source_sha256=bound['source_sha256'],
        source_rows=[dict(ordinal=i,ebay_item_id=item_id,source_fingerprint=fingerprint(p),
                         saved_detail_available=item_id in records) for i,(item_id,p) in enumerate(zip(ids,products),1)],
        saved_evidence=inventory, profile_sha256=(hashlib.sha256(profile_path.read_bytes()).hexdigest() if profile_path else None),
        proposed_job=proposal, pending_listing_ids=pending,
        budget=dict(jobs=1 if pending else 0,listing_values=len(pending),
                    general_tariff_default_credits=len(pending),
                    provisional_credit_reserve=2*len(pending),confirmed_account_credit_ceiling=None,
                    proposed_http_attempts=7 if pending else 0,submit=1 if pending else 0,
                    polls=5 if pending else 0,download=1 if pending else 0,retries=0,
                    executable_http_attempts=0,paid_credits_authorized=0),
        blocked_on=['Trial entitlement for ebay/us/product/id unverified',
                    'Source-specific tariff and free-only billing controls unverified',
                    'ID semantics (listing ID vs eBay catalog product ID) require verified sample',
                    'Complete vendor response-field mapping and shipping scope unverified'],
        execution_enabled=False, live_requests=0)
    return plan,products,records


def compare_field(source_value, target_value) -> str:
    if source_value is None or source_value == '' or target_value is None or target_value == '':
        return 'missing_evidence'
    if isinstance(source_value,str) and isinstance(target_value,str):
        return 'consistent' if identity(source_value)==identity(target_value) else 'contradiction'
    return 'consistent' if canonical(source_value)==canonical(target_value) else 'contradiction'


def import_saved(source: Path, saved: tuple[Path,...], profile_path: Path, output: Path) -> dict:
    plan,products,records=prepare_plan(source,saved,profile_path)
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    now=datetime.now(timezone.utc)
    store=ObservationStore(output/'source-details.sqlite3')
    run_id=store.start_run(now,plan,label=LABEL)
    config=Config(input=source,output=output/'SOURCE-DETAILS.xlsx',database=store.path)
    rows, audit, enrichments=[],[],[]
    for ordinal,product in enumerate(products,1):
        record=records.get(product.source_context['retailer_item_id'])
        enriched=product
        comparisons={}
        if record:
            fields=record['fields']
            values=dict(manufacturer=fields['manufacturer'],model=fields['model'],package_quantity=fields['package_quantity'],
                        gtin=record['normalized_gtins'][0] if len(record['normalized_gtins'])==1 else None)
            # Only compare like fields. Brand is never manufacturer, MPN is never model,
            # component count is never retail package quantity, and title text is never evidence.
            comparisons={key:compare_field(getattr(product,key) or None,value) for key,value in values.items()}
            updates={key:value for key,value in values.items() if value is not None and not getattr(product,key)}
            context=dict(product.source_context)
            context['source_detail_evidence']=canonical(record)
            if fields['package_contents'] is not None and not context.get('source_package_contents'):
                context['source_package_contents']=canonical(sorted(fields['package_contents']))
            # Retain new observation evidence separately; never relabel search observation timestamps.
            enriched=replace(product,**updates,source_context=context,
                issues=tuple(dict.fromkeys((*product.issues,'Source detail enrichment requires identity/package review'))))
        audit_row=dict(ordinal=ordinal,ebay_item_id=product.source_context['retailer_item_id'],
                       status='saved_detail_imported' if record else 'detail_missing',
                       detail=record,comparisons=comparisons,source=normalized(product),enriched_source=normalized(enriched))
        match=Match(None,False,Decimal('0'),('Source-only enrichment; Amazon identity remains unverified',))
        row=screen(enriched,match,config,now)
        row.update(input_ordinal=ordinal,source_detail_status=audit_row['status'])
        evidence=Evidence(audit_row,now,LABEL,False)
        store.record_item(run_id,ordinal,enriched,match,row,[('', 'ebay_source_detail',evidence,now)],now,provider='saved-ebay-details')
        rows.append(row);audit.append(audit_row)
        enrichments.append(dict(kind='ebay_source_detail',asin='',value=canonical(audit_row),provenance=LABEL))
    write_report(rows,config.output,discovery=True,job=dict(label=LABEL,live_requests=0),enrichment_rows=enrichments)
    store.history.finish(run_id,'succeeded',10,0,config.output)
    result=dict(plan=plan,run_id=run_id,rows=audit,live_requests=0,purchase_approved=False)
    (output/'source-details.json').write_text(canonical(result)+'\n')
    return result


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('plan','import-saved'))
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--saved-export',action='append',default=[],type=Path)
    parser.add_argument('--profile',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.action=='import-saved' and args.profile is None:
        parser.error('import-saved requires a verified schema profile')
    try:
        if args.action=='plan':
            result,_,_=prepare_plan(args.source,tuple(args.saved_export),args.profile)
            with args.output.open('x') as stream:
                stream.write(json.dumps(result,indent=2)+'\n')
        else:
            result=import_saved(args.source,tuple(args.saved_export),args.profile,args.output)
        print(json.dumps(dict(status='prepared_offline',live_requests=0,execution_enabled=False)))
        return 0
    except (OSError,ValueError,TypeError,KeyError):
        print('Source-detail preparation stopped; preserve inputs and inspect schema/scope locally.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
