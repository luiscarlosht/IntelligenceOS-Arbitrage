"""Offline source request preparation (ten rows by default, explicit one-row intake). No transport, credential or email access."""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.amazon_details import PricingSnapshot, apply_pricing_gate, proposed_price
from app.amazon_catalog import MARKETPLACE
from app.authorized_imports import validate
from app.config import Config
from app.connectors import CsvConnector
from app.discovery import screen
from app.marketplace import match_listings
from app.models import MarketplaceListing
from app.observations import ObservationStore, fingerprint
from app.provider_contracts import Evidence
from app.reporting import write_report

LABEL = 'OFFLINE AMAZON SOURCE PLAN — requests disabled; no purchase approval'


@dataclass(frozen=True)
class RestrictionCheck:
    asin: str
    seller_reference: str  # Nonsecret local alias, never a seller ID.
    marketplace_id: str
    condition: str
    listing_permitted: bool | None
    reason_codes: tuple[str, ...] = ()


def prepare(source: Path, listings: tuple[MarketplaceListing, ...],
            pricing: dict[str, Evidence[PricingSnapshot]],
            restrictions: dict[str, Evidence[RestrictionCheck]],
            selected_prices: dict[int, str], directory: Path, *, seller_reference: str,
            now: datetime | None = None,
            fba_eligibility: dict[str, Evidence[bool]] | None = None,
            expected_rows: int = 10) -> dict:
    """Persist every CSV ordinal and planned fee scenario using normalized evidence.

    Prices key by 1-based input row; no default, competitor-price substitution or
    live executor exists. Supplied catalog uses the existing deterministic matcher.
    Overall eligibility remains a separate requirement from listing permission.
    """
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None or type(expected_rows) is not int or expected_rows not in (1, 10):
        raise ValueError('Aware clock and explicit one- or ten-row intake required')
    if not seller_reference.strip() and (restrictions or selected_prices or fba_eligibility):
        raise ValueError('Authorized seller alias required for seller-specific evidence or fee planning')
    source, directory = Path(source), Path(directory)
    if source.stat().st_size > 1024 * 1024:
        raise ValueError('Source exceeds one MiB')
    products = list(CsvConnector(source).products())
    if len(products) != expected_rows:
        raise ValueError(f'Exactly {expected_rows} product rows required')
    prices = {}
    for ordinal, value in selected_prices.items():
        if type(ordinal) is not int or not 1 <= ordinal <= expected_rows:
            raise ValueError('Selected price must reference an input row')
        prices[ordinal] = proposed_price(value)
    findings = validate(source, now, maximum_rows=expected_rows)
    if any(issue.startswith('Header') for issue in findings):
        raise ValueError('Authorized CSV header required')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    database, report = directory/'source-plan.sqlite3', directory/'SOURCE-PLAN.xlsx'
    if source.resolve() in (database.resolve(), report.resolve()) or report.is_symlink():
        raise ValueError('Separate regular output paths required')
    config = Config(input=source, output=report, database=database, maximum_candidates=expected_rows)
    store = ObservationStore(database)
    manifest = dict(source_hash=fingerprint(products), catalog_hash=fingerprint(listings),
                    seller_reference=seller_reference, selected_prices=prices, live_requests=0)
    run_id = store.start_run(now, manifest, label=LABEL)
    rows, scenarios = [], []
    try:
        for ordinal, product in enumerate(products, 1):
            match = match_listings(product, listings)
            asin = match.listing.asin if match.listing else ''
            reasons = [issue.split(': ', 1)[-1] for issue in findings if issue.startswith(f'Row {ordinal}:')]
            enrichments = []
            if match.listing:
                listing = match.listing
                reasons.extend(getattr(listing, 'mapping_issues', ()))
                price = pricing.get(asin)
                restriction = restrictions.get(asin)
                fba = (fba_eligibility or {}).get(asin)
                if fba is None or fba.value is not True or not fba.fresh(now, 86400):
                    reasons.append('Missing or unverified FBA eligibility')
                for kind, evidence in (('pricing', price), ('restrictions', restriction), ('fba_eligibility', fba)):
                    if evidence is not None:
                        enrichments.append((asin, kind, evidence, now))
                    if evidence is None or evidence.value is None or not evidence.fresh(now, 86400):
                        reasons.append('Missing or stale ' + kind)
                if price is not None and price.value is not None:
                    if price.value.asin != asin:
                        reasons.append('Pricing ASIN mismatch')
                    elif (price.value.marketplace_id != MARKETPLACE or price.value.condition != 'New'
                          or price.value.customer_type != 'Consumer'):
                        reasons.append('Pricing scope mismatch')
                    else:
                        match = apply_pricing_gate(match, price)
                        if price.value.exclude_from_profitability_ranking:
                            reasons.append('Pricing incomplete or unavailable')
                check = restriction.value if restriction else None
                if check is None or (check.asin, check.seller_reference, check.marketplace_id, check.condition) != (
                        asin, seller_reference, MARKETPLACE, 'new_new'):
                    reasons.append('Restriction scope missing or mismatched')
                elif check.listing_permitted is not True or check.reason_codes:
                    reasons.append('Seller restricted: ' + ', '.join(check.reason_codes or ('permission unknown',)))
                    match = replace(match, listing=replace(match.listing, seller_eligible=False))
                if listing.seller_eligible is not True:
                    reasons.append('Overall seller/FBA eligibility not verified')
                if listing.retrieved_at is None or not 0 <= (now-listing.retrieved_at).total_seconds() <= 86400:
                    reasons.append('Catalog missing or stale')
                if not listing.provenance:
                    reasons.append('Missing catalog provenance')
            else:
                reasons.append('Unmatched product; no pricing/restriction/fee request planned')
            if asin == 'B0G1MJ24B4':
                reasons.append('NOT_ELIGIBLE: retained authorized-seller restriction; sourcing excluded')
            if ordinal not in prices:
                reasons.append('No explicitly selected fee price')
            match = replace(match, reasons=tuple(dict.fromkeys((*match.reasons, *reasons))))
            row = screen(product, match, config, now)
            # Request suitability is separate from profitability, demand and cost
            # completeness: those gates still apply to sourcing recommendations.
            blocked = reasons or not match.exact or product.issues or asin == 'B0G1MJ24B4'
            fee_ready = not blocked
            scenario = dict(ordinal=ordinal, asin=asin, fee_request_planned=fee_ready,
                            listing_price_usd=prices.get(ordinal), buyer_shipping_usd=Decimal('0'),
                            fulfillment='FBA', hypothetical=True, requests_enabled=False,
                            reasons=list(match.reasons) if not fee_ready else [])
            scenarios.append(scenario)
            row.update(input_ordinal=ordinal, fee_request_planned=fee_ready, fee_scenario=scenario)
            enrichments.append((asin, 'fee_request_plan', Evidence(scenario, now, LABEL, False), now))
            store.record_item(run_id, ordinal, product, match, row, enrichments, now,
                              provider='supplied-normalized-catalog')
            rows.append(row)
        fee_count = len({(s['asin'], s['listing_price_usd']) for s in scenarios if s['fee_request_planned']})
        budget = dict(authentication=1, catalog=expected_rows, pricing=expected_rows, restrictions=expected_rows,
                      fees=fee_count, maximum_attempts=1+3*expected_rows+fee_count, absolute_ceiling=1+4*expected_rows,
                      retries=0, live_requests=0, batch_enabled=False)
        write_report(rows, report, discovery=True,
                     job=dict(label=LABEL, run_id=run_id, live_requests=0,
                              phase='Offline preparation; final status in SQLite',
                              maximum_http_attempts=budget['maximum_attempts'], batch_enabled=False),
                     enrichment_rows=[dict(kind='fee_request_plan', asin=s['asin'], value=str(s),
                                           provenance=LABEL) for s in scenarios])
        store.history.finish(run_id, 'succeeded', expected_rows, sum(r['status']=='REVIEW' for r in rows), report)
        return dict(label=LABEL, run_id=run_id, rows=rows, scenarios=scenarios, budget=budget, source_findings=findings)
    except Exception as error:
        store.history.finish(run_id, 'failed', len(rows), 0, error=type(error).__name__)
        raise
