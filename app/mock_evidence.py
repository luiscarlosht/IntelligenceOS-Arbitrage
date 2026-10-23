"""In-memory fictional contract double; never wired into the job/provider selector."""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Literal, TypeVar

from app.models import MarketplaceListing, RetailProduct
from app.provider_contracts import DemandSignal, Evidence, FeeQuote, SellerContext

T = TypeVar('T')


class MockEvidenceProvider:
    def __init__(self, observed_at: datetime, listings: tuple[MarketplaceListing, ...] = (),
                 fees: tuple[FeeQuote, ...] = (),
                 eligibility: dict[tuple[str, SellerContext], bool | None] | None = None,
                 signals: tuple[DemandSignal, ...] = ()) -> None:
        self.observed_at = observed_at
        self.listings = listings
        self.fees = fees
        self.permissions = dict(eligibility or {})
        self.signals = signals

    def evidence(self, value: T | None) -> Evidence[T]:
        return Evidence(value, self.observed_at, 'MOCK: fictional contract test', is_mock=True)

    def candidates(self, product: RetailProduct) -> tuple[Evidence[MarketplaceListing], ...]:
        # Return candidates for deterministic package/variation matching, never eligibility.
        return tuple(self.evidence(replace(row, is_mock=True, seller_eligible=None))
                     for row in self.listings if product.gtin and product.gtin == row.gtin)

    def quote(self, asin: str, context: SellerContext, sale_price: Decimal,
              fulfillment: Literal['FBA', 'FBM']) -> Evidence[FeeQuote]:
        matches = [row for row in self.fees if (row.asin, row.context, row.sale_price, row.fulfillment) ==
                   (asin, context, sale_price, fulfillment)]
        return self.evidence(matches[0] if len(matches) == 1 else None)

    def eligibility(self, asin: str, context: SellerContext) -> Evidence[bool]:
        return self.evidence(self.permissions.get((asin, context)))

    def demand(self, asin: str, marketplace_id: str) -> Evidence[DemandSignal]:
        matches = [row for row in self.signals if (row.asin, row.marketplace_id) == (asin, marketplace_id)]
        return self.evidence(matches[0] if len(matches) == 1 else None)
