"""Decimal cost analysis; estimates are never guaranteed returns."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

ZERO = Decimal('0')
ACQUISITION_EXTRAS = ('inbound_shipping', 'preparation', 'packaging', 'sales_tax', 'other_cost')
SALE_COSTS = ('fulfillment_fee', 'storage', 'transaction_cost')
COST_FIELDS = ACQUISITION_EXTRAS + SALE_COSTS + ('referral_fee',)

@dataclass(frozen=True)
class Economics:
    net_profit: Decimal
    roi: Decimal
    acquisition_cost: Decimal
    break_even_price: Decimal
    maximum_purchase_price: Decimal
    referral_fee: Decimal


def analyze(purchase: Decimal, sale: Decimal, costs: Mapping[str, Decimal],
            minimum_roi: Decimal = Decimal('50'), minimum_profit: Decimal = Decimal('5'),
            referral_rate: Decimal | None = None) -> Economics:
    values = [purchase, sale, minimum_roi, minimum_profit, *costs.values()]
    if any(not v.is_finite() or v < 0 for v in values) or purchase <= 0:
        raise ValueError('Invalid economics input')
    if referral_rate is not None and (not referral_rate.is_finite() or not ZERO <= referral_rate < 1):
        raise ValueError('Invalid referral rate')
    extras = sum((costs[k] for k in ACQUISITION_EXTRAS), ZERO)
    sale_costs = sum((costs[k] for k in SALE_COSTS), ZERO)
    referral = sale * referral_rate if referral_rate is not None else costs['referral_fee']
    acquisition = purchase + extras
    profit = sale - referral - sale_costs - acquisition
    break_even = ((acquisition + sale_costs) / (1 - referral_rate) if referral_rate is not None
                  else acquisition + sale_costs + referral)
    revenue_after_fees = sale - referral - sale_costs
    maximum = min(revenue_after_fees - minimum_profit - extras,
                  revenue_after_fees / (1 + minimum_roi / 100) - extras)
    return Economics(profit, profit / acquisition * 100, acquisition, break_even, max(ZERO, maximum), referral)
