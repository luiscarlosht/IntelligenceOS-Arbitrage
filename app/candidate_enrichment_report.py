"""Strict, read-only projection of saved candidate enrichment into report columns."""
from app.amazon_catalog import MARKETPLACE
from app.amazon_candidate_enrichment import selected_offer
from app.normalization import money, timestamp

# key, readable heading, width, monetary
COLUMNS = (
    ('amazon_item_price','Amazon observed item price (USD)',24,True),
    ('amazon_shipping','Amazon buyer-paid shipping (USD)',24,True),
    ('amazon_landed_price','Amazon landed offer price (USD)',24,True),
    ('offer_condition','Amazon offer condition',22,False),
    ('offer_fulfillment','Amazon offer fulfillment channel',24,False),
    ('offer_marketplace','Amazon offer marketplace',23,False),
    ('offer_basis','Amazon price observation basis',26,False),
    ('pricing_status','Amazon pricing stage status',25,False),
    ('offer_coverage','Amazon offer coverage / limitations',48,False),
    ('estimated_referral_fee','Estimated referral fee (USD)',23,True),
    ('estimated_fba_fee','Estimated FBA fulfillment fee (USD)',24,True),
    ('estimated_total_fees','Total estimated Amazon fees (USD)',24,True),
    ('fee_sale_price','Fee-estimate sale price (USD)',24,True),
    ('fee_buyer_shipping','Fee-estimate buyer-paid shipping (USD)',24,True),
    ('fee_fulfillment','Fee-estimate fulfillment assumption',26,False),
    ('fee_price_policy','Fee-estimate price assumption',30,False),
    ('fee_estimated_at','Amazon fee-estimation timestamp',27,False),
    ('fee_checked_at','Fee response observed at',27,False),
    ('fee_provenance','Fee estimate provenance',60,False),
    ('fees_status','Amazon fee stage status',25,False),
    ('restriction_status','Listing-restriction status',32,False),
    ('restriction_reasons','Listing-restriction reason codes',35,False),
    ('approval_requirements','Listing approval requirements',55,False),
    ('eligibility_marketplace','Eligibility marketplace',23,False),
    ('eligibility_condition','Eligibility condition',22,False),
    ('eligibility_checked_at','Eligibility checked at',27,False),
    ('eligibility_provenance','Listing-permission provenance',60,False),
    ('restrictions_status','Amazon restriction stage status',25,False),
    ('inbound_fba_shipping','Inbound-to-FBA shipping cost (USD)',25,True),
    ('merchant_fulfillment_cost','Merchant fulfillment cost (USD)',25,True),
    ('overall_fba_eligibility','Overall seller / FBA eligibility',28,False),
    ('analysis_notice','Candidate analysis limitations',70,False),
)


def aware(value):
    stamp = timestamp(value)
    if stamp is None:
        raise ValueError('Amazon evidence requires an aware observation timestamp')
    return stamp.isoformat()


def validate_evidence(evidence, mocked):
    if (not isinstance(evidence, dict) or evidence.get('is_mock') is not mocked
            or not evidence.get('provenance') or evidence.get('value') is None):
        raise ValueError('Amazon enrichment evidence provenance missing/mismatched')
    aware(evidence.get('observed_at'))


