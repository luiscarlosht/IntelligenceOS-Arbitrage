"""Offline Amazon-first contracts; no credentials, network or production selector."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
import argparse
import json
import os
from pathlib import Path

from app.keepa_adapter import ASIN, US_MARKETPLACE, history_point, keepa_time
from app.observations import ObservationStore, canonical, fingerprint, normalized
from app.profitability import COST_FIELDS, analyze
from app.marketplace import match_listings
from app.discovery import screen
from app.normalization import identity

TARGET_TAB_FIELDS = ('target_id', 'revision', 'schema_version', 'target_json')
JOB_TAB_FIELDS = ('job_id', 'target_id', 'target_revision', 'retailer', 'location',
                  'query_version', 'schema_version', 'job_json')
OUTCOME_TAB_FIELDS = ('event_id', 'job_id', 'target_id', 'outcome', 'query',
                      'observed_at', 'evidence_reference', 'elapsed_seconds', 'cost_usd',
                      'intake_record_id', 'browser_claim_json')


def select_discovery_asins(payload, *, exclude_asin):
    """Bounded offline Finder-response adapter; no implicit page/detail requests."""
    if not isinstance(payload, dict) or payload.get('error'):
        raise ValueError('Successful Finder response required')
    values = payload.get('asinList')
    if not isinstance(values, list) or len(values) > 50:
        raise ValueError('One minimum Finder page required')
    if any(not isinstance(v, str) or not ASIN.fullmatch(v) for v in values):
        raise ValueError('Invalid ASIN')
    return list(dict.fromkeys(v for v in values if v != exclude_asin))[:10]


def sheets_export(targets, jobs):
    """Proposed separate tabs only; values must later be written as RAW plain text."""
    return dict(schema_version=1, write_mode='RAW; all cells literal text', tabs={
        'Amazon_Targets': dict(owner='application producer; immutable revisions', fields=TARGET_TAB_FIELDS,
            rows=[[t.target_id, fingerprint(t), '1', canonical(t)] for t in targets]),
        'Amazon_Search_Jobs': dict(owner='application producer; browser reads only', fields=JOB_TAB_FIELDS,
            rows=[[str(job[k]) if k != 'job_json' else canonical(job) for k in JOB_TAB_FIELDS] for job in jobs]),
        'Amazon_Search_Outcomes': dict(owner='browser producer; append-only; application reads only',
            fields=OUTCOME_TAB_FIELDS, rows=[])})


def aware(stamp):
    if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
        raise ValueError('Aware timestamp required')


@dataclass(frozen=True)
class Identifier:
    kind: str
    value: str
    provenance: str
    observed_at: datetime
    status: str = 'uncertain'

    def __post_init__(self):
        aware(self.observed_at)
        if self.kind not in ('UPC', 'EAN', 'GTIN', 'MODEL') or not self.value or not self.provenance:
            raise ValueError('Identifier value/type/provenance required')
        if self.status not in ('uncertain', 'verified', 'conflicting'):
            raise ValueError('Invalid identifier status')


@dataclass(frozen=True)
class AmazonTarget:
    asin: str
    created_at: datetime
    observed_at: datetime | None
    fetched_at: datetime
    provenance: str
    brand: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    title: str | None = None
    identifiers: tuple[Identifier, ...] = ()
    exact_package_evidence: dict = field(default_factory=dict)
    historical_metrics: dict = field(default_factory=dict)
    current_price_context: dict = field(default_factory=dict)
    seller_restrictions: dict = field(default_factory=lambda: {'eligible': None})
    fee_assumptions: dict = field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    marketplace: str = US_MARKETPLACE
    schema_version: int = 1

    def __post_init__(self):
        if not ASIN.fullmatch(self.asin) or self.marketplace != US_MARKETPLACE or not self.provenance:
            raise ValueError('Explicit US ASIN and provenance required')
        for stamp in (self.created_at, self.fetched_at):
            aware(stamp)
        if self.observed_at:
            aware(self.observed_at)
            if self.observed_at > self.fetched_at:
                raise ValueError('Future evidence')
        if self.schema_version != 1:
            raise ValueError('Unknown target schema')

    @property
    def target_id(self):
        return f'amazon:{self.marketplace}:{self.asin}'


def acquisition_ceiling(target, minimum_profit=Decimal('5'), minimum_roi=Decimal('50')):
    """Reuse economics only for explicit USD proposed resale/cost assumptions."""
    assumptions = target.fee_assumptions
    if not assumptions.get('provenance') or not assumptions.get('observed_at') or assumptions.get('currency') != 'USD':
        return None
    stamp = assumptions['observed_at']
    if isinstance(stamp, str):
        stamp = datetime.fromisoformat(stamp)
    aware(stamp)
    if stamp > target.fetched_at:
        raise ValueError('Future fee assumptions')
    values = assumptions.get('costs', {})
    if any(values.get(key) is None for key in COST_FIELDS) or assumptions.get('proposed_sale_price') is None:
        return None
    costs = {key: Decimal(str(values[key])) for key in COST_FIELDS}
    result = analyze(Decimal('1'), Decimal(str(assumptions['proposed_sale_price'])), costs,
                     Decimal(str(minimum_roi)), Decimal(str(minimum_profit)))
    return result.maximum_purchase_price.quantize(Decimal('.01'), rounding=ROUND_FLOOR)


def target_from_keepa(row, fetched_at, *, provenance):
    """Normalize an offline product object. Identifier lists never become a selected UPC."""
    aware(fetched_at)
    if type(row.get('domainId')) is not int or row.get('domainId') != 1 or type(row.get('productType')) is not int or row['productType'] != 0:
        raise ValueError('Supported US product object required')
    stamp = keepa_time(row.get('lastUpdate'))
    if stamp is None or stamp > fetched_at:
        raise ValueError('Valid product observation time required')
    identifiers = []
    for key, kind in (('upcList', 'UPC'), ('eanList', 'EAN'), ('gtinList', 'GTIN')):
        values = row.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
            raise ValueError('Identifier list must preserve nonempty strings')
        identifiers.extend(Identifier(kind, value, provenance + ':' + key, stamp) for value in values)
    histories = row.get('csv', [])
    metrics = {}
    for index, name in ((0, 'amazon_price_usd'), (1, 'new_price_usd'), (3, 'sales_rank')):
        series = histories[index] if isinstance(histories, list) and len(histories) > index else None
        point = history_point(series, fetched_at)
        metrics[name] = None if not point else dict(
            latest=Decimal(point[1]) / 100 if index != 3 else point[1],
            observed_at=point[0], provenance=f'{provenance}:csv[{index}]',
            history=series, interpretation='historical price' if index != 3 else 'rank signal; not verified sales')
    metrics['monthly_sold'] = dict(value=row.get('monthlySold'),
        observed_at=keepa_time(row.get('lastSoldUpdate')),
        interpretation='provider lower-bound demand signal; not verified sales')
    stats = row.get('stats')
    if isinstance(stats, dict):
        metrics['statistics'] = dict(
            values={k: stats.get(k) for k in ('current', 'avg90', 'minInInterval', 'maxInInterval',
                                             'salesRankDrops90', 'totalOfferCount')},
            provenance=provenance + ':stats', observed_at=stamp,
            interpretation='cached price/rank/offer statistics; rank drops are not verified sales')
    package = {key: dict(value=row.get(key), provenance=provenance + ':' + key,
                        observed_at=stamp, status='uncertain')
               for key in ('size', 'color', 'model', 'packageQuantity', 'numberOfItems', 'unitCount')}
    missing = ['seller_restrictions', 'fees', 'current_executable_sale_price', 'exact_retail_pack_verification']
    for key in ('brand', 'manufacturer', 'model', 'size', 'packageQuantity'):
        if row.get(key) is None or row.get(key) == '':
            missing.append(key)
    if not identifiers:
        missing.append('identifiers')
    return AmazonTarget(row['asin'], fetched_at, stamp, fetched_at, provenance,
        brand=row.get('brand'), manufacturer=row.get('manufacturer'), model=row.get('model'),
        title=row.get('title'), identifiers=tuple(identifiers), exact_package_evidence=package,
        historical_metrics=metrics, current_price_context=dict(
            executable_sale_price=None, availability=None, reason='history does not establish current offer'),
        missing_fields=tuple(missing))


def pilot_plan(asin):
    if not ASIN.fullmatch(asin):
        raise ValueError('Invalid ASIN')
    product_options = dict(domain=1, update=-1, history=1, days=90, stats=90)
    return dict(schema_version=1, live_execution_available=False, actual_requests=0,
        broad_walmart_campaign_preparation='PAUSED; existing operations preserved',
        connectivity=dict(method='GET', endpoint='https://api.keepa.com/product',
                          options=dict(product_options, asin=asin), maximum_requests=1, documented_tokens=1),
        discovery=dict(method='POST', endpoint='https://api.keepa.com/query', options={'domain': 1},
            selection=dict(page=0, perPage=50, productType=0, title='kitchen',
                current_NEW_gte=2000, current_NEW_lte=6000, avg90_SALES_gte=1,
                avg90_SALES_lte=100000, sort=[['current_SALES', 'asc']]),
            maximum_requests=1, documented_token_reservation=11,
            maximum_returned_asins=50, maximum_selected_targets=10),
        hydration=dict(method='GET', endpoint='https://api.keepa.com/product', options=product_options,
            selection='first ten distinct valid ASINs in Finder order; exclude connectivity ASIN',
            maximum_requests=10, documented_tokens=10),
        maximum_requests=12, documented_total_token_reservation=22,
        hard_vendor_billing_ceiling_guaranteed=False,
        warning='Local request cap is enforceable; vendor billing is not. Finder charges per returned '
                '100 ASINs; reserve 11 for the minimum page of 50. Confirm tariff/rounding before execution. '
                'No retries, pagination, refill waits, offers, buybox, stock, rating or Finder stats.',
        authentication='future private TTY read_pilot_key; key query parameter omitted from reports',
        output_schema=dict(target='AmazonTarget v1', job='AmazonSearchJob v1',
                           usage=['tokensConsumed', 'tokensLeft', 'refillIn', 'refillRate', 'request_count']))


def browser_jobs(targets, *, query_version='v1', minimum_profit=Decimal('5'), minimum_roi=Decimal('50')):
    if not 1 <= len(targets) <= 10 or len({t.target_id for t in targets}) != len(targets):
        raise ValueError('One to ten distinct targets required')
    if not query_version or len(query_version) > 64:
        raise ValueError('Explicit bounded query version required')
    jobs = []
    for target in targets:
        queries = [dict(query=i.value, basis=i.kind, status=i.status, provenance=i.provenance)
                   for i in target.identifiers]
        if target.model:
            queries.append(dict(query=' '.join(filter(None, (target.brand, target.model))), basis='model'))
        if target.brand and target.title:
            queries.append(dict(query=target.brand + ' ' + target.title, basis='wording_fallback'))
        identity = dict(target_id=target.target_id, retailer='Walmart', location='76063', query_version=query_version)
        jobs.append(dict(schema_version=1, job_id='search:' + fingerprint(identity), **identity,
            target_revision=fingerprint(target), asin=target.asin,
            amazon_url='https://www.amazon.com/dp/' + target.asin,
            identifiers=normalized(target.identifiers), required_brand=target.brand,
            required_manufacturer=target.manufacturer, required_model=target.model,
            required_package=normalized(target.exact_package_evidence), queries=queries,
            acquisition_price_ceiling_usd=normalized(acquisition_ceiling(target, minimum_profit, minimum_roi)),
            fields_needing_verification=list(target.missing_fields), status='prepared' if queries else 'unresolved',
            refresh_rule='Never auto-repeat; new version plus explicit reason and prior job ID required',
            browser_match_claim=None, application_verified_exact=False))
    return jobs


class TargetStore(ObservationStore):
    """Additive, append-only contracts beside existing history/observations, not replacements."""
    def __init__(self, path):
        super().__init__(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS amazon_target_versions (target_id TEXT, revision TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS amazon_search_jobs (job_id TEXT PRIMARY KEY, target_id TEXT NOT NULL, revision TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS amazon_search_events (event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS amazon_search_evaluations (evaluation_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, source_observation_id INTEGER NOT NULL, payload TEXT NOT NULL)')

    def save_target(self, target):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO amazon_target_versions VALUES (?, ?, ?)',
                       (target.target_id, fingerprint(target), canonical(target)))

    def save_job(self, job, *, prior_job_id=None, refresh_reason=None):
        identity = {k: job[k] for k in ('target_id', 'retailer', 'location', 'query_version')}
        if (job['job_id'] != 'search:' + fingerprint(identity) or job['schema_version'] != 1
                or job['retailer'] != 'Walmart' or job['location'] != '76063'):
            raise ValueError('Invalid durable job identity')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT payload FROM amazon_search_jobs WHERE job_id=?', (job['job_id'],)).fetchone()
            if existing:
                if existing[0] != canonical(job):
                    raise ValueError('Immutable job changed; explicit refresh required')
                return False
            previous = db.execute('SELECT job_id FROM amazon_search_jobs WHERE target_id=?', (job['target_id'],)).fetchall()
            if previous and (prior_job_id not in [r[0] for r in previous] or not refresh_reason or not refresh_reason.strip()):
                raise ValueError('Refresh requires prior job and reason')
            revision = db.execute('SELECT 1 FROM amazon_target_versions WHERE target_id=? AND revision=?',
                                  (job['target_id'], job['target_revision'])).fetchone()
            if not revision:
                raise ValueError('Persist target revision first')
            db.execute('INSERT INTO amazon_search_jobs VALUES (?, ?, ?, ?)',
                       (job['job_id'], job['target_id'], job['target_revision'], canonical(job)))
            if previous:
                self._event(db, job['job_id'], dict(outcome='refresh', prior_job_id=prior_job_id, reason=refresh_reason))
            return True

    def _event(self, db, job_id, payload):
        db.execute('INSERT OR IGNORE INTO amazon_search_events VALUES (?, ?, ?)',
                   (fingerprint([job_id, payload]), job_id, canonical(payload)))

    def record_outcome(self, job_id, *, outcome, observed_at, query, evidence_reference,
                       elapsed_seconds, cost_usd=None, source_observation_id=None):
        if outcome not in ('no_result', 'mismatch', 'unavailable', 'unresolved', 'matched'):
            raise ValueError('Invalid outcome')
        aware(observed_at)
        if not query or not evidence_reference or elapsed_seconds is None:
            raise ValueError('Query and evidence reference required')
        for value in (elapsed_seconds, cost_usd):
            if value is not None and (not Decimal(str(value)).is_finite() or Decimal(str(value)) < 0):
                raise ValueError('Invalid measurement')
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM amazon_search_jobs WHERE job_id=?', (job_id,)).fetchone():
                raise ValueError('Unknown job')
            if source_observation_id is not None and not db.execute(
                    'SELECT 1 FROM source_observations WHERE id=?', (source_observation_id,)).fetchone():
                raise ValueError('Unknown source observation')
            self._event(db, job_id, dict(outcome=outcome, observed_at=observed_at, query=query,
                evidence_reference=evidence_reference, elapsed_seconds=elapsed_seconds, cost_usd=cost_usd,
                source_observation_id=source_observation_id, browser_match_claim=outcome == 'matched',
                application_verified_exact=False))

    def evaluate(self, target, job, source_observation_id, product, listing, config, now):
        with self.connect() as db:
            saved = db.execute('SELECT payload FROM amazon_search_jobs WHERE job_id=?', (job['job_id'],)).fetchone()
            if not saved or saved[0] != canonical(job):
                raise ValueError('Persist immutable job first')
            source = db.execute('SELECT payload_json FROM source_observations WHERE id=?', (source_observation_id,)).fetchone()
            if not source or source[0] != canonical(product):
                raise ValueError('Observation does not match saved product')
            row = verify_observation(target, job, product, listing, config, now)
            db.execute('INSERT OR IGNORE INTO amazon_search_evaluations VALUES (?, ?, ?, ?)',
                       (fingerprint([job['job_id'], source_observation_id, row, now]), job['job_id'],
                        source_observation_id, canonical(row)))
        return row

    def metrics(self):
        with self.connect() as db:
            events = [json.loads(r[0]) for r in db.execute('SELECT payload FROM amazon_search_events')]
            evaluations = [(job_id, json.loads(payload)) for job_id, payload in db.execute(
                'SELECT job_id, payload FROM amazon_search_evaluations')]
        searches = [e for e in events if e['outcome'] != 'refresh']
        exact = {job_id for job_id, row in evaluations if row['application_verified_exact']}
        profitable = {job_id for job_id, row in evaluations if row['verified_profitable']}
        total = len(searches)
        complete = all(e['cost_usd'] is not None for e in searches) if total else False
        known_cost = sum((Decimal(str(e['cost_usd'])) for e in searches if e['cost_usd'] is not None), Decimal('0'))
        return dict(retailer='Walmart', location='76063', query_attempts=total,
            exact_match_jobs=len(exact), profitable_match_jobs=len(profitable),
            exact_matches_per_search=len(exact) / total if total else None,
            profitable_matches_per_search=len(profitable) / total if total else None,
            elapsed_seconds=sum(Decimal(str(e['elapsed_seconds'])) for e in searches),
            known_cost_usd=known_cost, total_cost_usd=known_cost if complete else None,
            cost_complete=complete,
            outcomes={name: sum(e['outcome'] == name for e in searches)
                      for name in ('no_result', 'mismatch', 'unavailable', 'unresolved', 'matched')})


def verify_observation(target, job, product, listing, config, now):
    """Independent supplied evidence only; browser claims never set matching/eligibility."""
    if job['target_id'] != target.target_id or job['target_revision'] != fingerprint(target) or listing.asin != target.asin:
        raise ValueError('Target/job/listing lineage mismatch')
    if product.retailer.casefold() != job['retailer'].casefold():
        raise ValueError('Retailer mismatch')
    match = match_listings(product, (listing,))
    reasons = []
    source_context = getattr(product, 'source_context', {})
    if target.brand and identity(source_context.get('brand') or '') != identity(target.brand):
        reasons.append('Target brand missing or mismatched in source evidence')
    if source_context.get('observed_zip') != job['location']:
        reasons.append('Source location missing or mismatched')
    for key in ('manufacturer', 'model'):
        expected = getattr(target, key)
        if expected and identity(expected) != identity(getattr(listing, key)):
            reasons.append('Target ' + key + ' missing or mismatched')
    package = target.exact_package_evidence
    quantity = package.get('packageQuantity', {}).get('value')
    if quantity is not None and quantity != listing.package_quantity:
        reasons.append('Target retail pack mismatch')
    for key in ('size', 'color'):
        expected = package.get(key, {}).get('value')
        if expected and identity(str(expected)) not in identity(listing.variation):
            reasons.append('Target ' + key + ' not supported by supplied variation')
    if reasons:
        from dataclasses import replace
        match = replace(match, exact=False, confidence=Decimal('0'), reasons=match.reasons + tuple(reasons))
    row = screen(product, match, config, now)
    # Existing engine treats declared unverified costs as estimates. This pilot
    # requires verified costs before its verified-profitability label.
    supported = match.exact and row['status'] == 'REVIEW' and not row['unverified_costs'] and not listing.is_mock
    if row['status'] == 'REVIEW' and not supported:
        reason = 'Amazon-first verified profitability requires verified costs and non-mock evidence'
        row.update(status='REJECT', reason=reason, ranking_score=0, budget_units=0,
                   rejection_reasons=row['rejection_reasons'] + [reason],
                   quality_issues=reason)
    return dict(row, target_id=target.target_id, search_job_id=job['job_id'],
                application_verified_exact=match.exact, verified_profitable=supported)


def write_target_report(rows, destination):
    """Existing report writer; preserve job/target lineage in execution metadata."""
    from app.reporting import write_report
    lineage = [{k: row[k] for k in ('target_id', 'search_job_id', 'application_verified_exact',
                                   'verified_profitable')} for row in rows]
    write_report(rows, destination, discovery=True, job={
        'pilot': 'Amazon-first supplied evidence; no purchase approval', 'lineage_json': canonical(lineage)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asin', default='B002XQ1R06')
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--database', type=Path)
    parser.add_argument('--metrics', action='store_true')
    parser.add_argument('--minimum-profit', type=Decimal, default=Decimal(os.environ.get('MINIMUM_PROFIT', '5')))
    parser.add_argument('--minimum-roi', type=Decimal, default=Decimal(os.environ.get('MINIMUM_ROI', '50')))
    args = parser.parse_args()
    if any(not v.is_finite() or v < 0 for v in (args.minimum_profit, args.minimum_roi)):
        parser.error('Finite nonnegative profit/ROI thresholds required')
    if args.metrics:
        if not args.database or args.fixture or not args.database.is_file():
            parser.error('--metrics requires an existing offline --database and no --fixture')
        print(json.dumps(normalized(TargetStore(args.database).metrics()), indent=2))
        return
    output = {'plan': pilot_plan(args.asin)}
    if args.fixture:
        fixture = json.loads(args.fixture.read_text())
        stamp = datetime.fromisoformat(fixture['fetched_at'])
        targets = [target_from_keepa(row, stamp, provenance='OFFLINE illustrative fixture') for row in fixture['products']]
        jobs = browser_jobs(targets, minimum_profit=args.minimum_profit, minimum_roi=args.minimum_roi)
        if args.database:
            store = TargetStore(args.database)
            for target, job in zip(targets, jobs):
                store.save_target(target)
                store.save_job(job)
        output.update(targets=[dict(normalized(t), target_id=t.target_id) for t in targets], jobs=jobs,
                      sheets_handoff=sheets_export(targets, jobs))
    elif args.database:
        parser.error('--database requires --fixture')
    print(json.dumps(normalized(output), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
