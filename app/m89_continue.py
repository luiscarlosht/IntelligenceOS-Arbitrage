"""Bounded M89 research continuation; no commerce mutations or automatic retries."""
import argparse
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import os
from pathlib import Path
import re
import signal
import time
from urllib.parse import urlencode
from urllib.request import Request

from app import amazon_pilot as pilot
from app.amazon_details import parse_fees, parse_restrictions
from app.amazon_diagnostics import failure_metadata
from app.amazon_pacing import OperationPacer
from app.evidence_io import publication, digest
from app.m80_execution import scrub
from app.m88 import implementation, offer_result, readiness, Stop
from app.m88_state import Journal, ledger, lock, read, sha, stamp, write
from app.m88_targeted_state import prefix_sha
from app.m89 import LEDGER
from app.product_analysis import comparison, workbook
from app.provider_contracts import SellerContext

ASIN = 'B001BE12BA'
US = 'ATVPDKIKX0DER'
PHASES = ('authentication', 'restrictions', 'offers', 'fees_FBA', 'fees_FBM')
CLAIM = 'm89_walmart_research'


def reconcile(research: dict, baseline: dict) -> list[dict]:
    """Amazon identifiers come only from independently authenticated saved receipts."""
    if research.get('purchase_authorized') is not False:
        raise ValueError('Research must prohibit purchasing')
    rows = []
    for item in research['candidates']:
        lead = next(r for r in baseline['candidates'] if r['asin'] == item['asin'])
        amazon = lead['amazon_evidence']
        upcs = {v['value'] for v in amazon['identifiers'] if v['identifier_type'] == 'UPC'}
        match = item['walmart_upc'] in upcs
        supported = (item['asin'] == ASIN and match and amazon['model'] == item['walmart_model'] == '600K3'
                     and amazon['size'] == '3 Rolls' and amazon['brand'] == 'Scotch'
                     and item['walmart_item_id'] == '21014274'
                     and item.get('retail_pack', '').startswith('3 boxes, one roll per box;'))
        rows.append(dict(asin=item['asin'], walmart=item, amazon=amazon,
            classification='SUPPORTED_MATCH_WITH_SPEC_CAVEAT' if supported else 'NEEDS_REVIEW',
            upc_match=match, verified_exact_match=False,
            unresolved=(['Walmart inconsistent 2.625 inch dimensions', 'Walmart core size UNKNOWN; Amazon title says 1 inch',
                         'Referenced screenshot/HTML binaries not imported', 'Independent human signoff absent']
                        if supported else ['UPC_CONFLICT' if not match else 'Identity requires review'])))
    if len(rows) != 3 or len({r['asin'] for r in rows}) != 3 or {r['asin'] for r in rows} != {ASIN, 'B003SI0TD4', 'B0006BAFKI'}:
        raise ValueError('Exactly the three authorized research candidates required')
    if next(r for r in rows if r['asin'] == ASIN)['classification'] != 'SUPPORTED_MATCH_WITH_SPEC_CAVEAT':
        raise ValueError('Priority Catalog/source identity unsupported')
    return rows


