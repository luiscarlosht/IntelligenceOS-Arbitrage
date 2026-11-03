"""M80-only frozen research contract. No credential reads or network on import."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from app.m65_intelligence import ASIN, US
from app.m67_state import secure
from app.observations import fingerprint, canonical

OPERATION = 'M80-US-TOP20-SALES-ONCE'
LEDGER = 'm80-us-top20-once.sqlite3'
PLAN = 'm80-plan.json'
ACCOUNT = 'm80-account.json'
BUDGET = {'authentication': 1, 'catalog': 20, 'offers_batch': 1, 'restrictions': 20, 'http_maximum': 42,
          'pricing_subrequests': 20, 'retries': 0, 'refreshes': 0, 'pagination': 0}
RATES = {'catalog': 1.0, 'offers_batch': 0.05, 'restrictions': 1.0}
DATA = 'salesRanks,summaries,identifiers,productTypes,classifications,relationships,attributes'
ACK = 'AUTHORIZE M80 42 REQUESTS TOP20 NO RETRY NO REPLAY'


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def read(path: Path) -> tuple[dict, str]:
    secure(path)
    if {'system.posix_acl_access','system.posix_acl_default'} & set(os.listxattr(path,follow_symlinks=False)):
        raise ValueError('Extended ACL on private input')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:
            raise ValueError('Owner-only single-link private input required')
        if info.st_size>64*1024*1024: raise ValueError('Bounded private JSON required')
        raw=stream.read(64*1024*1024+1)
    if len(raw)>64*1024*1024: raise ValueError('Bounded private JSON required')
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    if not isinstance(value, dict): raise ValueError('Private object required')
    return value, hashlib.sha256(raw).hexdigest()


def write(path: Path, value: dict) -> None:
    secure(path.parent, directory=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())


def implementation() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    paths = sorted(root.rglob('*.py'))
    if any(p.is_symlink() for p in paths): raise ValueError('Nonsymlink code required')
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def definitions(asins: list[str]) -> list[dict]:
    if len(asins) != 20 or len(set(asins)) != 20 or any(not isinstance(a,str) or not ASIN.fullmatch(a) for a in asins):
        raise ValueError('Exactly 20 distinct allowlisted ASINs required')
    result = [dict(slot=1, phase='authentication', method='POST', host='api.amazon.com', path='/auth/o2/token', query={}, body=None)]
    for asin in asins:
        result.append(dict(slot=len(result)+1, phase='catalog', method='GET', host='sellingpartnerapi-na.amazon.com',
            path=f'/catalog/2022-04-01/items/{asin}', query={'marketplaceIds': US, 'includedData': DATA}, body=None, asin=asin))
    batch = [dict(uri=f'/products/pricing/v0/items/{a}/offers', method='GET', MarketplaceId=US,
                  ItemCondition='New', CustomerType='Consumer') for a in asins]
    result.append(dict(slot=22, phase='offers_batch', method='POST', host='sellingpartnerapi-na.amazon.com',
        path='/batches/products/pricing/v0/itemOffers', query={}, body={'requests':batch}))
    for asin in asins:
        result.append(dict(slot=len(result)+1, phase='restrictions', method='GET', host='sellingpartnerapi-na.amazon.com',
            path='/listings/2021-08-01/restrictions', query={'asin': asin, 'marketplaceIds': US,
                'conditionType':'new_new', 'sellerId':'$BOUND_SELLER'}, body=None, asin=asin))
    return result


def account(private: Path) -> tuple[dict, str]:
    if private.resolve().is_relative_to('/mnt'): raise ValueError('M80 execution state must stay outside deployment volumes')
    secure(private, directory=True)
    data, sha = read(private / ACCOUNT)
    if (set(data) != {'schema','operation_id','seller_id','marketplace_id','condition','credentials_sha256'}
            or type(data['schema']) is not int or data['schema'] != 1 or data['operation_id'] != OPERATION
            or data['marketplace_id'] != US or data['condition'] != 'new_new'
            or not isinstance(data['seller_id'],str) or not re.fullmatch('[A-Z0-9]{1,32}',data['seller_id'])
            or not isinstance(data['credentials_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',data['credentials_sha256'])):
        raise ValueError('Separate explicit M80 account binding required')
    return data, sha


def source(handoff: Path, expected_sha: str) -> tuple[dict, list[dict], str]:
    if handoff.name != 'M79_walmart_handoff.json': raise ValueError('Original M79 handoff required')
    data, sha = read(handoff)
    if sha != expected_sha: raise ValueError('Reviewed M79 handoff digest mismatch')
    all_rows = {r['asin']:r for r in data.get('all_asins', [])}
    selected = data.get('priority20', [])
    if (data.get('synthetic') is True or len(all_rows) != len(data.get('all_asins',[])) or data.get('ready_for_walmart_sourcing') is not False
            or len(selected) != 20 or any(all_rows.get(r['asin']) != r or r.get('permanently_excluded')
            or r.get('identity_conflicts') or r.get('is_mock') or r.get('is_synthetic')
            or r.get('marketplace')!='ATVPDKIKX0DER' or r.get('sourcing_allowed') is not False for r in selected)):
        raise ValueError('Exact unblocked original M79 priority20 required')
    definitions([r['asin'] for r in selected])
    return data, selected, sha


def prepare(handoff: Path, expected_sha: str, private: Path) -> dict:
    data, selected, sha=source(handoff,expected_sha)
    _, binding_sha = account(private)
    secure(private / 'credentials.json')  # metadata only; contents remain unread
    secure(private / 'candidate-execution.lock')
    if any(Path(str(private/LEDGER)+suffix).exists() or Path(str(private/LEDGER)+suffix).is_symlink() for suffix in ('','-journal','-wal','-shm')):
        raise ValueError('M80 permanently claimed; no replay')
    protected=sorted({str(handoff.parent.resolve()),*(str(Path(name).resolve().parent) for name in data.get('input_sha256',{}))})
    if any(private.resolve().is_relative_to(root) for root in protected): raise ValueError('Private execution root cannot be inside historical evidence')
    asins = [r['asin'] for r in selected]
    return dict(schema=1, operation_id=OPERATION, marketplace_id=US, condition='new_new',
        private_root=str(private.resolve()), handoff_path=str(handoff.resolve()), handoff_sha256=sha,
        account_sha256=binding_sha, protected_roots=protected, asins=asins, targets=deepcopy(selected), requests=definitions(asins), budget=deepcopy(BUDGET),
        rates=deepcopy(RATES), maximum_seconds=600, implementation_sha256=implementation(),
        purchase_authorized=False, walmart_sourcing_authorized=False)


def validate(plan: dict, *, current_code: bool = True) -> None:
    required = {'schema','operation_id','marketplace_id','condition','private_root','handoff_path','handoff_sha256',
                'account_sha256','protected_roots','asins','targets','requests','budget','rates','maximum_seconds','implementation_sha256',
                'purchase_authorized','walmart_sourcing_authorized'}
    if (set(plan) != required or type(plan['schema']) is not int or plan['schema'] != 1
            or plan['operation_id'] != OPERATION or plan['marketplace_id'] != US or plan['condition'] != 'new_new'
            or plan['budget'] != BUDGET or any(type(x) is not int for x in plan['budget'].values())
            or plan['rates'] != RATES or any(type(x) is not float for x in plan['rates'].values())
            or type(plan['maximum_seconds']) is not int or plan['maximum_seconds'] != 600
            or len(plan['targets']) != 20 or [r['asin'] for r in plan['targets']] != plan['asins']
            or any(r.get('permanently_excluded') or r.get('identity_conflicts') or r.get('sourcing_allowed') is not False for r in plan['targets'])
            or not isinstance(plan['protected_roots'],list) or not plan['protected_roots']
            or any(not Path(root).is_absolute() or str(Path(root).resolve())!=root for root in plan['protected_roots'])
            or any(Path(plan['private_root']).resolve().is_relative_to(root) for root in plan['protected_roots'])
            or plan['requests'] != definitions(plan['asins'])
            or not isinstance(plan['implementation_sha256'],dict) or not plan['implementation_sha256']
            or any(not isinstance(k,str) or not k.endswith('.py') or '..' in Path(k).parts
                   or Path(k).is_absolute() or not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v)
                   for k,v in plan['implementation_sha256'].items())
            or current_code and plan['implementation_sha256'] != implementation()
            or plan['purchase_authorized'] is not False or plan['walmart_sourcing_authorized'] is not False):
        raise ValueError('Exact M80 code/ASIN/request/budget contract required')


def check_inputs(plan: dict) -> None:
    validate(plan)
    private=Path(plan['private_root'])
    if str(private.resolve()) != plan['private_root']: raise ValueError('Canonical private root required')
    _, binding_sha=account(private)
    data, selected, sha=source(Path(plan['handoff_path']),plan['handoff_sha256'])
    protected=sorted({str(Path(plan['handoff_path']).parent.resolve()),*(str(Path(name).resolve().parent) for name in data.get('input_sha256',{}))})
    if (sha!=plan['handoff_sha256'] or plan['protected_roots']!=protected or binding_sha!=plan['account_sha256']
            or selected!=plan['targets']):
        raise ValueError('Plan/source/account drift')
    secure(private/'credentials.json'); secure(private/'candidate-execution.lock')


def permission(plan: dict, reference: str, now: datetime) -> dict:
    validate(plan)
    auth = dict(schema=1, mode='M80_EXPLICIT_OWNER_AUTHORIZATION', operation_id=OPERATION,
        plan_sha256=fingerprint(plan), private_root=plan['private_root'], account_sha256=plan['account_sha256'],
        asins=deepcopy(plan['asins']), budget=deepcopy(BUDGET), issued_at=now.isoformat(),
        expires_at=(now+timedelta(seconds=600)).isoformat(), review_reference=reference,
        approved=True, no_retry=True, no_replay=True)
    check_permission(auth, plan, now)
    return auth


def check_permission(auth: dict, plan: dict, now: datetime) -> None:
    if now.tzinfo is None: raise ValueError('Aware authorization time required')
    expected = {'schema','mode','operation_id','plan_sha256','private_root','account_sha256','asins','budget',
                'issued_at','expires_at','review_reference','approved','no_retry','no_replay'}
    if (set(auth) != expected or type(auth['schema']) is not int or auth['schema'] != 1
            or auth['mode'] != 'M80_EXPLICIT_OWNER_AUTHORIZATION' or auth['operation_id'] != OPERATION
            or auth['plan_sha256'] != fingerprint(plan) or auth['private_root'] != plan['private_root']
            or auth['account_sha256'] != plan['account_sha256'] or auth['asins'] != plan['asins']
            or auth['budget'] != BUDGET or any(type(x) is not int for x in auth['budget'].values()) or auth['approved'] is not True or auth['no_retry'] is not True
            or auth['no_replay'] is not True or not isinstance(auth['review_reference'],str)
            or not re.fullmatch(r'manual:[A-Za-z0-9._-]{1,80}',auth['review_reference'])):
        raise ValueError('Separate exact M80 owner permission required')
    start=datetime.fromisoformat(auth['issued_at']); end=datetime.fromisoformat(auth['expires_at'])
    if (start.tzinfo is None or end.tzinfo is None or not start<=now<end
            or not timedelta(0)<end-start<=timedelta(seconds=600)):
        raise ValueError('Fresh maximum ten-minute owner authorization required')
