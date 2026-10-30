"""Explicit candidate-ASIN enrichment: offline manifest, bounded manual execution."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import time

from app import amazon_pilot as pilot
from app.amazon_catalog import MARKETPLACE
from app.amazon_details import (parse_fees, parse_pricing, parse_restrictions,
                                proposed_price, prompt_seller_id)
from app.amazon_diagnostics import failure_metadata, response_metadata
from app.amazon_pricing_shape import validate_asin
from app.observations import canonical, normalized
from app.provider_contracts import SellerContext

SELECTION = [dict(basis=basis, fulfillment_channel=channel)
             for channel in ('Amazon', 'Merchant')
             for basis in ('buy_box_observed', 'lowest_observed')]
NOTICE = ('Candidate ASIN analysis only; product identity unverified. Listing permission is not '
          'purchase approval or FBA eligibility. Fee estimates are hypothetical; no verified net profit.')


def read_saved(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Saved candidate report exceeds bound')
    report = json.loads(raw)
    if (type(report.get('is_mock')) is not bool or len(report.get('rows', [])) != 10
            or [r['ordinal'] for r in report['rows']] != list(range(1, 11))):
        raise ValueError('Exactly ten saved source ordinals and explicit provenance required')
    return report, hashlib.sha256(raw).hexdigest()


def plan(saved: Path, *, fixed_fee_prices: dict | None = None,
         seller_reference: str = 'authorized-seller') -> dict:
    report, digest = read_saved(saved)
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', seller_reference):
        raise ValueError('Nonsecret seller reference required')
    ordinals = {}
    for row in report['rows']:
        asin = (row.get('search') or {}).get('selected_asin')
        if asin:
            validate_asin(asin)
            ordinals.setdefault(asin, []).append(row['ordinal'])
    prices = {asin: str(proposed_price(str(price))) for asin, price in (fixed_fee_prices or {}).items()}
    if set(prices) - set(ordinals):
        raise ValueError('Fee scenarios must reference existing candidate ASINs')
    requests = []
    for asin, rows in ordinals.items():
        requests.append(dict(asin=asin, source_ordinals=rows, marketplace_id=MARKETPLACE,
            condition='new_new', customer_type='Consumer', seller_reference=seller_reference,
            pricing=dict(method='GET', path=f'/products/pricing/v0/items/{asin}/offers',
                params=dict(MarketplaceId=MARKETPLACE, ItemCondition='New', CustomerType='Consumer'),
                selection=SELECTION),
            fees=dict(method='POST', path=f'/products/fees/v0/items/{asin}/feesEstimate',
                sale_price=prices.get(asin), price_policy='fixed_hypothetical' if asin in prices else 'selected_observed_item_price',
                buyer_shipping='0', fulfillment='FBA', currency='USD',
                identifier='candidate-enrichment-'+asin,
                missing_price_policy='skip fee request; retain other outcomes'),
            restrictions=dict(method='GET', path='/listings/2021-08-01/restrictions',
                params=dict(asin=asin, sellerId='[hidden seller entry]', marketplaceIds=MARKETPLACE,
                            conditionType='new_new', reasonLocale='en_US'))))
    n = len(requests)
    return dict(schema=1, saved_report_sha256=digest, source_rows=10,
        seller_reference=seller_reference, fixed_fee_prices=prices, requests=requests,
        authentication=dict(method='POST', url='https://api.amazon.com/auth/o2/token', grant_type='refresh_token'),
        budget=dict(authentication=1, pricing=n, fees=n, restrictions=n, maximum_requests=1+3*n, retries=0),
        deadline_seconds=300, minimum_interval_seconds=2.1, notice=NOTICE,
        pagination=False, execution_authorized=False, live_requests=0)


def selected_offer(pricing: dict | None) -> dict | None:
    """Select a declared summary observation, never combine prices across offers."""
    snapshot = (pricing or {}).get('value') or {}
    for selector in SELECTION:
        for offer in snapshot.get('prices', []):
            if all(offer.get(k) == v for k, v in selector.items()) and offer.get('listing_price') is not None:
                return offer
    return None


def execute(saved: Path, manifest: dict, private_path: Path = pilot.DIRECTORY, *,
            transport=None, credential_loader=None, seller_prompt=None, is_mock: bool = False,
            sleep=time.sleep, monotonic=time.monotonic) -> dict:
    expected = plan(saved, fixed_fee_prices=manifest.get('fixed_fee_prices'),
                    seller_reference=manifest.get('seller_reference', ''))
    if manifest != expected:
        raise ValueError('Manifest differs from exact candidate/scenario plan')
    source, _ = read_saved(saved)
    if source['is_mock'] is not is_mock:
        raise ValueError('Execution provenance must match saved candidate provenance')
    return _execute(manifest, private_path, transport=transport, credential_loader=credential_loader,
                    seller_prompt=seller_prompt, is_mock=is_mock, sleep=sleep, monotonic=monotonic)


def _execute(manifest, private_path, *, transport=None, credential_loader=None,
             seller_prompt=None, is_mock=False, sleep=time.sleep, monotonic=time.monotonic,
             initial_report=None, operations=None, stem=None, request_limit=None):
    """Shared bounded engine; callers validate the complete execution scope first."""
    from app.amazon_pacing import OperationPacer
    pacer = (OperationPacer(monotonic=monotonic, sleep=sleep)
             if transport is not None else pilot.default_pacer())
    directory = pilot.private_directory(private_path)
    stem = stem or 'candidate-enrichment-'+manifest['saved_report_sha256']+'-01'
    try:
        fd = pilot.create_file(directory, stem+'.json')
    except BaseException:
        os.close(directory)
        raise
    report = dict(schema=1, manifest=manifest, is_mock=is_mock, status='reserved', attempts=[],
        live_requests=0, purchase_approved=False, seller_eligible=None,
        rows=[dict(asin=s['asin'], marketplace_id=MARKETPLACE, condition='new_new',
                   seller_reference=s['seller_reference'],
                   **{stage: dict(status='not_attempted', data=None) for stage in ('pricing','fees','restrictions')})
              for s in manifest['requests']])
    if initial_report is not None:
        report.update(initial_report)
    output = os.fdopen(fd, 'w')
    previous = None
    start = None

    def checkpoint():
        output.seek(0)
        output.write(canonical(report)+'\n')
        output.truncate()
        output.flush()
        os.fsync(output.fileno())

    def call(stage, asin, request):
        if len(report['attempts']) >= (request_limit or manifest['budget']['maximum_requests']):
            raise RuntimeError('Request cap reached')
        remaining = manifest['deadline_seconds']-(monotonic()-start)
        if remaining <= 0:
            raise TimeoutError('Enrichment deadline')
        if monotonic()-start >= manifest['deadline_seconds']:
            raise TimeoutError('Enrichment deadline')
        attempt = dict(stage=stage, asin=asin, status='reserved')
        report['attempts'].append(attempt)
        report['live_requests'] = 0 if is_mock else len(report['attempts'])
        checkpoint()  # Durable attempt reservation before every network operation.
        try:
            document = pacer.call(request, transport or pilot._request_json, deadline=start+manifest['deadline_seconds'])
            attempt.update(status='response_received', **response_metadata(document))
            if getattr(document, 'pacing', None):
                attempt['pacing'] = document.pacing
            checkpoint()
            return document
        except Exception as error:
            attempt.update(status='failed', failure=failure_metadata(error))
            checkpoint()
            raise

    def stage(row, name, request, parser):
        outcome = row[name]
        outcome['status'] = 'attempted'
        checkpoint()
        try:
            outcome['data'] = normalized(parser(call(name, row['asin'], request)))
            outcome['status'] = 'succeeded'
        except TimeoutError:
            raise
        except Exception as error:
            outcome.update(status='failed', data=None, failure=failure_metadata(error))
        checkpoint()

    try:
        checkpoint()  # Reserve all candidate outcomes before prompting or loading credentials.
        seller = (seller_prompt or prompt_seller_id)()
        if not re.fullmatch(r'[A-Z0-9]{1,32}', seller):
            raise ValueError('Invalid seller ID')
        context = SellerContext(seller, MARKETPLACE, 'new_new')
        previous = signal.signal(signal.SIGALRM, pilot.deadline)
        signal.alarm(manifest['deadline_seconds'])
        start = monotonic()
        credentials = (credential_loader or pilot.load_credentials)(directory)
        access = pilot.exchange_token(credentials, lambda req: call('authentication', None, req))
        for row, spec in zip(report['rows'], manifest['requests']):
            asin = spec['asin']
            allowed = operations.get(asin, ()) if operations is not None else ('pricing', 'restrictions', 'fees')
            if not allowed:
                continue
            pricing = spec['pricing']
            if 'pricing' in allowed:
                stage(row, 'pricing', pilot.amazon_request(access, pricing['path'], pricing['params']),
                      lambda data: asdict(parse_pricing(data, is_mock=is_mock, expected_asin=asin)))
            # Restriction outcomes are independent of pricing and fee availability.
            restrictions = spec['restrictions']
            params = dict(restrictions['params'], sellerId=seller)
            if 'restrictions' in allowed:
                stage(row, 'restrictions', pilot.amazon_request(access, restrictions['path'], params),
                      lambda data: parse_restrictions(data, context, is_mock=is_mock))
            if 'fees' not in allowed:
                continue
            fee = spec['fees']
            offer = selected_offer(row['pricing']['data'])
            price = proposed_price(fee['sale_price']) if fee['sale_price'] is not None else (
                    Decimal(str(offer['listing_price'])) if offer else None)
            scenario = dict(sale_price=str(price) if price is not None else None,
                            buyer_shipping=fee['buyer_shipping'], fulfillment=fee['fulfillment'],
                            price_policy=fee['price_policy'], currency='USD')
            row['fees']['scenario'] = scenario
            if price is None or price <= 0:
                row['fees'].update(status='skipped_missing_price', data=None)
                checkpoint()
                continue
            body = dict(FeesEstimateRequest=dict(MarketplaceId=MARKETPLACE, IsAmazonFulfilled=True,
                Identifier=fee['identifier'], PriceToEstimateFees=dict(
                    ListingPrice=dict(CurrencyCode='USD', Amount=float(price)),
                    Shipping=dict(CurrencyCode='USD', Amount=float(Decimal(fee['buyer_shipping']))))))
            def fee_parser(data):
                parsed = parse_fees(data, context, price, fee['identifier'], is_mock=is_mock,
                    expected_asin=asin, buyer_shipping=Decimal(fee['buyer_shipping']), fulfillment=fee['fulfillment'])
                parsed['quote']['value']['context']['seller_id'] = '[hidden authorized seller]'
                return parsed
            stage(row, 'fees', pilot.amazon_request(access, fee['path'], body=body), fee_parser)
        outcomes = [row[k]['status'] for row in report['rows'] for k in ('pricing','fees','restrictions')]
        report['status'] = 'succeeded' if all(s == 'succeeded' for s in outcomes) else 'partial'
    except (Exception, KeyboardInterrupt) as error:
        report.update(status='stopped_no_retry', failure=failure_metadata(error))
        for row in report['rows']:
            for name in ('pricing','fees','restrictions'):
                if row[name]['status'] == 'attempted':
                    row[name].update(status='interrupted', data=None)
    finally:
        if previous is not None:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        checkpoint()
        output.close()
        os.close(directory)
    return normalized(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan','run'))
    parser.add_argument('--saved-report', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--fee-prices', type=Path, help='Offline ASIN to fixed hypothetical USD price JSON')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.action == 'plan':
        if args.execute:
            parser.error('--execute is only valid for run')
        manifest = plan(args.saved_report, fixed_fee_prices=json.loads(args.fee_prices.read_text()) if args.fee_prices else None)
        with args.manifest.open('x') as output:
            output.write(json.dumps(manifest, indent=2)+'\n')
        print(json.dumps(manifest['budget']))
        return 0
    if not args.execute or args.fee_prices:
        parser.error('run requires --execute and uses only the reviewed manifest scenarios')
    try:
        report = execute(args.saved_report, json.loads(args.manifest.read_text()))
        print(json.dumps(dict(status=report['status'], attempts=len(report['attempts']), purchase_approved=False)))
        return 0 if report['status'] == 'succeeded' else 1
    except (Exception, KeyboardInterrupt):
        print('Enrichment stopped; no retry. Existing private reports remain preserved.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