def prepare(root: Path, baseline_path: Path, research_path: Path, private: Path, output: Path) -> dict:
    baseline = read(baseline_path)
    if baseline.get('schema') != 'm89-amazon-first-offline-v1' or baseline.get('cumulative_attempts') != 11:
        raise ValueError('Verified M89 baseline required')
    for path, expected in baseline['source_inventory'].items():
        if digest(Path(path)) != expected:
            raise ValueError('Saved evidence drift')
    path = (root / LEDGER).resolve()
    data = ledger(path)
    if data['attempts_used'] != 11 or any(a['status'] != 'COMPLETE' for a in data['attempts']) or CLAIM in data:
        raise PermissionError('Completed 11/49 baseline and unused M89 claim required')
    rows = reconcile(read(research_path), baseline)
    account = private / 'm67-account-context.json'
    plan = dict(schema='m89-read-only-v1', starting_commit='b6cbeb9', asin=ASIN,
        ledger_path=str(path), baseline_sha256=sha(path), prefix_sha256=prefix_sha(data['attempts']),
        baseline_path=str(baseline_path.resolve()), research_path=str(research_path.resolve()),
        baseline_report_sha256=sha(baseline_path), research_sha256=sha(research_path),
        private_root=str(private.resolve()), account_sha256=sha(account), credential_readiness=readiness(private),
        implementation_sha256=implementation(), maximum_new_attempts=5, cumulative_ceiling=49,
        phases=list(PHASES), retries=0, refreshes=0, catalog_calls=0, purchase_authorized=False,
        fee_gate='Single supported New buy-box price, explicit zero buyer shipping, bound seller; estimates only',
        identity_gate='Saved authenticated Catalog identity supports research; strict match remains unresolved for Walmart specs',
        rows=rows)
    with publication(output, [root, research_path, baseline_path]) as stage:
        write(stage / 'plan.json', plan)
    return plan


class ResearchJournal(Journal):
    def __init__(self, path: Path, digest: str, plan: dict):
        super().__init__(path, digest)
        self.plan = plan

    def history(self):
        data = ledger(self.path)
        if prefix_sha(data['attempts'][:11]) != self.plan['prefix_sha256']:
            raise ValueError('Original eleven attempts changed')
        return data

    def start(self):
        data = self.history()
        if data['attempts_used'] != 11 or CLAIM in data or sha(self.path) != self.plan['baseline_sha256']:
            raise PermissionError('M89 already claimed or ledger advanced; report-only recovery')

    def reserve(self, phase, candidate_id):
        data = self.history()
        own = data['attempts'][11:]
        if (phase not in PHASES or candidate_id != (None if phase == 'authentication' else ASIN)
                or data.get(CLAIM) not in (None, self.plan_sha)
                or len(own) >= 5 or data['attempts_used'] >= 49
                or any(a.get('plan_sha256') != self.plan_sha or a['status'] != 'COMPLETE' for a in own)
                or any(a['phase'] == phase for a in own)
                or (phase != 'authentication' and not own)
                or (phase.startswith('fees_') and not any(a['phase'] == 'offers' for a in own))):
            raise PermissionError('Invalid phase, replay, missing prerequisite or exhausted budget')
        number = data['attempts_used'] + 1
        data[CLAIM] = self.plan_sha
        data['attempts_used'] = number
        data['attempts'].append(dict(number=number, phase=phase, candidate_id=candidate_id,
            plan_sha256=self.plan_sha, status='RESERVED', reserved_at=stamp()))
        write(self.path, data, replace=True)
        return number


def check(plan):
    if (plan['schema'] != 'm89-read-only-v1' or plan['asin'] != ASIN or plan['phases'] != list(PHASES)
            or plan['maximum_new_attempts'] != 5 or plan['cumulative_ceiling'] != 49
            or any(plan[k] != 0 for k in ('retries', 'refreshes', 'catalog_calls'))
            or plan['purchase_authorized'] is not False or plan['implementation_sha256'] != implementation()):
        raise ValueError('Frozen M89 contract/code required')
    baseline = read(Path(plan['baseline_path']))
    if sha(Path(plan['baseline_path'])) != plan['baseline_report_sha256'] or sha(Path(plan['research_path'])) != plan['research_sha256']:
        raise ValueError('M89 source drift')
    for path, expected in baseline['source_inventory'].items():
        if path != plan['ledger_path'] and digest(Path(path)) != expected:
            raise ValueError('Prior evidence drift')
    research = read(Path(plan['research_path']))
    if reconcile(research, baseline) != plan['rows']:
        raise ValueError('Identity projection drift')
    for row in plan['rows']:
        for at in (row['walmart']['observed_utc'], row['amazon']['observed_at']):
            age = datetime.now(timezone.utc) - datetime.fromisoformat(at.replace('Z', '+00:00'))
            if not timedelta(0) <= age <= timedelta(hours=24):
                raise ValueError('Fresh source and Catalog evidence required')
    private = Path(plan['private_root'])
    if readiness(private) != plan['credential_readiness'] or sha(private / 'm67-account-context.json') != plan['account_sha256']:
        raise ValueError('Private account metadata drift')


