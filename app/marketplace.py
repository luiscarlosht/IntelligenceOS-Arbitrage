"""Deterministic Amazon matching and explicitly illustrative fixture provider."""
import json
from pathlib import Path
from typing import Protocol
from decimal import Decimal
from app.models import RetailProduct, MarketplaceListing, Match
from app.normalization import gtin, money, integer, timestamp, identity

class AmazonProvider(Protocol):
    def match(self, product: RetailProduct) -> Match: ...


def match_listings(product: RetailProduct, listings: tuple[MarketplaceListing, ...]) -> Match:
    candidates = []
    for listing in listings:
        if product.asin_hint:
            candidate = product.asin_hint.upper() == listing.asin.upper()
        elif product.gtin:
            candidate = product.gtin == listing.gtin
        else:
            candidate = bool(product.manufacturer and product.model and
                identity(product.manufacturer) == identity(listing.manufacturer) and
                identity(product.model) == identity(listing.model))
        if candidate: candidates.append(listing)
    if not candidates: return Match(None, False, Decimal('0'), ('No deterministic marketplace match',))
    if len(candidates) > 1: return Match(None, False, Decimal('0'), ('Ambiguous marketplace matches',))
    listing = candidates[0]
    reasons = []
    gtin_exact = bool(product.gtin and listing.gtin and product.gtin == listing.gtin)
    model_exact = bool(product.manufacturer and product.model and listing.manufacturer and listing.model and
                       identity(product.manufacturer) == identity(listing.manufacturer) and
                       identity(product.model) == identity(listing.model))
    if product.gtin and listing.gtin and not gtin_exact: reasons.append('GTIN mismatch')
    for field in ('manufacturer', 'model'):
        left, right = getattr(product, field), getattr(listing, field)
        if left and right and identity(left) != identity(right): reasons.append(field.title() + ' mismatch')
    if not (gtin_exact or model_exact): reasons.append('ASIN hint alone does not verify product identity')
    if not product.package_quantity or not listing.package_quantity or product.package_quantity != listing.package_quantity:
        reasons.append('Package quantity missing or mismatched')
    if not product.variation or not listing.variation: reasons.append('Variation information missing')
    elif identity(product.variation) != identity(listing.variation): reasons.append('Variation mismatch')
    return Match(listing, not reasons, Decimal('1') if not reasons else Decimal('0'), tuple(reasons))

class MockAmazonProvider:
    """User-owned JSON fixtures only. Every listing is marked mock regardless of file claims."""
    def __init__(self, path: Path):
        data = json.loads(path.read_text())
        if not isinstance(data, list): raise ValueError('Mock listing fixture must be an array')
        listings = []
        for row in data:
            eligible = row.get('seller_eligible')
            if eligible is not None and type(eligible) is not bool:
                raise ValueError('seller_eligible must be a boolean or null')
            costs = {key: money(value) for key, value in row.get('costs', {}).items()}
            rate = money(row.get('referral_rate'))
            if rate is not None and rate >= 1: raise ValueError('Referral rate must be below 1')
            listings.append(MarketplaceListing(
                asin=row['asin'], gtin=gtin(row.get('gtin', '')),
                manufacturer=row.get('manufacturer', ''), model=row.get('model', ''),
                package_quantity=integer(row.get('package_quantity')), variation=row.get('variation', ''),
                seller_eligible=eligible, sale_price=money(row.get('sale_price')), costs=costs,
                referral_rate=rate, monthly_sales=integer(row.get('monthly_sales')),
                offer_count=integer(row.get('offer_count')), retrieved_at=timestamp(row.get('retrieved_at', '')),
                provenance=row.get('provenance', ''), verified_costs=tuple(row.get('verified_costs', ())), is_mock=True,
            ))
        self.listings = tuple(listings)

    def match(self, product: RetailProduct) -> Match:
        return match_listings(product, self.listings)
