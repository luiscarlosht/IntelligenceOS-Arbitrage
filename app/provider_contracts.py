"""Future provider boundaries. No HTTP adapters or live provider registration."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Generic, Literal, Protocol, TypeVar

from app.models import MarketplaceListing, RetailProduct

T = TypeVar('T')


@dataclass(frozen=True)
class Evidence(Generic[T]):
    value: T | None
    observed_at: datetime
    provenance: str
    is_mock: bool = True

    def __post_init__(self) -> None:
        if self.observed_at.utcoffset() is None or not self.provenance.strip():
            raise ValueError('Evidence requires an aware timestamp and provenance')

    def fresh(self, now: datetime, maximum_age_seconds: float = 86400) -> bool:
        import math
        if now.utcoffset() is None or not math.isfinite(maximum_age_seconds) or maximum_age_seconds <= 0:
            raise ValueError('Invalid evidence clock or maximum age')
        return 0 <= (now - self.observed_at).total_seconds() <= maximum_age_seconds


@dataclass(frozen=True)
class SellerContext:
    seller_id: str
    marketplace_id: str
    condition: str = 'new_new'

    def __post_init__(self) -> None:
        if not all((self.seller_id.strip(), self.marketplace_id.strip(), self.condition.strip())):
            raise ValueError('Explicit seller, marketplace and condition required')


@dataclass(frozen=True)
class FeeQuote:
    asin: str
    context: SellerContext
    sale_price: Decimal
    fulfillment: Literal['FBA', 'FBM']
    referral_fee: Decimal | None
    fulfillment_fee: Decimal | None
    currency: Literal['USD'] = 'USD'

    def __post_init__(self) -> None:
        if not self.asin or self.fulfillment not in ('FBA', 'FBM') or self.currency != 'USD':
            raise ValueError('Invalid fee quote context')
        if not self.sale_price.is_finite() or self.sale_price <= 0:
            raise ValueError('Positive finite sale price required')
        for amount in (self.referral_fee, self.fulfillment_fee):
            if amount is not None and (not amount.is_finite() or amount < 0):
                raise ValueError('Invalid fee amount')


@dataclass(frozen=True)
class DemandSignal:
    asin: str
    marketplace_id: str
    monthly_units_lower_bound: int | None
    basis: Literal['bought_past_month_lower_bound', 'authorized_sales', 'unknown']

    def __post_init__(self) -> None:
        if not self.asin or not self.marketplace_id:
            raise ValueError('Demand requires ASIN and marketplace')
        if self.basis not in ('bought_past_month_lower_bound', 'authorized_sales', 'unknown'):
            raise ValueError('Unsupported demand basis')
        if self.monthly_units_lower_bound is not None:
            if type(self.monthly_units_lower_bound) is not int or self.monthly_units_lower_bound < 0 or self.basis == 'unknown':
                raise ValueError('Demand cannot be inferred from missing data or rank')


class CatalogProvider(Protocol):
    def candidates(self, product: RetailProduct) -> tuple[Evidence[MarketplaceListing], ...]: ...


class FeesProvider(Protocol):
    def quote(self, asin: str, context: SellerContext, sale_price: Decimal,
              fulfillment: Literal['FBA', 'FBM']) -> Evidence[FeeQuote]: ...


class EligibilityProvider(Protocol):
    def eligibility(self, asin: str, context: SellerContext) -> Evidence[bool]: ...


class DemandProvider(Protocol):
    def demand(self, asin: str, marketplace_id: str) -> Evidence[DemandSignal]: ...
