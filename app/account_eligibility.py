"""M61 local intake/replay. No transport, credentials or execution entry point."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

from openpyxl import Workbook
from app.amazon_catalog import MARKETPLACE
from app.amazon_details import parse_restrictions
from app.marketplace import match_listings
from app.models import MarketplaceListing, RetailProduct
from app.normalization import gtin, integer, money, timestamp
from app.provider_contracts import SellerContext

STATES = ('NO_REPORTED_RESTRICTIONS', 'APPROVAL_REQUIRED', 'OTHER_RESTRICTED', 'UNKNOWN', 'ERROR')


def safe_url(value: str) -> str | None:
    """Drop query/fragment, userinfo and non-HTTPS links from exported evidence."""
    try:
        p = urlsplit(value)
        if p.scheme == 'https' and p.hostname and not (p.username or p.password):
            return urlunsplit((p.scheme, p.netloc, p.path, '', ''))
    except (ValueError, TypeError):
        pass
    return None


def classify(evidence: dict, asin: str, account: str, now: datetime) -> dict:
    """Replay one explicitly scoped raw or existing normalized restrictions stage."""
    result = dict(status='UNKNOWN', reason_codes=[], instructions=[], links=[], observed_at=None)
    try:
        stage = evidence.get('restrictions') or {}
        if (not isinstance(account, str) or not account.strip() or evidence.get('seller_reference') != account
                or evidence.get('asin') != asin or evidence.get('marketplace_id') != MARKETPLACE
                or evidence.get('condition') != 'new_new' or not evidence.get('reference')):
            return result
        observed = timestamp(evidence.get('observed_at', ''))
        if observed is None or not 0 <= (now-observed).total_seconds() <= 86400:
            return result
        result['observed_at'] = observed.isoformat()
        if (stage.get('http_status') not in (None, 200)
                or stage.get('status') not in ('succeeded', 'not_attempted', None)):
            result['status'] = 'ERROR'
            return result
        if stage.get('status') != 'succeeded':
            return result
        if 'response' in stage:
            # The parser needs a nonsecret scope marker, never an actual merchant ID.
            data = parse_restrictions(stage['response'], SellerContext(account, MARKETPLACE), is_mock=True)
        else:
            data = stage.get('data') or {}
        count = data.get('restriction_count')
        permission = (data.get('listing_permission') or {}).get('value')
        codes = data.get('reason_codes', [])
        if (type(count) is not int or count < 0 or type(permission) is not bool
                or not isinstance(codes, list) or any(not isinstance(c, str) for c in codes)
                or permission != (count == 0) or (count == 0 and (codes or data.get('reasons')))):
            raise ValueError('Contradictory or incomplete restriction evidence')
        result['reason_codes'] = [c if re.fullmatch(r'[A-Z_]{1,80}', c) else 'OTHER' for c in codes]
        # Free text can contain merchant identifiers. Preserve standard instructions by
        # code and sanitized HTTPS links, never arbitrary provider message text.
        for reason in data.get('reasons', []):
            for link in reason.get('links', []):
                url = safe_url(link.get('resource'))
                if url and urlsplit(url).hostname in ('sellercentral.amazon.com', 'www.amazon.com'):
                    result['links'].append(url)
        approval = 'APPROVAL_REQUIRED' in codes
        if data.get('approval_required') is True and not approval:
            raise ValueError('Approval reason missing')
        result['status'] = ('NO_REPORTED_RESTRICTIONS' if count == 0 else
                            'APPROVAL_REQUIRED' if approval else 'OTHER_RESTRICTED')
        if approval:
            result['instructions'] = ['Amazon approval required; review the original private evidence and application link.']
    except (ValueError, TypeError, AttributeError, KeyError, RuntimeError):
        result.update(status='ERROR', reason_codes=[], instructions=[], links=[])
    return result


def evaluate(document: dict, now: datetime) -> dict:
    if now.tzinfo is None:
        raise ValueError('Aware evaluation time required')
    candidates = document['candidates']
    if not 20 <= len(candidates) <= 50:
        raise ValueError('Intake requires 20–50 candidate slots')
    account = document.get('account_reference', '')
    rows = []
    for ordinal, entry in enumerate(candidates, 1):
        r, a = entry.get('retailer', {}), entry.get('amazon', {})
        asin = a.get('asin', '')
        gaps = []
        exact, confidence = False, '0'
        try:
            product = RetailProduct(r.get('retailer', ''), r.get('title', ''), r.get('url', ''),
                gtin(r.get('gtin', '')), r.get('brand', ''), r.get('model', ''),
                integer(r.get('pack_count')), money(r.get('cost')), r.get('availability', 'unknown'),
                timestamp(r.get('observed_at', '')), r.get('provenance', ''), variation=r.get('variation', ''))
            listing = MarketplaceListing(asin, gtin(a.get('gtin', '')), a.get('brand', ''),
                a.get('model', ''), integer(a.get('pack_count')), a.get('variation', ''), None, None)
            match = match_listings(product, (listing,))
            gaps.extend(match.reasons)
            for label, source in (('retailer', r), ('amazon', a)):
                if not safe_url(source.get('url', '')): gaps.append(label + ' URL missing/invalid')
                if not source.get('provenance'): gaps.append(label + ' provenance missing')
                stamp = timestamp(source.get('observed_at', ''))
                if stamp is None or not 0 <= (now-stamp).total_seconds() <= 86400:
                    gaps.append(label + ' timestamp missing/stale/future')
                if not source.get('brand'): gaps.append(label + ' brand missing')
            if not re.fullmatch(r'[A-Z0-9]{10}', asin) or a.get('url') != 'https://www.amazon.com/dp/' + asin:
                gaps.append('ASIN URL mismatch')
            if product.purchase_price is None or product.purchase_price <= 0: gaps.append('Cost unknown/invalid')
            if product.availability != 'in_stock': gaps.append('Availability unknown/unavailable')
            exact = match.exact and not gaps
            confidence = str(match.confidence) if exact else '0'
        except (ValueError, TypeError):
            gaps.append('Invalid intake values')
        restriction = classify(entry.get('eligibility', {}), asin, account, now)
        restriction['evidence_sha256'] = hashlib.sha256(json.dumps(entry.get('eligibility', {}), sort_keys=True).encode()).hexdigest()
        # ASIN permission remains inspectable, but cannot qualify a mismatched retail pack.
        eligible = exact and restriction['status'] == 'NO_REPORTED_RESTRICTIONS'
        rows.append(dict(slot=ordinal, asin=asin, retailer_url=safe_url(r.get('url', '')),
            amazon_url=safe_url(a.get('url', '')), gtin=r.get('gtin'), brand=r.get('brand'),
            model=r.get('model'), pack_count=r.get('pack_count'), cost=r.get('cost'),
            observed_at=r.get('observed_at'), provenance=r.get('provenance'),
            match_confidence=confidence, exact_match=exact, review_required=True, gaps=gaps,
            eligibility=restriction, eligible_for_downstream_checks=eligible,
            fba_eligible=None, fees_verified=None, roi_ge_50=None, net_ge_5=None,
            manual_purchase_authorized=False, purchase_ready=False))
    return dict(schema=1, evaluated_at=now.isoformat(), is_synthetic=document.get('is_synthetic', False),
        account_reference=account, marketplace_id=MARKETPLACE, condition='new_new',
        candidate_slots=len(rows), exact_matches=sum(r['exact_match'] for r in rows),
        counts={s: sum(r['eligibility']['status'] == s for r in rows) for s in STATES},
        rows=rows, external_requests=0, purchase_ready=[])


def export(result: dict, path) -> None:
    book = Workbook()
    book.remove(book.active)
    for title, selected in (
        ('review', result['rows']),
        ('eligible', [r for r in result['rows'] if r['eligible_for_downstream_checks']]),
        ('restricted', [r for r in result['rows'] if r['eligibility']['status'] in ('APPROVAL_REQUIRED', 'OTHER_RESTRICTED')]),
        ('unknown', [r for r in result['rows'] if r['eligibility']['status'] in ('UNKNOWN', 'ERROR')])):
        sheet = book.create_sheet(title)
        sheet.append(['SYNTHETIC' if result['is_synthetic'] else 'LOCAL EVIDENCE', 'Never purchase approval'])
        sheet.append(list(result['rows'][0]))
        for row in selected:
            sheet.append([json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()])
        for line in sheet:
            for cell in line:
                if isinstance(cell.value, str): cell.data_type = 's'
    book.save(path)


def plan(document: dict, result: dict, source_hash: str, asins: list[str], opt_in: bool) -> dict:
    """A nonexecutable proposal; the existing one-shot runner is the future boundary."""
    if not opt_in or not str(document.get('account_reference') or '').strip() or document.get('is_synthetic'):
        raise ValueError('Explicit plan opt-in and real account-bound intake required')
    if not 1 <= len(asins) <= 20 or len(set(asins)) != len(asins):
        raise ValueError('Select 1–20 unique exact targets per future manifest')
    for asin in asins:
        originals = [e for e in document['candidates'] if e.get('amazon', {}).get('asin') == asin]
        if any(e.get('eligibility', {}).get('restrictions', {}).get('status') not in (None, 'not_attempted') for e in originals):
            raise ValueError('Previously attempted target requires owner review, even if stale')
        rows = [r for r in result['rows'] if r['asin'] == asin]
        if len(rows) != 1 or not rows[0]['exact_match'] or rows[0]['eligibility']['status'] != 'UNKNOWN':
            raise ValueError('Unique exact target with missing check required; failures/restrictions need owner review')
    return dict(mode='M61_PROPOSAL_ONLY', source_sha256=source_hash, asins=asins,
        account_reference=document['account_reference'], marketplace_id=MARKETPLACE, condition='new_new',
        authentication=dict(method='POST', url='https://api.amazon.com/auth/o2/token'),
        requests=[dict(method='GET', path='/listings/2021-08-01/restrictions',
            params=dict(asin=a, marketplaceIds=MARKETPLACE, conditionType='new_new',
                        reasonLocale='en_US', sellerId='[private operator entry]')) for a in asins],
        deadline_seconds=120, pagination=False,
        budget=dict(authentication=1, restrictions=len(asins), maximum_requests=1+len(asins), retries=0,
                    catalog=0, pricing=0, fees=0, retailer=0),
        execution_authorized=False, authorized_requests=0, purchase_approved=False,
        prerequisites=['Owner approves new manifest SHA-256, exact targets and budget',
            'Confirm account continuity privately; no merchant IDs in intake',
            'Re-audit all saved attempts including M60; exclude attempted/uncertain targets',
            'Bind source, exclusions, protected evidence and runner hashes using saved-target prepare/validate',
            'Reuse existing exclusive reservations, durable checkpoints, OperationPacer and cooldown/deadline stops; no retries'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('template', 'validate', 'classify', 'export', 'plan'))
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--now', default=datetime.now(timezone.utc).isoformat())
    parser.add_argument('--asins', nargs='+', default=[])
    parser.add_argument('--opt-in-plan', action='store_true')
    args = parser.parse_args()
    if args.action == 'template':
        result = dict(account_reference='', is_synthetic=False, candidates=[dict(retailer={}, amazon={}) for _ in range(20)])
    else:
        if args.input is None: parser.error('--input required')
        raw = args.input.read_bytes()
        document = json.loads(raw)
        result = evaluate(document, timestamp(args.now))
        result['source_sha256'] = hashlib.sha256(raw).hexdigest()
        if args.action == 'plan':
            result = plan(document, result, hashlib.sha256(raw).hexdigest(), args.asins, args.opt_in_plan)
    # Exclusive output protects historical evidence and previous reports.
    with args.output.open('xb') as handle:
        if args.action == 'export':
            export(result, handle)
        else:
            handle.write((json.dumps(result, indent=2) + '\n').encode())


if __name__ == '__main__':
    main()
