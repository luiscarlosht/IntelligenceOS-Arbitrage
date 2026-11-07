"""M94 five-ASIN, one-shot, restriction-only Amazon pilot.

Offline validation by default. Live execution requires explicit reviewed digest.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path

from app import amazon_candidate_enrichment as engine
from app import amazon_pilot as pilot
from app.amazon_catalog import MARKETPLACE
from app.amazon_diagnostics import ResponseDocument
from app.m63_history import audit, sha256

ASINS = ('B000255NH8', 'B0002AR73G', 'B00061SL0Y', 'B000AQSCE0', 'B000NP2SBG')
ROOT = Path('/root/IntelligenceOS-Arbitrage-M61/var')
M69 = ROOT / 'm69-offline-review/M69_history.json'
M79 = ROOT / 'm79-amazon-intelligence-final-20261103/M79_report.json'
MANIFEST = Path('var/m94-offline-review/M94_pilot_manifest.json')
EXPECTED_DIGEST = '8004c4bba07fa40b0636324424b0b5cf8b65498fb7305fe4b4945b443ddc9598'
AUTHORIZATION = 'm94-eligibility-authorization-01.json'


def audit_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate(path, digest, private=pilot.DIRECTORY):
    if path.is_symlink() or not path.is_file() or sha256(path) != digest or digest != EXPECTED_DIGEST:
        raise ValueError('Reviewed manifest SHA256 mismatch')
    m = json.loads(path.read_bytes())
    m69 = json.loads(M69.read_bytes())
    m79 = json.loads(M79.read_bytes())
    historical = audit(private)
    if m.get('schema') != 1 or m.get('mode') != 'M94_RESTRICTIONS_ONLY_PROPOSAL':
        raise ValueError('Unexpected M94 manifest')
    if m.get('execution_authorized') is not False or m.get('purchase_authorized') is not False or m.get('live_requests') != 0:
        raise ValueError('Manifest is not an offline proposal')
    if m.get('asins') != list(ASINS) or m.get('marketplace_id') != MARKETPLACE or m.get('condition') != 'new_new':
        raise ValueError('ASIN cohort, marketplace, or condition changed')
    if m.get('source_sha256') != {'M69': sha256(M69), 'M79': sha256(M79)}:
        raise ValueError('Historical source file changed')
    if m.get('historical_audit_sha256') != audit_digest(historical):
        raise ValueError('Historical audit changed; re-review required')
    excluded = set(m69['excluded_asins']) | set(historical['excluded_asins'])
    checked = {r['asin'] for r in m69['rows']}
    if len(m69['rows']) != 40 or len(m69['excluded_asins']) != 97 or len(m79['catalog']) != 1397:
        raise ValueError('Historical source shape changed')
    if set(ASINS) & (excluded | checked):
        raise ValueError('Previously excluded or checked ASIN')
    if m.get('historical_exclusion_union_count') != len(excluded):
        raise ValueError('Historical exclusion count changed')
    catalog = {r['asin']: r for r in m79['catalog']}
    if any(a not in catalog or catalog[a].get('marketplace') != MARKETPLACE for a in ASINS):
        raise ValueError('Catalog identity/marketplace mismatch')
    budget = dict(authentication=1, restrictions=5, maximum_requests=6, retries=0,
                  pricing=0, fees=0, catalog=0, retailer=0)
    if m.get('budget') != budget or len(m.get('requests', [])) != 5:
        raise ValueError('Request ceiling changed')
    for asin, request in zip(ASINS, m['requests'], strict=True):
        expected = dict(method='GET', path='/listings/2021-08-01/restrictions',
                        params=dict(asin=asin, marketplaceIds=MARKETPLACE,
                                    conditionType='new_new', reasonLocale='en_US',
                                    sellerId='[private runtime value]'))
        if request != expected:
            raise ValueError('Request parameters changed')
    return m


def safe_transport(request):
    from urllib.parse import urlsplit

    url = urlsplit(request.full_url)
    allowed = (
        url.scheme == 'https'
        and (
            (url.hostname == 'api.amazon.com'
             and url.path == '/auth/o2/token')
            or
            (url.hostname == 'sellingpartnerapi-na.amazon.com'
             and url.path == '/listings/2021-08-01/restrictions')
        )
        and url.port in (None, 443)
        and not url.username
        and not url.password
        and not url.fragment
    )
    if not allowed:
        raise ValueError('Unexpected Amazon API endpoint')

    reply = pilot._request_json(request)
    if url.hostname == 'api.amazon.com':
        return reply
    items = reply.get('restrictions')
    if reply.get('errors') or not isinstance(items, list):
        raise ValueError('Invalid restriction response')
    cleaned = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('reasons', []), list):
            raise ValueError('Invalid restriction row')
        reasons = []
        for reason in item.get('reasons', []):
            if not isinstance(reason, dict):
                raise ValueError('Invalid restriction reason')
            code = reason.get('reasonCode')
            reasons.append(dict(reasonCode=code if code in
                                ('APPROVAL_REQUIRED', 'ASIN_NOT_FOUND', 'NOT_ELIGIBLE') else 'OTHER'))
        cleaned.append(dict(marketplaceId=item.get('marketplaceId'),
                            conditionType=item.get('conditionType'), reasons=reasons))
    result = ResponseDocument(dict(restrictions=cleaned), getattr(reply, 'http_status', 200))
    result.rate_headers = getattr(reply, 'rate_headers', {})
    return result


def run(path, digest):
    m = validate(path, digest)
    directory = pilot.private_directory(pilot.DIRECTORY)
    lock = None
    try:
        lock = os.open('candidate-execution.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                       0o600, dir_fd=directory)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        validate(path, digest)
        fd = pilot.create_file(directory, AUTHORIZATION)
        with os.fdopen(fd, 'w') as out:
            json.dump(dict(manifest_sha256=digest, asins=list(ASINS),
                           maximum_checks=5, state='claimed_no_replay'), out)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)

    internal = dict(deadline_seconds=120, budget=dict(maximum_requests=6),
                    requests=[dict(asin=a, seller_reference='authorized-seller', pricing={},
                                   restrictions=dict(path=s['path'], params=s['params']))
                              for a, s in zip(ASINS, m['requests'], strict=True)])
    rows = [dict(asin=a, target_id='amazon-us:' + a, marketplace_id=MARKETPLACE,
                 condition='new_new', seller_reference='authorized-seller',
                 pricing=dict(status='not_requested', data=None),
                 fees=dict(status='not_requested', data=None),
                 restrictions=dict(status='not_attempted', data=None)) for a in ASINS]
    return engine._execute(internal, pilot.DIRECTORY,
                           operations={a: ('restrictions',) for a in ASINS},
                           request_limit=6, stem='m94-eligibility-' + digest + '-01',
                           initial_report=dict(rows=rows, source_bound_manifest=m),
                           transport=safe_transport)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('validate', 'run'))
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--execute-reviewed', action='store_true')
    args = parser.parse_args()
    if (args.action == 'run') != args.execute_reviewed:
        parser.error('Live run requires --execute-reviewed')
    try:
        m = validate(args.manifest, args.sha256)
        if args.action == 'validate':
            print(json.dumps(dict(status='validated_offline', asins=m['asins'], live_requests=0)))
        else:
            result = run(args.manifest, args.sha256)
            print(json.dumps(dict(status=result['status'], attempts=len(result['attempts']),
                                  restrictions=[dict(asin=r['asin'], status=r['restrictions']['status'])
                                                for r in result['rows']])))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print('M94 stopped without replay; inspect private evidence. Error type:', type(error).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