def execute(path: Path, expected: str, *, transport=pilot._request_json):
    if sha(path) != expected:
        raise ValueError('Pinned plan required')
    plan = read(path)
    check(plan)
    private = Path(plan['private_root'])
    journal = ResearchJournal(Path(plan['ledger_path']), expected, plan)
    with lock(private / 'candidate-execution.lock'), lock(Path(plan['ledger_path']).with_suffix('.lock')):
        journal.start()
        account = read(private / 'm67-account-context.json')
        seller = account.get('seller_id')
        if (account.get('credentials_sha256') != sha(private / 'credentials.json')
                or account.get('marketplace_id') != US or account.get('condition') != 'new_new'
                or not isinstance(seller, str) or not re.fullmatch('[A-Z0-9]{1,32}', seller)):
            raise ValueError('Bound research seller context required')
        context = SellerContext(seller, US)
        credentials = {}
        token = None
        expires = time.monotonic() + 120
        pacer = OperationPacer(headroom=.5)
        previous = signal.signal(signal.SIGALRM, pilot.deadline)
        signal.alarm(120)

        def call(phase, request, parser):
            check(plan)
            if time.monotonic() >= expires:
                raise TimeoutError('M89 deadline')
            number = journal.reserve(phase, None if phase == 'authentication' else ASIN)
            try:
                doc = pacer.call(request, transport, deadline=expires)
                value = parser(doc)
                evidence = scrub(value, set(credentials.values()) | {seller} | ({token} if token else set()))
                write(path.parent / f'receipt-{number}.json', dict(number=number, phase=phase,
                    candidate_id=None if phase == 'authentication' else ASIN, observed_at=stamp(), evidence=evidence))
                journal.finish(number, 'COMPLETE', receipt_sha256=sha(path.parent / f'receipt-{number}.json'))
                return value
            except BaseException as error:
                journal.finish(number, 'FAILED', failure=failure_metadata(error))
                raise

        try:
            directory = os.open(private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                credentials = pilot.load_credentials(directory)
            finally:
                os.close(directory)

            def auth(doc):
                nonlocal token, expires
                access, seconds = doc.get('access_token'), doc.get('expires_in')
                if (str(doc.get('token_type', '')).lower() != 'bearer' or not isinstance(access, str)
                        or not 1 <= len(access) <= 2048 or not access.isascii()
                        or any(c.isspace() or not c.isprintable() for c in access)
                        or type(seconds) is not int or seconds <= 10):
                    raise ValueError('Invalid authentication response')
                token = access
                expires = min(expires, time.monotonic() + seconds - 10)
                return dict(token_received=True)

            call('authentication', Request('https://api.amazon.com/auth/o2/token',
                data=urlencode(dict(grant_type='refresh_token', **credentials)).encode(),
                headers={'Content-Type': 'application/x-www-form-urlencoded'}), auth)
            call('restrictions', pilot.amazon_request(token, '/listings/2021-08-01/restrictions',
                dict(asin=ASIN, sellerId=seller, marketplaceIds=US, conditionType='new_new', reasonLocale='en_US')),
                lambda doc: parse_restrictions(doc, context, is_mock=False))
            offers = call('offers', pilot.amazon_request(token, '/products/pricing/v0/items/' + ASIN + '/offers',
                dict(MarketplaceId=US, ItemCondition='New', CustomerType='Consumer')), lambda doc: offer_result(doc, ASIN))
            price = offers['fee_price']
            if price is not None:
                for mode in ('FBA', 'FBM'):
                    identifier = 'm89:' + ASIN + ':' + mode + ':base'
                    body = {'FeesEstimateRequest': dict(MarketplaceId=US, IsAmazonFulfilled=mode == 'FBA', Identifier=identifier,
                        PriceToEstimateFees=dict(ListingPrice=dict(CurrencyCode='USD', Amount=price),
                                                 Shipping=dict(CurrencyCode='USD', Amount='0')))}
                    call('fees_' + mode, pilot.amazon_request(token, '/products/fees/v0/items/' + ASIN + '/feesEstimate', body=body),
                        lambda doc: parse_fees(doc, context, Decimal(price), identifier, is_mock=False, expected_asin=ASIN, fulfillment=mode))
            write(path.parent / 'execution-status.json', dict(status='COMPLETE', fee_price=price, purchase_authorized=False))
        except BaseException:
            write(path.parent / 'execution-status.json', dict(status='STOPPED_NO_RETRY', purchase_authorized=False))
            raise Stop('M89 stopped; report-only recovery') from None
        finally:
            credentials.clear()
            token = None
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)


