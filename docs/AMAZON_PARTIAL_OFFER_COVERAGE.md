> Updated evidence: the owner completed selected validation on 2026-10-27.
> See [live results and authorized-source preparation](AMAZON_AUTHORIZED_SOURCE_WORKFLOW.md).
> The historical preparation and earlier evidence below are preserved.

# Aggregate counts and returned offer coverage — 2026-10-27

## Retained evidence

The owner-run count diagnostic for B0G1MJ24B4 at 02:38:17 UTC retained HTTP 200,
application status Success, integer TotalOfferCount **5**, returned Offers length
**1**, expected capped length **5**, and six true ASIN/marketplace/condition
comparisons. The old parser rejected it as pricing_offer_count_inconsistent.
The new preparation does not rewrite or reclassify that historical report.

The count report has no Summary.NumberOfOffers, BuyBoxEligibleOffers, actual
price components, SubCondition, offerType or other offer details. The selected
pilot report also lacks these facts. We cannot infer that four offers were Used,
Business-only, from a particular fulfillment channel, duplicates, unavailable,
or cheaper. The discrepancy is observed; its cause is unproven. Because prices
were not retained and count validation ran first, the report does not establish
that all monetary/detail fields passed validation.

Both sanitized reports were read without credential access. Before/after SHA-256
checks preserve the count report (`613d14cb6e27c651736f7586698bf0fad53fbf9c10a74a1e7d2c8cf17b626aa7`)
and selected pilot (`085f32a50b69878db1eadaf0daf052813070b429d0b632c8da8c2cbd0e638f95`).
Neither reports nor credentials are committed or modified. No live provider calls
were made during this work.

## What Amazon documents

Reviewed the [official v0 model](https://github.com/amzn/selling-partner-api-models/blob/main/models/product-pricing-api-model/productPricingV0.json)
at Summary, NumberOfOffers, OfferCountType, GetOffersResult, OfferDetailList and
getItemOffers, plus the [official operation reference](https://developer-docs.amazon.com/sp-api/reference/getitemoffers).

| Field or operation | Documented contract |
| --- | --- |
| TotalOfferCount | Aggregate unique offers represented in NumberOfOffers |
| NumberOfOffers | Counts grouped by condition and fulfillment channel; not detailed seller rows |
| OfferCountType | Optional condition/channel labels, numeric OfferCount; channel is Amazon or Merchant |
| BuyBoxEligibleOffers | Eligible-offer counts grouped by condition/channel, distinct from the total |
| ItemCondition / CustomerType | Filter by condition and select Consumer or Business offers; Consumer is the default |
| Offers / OfferDetailList | Length is documented as min(total, 20), with maxItems 20 |

The grouping model has no customer-type dimension. It does not prove that this
response's total spans both customer types. The operation advertises lowest
priced offers, but the 5/1 result contradicts its documented length rule. No
reviewed source states that filtering exempts a response from that rule. We
therefore cannot use filtering as a confirmed explanation or guarantee that the
one returned offer is the cheapest overall or represents every seller.

Amazon also documents condition-specific details with broader Summary data for
[ANY_OFFER_CHANGED notifications](https://developer-docs.amazon.com/sp-api/docs/notification-type-values).
That is a different interface; its semantics are context, not a replacement
contract for getItemOffers. No community issue is treated as an API guarantee.

## Conservative evidence mapping

The parser now separates total_offer_count from an OfferCoverage object containing
returned_offer_count, documented_expected_offer_count, documented_count_matches,
incomplete_coverage, coverage, and optional normalized NumberOfOffers and
BuyBoxEligibleOffers groups. Missing breakdown arrays stay null; missing optional
bucket labels stay null rather than becoming New/Amazon. Explicit empty arrays
remain distinguishable. No raw seller details or new prices are persisted.

| Coverage | Meaning | Treatment |
| --- | --- | --- |
| count_matched | Returned length equals the aggregate and documented expectation | A count match only; does not establish every seller or an overall minimum |
| capped | Documented 20-detail cap reached, aggregate exceeds returned count | Mark incomplete and exclude from profitability ranking |
| partial | Positive returned length below the documented expectation | Preserve both counts, mark contract mismatch and incomplete, exclude from ranking |

Partial acceptance is an explicit evidence policy based on the observed
discrepancy, not a claim that the API response conforms to the documented
equality. It is more than an unchecked inequality:

- Required identities, US marketplace, New condition, supported status, containers
  and nonnegative integer total remain mandatory. Excess rows above min(total,20)
  fail. A positive total with zero details still fails; a partial response cannot
  masquerade as NoBuyableOffers.
- Below-contract responses require actual detail structure: boolean fulfillment,
  a ShippingTime object, New SubCondition, and explicit finite nonnegative USD
  ListingPrice/Shipping. Lowercase new is accepted because official examples use
  it. Supplied B2B detail/summary offerType is rejected in this Consumer parser.
  Every supplied supported money component is validated even when counts match.
- Optional breakdown arrays, when present, require nonnegative integer counts
  bounded by the total and known labels when supplied. Duplicate named buckets,
  NumberOfOffers sums differing from the aggregate, eligible totals exceeding
  the aggregate, or eligible named counts exceeding matching buckets fail.
  A fully named breakdown also bounds returned details by their known New
  condition and fulfillment channel; a detail cannot exceed or contradict its
  bucket. Missing labels are not guessed to perform this check.
  These are additional local conservative checks; the model does not provide a
  separate formal sum/uniqueness validator. No breakdown is synthesized when absent.
- NoBuyableOffers still requires zero total, empty details, absent/empty summary
  price groups and consistent zero optional counts. Existing identity and monetary
  rules are preserved. Missing summary prices remain unknown; returned detail
  prices are validated but never promoted to summary prices or a sale quote.

A partial diagnostic result uses pricing_partial_coverage_validated, retains
lookup status Success and the coverage object, and keeps ranking exclusion true.
Successful capped responses also remain excluded. apply_pricing_gate clears an
older sale quote and records incomplete coverage. Even if a New summary price is
present, it stays a reported observation, not an overall minimum or achievable
seller sale price. overall_lowest_price_verified is always false; customer_type
is explicitly Consumer. Existing exclusive report names, request caps, deadlines
and no-retry behavior remain unchanged; no diagnostic has been rerun.

## Regression evidence and uncertainty

The committed 5-total/1-detail fixture reproduces the retained counts and context.
Its offer shape and numeric prices are explicitly fictional test inputs, not a
reconstruction of live prices. The base fixture omits NumberOfOffers because it
was not retained; separate synthetic tests exercise condition/channel breakdowns.
Tests cover coverage states, malformed counts/details, currencies/amounts,
duplicate and contradictory buckets, identity/customer type, unchanged no-offer
rules, ranking exclusion, safe diagnostic output and existing request bounds.

The new parser has been verified with mocks only. We cannot assert that the
original live response would pass the new required detail/money checks. An
already-retained sanitized breakdown and detail-validation facts from that same
response could narrow the explanation; none are available in these reports.
No further live diagnostic is proposed or required for this PR.
