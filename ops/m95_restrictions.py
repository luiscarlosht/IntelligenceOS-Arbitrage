"""M95 controlled restriction-only pilot; offline validation by default."""

import argparse
import fcntl
import os
import re
from urllib.parse import parse_qs, urlsplit

from app import amazon_pilot as pilot
from app.amazon_catalog import MARKETPLACE
from app.amazon_details import parse_restrictions as shared_parse_restrictions
import json
from pathlib import Path

from ops import m94_restrictions as m94
from ops import m95_manifest as manifest

EXPECTED_DIGEST = (
    "618a5d38b01b622983e25d3e81acec8d19e5e78d8965bcd160b522e766bc6792"
)

AUTHORIZATION = "m95-eligibility-authorization-01.json"
REPORT_STEM = "m95-eligibility-" + EXPECTED_DIGEST + "-01"


def validate(path=None, digest=EXPECTED_DIGEST):
    path = manifest.OUTPUT if path is None else Path(path)
    if digest != EXPECTED_DIGEST:
        raise ValueError("Unreviewed M95 manifest fingerprint")

    reviewed = manifest.validate(path, digest)

    if reviewed["asins"] != list(manifest.ASINS):
        raise ValueError("M95 cohort mismatch")

    if reviewed["budget"] != manifest.BUDGET:
        raise ValueError("M95 request budget mismatch")

    if reviewed["execution_authorized"] is not False:
        raise ValueError("Unexpected execution authorization")

    if reviewed["purchase_authorized"] is not False:
        raise ValueError("Unexpected purchase authorization")

    if reviewed["live_requests"] != 0:
        raise ValueError("Manifest must be an offline proposal")

    return reviewed


def parse_restrictions(data, context, *, is_mock):
    """Conservative M95 semantics: empty rows alone do not prove permission.

    The legacy parser's boolean is intentionally suppressed. No affirmative
    provider signal has yet been validated for the reviewed API response shape.
    """
    result = shared_parse_restrictions(data, context, is_mock=is_mock)
    result['listing_permission']['value'] = None
    result['listing_permission']['provenance'] = 'M95: no validated affirmative permission signal'
    result['parser_semantics'] = 'm95-conservative-v1'
    from ops.m95_eligibility import m95_decision
    result['eligibility_status'] = m95_decision(
        dict(restrictions=dict(status='succeeded', data=result)))
    return result


def bounded_transport(network):
    """Per-run exact operation, query and budget gate, before any I/O."""
    authentication = 0
    checked = set()
    bound_seller = None

    def send(request):
        nonlocal authentication, bound_seller
        url = urlsplit(request.full_url)
        if (url.scheme != 'https' or url.port not in (None, 443)
                or url.username or url.password or url.fragment):
            raise ValueError('Unexpected Amazon API endpoint')
        if url.hostname == 'api.amazon.com' and url.path == '/auth/o2/token':
            if request.get_method() != 'POST' or url.query:
                raise ValueError('Unexpected authentication operation')
            if authentication or checked:
                raise ValueError('Authentication request budget exceeded')
            authentication += 1
        elif (url.hostname == 'sellingpartnerapi-na.amazon.com'
              and url.path == '/listings/2021-08-01/restrictions'):
            params = parse_qs(url.query, keep_blank_values=True, strict_parsing=True)
            asin = params.get('asin', [None])[0]
            seller = params.get('sellerId', [''])[0]
            expected = dict(asin=[asin], sellerId=[seller], marketplaceIds=[MARKETPLACE],
                            conditionType=['new_new'], reasonLocale=['en_US'])
            if (request.get_method() != 'GET' or request.data is not None
                    or params != expected or asin not in manifest.ASINS
                    or not re.fullmatch(r'[A-Z0-9]{1,32}', seller)):
                raise ValueError('Unexpected restriction operation or scope')
            if authentication != 1 or asin in checked or len(checked) >= 10:
                raise ValueError('Restriction request budget exceeded')
            if bound_seller is not None and seller != bound_seller:
                raise ValueError('Seller context changed')
            bound_seller = seller
            checked.add(asin)
        else:
            raise ValueError('Unexpected Amazon API endpoint')
        # Retain only known reason codes and scope fields.
        reply = network(request)
        if url.hostname == 'api.amazon.com':
            return reply
        from app.amazon_diagnostics import ResponseDocument
        if not isinstance(reply, dict) or reply.get('errors') or not isinstance(reply.get('restrictions'), list):
            raise ValueError('Invalid restriction response')
        cleaned = []
        for row in reply['restrictions']:
            if (not isinstance(row, dict) or row.get('marketplaceId') != MARKETPLACE
                    or row.get('conditionType') not in (None, 'new_new')
                    or not isinstance(row.get('reasons', []), list)):
                raise ValueError('Invalid restriction scope or row')
            reasons = []
            for reason in row.get('reasons', []):
                if not isinstance(reason, dict):
                    raise ValueError('Invalid restriction reason')
                code = reason.get('reasonCode')
                reasons.append(dict(reasonCode=code if code in
                    ('APPROVAL_REQUIRED', 'NOT_ELIGIBLE', 'ASIN_NOT_FOUND') else 'OTHER'))
            cleaned.append(dict(marketplaceId=MARKETPLACE,
                                conditionType=row.get('conditionType'), reasons=reasons))
        status = getattr(reply, 'http_status', 200)
        if status != 200:
            raise ValueError('Unsuccessful restriction response')
        result = ResponseDocument(dict(restrictions=cleaned), status)
        result.rate_headers = getattr(reply, 'rate_headers', {})
        return result
    return send


