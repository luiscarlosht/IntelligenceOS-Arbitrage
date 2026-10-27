# eBay source-detail enrichment preparation

Prepared offline on 2026-10-27. The public overview advertises an eBay US
`product` topic with `key=id`; full-URL input and this trial's entitlement are
**not verified**. The numeric IDs in this proposal were extracted from the ten
original `/itm/` listing URLs. Whether this product topic accepts those listing
IDs rather than eBay catalog product IDs requires a source-specific example or
provider confirmation. No data requests, credential reads, discovery jobs,
messages, paid activation or production changes were performed.

## What was verified and what remains unknown

The [official source overview](https://readme.priceapi.com/reference/sources)
lists `product`/`id` for eBay in the United States. Its `product_and_offers` entry
uses `term`/`gtin`, which would repeat discovery and is excluded. The dedicated
[eBay reference](https://readme.priceapi.com/reference/ebay) could not be retrieved;
the overview's eBay link resolved back to the overview rather than exposing a
response schema. We could not retrieve a public source-specific sample. Do not
substitute a different vendor's eBay schema or Google's field paths.

The existing saved Price API file contains one `search_results` result with
`id=null` on every selected listing. It provides title, URL, seller, condition,
search price/currency and some shipping values, but none of the missing source
identifier/package fields. Its credit counters are 1.0 free and 0.0 paid for that
search job, not proof of the future product-topic tariff or current balance.
The saved Amazon detail report describes destination candidates; its brand,
barcode, component count and variation cannot establish eBay source facts.
No saved eBay product-detail export was found in the existing import directory.

| Requested evidence | Saved eBay evidence | Product-detail response coverage |
| --- | --- | --- |
| Brand | Unknown; title text is not a verified brand | Unverified |
| Manufacturer/model/MPN | Unknown; these are separate fields | Unverified |
| UPC/EAN/GTIN | Unknown; never infer from destination ASIN/UPC | Unverified |
| Item specifics | Absent | Unverified; require exact field paths and types |
| Package contents | Unknown; no title-derived components | Unverified |
| Retail package quantity / component count | Both unknown; title piece counts are clues only | Unverified; must distinguish one set from its utensils |
| Variation | Unknown; requested/available choices are not selected-variant evidence | Unverified; require selected size/color/material and variation identity |
| Condition | Search observation says Brand New for all ten | Detail path and semantics unverified |
| Shipping | First two costs unknown; remaining eight explicitly zero | Detail destination/fulfillment/currency/conditions paths unverified |

Current trial evidence is historical Free / One-time workspace information; no
current entitlement, remaining balance, expiry, no-paid-fallback or auto-recharge
state was checked. The earlier Google Shopping account review cannot authorize
this eBay topic. Public availability and a successful eBay search do not establish
trial permission for product details.

## Bounded request proposal, not an executable job

The [manifest](../ops/examples/ebay-source-details-20261027.json) binds the original
CSV bytes (`cabbbda426bff05faff0b6d8f051e62bde21fa927efafe9fc347e9380ee24f11`),
all ten ordinals, item IDs and normalized source fingerprints. It inventories the
saved search export, which cannot satisfy a detail lookup. A verified saved
product export with usable fields excludes that ID from the pending values before
planning any new collection. Partial, failed, unrelated or unmapped exports do
not count as usable detail evidence. No automatic refresh or retry is performed.

Proposed one job: POST `https://priceapi.metoda.com/v2/jobs` with
`source=ebay`, `country=us`, `topic=product`, `key=id`, and newline-separated pending
IDs in original order. No URL key, keyword/GTIN discovery, offers, page expansion,
webhook, sort, condition, max_age or timeout overrides are proposed. Defaults
remain unverified for this topic. General endpoint defaults are inconsistent in
the documentation and cannot certify the eBay topic's settings or deadline.

The [general credit guide](https://readme.priceapi.com/docs/credits) describes one
credit per product with default settings, including a looked-up but unavailable
product; changing nondefault settings generally doubles credits. It explicitly
allows source-specific tariffs. Therefore **10 credits is a general-tariff
estimate**, and **20 credits is a provisional review reserve**, not a guaranteed
account/provider cap. Neither is approved spending. Poll/download charges and any
source-specific surcharge remain unverified. Maximum paid usage authorized: zero.
No dollar price or free-only server enforcement has been established.

A future reviewed executor could cap transport to one submit, five status checks
and one download (7 HTTP attempts), with zero retries, no resubmission, and a
permanent one-shot reservation before credential access. The current code has
**no live executor, credential loader or network transport**, so its executable
request budget is **zero**. It does not reuse the existing discovery runner, which
has a different topic and account gate. No working live-submit command can be
provided until the ID semantics, schema, trial entitlement, exact tariff and
free-only behavior are verified. Do not use raw curl to bypass these open checks.

## Adapter and pipeline compatibility

`app.ebay_source_details` implements an offline schema-profile adapter rather than
claiming an unverified vendor response mapping. A reviewed profile supplies
explicit JSON paths relative to each result's `content`; all unmapped/missing
paths become null. The [profile template](../ops/examples/ebay-detail-schema-profile.json)
is intentionally unverified with null paths. Flipping its flag is insufficient:
first supply an actual provider schema/sample reference, exact paths/types and
retail-package quantity semantics. Synthetic fixtures establish our behavior,
not the vendor's capability. No real detail enrichment has occurred.

The importer checks completed `ebay/us/product/id` scope and original listing
identity where a URL is supplied. It keeps brand distinct from manufacturer,
MPN distinct from model, component count distinct from retail package quantity,
and raw barcode observations distinct from validated canonical GTINs. Invalid
barcodes stay invalid; multiple differing valid barcodes are an explicit
identifier contradiction. It preserves structured specifics, components,
variation, condition, seller and shipping scope in normalized source context.
No title parsing or destination-field backfilling is used.

Missing evidence and contradictory known values have separate classifications.
The candidate matcher also now reports unknown source count/contents as missing,
not as a package contradiction; a component count versus retail pack count with
unverified units requires basis verification. Historic candidate reports are
preserved, not rewritten. Source-detail observations retain their own provider
observation time; local import time never replaces the original source time.

On offline import, every original row survives with status `saved_detail_imported`
or `detail_missing`. Known source fields are not overwritten by conflicting new
values. New evidence is appended to a new directory through RetailProduct,
ObservationStore, existing screening and formula-safe Excel. JSON retains both
original and enriched source objects. The source CSV, old database, reports and
Amazon manifest remain unchanged. New optional specifics do not expand the global
CSV schema; they remain nested normalized evidence in source context. Existing
source issues are retained, so enrichment alone cannot create an exact Amazon
match or purchase approval. Condition/shipping observations do not become stock,
tax, landed acquisition cost or seller eligibility.

## Exact offline operator commands

From the existing SSH session, prepare a new manifest without credential access:

```sh
cd /root/IntelligenceOS-Arbitrage
.venv/bin/python -m app.ebay_source_details plan \
  --source /root/IntelligenceOS-Arbitrage/var/source-imports/ebay_6ae1298795263c2adcdb3ac7_offline/observations.csv \
  --saved-export /root/IntelligenceOS-Arbitrage/var/source-imports/20261027224527_ebay_us_6ae1298795263c2adcdb3ac7.json \
  --output /tmp/ebay-source-details-review.json
```

Use a new output filename if one exists; no file is overwritten. Once an existing
licensed product-detail export and a verified profile are supplied, the offline
import command is (the two `/tmp` inputs below are future inputs, not existing
provider evidence):

```sh
.venv/bin/python -m app.ebay_source_details import-saved \
  --source /root/IntelligenceOS-Arbitrage/var/source-imports/ebay_6ae1298795263c2adcdb3ac7_offline/observations.csv \
  --saved-export /tmp/verified-ebay-product-export.json \
  --profile /tmp/verified-ebay-detail-schema-profile.json \
  --output /root/IntelligenceOS-Arbitrage/var/source-imports/ebay-details-offline
```

Repeat `--saved-export` for multiple existing files. Contradictory saved exports
require explicit selection rather than silently taking the latest one. The
import output directory must be new. No retries, email or production behavior
is introduced by either command.

The next evidence needed is a nonsecret existing eBay `product`/`id` sample/schema
and the trial's exact entitlement/tariff/free-only terms. No new collection or
provider contact is authorized by this preparation.
