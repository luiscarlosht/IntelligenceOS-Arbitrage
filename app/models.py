"""Normalized data contracts shared by connectors and matching providers."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Mapping

@dataclass(frozen=True)
class RetailProduct:
    retailer: str
    name: str
    url: str
    gtin: str
    manufacturer: str
    model: str
    package_quantity: int | None
    purchase_price: Decimal | None
    availability: str
    retrieved_at: datetime | None
    provenance: str
    asin_hint: str = ''
    variation: str = ''
    issues: tuple[str, ...] = ()
    authorization_reference: str = ''
    source_context: Mapping[str, str | Decimal | None] = field(default_factory=dict)

@dataclass(frozen=True)
class MarketplaceListing:
    asin: str
    gtin: str
    manufacturer: str
    model: str
    package_quantity: int | None
    variation: str
    seller_eligible: bool | None
    sale_price: Decimal | None
    costs: Mapping[str, Decimal | None] = field(default_factory=dict)
    referral_rate: Decimal | None = None
    monthly_sales: int | None = None
    offer_count: int | None = None
    retrieved_at: datetime | None = None
    provenance: str = ''
    verified_costs: tuple[str, ...] = ()
    is_mock: bool = True

@dataclass(frozen=True)
class Match:
    listing: MarketplaceListing | None
    exact: bool
    confidence: Decimal
    reasons: tuple[str, ...] = ()
