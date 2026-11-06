"""Exact, bounded broker authorization contracts; no filesystem or network I/O."""
from datetime import datetime
import json
from pathlib import PurePosixPath
import re
from app.m80_contract import unique

OPERATION = 'M902_AUTH14_CATALOG15'
EVIDENCE = ('seller_authorization', 'application_product_listing_role',
            'us_marketplace_participation', 'protected_credentials_binding')


def text(value, pattern, maximum):
    if type(value) is not str or len(value) > maximum or not re.fullmatch(pattern, value, flags=re.ASCII):
        raise ValueError('Invalid scalar')


def identifier(value):
    text(value, r'[A-Za-z0-9][A-Za-z0-9_.:@-]*', 256)


def digest(value, length=64):
    text(value, '[0-9a-f]{'+str(length)+'}', length)


def integer(value):
    if type(value) is not int or not 0 <= value <= 2**64-1:
        raise ValueError('Invalid integer')


def path(value):
    if type(value) is not str or len(value) > 4096 or not value.isascii() or not value.isprintable():
        raise ValueError('Invalid path')
    parsed = PurePosixPath(value)
    if not parsed.is_absolute() or '..' in parsed.parts or str(parsed) != value:
        raise ValueError('Noncanonical path')


def exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('Invalid schema')


def aware(value):
    text(value, r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', 32)
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Aware timestamp required')
    return result


def document(raw):
    if type(raw) is not bytes or len(raw) > 65536:
        raise ValueError('Bounded JSON required')
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON')))
    if type(value) is not dict:
        raise ValueError('Object required')
    return value


def binding(value):
    hashes = ('baseline_sha256', 'credential_sha256', 'evidence_sha256')
    paths = ('account_lock', 'ledger', 'ledger_lock', 'credential_path')
    integers = ('requester_uid', 'account_device', 'account_inode', 'ledger_device', 'ledger_inode')
    exact(value, (*hashes, *paths, *integers, 'operation', 'release_commit', 'seller_id',
                  'marketplace_id', 'application_id'))
    for key in hashes: digest(value[key])
    for key in paths: path(value[key])
    for key in integers: integer(value[key])
    digest(value['release_commit'], 40)
    text(value['seller_id'], '[A-Z0-9]{1,32}', 32)
    identifier(value['application_id'])
    if value['operation'] != OPERATION or value['marketplace_id'] != 'ATVPDKIKX0DER':
        raise ValueError('Fixed operation required')
    if value['account_inode'] == 0 or value['ledger_inode'] == 0:
        raise ValueError('Existing inode required')


def approval(value):
    exact(value, ('binding', 'approved_by', 'approved_at', 'expires_at', 'nonce'))
    binding(value['binding'])
    identifier(value['approved_by'])
    digest(value['nonce'])
    aware(value['approved_at'])
    aware(value['expires_at'])


def evidence(value):
    exact(value, ('seller_id', 'application_id', 'marketplace_id', 'credential_sha256',
                  'reviewer', 'reviewed_at', *EVIDENCE))
    text(value['seller_id'], '[A-Z0-9]{1,32}', 32)
    identifier(value['application_id'])
    identifier(value['reviewer'])
    digest(value['credential_sha256'])
    aware(value['reviewed_at'])
    if value['marketplace_id'] != 'ATVPDKIKX0DER':
        raise ValueError('Fixed marketplace required')
    for key in EVIDENCE:
        item = value[key]
        exact(item, ('confirmed', 'reference'))
        if type(item['confirmed']) is not bool or item['confirmed'] is not True:
            raise ValueError('Reviewed confirmation required')
        ref = item['reference']
        if (type(ref) is not str or not 1 <= len(ref) <= 2048
                or ref.strip() != ref or not ref or not all(c.isprintable() for c in ref)):
            raise ValueError('Bounded evidence reference required')
