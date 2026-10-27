"""Conservative normalization of aggregate counts and returned detail coverage."""
from dataclasses import dataclass

from app.amazon_pricing_shape import pricing_usd, require


@dataclass(frozen=True)
class OfferCountGroup:
    condition: str | None
    fulfillment_channel: str | None
    offer_count: int


@dataclass(frozen=True)
class OfferCoverage:
    returned_offer_count: int
    documented_expected_offer_count: int
    documented_count_matches: bool
    incomplete_coverage: bool
    coverage: str
    number_of_offers: tuple[OfferCountGroup, ...] | None
    buy_box_eligible_offers: tuple[OfferCountGroup, ...] | None


def count_groups(summary: dict, name: str, total: int) -> tuple[OfferCountGroup, ...] | None:
    if name not in summary:
        return None
    rows = summary[name]
    require(isinstance(rows, list), 'pricing_summary_counts_invalid')
    groups = []
    seen = set()
    for row in rows:
        require(isinstance(row, dict), 'pricing_summary_counts_invalid')
        count = row.get('OfferCount')
        require(type(count) is int and 0 <= count <= total, 'pricing_summary_counts_invalid')
        condition = row.get('condition')
        channel = row.get('fulfillmentChannel')
        if 'condition' in row:
            require(isinstance(condition, str) and condition.lower() in
                    ('new', 'used', 'collectible', 'refurbished', 'club'), 'pricing_summary_counts_invalid')
            condition = condition.lower()
        if 'fulfillmentChannel' in row:
            require(channel in ('Amazon', 'Merchant'), 'pricing_summary_counts_invalid')
        # Schema-optional labels stay missing; they are never inferred as New/FBA.
        if condition is not None and channel is not None:
            require((condition, channel) not in seen, 'pricing_summary_counts_inconsistent')
            seen.add((condition, channel))
        groups.append(OfferCountGroup(condition, channel, count))
    group_total = sum(group.offer_count for group in groups)
    # Local conservative consistency policy, not a filtering explanation.
    require(group_total == total if name == 'NumberOfOffers' else group_total <= total,
            'pricing_summary_counts_inconsistent')
    return tuple(groups)


def offer_coverage(summary: dict, offers: list[dict], total: int) -> OfferCoverage:
    returned = len(offers)
    expected = min(total, 20)
    require(returned <= expected and (total == 0 or returned > 0), 'pricing_offer_count_inconsistent')
    partial = returned < expected
    groups = count_groups(summary, 'NumberOfOffers', total)
    eligible = count_groups(summary, 'BuyBoxEligibleOffers', total)
    if groups is not None and eligible is not None:
        known = {(g.condition, g.fulfillment_channel): g.offer_count for g in groups
                 if g.condition is not None and g.fulfillment_channel is not None}
        for group in eligible:
            key = (group.condition, group.fulfillment_channel)
            if key in known:
                require(group.offer_count <= known[key], 'pricing_summary_counts_inconsistent')
    for row in offers:
        # A below-contract response must contain actual schema-shaped detail
        # evidence. Empty object placeholders cannot justify partial acceptance.
        if partial:
            require(type(row.get('IsFulfilledByAmazon')) is bool and
                    isinstance(row.get('ShippingTime'), dict) and
                    'SubCondition' in row, 'pricing_offer_details_invalid')
        if 'SubCondition' in row:
            # Amazon's model examples also use lowercase "new".
            require(isinstance(row['SubCondition'], str) and row['SubCondition'].lower() == 'new',
                    'pricing_offer_condition_mismatch')
        if 'offerType' in row:
            require(row['offerType'] == 'B2C', 'pricing_offer_customer_type_mismatch')
        for name in ('ListingPrice', 'Shipping', 'LandedPrice'):
            if name in row or partial and name in ('ListingPrice', 'Shipping'):
                value = pricing_usd(row.get(name))
                require(value is not None, 'pricing_amount_invalid')
    if groups is not None and all(g.condition is not None and g.fulfillment_channel is not None for g in groups):
        known = {(g.condition, g.fulfillment_channel): g.offer_count for g in groups}
        detail_counts: dict[tuple[str, str], int] = {}
        for row in offers:
            if 'SubCondition' in row and type(row.get('IsFulfilledByAmazon')) is bool:
                key = ('new', 'Amazon' if row['IsFulfilledByAmazon'] else 'Merchant')
                detail_counts[key] = detail_counts.get(key, 0) + 1
                require(detail_counts[key] <= known.get(key, 0), 'pricing_summary_counts_inconsistent')
    return OfferCoverage(returned, expected, not partial, returned < total,
        'partial' if partial else 'capped' if returned < total else 'count_matched', groups, eligible)
