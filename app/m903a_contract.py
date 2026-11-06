"""Bounded canonical storage contracts; no filesystem or network I/O."""
import hashlib
import json
import re
from app.m902_history import unique
from app.m902c_cutover import SOURCE, DESTINATION, ACCOUNT_LOCK

ZERO = '0'*64
MAX_RECORD = 65536
MAX_REGISTRY = 1024*1024
TRANSITIONS = ('WRITERS_FROZEN','SOURCE_VERIFIED','DESTINATION_STAGED','DESTINATION_VERIFIED',
               'CLAIMS_RECONCILED','RUNTIME_ATTESTED','AUTHORITY_COMMITTED','POST_CUTOVER_VERIFIED')


def canonical(value) -> bytes:
    return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()


def sha(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()


def exact(value, keys):
    if type(value) is not dict or set(value) != set(keys): raise ValueError('SCHEMA_BLOCKED')


def number(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value < 2**64: raise ValueError('SCHEMA_BLOCKED')


def hashed(value, length=64):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{'+str(length)+'}',value): raise ValueError('SCHEMA_BLOCKED')


def hashes(value):
    if type(value) is not list or len(value)>2048 or len(set(value))!=len(value): raise ValueError('SCHEMA_BLOCKED')
    for item in value: hashed(item)


def identity(value):
    exact(value,('device','inode'));number(value['device']);number(value['inode'],positive=True)


def load(raw,maximum=MAX_RECORD):
    if type(raw) is not bytes or len(raw)>maximum: raise ValueError('BOUND_EXCEEDED')
    value=json.loads(raw,object_pairs_hook=unique,
                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError('SCHEMA_BLOCKED')))
    if canonical(value)!=raw: raise ValueError('NONCANONICAL_STORAGE')
    return value


def common(value):
    if type(value['version']) is not int or value['version']!=1: raise ValueError('SCHEMA_BLOCKED')
    hashed(value['migration_id']);number(value['generation'],positive=True)


def record(value):
    exact(value,('version','migration_id','generation','sequence','previous','kind','transition','nonce',
                 'operation_claim','payload_sha256','decision','record_sha256'))
    common(value);number(value['sequence'],positive=True)
    for key in ('previous','nonce','operation_claim','payload_sha256','record_sha256'):hashed(value[key])
    if value['kind'] not in ('INTENT','COMPLETE') or value['transition'] not in TRANSITIONS: raise ValueError('SCHEMA_BLOCKED')
    if value['decision'] not in ('OLD','PENDING_NO_WRITERS','NEW'):raise ValueError('SCHEMA_BLOCKED')
    payload={key:item for key,item in value.items() if key!='record_sha256'}
    if sha(canonical(payload))!=value['record_sha256']:raise ValueError('HASH_CHAIN_BLOCKED')
    if len(canonical(value))>MAX_RECORD: raise ValueError('BOUND_EXCEEDED')


def registry(value):
    exact(value,('version','migration_id','generation','sequence','journal_sha256','nonces','operation_claims',
                 'decision','pending','claims_sha256'))
    common(value);number(value['sequence']);hashed(value['journal_sha256']);hashed(value['claims_sha256'])
    hashes(value['nonces']);hashes(value['operation_claims'])
    if value['decision'] not in ('OLD','PENDING_NO_WRITERS','NEW'):raise ValueError('SCHEMA_BLOCKED')
    if type(value['pending']) is not bool:raise ValueError('SCHEMA_BLOCKED')
    if len(canonical(value))>MAX_REGISTRY:raise ValueError('BOUND_EXCEEDED')


MANIFEST_KEYS=('version','migration_id','generation','source_path','destination_path','account_lock_path',
    'source_identity','destination_identity','account_lock_identity','source_lock_identity','destination_lock_identity',
    'ledger_sha256','prefix_sha256','ceiling','purchase_authorized','claims_sha256','runtime_sha256',
    'release_commit','previous_checkpoint','approval_nonce','authority','active_authorities','retirement_sha256')


def manifest(value):
    exact(value,MANIFEST_KEYS);common(value)
    if (value['source_path']!=SOURCE or value['destination_path']!=DESTINATION or value['account_lock_path']!=ACCOUNT_LOCK
            or type(value['ceiling']) is not int or value['ceiling']!=49 or value['purchase_authorized'] is not False
            or value['authority']!='NEW' or value['active_authorities']!=['NEW']):raise ValueError('AUTHORITY_BLOCKED')
    for key in ('source_identity','destination_identity','account_lock_identity','source_lock_identity','destination_lock_identity'):
        identity(value[key])
    for key in ('ledger_sha256','prefix_sha256','claims_sha256','runtime_sha256','approval_nonce','retirement_sha256'):hashed(value[key])
    hashed(value['release_commit'],40)
    exact(value['previous_checkpoint'],('sequence','journal_sha256'))
    number(value['previous_checkpoint']['sequence']);hashed(value['previous_checkpoint']['journal_sha256'])
    if len(canonical(value))>MAX_RECORD:raise ValueError('BOUND_EXCEEDED')