def report(path: Path, expected: str, output: Path):
    if sha(path) != expected:
        raise ValueError('Pinned plan required')
    plan = read(path)
    if (sha(Path(plan['research_path'])) != plan['research_sha256']
            or sha(Path(plan['baseline_path'])) != plan['baseline_report_sha256']):
        raise ValueError('Pinned research/baseline drift; recovery cannot invent evidence')
    data = ResearchJournal(Path(plan['ledger_path']), expected, plan).history()
    receipts = {}
    for attempt in data['attempts'][11:]:
        if attempt['plan_sha256'] != expected:
            raise ValueError('Unrelated continuation')
        if attempt['status'] == 'COMPLETE':
            receipt_path = path.parent / f"receipt-{attempt['number']}.json"
            if sha(receipt_path) != attempt['receipt_sha256']:
                raise ValueError('Receipt drift')
            receipt = read(receipt_path)
            if any(receipt[k] != attempt[k] for k in ('number', 'phase', 'candidate_id')):
                raise ValueError('Receipt binding mismatch')
            receipts[attempt['phase']] = receipt
    candidates = []
    for row in plan['rows']:
        w = row['walmart']
        retailer = dict(title=w['product'], walmart_item_id=w['walmart_item_id'], url=w['walmart_url'],
            gtin=w['walmart_upc'], model=w['walmart_model'], observed_at=w['observed_utc'],
            source_reference='Drive 1ShxyCyLb4PcCa1TUct7SBHTT2d1qkpV7; ' + plan['research_sha256'],
            confidence='MEDIUM', verified=False, pack_description=w['retail_pack'], core_size=w.get('walmart_core_size', 'UNKNOWN'))
        obs = dict(value=str(w['walmart_price_usd']), observed_at=w['observed_utc'], source='Imported Walmart research',
            source_reference=retailer['source_reference'], confidence='MEDIUM', verified=True, assumed=False)
        record = dict(candidate_id='m89:' + row['asin'], asin=row['asin'],
            identity=dict(amazon_product=row['amazon'], retailer_product=retailer),
            input_conflicts=row['unresolved'], research_reconciliation=row,
            financials={m: {'base': {'purchase': obs}} for m in ('FBA', 'FBM')},
            eligibility=dict(status='UNKNOWN'), api_evidence=receipts if row['asin'] == ASIN else {})
        candidates.append(record)
    now = datetime.now(timezone.utc)
    manifest = dict(schema='walmart_product_analysis_input_v1', expected_candidates=3, candidates=candidates,
        source_inventory=[dict(path=plan['research_path'], sha256=plan['research_sha256']),
                          dict(path=str(path), sha256=expected), dict(path=plan['ledger_path'], sha256=sha(Path(plan['ledger_path'])))])
    financial = comparison(manifest, now)
    restrictions = receipts.get('restrictions', {}).get('evidence')
    permission = ('UNKNOWN' if restrictions is None else 'NO_REPORTED_RESTRICTIONS' if restrictions['restriction_count'] == 0
                  else 'APPROVAL_REQUIRED' if restrictions['approval_required'] else 'RESTRICTED')
    audit = dict(additional_amazon_http_attempts=data['attempts_used'] - 11, cumulative_attempts=data['attempts_used'],
        remaining_attempts=49-data['attempts_used'], ceiling=49, attempts=data['attempts'][11:],
        listing_permission=permission, fulfillment_eligibility='UNKNOWN', receipts=receipts, purchase_authorized=False)
    financial['amazon_research'] = audit
    with publication(output, [path, Path(plan['research_path']), Path(plan['ledger_path'])]) as stage:
        write(stage / 'comparison.json', financial)
        workbook(financial, stage / 'comparison.xlsx')
        write(stage / 'missing-data-report.json', dict(records=[dict(asin=r['asin'], missing=r['missing_information']) for r in financial['records']],
            reconciliation=plan['rows'], amazon_research=audit, purchase_authorized=False))
        write(stage / 'execution-report.json', audit)
        summary = (f"# M89 research continuation\n\nB001BE12BA / Walmart 21014274: UPC 021200471797, Scotch model 600K3 and three rolls supported by independently saved Amazon Catalog receipts. "
            "Walmart price $12.34; sold and shipped by Staples Business. Classification SUPPORTED_MATCH_WITH_SPEC_CAVEAT; strict identity unresolved. "
            "Walmart 2.625 inch dimension discrepancy and UNKNOWN core size preserved; Amazon title says 1 inch core. Referenced screenshot/HTML binaries absent; human signoff false.\n\n"
            f"New-condition listing permission: {permission}; FBA/fulfillment eligibility UNKNOWN. "
            f"Amazon attempts: {audit['additional_amazon_http_attempts']} new, {data['attempts_used']}/49 cumulative, {audit['remaining_attempts']} remaining. Authentication, failures and uncertain reservations count; no retries or refreshes.\n\n"
            + ('Authentication FAILED: transport_error, no Amazon HTTP response received. Restrictions, offers and fees NOT_ATTEMPTED.\n\n'
               if any(a['phase'] == 'authentication' and a['status'] == 'FAILED' and a.get('failure', {}).get('reason') == 'transport_error'
                      for a in audit['attempts']) else '') +
            "B003SI0TD4 and B0006BAFKI remain NEEDS_REVIEW: Walmart/Amazon UPC conflicts. No calls for these products.\n\n"
            "M86 FBA/FBM conservative/base/optimistic scenarios: INSUFFICIENT_DATA; net profit UNKNOWN; ROI UNKNOWN. Missing strict identity, source tax/shipping, inbound, prep, packaging, storage, other costs and complete price-bound selling costs. "
            "Market demand/history and Sacramento-specific availability remain unsupported. No inferred zero costs, sale prices or velocity. Targets remain $5 net profit and 50% acquisition ROI.\n\npurchase_authorized=false.\n")
        (stage / 'executive-summary.md').write_text(summary)
        (stage / 'executive-summary.md').chmod(0o600)
    return audit


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    for key in ('root', 'baseline', 'research', 'private', 'output'):
        prep.add_argument('--' + key, type=Path, required=True)
    for name in ('execute', 'report'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--plan', type=Path, required=True)
        cmd.add_argument('--plan-sha256', required=True)
        if name == 'report':
            cmd.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.command == 'prepare':
        prepare(a.root, a.baseline, a.research, a.private, a.output)
        print('Prepared; zero attempts, credential values unread')
    elif a.command == 'execute':
        execute(a.plan, a.plan_sha256)
        print('Read-only operation complete; no retries')
    else:
        audit = report(a.plan, a.plan_sha256, a.output)
        print(f"Amazon attempts {audit['cumulative_attempts']}/49; {audit['remaining_attempts']} remaining")


if __name__ == '__main__':
    main()
