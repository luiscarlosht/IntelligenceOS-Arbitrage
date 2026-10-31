"""Shared Amazon-first contracts ported from PR #43; Keepa deferred; no live selector."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
import json
from pathlib import Path

from app.observations import ObservationStore, canonical, fingerprint, normalized
from app.profitability import COST_FIELDS, analyze
from app.marketplace import match_listings
from app.discovery import screen
from app.normalization import identity
import re
from app.amazon_catalog import MARKETPLACE as US_MARKETPLACE
ASIN = re.compile(r"[A-Z0-9]{10}")

TARGET_TAB_FIELDS = ('target_id', 'revision', 'schema_version', 'target_json')
JOB_TAB_FIELDS = ('job_id', 'target_id', 'target_revision', 'retailer', 'location',
                  'query_version', 'schema_version', 'job_json')
OUTCOME_TAB_FIELDS = ('event_id', 'job_id', 'target_id', 'outcome', 'query',
                      'observed_at', 'evidence_reference', 'elapsed_seconds', 'cost_usd',
                      'intake_record_id', 'browser_claim_json')




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
    for key in ('brand', 'manufacturer', 'model', 'size', 'color', 'style',
                'package_quantity', 'number_of_items', 'unit_count', 'variation'):
        if package.get(key, {}).get('status') == 'conflicting':
            reasons.append('Unresolved target ' + key + ' conflict')
    quantity = package.get('package_quantity', {}).get('value')
    if quantity is not None and quantity != listing.package_quantity:
        reasons.append('Target retail pack mismatch')
    try:
        variation = json.loads(listing.variation)
    except (ValueError, TypeError):
        variation = {}
    if not isinstance(variation, dict):
        variation = {}
    for key in ('size', 'color', 'style'):
        expected = package.get(key, {}).get('value')
        if expected and identity(str(expected)) != identity(str(variation.get(key, ''))):
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
