"""Future profitability contract. No prices, fees, calculations or purchase gate."""


def readiness() -> dict:
    """Null is unknown; none of these facts may be inferred from a Catalog match."""
    return dict(schema=1,enabled=False,currency='USD',
        seller_listing_permission=None,fba_fulfillment_eligibility=None,
        amazon_selling_price=None,referral_fee=None,fba_fee=None,
        retailer_acquisition_cost=None,sales_tax=None,inbound_shipping=None,
        preparation_cost=None,packaging_cost=None,storage_cost=None,other_costs=None,
        exact_identity_match=dict(upc_gtin=None,model=None,size=None,variation=None,pack_quantity=None),
        expected_net_profit=None,roi=None,inventory_budget_allocation=None,
        thresholds=dict(minimum_roi_percent=50,minimum_net_profit_usd=5,maximum_inventory_budget_usd=500),
        required_evidence='Each value requires independent source, scope, observation time and exact selling-unit evidence',
        purchase_authorized=False,listing_creation_authorized=False)