def run(path=None, digest=EXPECTED_DIGEST, *, execute_reviewed=False,
        private=None, transport=None, credential_loader=None, seller_prompt=None,
        is_mock=False):
    if not execute_reviewed:
        raise RuntimeError('M95 live execution is disabled; explicit --execute-reviewed required')
    if is_mock and (private is None or transport is None or credential_loader is None or seller_prompt is None):
        raise ValueError('Mock execution requires isolated evidence and explicit dependencies')
    private = pilot.DIRECTORY if private is None else Path(private)
    if is_mock and private.resolve() == pilot.DIRECTORY.resolve():
        raise ValueError('Mock execution cannot use production evidence')
    validate(path, digest)
    directory = pilot.private_directory(private)
    lock = None
    try:
        lock = os.open('candidate-execution.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                       0o600, dir_fd=directory)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        reviewed = validate(path, digest)  # Fresh historical audit under the shared lock.
        fd = pilot.create_file(directory, AUTHORIZATION)
        with os.fdopen(fd, 'w') as out:
            json.dump(dict(manifest_sha256=digest, asins=list(manifest.ASINS),
                           maximum_checks=10, state='claimed_no_replay', is_mock=is_mock), out)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.fsync(directory)
        internal = dict(deadline_seconds=120, budget=dict(manifest.BUDGET),
            requests=[dict(asin=a, seller_reference='authorized-seller', pricing={},
                           restrictions=dict(path=r['path'], params=r['params']))
                      for a, r in zip(manifest.ASINS, reviewed['requests'], strict=True)])
        return m94.engine._execute(internal, private,
            operations={a: ('restrictions',) for a in manifest.ASINS},
            request_limit=11, stem=REPORT_STEM, stop_after_no_restrictions=1,
            initial_report=dict(source_bound_manifest=reviewed, listing_authorized=False),
            transport=bounded_transport(transport or pilot._request_json),
            credential_loader=credential_loader, seller_prompt=seller_prompt,
            is_mock=is_mock, restriction_parser=parse_restrictions)
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "run"))
    parser.add_argument(
        "--manifest", type=Path, default=manifest.OUTPUT
    )
    parser.add_argument(
        "--sha256", default=EXPECTED_DIGEST
    )
    parser.add_argument("--execute-reviewed", action="store_true")
    args = parser.parse_args()
    if (args.action == "run") != args.execute_reviewed:
        parser.error("run requires --execute-reviewed")

    try:
        reviewed = validate(args.manifest, args.sha256)
        if args.action == "run":
            result = run(args.manifest, args.sha256, execute_reviewed=True)
            print(json.dumps(dict(status=result["status"], attempts=len(result["attempts"]))))
            return 0
        print(json.dumps({
            "status": "validated_offline",
            "asins": len(reviewed["asins"]),
            "maximum_requests":
                reviewed["budget"]["maximum_requests"],
            "live_requests": 0,
            "execution_enabled": False,
            "purchase_authorized": False,
        }, indent=2))
        return 0
    except Exception as error:
        print(
            "M95 validation failed:",
            type(error).__name__
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