def project(comparison: dict, result: dict | None, spec: dict | None, *, mocked: bool) -> dict:
    """No fee or permission value ever enters verified economics or identity fields."""
    out = {key: None for key, *_ in COLUMNS}
    out.update(pricing_status='not_attempted', fees_status='not_attempted', restrictions_status='not_attempted',
        restriction_status='UNKNOWN', overall_fba_eligibility='UNKNOWN',
        analysis_notice='Candidate ASIN only; identity unverified. Unrestricted listing is not purchase approval. '
                        'Source acquisition shipping, buyer shipping, inbound-to-FBA shipping and merchant fulfillment '
                        'are separate. Unknown required costs block verified net profit.')
    if result is None:
        return out
    asin = comparison['candidate_asin']
    if (result.get('asin'),result.get('marketplace_id'),result.get('condition'),result.get('seller_reference')) != (
            asin, MARKETPLACE, 'new_new', spec['seller_reference']):
        raise ValueError('Enrichment ASIN/marketplace/condition/seller scope mismatch')
    for name, key in (('pricing','pricing_status'),('fees','fees_status'),('restrictions','restrictions_status')):
        outcome = result[name]
        if outcome['status'] not in ('not_attempted','attempted','succeeded','failed','interrupted','skipped_missing_price'):
            raise ValueError('Unknown enrichment stage outcome')
        out[key] = outcome['status']
        if outcome['status'] != 'succeeded' and outcome.get('data') is not None:
            raise ValueError('Failed stage cannot supply usable evidence')
    pricing = result['pricing']['data'] if result['pricing']['status'] == 'succeeded' else None
    if pricing:
        validate_evidence(pricing, mocked)
        value = pricing['value']
        if (value['asin'],value['marketplace_id'],value['condition'],value['customer_type']) != (
                asin, MARKETPLACE, 'New','Consumer'):
            raise ValueError('Pricing evidence scope mismatch')
        out['pricing_status'] = 'succeeded / '+value['lookup_status']
        offer = selected_offer(pricing)
        out['offer_coverage'] = ('Partial/limited observations; no overall lowest-price guarantee; excluded from ranking'
            if value.get('exclude_from_profitability_ranking') else 'Summary observations; no overall lowest-price guarantee')
        if offer:
            item, shipping, landed = (money(offer.get(k)) for k in ('listing_price','shipping','landed_price'))
            out.update(amazon_item_price=item,amazon_shipping=shipping,
                amazon_price_observed_at=aware(pricing['observed_at']), price_provenance=pricing['provenance']+' | eBay/prior price basis: '+comparison['price_provenance'],
                amazon_landed_price=landed,offer_condition='New / Consumer',
                offer_fulfillment=offer['fulfillment_channel'], offer_marketplace=MARKETPLACE,offer_basis=offer['basis'])
            # Landed price is reported evidence, never a subtraction used to guess unknown shipping.
            ebay = comparison.get('observed_item_price')
            coupon = comparison.get('conditional_ebay_coupon_price')
            out['gross_item_price_difference'] = item-ebay if item is not None and ebay is not None else None
            out['gross_difference_with_coupon'] = item-coupon if item is not None and coupon is not None else None
    fee_spec = spec['fees']
    fee = result['fees']
    if fee.get('scenario') is not None:
        scenario = fee['scenario']
        expected_price = (money(fee_spec['sale_price']) if fee_spec['sale_price'] is not None else
                          money((selected_offer(pricing) or {}).get('listing_price')))
        if (money(scenario['sale_price']) != expected_price or scenario['buyer_shipping'] != fee_spec['buyer_shipping']
                or scenario['fulfillment'] != fee_spec['fulfillment'] or scenario['price_policy'] != fee_spec['price_policy']
                or scenario['currency'] != 'USD'):
            raise ValueError('Fee scenario does not match selected price/manifest')
        out.update(fee_sale_price=expected_price,fee_buyer_shipping=money(scenario['buyer_shipping']),
                   fee_fulfillment=scenario['fulfillment']+' hypothetical; not FBA eligibility',
                   fee_price_policy=scenario['price_policy'])
    if fee['status'] == 'succeeded':
        if not fee.get('scenario'):
            raise ValueError('Fee estimate requires exact scenario')
        data = fee['data']
        quote = data['quote']
        validate_evidence(quote, mocked)
        value = quote['value'];context = value['context']
        if ((value['asin'],context['marketplace_id'],context['condition'],value['fulfillment'],value['currency']) !=
                (asin, MARKETPLACE, 'new_new', fee_spec['fulfillment'],'USD')
                or money(value['sale_price']) != out['fee_sale_price']
                or money(data.get('buyer_shipping_scenario')) != out['fee_buyer_shipping']):
            raise ValueError('Fee evidence scope or sale-price/shipping scenario mismatch')
        out.update(estimated_referral_fee=money(value.get('referral_fee')),
            estimated_fba_fee=money(value.get('fulfillment_fee')),estimated_total_fees=money(data.get('total_fees_estimate')),
            fee_estimated_at=aware(data['estimated_at']) if data.get('estimated_at') else None,
            fee_checked_at=aware(quote['observed_at']),fee_provenance=quote['provenance'])
    restriction = result['restrictions']
    if restriction['status'] == 'succeeded':
        data = restriction['data'];evidence = data['listing_permission']
        validate_evidence(evidence, mocked)
        allowed = evidence['value']
        if type(allowed) is not bool or type(data['restriction_count']) is not int:
            raise ValueError('Invalid restriction evidence')
        codes = data['reason_codes']
        if any(not isinstance(c, str) for c in codes):
            raise ValueError('Unknown restriction reason')
        if allowed != (data['restriction_count'] == 0) or (allowed and codes):
            raise ValueError('Contradictory restriction evidence')
        details = data.get('reasons') or []
        out['approval_messages'] = '\n'.join(r['message'] for r in details if isinstance(r.get('message'), str)) or 'UNKNOWN — instructions not returned'
        out['approval_links'] = [dict(link, reason_code=r.get('reasonCode')) for r in details
                                 for link in r.get('links', []) if isinstance(link, dict)]
        out.update(restriction_status='UNRESTRICTED — listing permission only' if allowed else 'RESTRICTED',
            restriction_reasons='; '.join(codes) or ('No restrictions returned' if allowed else 'Reason unknown'),
            approval_requirements=('APPROVAL_REQUIRED — obtain Seller Central approval; approval not granted'
                if 'APPROVAL_REQUIRED' in codes else 'None returned for this listing check' if allowed else
                'Unknown; resolve returned restrictions with Amazon'),
            eligibility_marketplace=MARKETPLACE,eligibility_condition='new_new',
            eligibility_checked_at=aware(evidence['observed_at']),eligibility_provenance=evidence['provenance'])
    return out
