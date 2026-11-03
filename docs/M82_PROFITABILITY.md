# M82 conservative saved-evidence profitability

`app.opportunity_engine.evaluate` is an offline typed boundary: it has no HTTP client, credentials, acquisition or purchasing action. The integrated M83 pipeline supplies owner-pinned original M80 ledgers and saved receipts. Calling the pure function directly does not authenticate evidence.

The minimum review gate remains **50% acquisition ROI and $5 estimated net profit per Amazon selling unit**. Listing permission is account/US/New/time scoped, never FBA permission, brand approval, invoice acceptance or purchase approval. Every result sets purchase and sourcing authorization false; quantity remains UNKNOWN.

Required inputs:

- Completed M80 observation: fresh ranks/restrictions (24 hours), New landed offers (6 hours), account binding, no identity conflicts, current catalog brand/model/package quantity and checksum-valid GTIN.
- Saved Walmart quote: exact ASIN, normalized GTIN, brand, model, Amazon pack quantity, size and variation; independently reviewed match and variation flags. No fuzzy titles, inferred multipack conversion or UPC-only eligibility. Source must be a saved HTTPS walmart.com product quote, not a fetched URL.
- Fee receipt: exact ASIN, account, US/New, FBA, package quantity and conservative selling price. A fee estimate is not an FBA eligibility decision. Referral fee, fulfillment, storage and transaction costs must each be explicit USD values.
- Acquisition receipt: positive purchase price plus explicit Walmart shipping, sales tax, prep, inbound shipping, packaging and other costs. Explicit zero is allowed only when supported by the reviewed source; absent values never default to zero.
- Independent owner risk receipt: exact reviewed Amazon identity (including size/variation), brand resale, authenticity, invoice acceptability and account/product FBA eligibility. Each risk must be `VERIFIED_FOR_EXACT_ACCOUNT_AND_PRODUCT`; unresolved or unsupported claims block review.

All saved receipts require original artifact SHA-256, source reference, observed timestamp, evidence class, scope, currency and explicit owner review. Maximum age 24 hours, no future timestamps. Synthetic inputs can only produce synthetic results. An `owner_reviewed` assertion is a human trust input, not cryptographic proof; the M83 manifest must pin the receipt and independently obtained original artifact. Never derive authenticity from hashes of untrusted staging files.

Calculation (unrounded Decimal):

- Acquisition = Walmart purchase + Walmart shipping + tax + prep + inbound shipping + packaging + other acquisition costs.
- Net profit = current lowest observed New landed Amazon price − referral − fulfillment − storage − transaction − acquisition.
- ROI and net markup = net profit / acquisition × 100. Here markup deliberately uses **net** profit, not retail-price markup; the legacy profit/acquisition ROI formula is preserved.
- Margin = net profit / Amazon selling price × 100.

The minimum observed New price is used across available fulfillment channels; Buy Box or catalog list prices do not replace it. The fee estimate must match that exact conservative price. No price-drop, demand or future profit guarantee is implied. Missing current Amazon evidence, identity, receipts, fee coverage or risk clearance produces EXCLUDED and UNKNOWN economics. Negative or below-target completed calculations remain visible with exclusion flags; rounding never promotes a sub-threshold result.

Development tests use fictional receipts exclusively. No Walmart acquisition, fee API call, seller approval or invoice submission occurs. Actual Walmart sourcing remains separately unauthorized. Owner may supply independently acquired and reviewed saved data only within an explicitly approved acquisition scope.
