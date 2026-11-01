"""M63 bounded Catalog-only discovery and offline eligibility proposal."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import socket
import ssl

from app import amazon_pilot as pilot
from app.amazon_catalog import MARKETPLACE, clean_text, marketplace_row
from app.amazon_diagnostics import failure_metadata
from app.amazon_pacing import OperationPacer
from app.m63_history import ASIN, EXCLUSIONS, audit, sha256
from app.observations import canonical, fingerprint
from app.sp_catalog_targets import audit_saved, parse_target_item

AUTHORIZATION = 'M63-CATALOG-2026-11-01'
PATH = '/catalog/2022-04-01/items'
DATA = 'summaries,identifiers,relationships,attributes,dimensions,productTypes'
# Three independent brands per area; first pages interleaved before second pages.
QUERIES = (
    ('kitchen', 'OXO', 'measuring cups', ('measuring',)),
    ('household', 'Whitmor', 'drawer organizer', ('organizer', 'organizers')),
    ('office', 'Post-it', 'sticky notes', ('notes',)),
    ('home_improvement', 'Command', 'picture hanging strips', ('hanging', 'strips')),
    ('kitchen', 'KitchenAid', 'measuring spoons', ('measuring',)),
    ('household', 'iDesign', 'drawer organizer', ('organizer', 'organizers')),
    ('office', 'Avery', 'index tabs', ('tabs',)),
    ('home_improvement', 'Duck', 'shelf liner', ('liner', 'liners')),
    ('kitchen', 'Joseph Joseph', 'kitchen utensils', ('spoon', 'spatula', 'utensil', 'utensils', 'turner', 'tongs')),
    ('household', 'Sterilite', 'small storage box', ('box', 'boxes', 'storage')),
    ('office', 'BIC', 'ballpoint pens', ('pen', 'pens')),
    ('home_improvement', 'STANLEY', 'tape measure', ('tape', 'measure')),
)
HAZARDS = re.compile(r'\b(aerosol|flammable|battery|batteries|bleach|pesticide|insecticide|food supplement|knife|knives|blade|blades|liquid cleaner|disinfectant|solvent|propane|butane|spray|perishable)\b', re.I)
FIELDS = ('candidate_id', 'asin', 'title', 'brand', 'category', 'amazon_category',
          'amazon_url', 'discovery_source', 'observed_at', 'identifiers_json',
          'model', 'pack_information_json', 'variation_json', 'missing_fields_json',
          'mapping_issues_json', 'previously_attempted', 'evidence_refs_json')


def brand_key(brand: str) -> str:
    return 'philips' if brand.casefold() == 'philips led' else brand.casefold()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def plan(history: dict) -> dict:
    sources = ('app/m63_catalog.py', 'app/m63_history.py', 'app/amazon_pilot.py',
               'app/amazon_pacing.py', 'app/amazon_catalog.py', 'app/sp_catalog_targets.py')
    root = Path(__file__).resolve().parent.parent
    return dict(schema=1, authorization=AUTHORIZATION, marketplace_id=MARKETPLACE,
                account_reference='existing-authorized-account', target=100,
                budget=dict(keyword=24, identity=5, catalog_total=29, authentication=1,
                            restrictions=0, pricing=0, fees=0, retailer=0, browser=0, retries=0),
                queries=[dict(category=c, brand=b, keywords=k, title_terms=list(t)) for c,b,k,t in QUERIES],
                included_data=DATA, page_size=20, maximum_pages_per_query=2,
                deadline_seconds=300, history=history,
                code_sha256={p: sha256(root/p) for p in sources})


def write_json(path: Path, data: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(canonical(data) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def prepare(output: Path, private: Path = pilot.DIRECTORY) -> dict:
    proposal = plan(audit(private))
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_json(output/'catalog-manifest.json', proposal)
    return dict(manifest_sha256=sha256(output/'catalog-manifest.json'), live_requests=0)


def identity_missing(snapshot: dict) -> list[str]:
    cat = snapshot['catalog']
    missing = []
    if not any(i.get('normalized_gtin') for i in cat['identifiers']):
        missing.append('gtin')
    if not cat.get('model'):
        missing.append('model')
    if not cat.get('package_quantity'):
        missing.append('package_quantity')
    if not snapshot.get('package_attributes'):
        missing.append('pack_attributes')
    if 'Variation relationships unavailable' in cat['mapping_issues']:
        missing.append('relationships')
    return missing


def screen(item: dict, query: dict, observed: str, ref: str, *, secrets=(), is_mock=False) -> tuple[dict | None, str]:
    snapshot = parse_target_item(item, observed_at=observed, provenance=ref, secrets=secrets, is_mock=is_mock)
    cat = snapshot['catalog']
    summary = marketplace_row(item, 'summaries') or {}
    title = cat.get('title') or ''
    brand = clean_text(summary.get('brand'), secrets)
    if not title or not brand or brand.casefold() != query['brand'].casefold():
        return None, 'missing_or_different_brand_title'
    if not any(re.search(r'\b'+re.escape(t)+r'\b', title, re.I) for t in query['title_terms']):
        return None, 'unrelated_title'
    if item['asin'] in EXCLUSIONS or HAZARDS.search(title):
        return None, 'excluded_or_obvious_risk'
    if cat['item_classification'] == 'VARIATION_PARENT' or any(r['child_asins'] for r in cat['relationships'] if r['relationship_type']=='VARIATION'):
        return None, 'variation_parent'
    # Reject explicit large parcel observations; absence remains a review flag.
    dimensions = marketplace_row(item, 'dimensions') or {}
    package = dimensions.get('package') or {}
    for key in ('length', 'width', 'height', 'weight'):
        d = package.get(key) or {}
        value, unit = d.get('value'), str(d.get('unit', '')).casefold()
        ceilings = {'inches':18, 'inch':18, 'centimeters':45.72, 'millimeters':457.2} if key != 'weight' else {'pounds':5, 'kilograms':2.268, 'grams':2268}
        if type(value) in (int,float) and unit in ceilings and value > ceilings[unit]:
            return None, 'large_or_heavy_package'
    snapshot.update(brand=brand, category=query['category'],
                    amazon_category=clean_text((summary.get('browseClassification') or {}).get('displayName'), secrets),
                    dimensions_present=bool(package), missing_identity=identity_missing(snapshot))
    return snapshot, ''


def select_sample(candidates: dict, blocked: set) -> list[dict]:
    """Round-robin categories, then identity completeness; at most two per brand."""
    chosen, brands = [], Counter()
    pools = {c: sorted((v for a,v in candidates.items() if a not in blocked and v['category']==c
                        and not any('Ambiguous' in issue or 'Invalid GTIN' in issue for issue in v['catalog']['mapping_issues'])),
                       key=lambda v:(len(v['missing_identity']), len(v['catalog']['mapping_issues']), v['catalog']['asin']))
             for c in dict.fromkeys(q[0] for q in QUERIES)}
    while len(chosen)<20:
        progress = False
        for pool in pools.values():
            eligible = next((v for v in pool if brands[brand_key(v['brand'])]<2), None)
            if eligible:
                pool.remove(eligible)
                brands[brand_key(eligible['brand'])] += 1
                chosen.append(eligible)
                progress = True
                if len(chosen)==20:
                    break
        if not progress:
            break
    return chosen


def csv_value(value: object) -> str:
    text = str(value)
    return "'"+text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else text


def export(report: dict, output: Path) -> dict:
    """Offline-only exports; raw responses and private account context omitted."""
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    blocked = set(report['manifest']['history']['excluded_asins'])
    candidates = report['candidates']
    path = output/'M63_amazon_candidates_100.csv'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for asin, snap in sorted(candidates.items()):
            cat = snap['catalog']
            row = dict(candidate_id='amazon-us:'+asin, asin=asin, title=cat['title'], brand=snap['brand'],
                category=snap['category'], amazon_category=snap['amazon_category'], amazon_url='https://www.amazon.com/dp/'+asin,
                discovery_source=snap.get('discovery_source','Amazon SP-API Catalog Items 2022-04-01'), observed_at=snap['observed_at'],
                identifiers_json=canonical(cat['identifiers']), model=cat.get('model') or '',
                pack_information_json=canonical(dict(package_quantity=cat.get('package_quantity'), attributes=snap['package_attributes'])),
                variation_json=canonical(dict(summary=cat.get('variation'), relationships=cat['relationships'])),
                missing_fields_json=canonical(snap['missing_identity']+([] if snap['dimensions_present'] else ['package_dimensions'])),
                mapping_issues_json=canonical(cat['mapping_issues']), previously_attempted=asin in blocked,
                evidence_refs_json=canonical(snap['evidence_refs']))
            writer.writerow({k:csv_value(v) for k,v in row.items()})
    selected = select_sample(candidates, blocked)
    manifest = dict(schema=1, mode='M63_LISTINGS_RESTRICTIONS_PROPOSAL', execution_authorized=False,
        discovery_report_sha256=fingerprint(report), candidates_csv_sha256=sha256(path),
        history_sha256=fingerprint(report['manifest']['history']), marketplace_id=MARKETPLACE,
        condition='new_new', account_reference='existing-authorized-account',
        asins=[s['catalog']['asin'] for s in selected],
        requests=[dict(method='GET', path='/listings/2021-08-01/restrictions',
            params=dict(asin=s['catalog']['asin'], marketplaceIds=MARKETPLACE, conditionType='new_new', reasonLocale='en_US', sellerId='[private runtime value]'),
            candidate_id='amazon-us:'+s['catalog']['asin'], brand=s['brand'], category=s['category'],
            title=s['catalog']['title'], missing_identity=s['missing_identity'], evidence_refs=s['evidence_refs']) for s in selected],
        budget=dict(restrictions=len(selected), distinct_asins=len(selected), maximum_distinct_asins=20,
                    authentication=1 if selected else 0, retries=0, catalog=0, pricing=0, fees=0, retailer=0),
        purchase_approved=False, fulfillment_eligibility=None)
    write_json(output/'M63_eligibility_manifest_20.json', manifest)
    summary = dict(status=report['status'], verified_candidates=len(candidates), proposed_checks=len(selected),
                   keyword_requests=sum(a['kind']=='keyword' for a in report['attempts']),
                   identity_requests=sum(a['kind']=='identity' for a in report['attempts']),
                   authentication_attempts=sum(a['kind']=='authentication' for a in report['attempts']),
                   duration_seconds=report.get('duration_seconds'), errors=report.get('errors', []),
                   history_exclusion_count=len(blocked), manifest_sha256=sha256(output/'M63_eligibility_manifest_20.json'),
                   category_counts=dict(Counter(v['category'] for v in candidates.values())),
                   brand_counts=dict(Counter(v['brand'] for v in candidates.values())),
                   retailer_searches=0, restrictions_checks=0, is_mock=report['is_mock'],
                   evidence_mode=report['mode'], limitations=report.get('limitations',[]))
    write_json(output/'M63_discovery_summary.json', summary)
    return summary


def saved_report(private: Path = pilot.DIRECTORY) -> dict:
    """Reuse authentic saved API observations without refreshing timestamps.

    Search summaries verify a Catalog observation, not full product identity.
    Category is our explicit workflow grouping, never a fabricated Amazon taxonomy.
    """
    snapshots, inventory = audit_saved(private)
    rules = (
        ('kitchen', ('Rubbermaid','Ziploc','Pyrex','Anchor Hocking'), r'\b(storage|containers?|bags?|bakeware)\b'),
        ('office', ('BIC','Post-it','Scotch','Crayola','Mead','U Brands'), r'\b(pens?|notes|tape|markers?|notebooks?)\b'),
        ('household', ('Scotch-Brite','3M','Swiffer','Kleenex'), r'\b(sponges?|dusters?|tissues)\b'),
        ('home_improvement', ('PHILIPS','Philips LED'), r'\bA19\b.*\b(bulbs?|light)\b|\bLED\b.*\bA19\b'),
    )
    pools = {c:[] for c,_,_ in rules}
    grouped = {}
    for original in snapshots:
        # Deep copy avoids rewriting the saved audit's in-memory observations.
        snap=json.loads(canonical(original))
        observed=datetime.fromisoformat(snap['observed_at'])
        if observed.utcoffset() is None or observed>datetime.now(timezone.utc):
            raise ValueError('Saved evidence has invalid/future observation time')
        cat=snap['catalog']
        asin=cat.get('asin')
        title=cat.get('title') or ''
        brand=(snap.get('summary_fields') or {}).get('brand') or ''
        if not brand:
            # Detailed observations can carry brand in package attributes.
            values=snap.get('package_attributes',{}).get('brand',[])
            brand=next((v.get('value') for v in values if isinstance(v,dict) and isinstance(v.get('value'),str)), '')
        if not brand or not title or asin in EXCLUSIONS or HAZARDS.search(title):
            continue
        if re.search(r'\b(4\s*(?:ft|foot)|48\s*(?:in|inch)|fluorescent|extendable|extender|200ct|250-count|100-count|120 count|500-count|8-piece.*bakeware)\b',title,re.I):
            continue
        if re.search(r'\b(?:[5-9]|[1-9]\d+)\s+flat boxes\b',title,re.I):
            continue
        if cat.get('item_classification')=='VARIATION_PARENT':
            continue
        for category,brands,pattern in rules:
            if brand.casefold() in {b.casefold() for b in brands} and re.search(pattern,title,re.I):
                break
        else:
            continue
        for field,default in (('identifiers',[]),('relationships',[]),('mapping_issues',[])):
            cat.setdefault(field,default)
        if original['kind']=='saved_search_summary':
            cat['mapping_issues'].append('Saved search summary; identity datasets unavailable')
        snap.update(brand=brand,category=category,amazon_category='',dimensions_present=False,
                    discovery_source='Saved Amazon SP-API Catalog Items observation; not refreshed',
                    source_evidence=original['provenance'],
                    evidence_refs=[dict(provenance=original['provenance'],observed_at=original['observed_at'],
                                        snapshot_sha256=fingerprint(original))])
        snap['missing_identity']=identity_missing(snap)
        if original['kind']=='saved_search_summary':
            snap['missing_identity']=sorted(set(snap['missing_identity'])|{'relationships','pack_attributes'})
        grouped.setdefault(asin,[]).append(snap)
    for records in grouped.values():
        snap=min(records,key=lambda v:(len(v['missing_identity']),len(v['catalog']['mapping_issues']),v['observed_at']))
        snap['evidence_refs']=[ref for v in records for ref in v['evidence_refs']]
        conflicts=[]
        for field in ('title','model','gtin','package_quantity','variation'):
            values={canonical(v['catalog'][field]) for v in records if v['catalog'].get(field)}
            if len(values)>1:
                conflicts.append(field)
        if conflicts:
            snap['identity_conflicts']=conflicts
            snap['catalog']['mapping_issues'].append('Ambiguous repeated identity observations')
        pools[snap['category']].append(snap)
    blocked=set(audit(private)['excluded_asins'])
    for pool in pools.values():
        pool.sort(key=lambda v:(v['catalog']['asin'] in blocked,len(v['missing_identity']),v['catalog']['asin']))
    candidates,brands,categories={},Counter(),Counter()
    while len(candidates)<100:
        progress=False
        for category,pool in pools.items():
            choice=next((v for v in pool if brands[v['brand'].casefold()]<10 and categories[category]<40),None)
            if choice:
                pool.remove(choice)
                candidates[choice['catalog']['asin']]=choice
                brands[choice['brand'].casefold()]+=1
                categories[category]+=1
                progress=True
                if len(candidates)==100:
                    break
        if not progress:
            break
    return dict(schema=1,mode='M63_SAVED_CATALOG_OFFLINE',manifest=plan(audit(private)),
                saved_inventory=inventory,is_mock=False,status='saved_evidence_only_network_unavailable',
                candidates=candidates,attempts=[],errors=[],duration_seconds=0,
                limitations=['Historical observations; not refreshed. Missing identity remains unknown.',
                             'No live API execution: runtime DNS unavailable.',
                             'Category is workflow grouping; Amazon category absent in saved summaries.'])


def runtime_preflight() -> None:
    """Verified TLS only, no HTTP, credentials or quota before runtime reservation."""
    for host in ('api.amazon.com','sellingpartnerapi-na.amazon.com'):
        with socket.create_connection((host,443),timeout=10) as connection:
            with ssl.create_default_context().wrap_socket(connection,server_hostname=host):
                pass


def run(manifest_path: Path, expected_hash: str, *, private: Path = pilot.DIRECTORY,
        transport=None, credential_loader=None, monotonic=time.monotonic, sleep=time.sleep) -> dict:
    proposal = json.loads(manifest_path.read_bytes())
    if sha256(manifest_path)!=expected_hash or proposal != plan(audit(private)):
        raise ValueError('Manifest/code/history drift')
    if transport is None:
        runtime_preflight()
    directory = pilot.private_directory(private)
    lock = db = stream = None
    started = monotonic()
    report = dict(schema=1, mode='M63_CATALOG_DISCOVERY', manifest=proposal, is_mock=transport is not None,
                  started_at=now(), status='reserved', attempts=[], candidates={}, observations=[], errors=[], rejected=Counter())
    try:
        lock = os.open('candidate-execution.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ValueError('Unsafe shared lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if proposal != plan(audit(private)):
            raise ValueError('History changed while acquiring lock')
        # A single authorization reservation survives crashes, output renames and changed manifests.
        stream = os.fdopen(pilot.create_file(directory, 'm63-catalog-discovery-01.json'), 'w')
        db_fd = pilot.create_file(directory, 'm63-catalog-accounting-01.sqlite3')
        os.close(db_fd)
        db = sqlite3.connect(f'/proc/self/fd/{directory}/m63-catalog-accounting-01.sqlite3')
        db.execute('PRAGMA synchronous=FULL')
        db.executescript('CREATE TABLE authorization (id TEXT PRIMARY KEY, manifest_hash TEXT NOT NULL); CREATE TABLE attempts (ordinal INTEGER PRIMARY KEY, kind TEXT NOT NULL, request_hash TEXT NOT NULL, state TEXT NOT NULL);')
        with db:
            db.execute('INSERT INTO authorization VALUES (?,?)', (AUTHORIZATION,expected_hash))

        def checkpoint():
            stream.seek(0)
            stream.write(canonical(report)+'\n')
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())

        checkpoint()
        pacer = OperationPacer(state_path=f'/proc/self/fd/{directory}/m63-catalog-accounting-01.sqlite3', monotonic=monotonic, sleep=sleep)
        # Honor historical shared cooldowns without changing historical databases.
        old_ledger = private/'candidate-executions.sqlite3'
        if old_ledger.exists():
            with sqlite3.connect('file:'+str(old_ledger)+'?mode=ro', uri=True) as old:
                if old.execute("SELECT 1 FROM sqlite_master WHERE name='amazon_cooldowns'").fetchone():
                    for operation, utc in old.execute('SELECT operation,not_before_utc FROM amazon_cooldowns'):
                        pacer.restore_cooldown(operation, utc)
        deadline = started+proposal['deadline_seconds']

        def call(kind, params=None):
            counts = Counter(a['kind'] for a in report['attempts'])
            limit = {'authentication':1,'keyword':24,'identity':5}[kind]
            if counts[kind]>=limit or (kind!='authentication' and counts['keyword']+counts['identity']>=29):
                raise ValueError('Authorization exhausted')
            if kind!='authentication' and (params.get('marketplaceIds')!=MARKETPLACE or params.get('pageSize')!=20):
                raise ValueError('Unexpected Catalog scope')
            spec = dict(kind=kind, path=PATH if params else '/auth/o2/token', params=params or {})
            index = len(report['attempts'])+1
            # Tokens/page cursors never enter reports, logs or request hash inputs in plaintext.
            attempt = dict(ordinal=index, kind=kind, request_hash=fingerprint(spec), status='reserved', started_at=now())
            with db:
                db.execute('INSERT INTO attempts VALUES (?,?,?,?)',(index,kind,attempt['request_hash'],'reserved'))
            report['attempts'].append(attempt)
            checkpoint()
            before=monotonic()
            try:
                request = pilot.amazon_request(access, PATH, params) if params else None
                if kind=='authentication':
                    response = pilot.exchange_token(credentials, lambda r:pacer.call(r, transport or pilot._request_json, deadline=deadline))
                else:
                    response = pacer.call(request, transport or pilot._request_json, deadline=deadline)
                attempt['status']='response_received'
                if params:
                    attempt['pacing']=getattr(response,'pacing',{})
                return response
            except (Exception, KeyboardInterrupt) as error:
                attempt.update(status='failed', failure=failure_metadata(error))
                raise
            finally:
                attempt.update(duration_seconds=round(monotonic()-before,3), finished_at=now())
                with db:
                    db.execute('UPDATE attempts SET state=? WHERE ordinal=?',(attempt['status'],index))
                checkpoint()

        if pacer.not_before.get('searchCatalogItems',0)>monotonic()+2:
            raise ValueError('Historical cooldown defers discovery')
        if transport is None:
            import resource
            resource.setrlimit(resource.RLIMIT_CORE, (0,0))
        credentials = (credential_loader or pilot.load_credentials)(directory)
        access = call('authentication')
        secrets = (*credentials.values(), access)
        tokens = {}
        def accept(reply, query, identity_asins=None):
            items = reply.get('items')
            count = reply.get('numberOfResults')
            if reply.get('errors') or not isinstance(items,list) or len(items)>20 or type(count) is not int or count<len(items):
                raise ValueError('Malformed Catalog search response')
            ordinal=len(report['attempts'])
            observed=now()
            for item in items:
                try:
                    asin=item.get('asin')
                    if identity_asins is not None and asin not in identity_asins:
                        raise ValueError('Unexpected identity response ASIN')
                    q=query if query else next(v for v in proposal['queries'] if v['brand'].casefold()==report['candidates'][asin]['brand'].casefold())
                    snap, reason=screen(item,q,observed,'m63-catalog-discovery-01.json:response='+str(ordinal), secrets=secrets, is_mock=report['is_mock'])
                    if snap is None:
                        report['rejected'][reason]+=1
                        continue
                    prior=report['candidates'].get(asin)
                    ref=dict(attempt=ordinal,item_sha256=fingerprint(item),observed_at=observed)
                    snap['evidence_refs']=(prior['evidence_refs'] if prior else [])+[ref]
                    # Persist normalized observations only; untrusted seller-specific messages are never cached.
                    report['observations'].append(snap)
                    if prior:
                        # Contradictory observations stay visible and cannot enter
                        # the eligibility sample by choosing the convenient reply.
                        conflicts = list(prior.get('identity_conflicts', []))
                        for field in ('title','model','gtin','package_quantity','variation'):
                            old, new = prior['catalog'].get(field), snap['catalog'].get(field)
                            if old and new and old != new:
                                conflicts.append(field)
                        snap['identity_conflicts']=sorted(set(conflicts))
                        if conflicts:
                            snap['catalog']['mapping_issues'].append('Ambiguous repeated identity observations')
                            prior['catalog']['mapping_issues'].append('Ambiguous repeated identity observations')
                        if len(snap['missing_identity'])<=len(prior['missing_identity']):
                            report['candidates'][asin]=snap
                        else:
                            prior['evidence_refs']=snap['evidence_refs']
                        report['rejected']['duplicate_observation']+=1
                    elif len(report['candidates'])<100:
                        brands=Counter(v['brand'].casefold() for v in report['candidates'].values())
                        categories=Counter(v['category'] for v in report['candidates'].values())
                        if brands[snap['brand'].casefold()]>=10 or categories[snap['category']]>=25:
                            report['rejected']['diversity_cap']+=1
                        else:
                            report['candidates'][asin]=snap
                except Exception:
                    report['rejected']['invalid_item']+=1
                if len(report['candidates'])>=100:
                    break
            pagination=reply.get('pagination') or {}
            token=pagination.get('nextToken')
            if token is not None and (not isinstance(token,str) or len(token)>8192):
                raise ValueError('Invalid pagination')
            checkpoint()
            return token

        for page in range(2):
            for i,q in enumerate(proposal['queries']):
                if len(report['candidates'])>=100:
                    break
                if page and not tokens.get(i):
                    continue
                params=dict(marketplaceIds=MARKETPLACE, includedData=DATA, pageSize=20,
                            locale='en_US', keywordsLocale='en_US', keywords=q['keywords'],brandNames=q['brand'])
                if page:
                    params['pageToken']=tokens[i]
                reply=call('keyword',params)
                tokens[i]=accept(reply,q)
                if report['attempts'][-1].get('pacing',{}).get('retry_after_seconds') is not None:
                    raise ValueError('Retry-After stops discovery')
            if len(report['candidates'])>=100:
                break
        # Additional identity searches only after keyword discovery falls short;
        # the explicit stop-at-100 rule also applies to identity enrichment.
        pending=[a for a,v in sorted(report['candidates'].items()) if v['missing_identity']]
        for offset in range(0,min(len(pending),100),20):
            if len(report['candidates'])>=100:
                break
            batch=pending[offset:offset+20]
            reply=call('identity',dict(marketplaceIds=MARKETPLACE,includedData=DATA,pageSize=20,
                                      locale='en_US',identifiersType='ASIN',identifiers=','.join(batch)))
            accept(reply,None,batch)
            if report['attempts'][-1].get('pacing',{}).get('retry_after_seconds') is not None:
                raise ValueError('Retry-After stops discovery')
        report['status']='target_reached' if len(report['candidates'])==100 else 'completed_bounded_shortfall'
    except (Exception, KeyboardInterrupt) as error:
        if stream is None:
            raise
        report['status']='stopped_no_retry'
        report['errors'].append(failure_metadata(error))
    finally:
        if stream is not None:
            report.update(finished_at=now(),duration_seconds=round(monotonic()-started,3))
            stream.seek(0)
            stream.write(canonical(report)+'\n')
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
        if db is not None:
            db.close()
        if lock is not None:
            os.close(lock)
        os.close(directory)
    return report


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','run','export','saved'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--sha256')
    args=parser.parse_args()
    try:
        if args.action=='prepare':
            result=prepare(args.output)
        elif args.action=='saved':
            result=export(saved_report(),args.output)
        elif args.action=='run':
            if not args.manifest or not args.sha256:
                parser.error('run requires manifest and reviewed SHA256')
            report=run(args.manifest,args.sha256)
            result=export(report,args.output)
        else:
            report=json.loads((pilot.DIRECTORY/'m63-catalog-discovery-01.json').read_bytes())
            result=export(report,args.output)
        print(canonical(result))
        return 0 if result.get('status')!='stopped_no_retry' else 1
    except (Exception,KeyboardInterrupt):
        print('M63 stopped; no replay. Inspect private evidence; no exception payload logged.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
