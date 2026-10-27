"""Authorized input boundary. No automatic URL fetching or scraping."""
import csv
from pathlib import Path
from urllib.parse import urlsplit
import re
from typing import Iterable, Protocol
from app.models import RetailProduct
from app.normalization import gtin, integer, money, timestamp, http_url

WALMART_FIELDS = ('source_item_id', 'source_seller', 'destination_zip',
                  'fulfillment_method', 'source_shipping_cost', 'shipping_conditions')
SOURCE_FIELDS = ('source_provider', 'provider_product_id', 'retailer_item_id',
                 'source_seller', 'requested_zip', 'observed_zip',
                 'source_shipping_cost', 'shipping_conditions', 'source_observed_at',
                 'source_issues', 'search_price', 'search_currency', 'retrieved_at_utc',
                 'source_condition', 'source_seller_id', 'source_price_with_shipping',
                 'source_package_contents')


class RetailerConnector(Protocol):
    def products(self) -> Iterable[RetailProduct]: ...

class CsvConnector:
    """Stream user-provided products; malformed records remain visible as blocked rows."""
    REQUIRED_HEADERS = {'retailer', 'name', 'purchase_price'}

    def __init__(self, path: Path):
        self.path = path

    def products(self) -> Iterable[RetailProduct]:
        with self.path.open(newline='', encoding='utf-8-sig') as stream:
            reader = csv.DictReader(stream)
            if not self.REQUIRED_HEADERS <= set(reader.fieldnames or ()):
                raise ValueError('Discovery CSV requires retailer, name and purchase_price headers')
            if len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError('Duplicate CSV headers')
            for row in reader:
                issues = []
                if None in row: issues.append('Extra CSV fields')
                def parse(key, function):
                    try:
                        return function(row.get(key) or '')
                    except (ValueError, TypeError):
                        issues.append('Invalid ' + key)
                        return None
                normalized_gtin = parse('gtin', gtin) or ''
                quantity = parse('package_quantity', integer)
                price = parse('purchase_price', money)
                retrieved = parse('retrieved_at', timestamp)
                if quantity == 0: issues.append('Package quantity must be positive')
                if price == 0: issues.append('Purchase price must be positive')
                url = (row.get('url') or '').strip()
                if url and not http_url(url): issues.append('Invalid source URL')
                text = lambda key: (row.get(key) or '').strip()
                context = {}
                if 'source_provider' in row:
                    context = {key: text(key) or None for key in SOURCE_FIELDS}
                    context['source_shipping_cost'] = parse('source_shipping_cost', money)
                    issues.extend(x for x in text('source_issues').split('; ') if x)
                elif any(key in row for key in WALMART_FIELDS):
                    context = {key: text(key) or None for key in WALMART_FIELDS}
                    context['source_shipping_cost'] = parse('source_shipping_cost', money)
                    for key in WALMART_FIELDS:
                        if context[key] is None:
                            issues.append('Missing Walmart ' + key)
                    if text('retailer').lower() != 'walmart':
                        issues.append('Walmart observation retailer mismatch')
                    if text('destination_zip') != '76063':
                        issues.append('Walmart destination ZIP must be explicitly 76063')
                    if text('fulfillment_method') not in ('shipping', 'delivery', 'pickup'):
                        issues.append('Walmart fulfillment method missing or unsupported')
                    item_id = text('source_item_id')
                    if item_id and not re.fullmatch(r'[0-9]+', item_id):
                        issues.append('Invalid Walmart item ID')
                    if url:
                        try:
                            parsed = urlsplit(url)
                        except ValueError:
                            issues.append('Invalid Walmart product URL')
                            parsed = urlsplit('')
                        if parsed.hostname not in ('www.walmart.com', 'walmart.com') or not parsed.path.startswith('/ip/'):
                            issues.append('Walmart product URL required')
                        url_id = parsed.path.rstrip('/').rsplit('/', 1)[-1]
                        if item_id and url_id.isdigit() and url_id != item_id:
                            issues.append('Walmart item ID and URL mismatch')
                yield RetailProduct(text('retailer'), text('name'), url, normalized_gtin,
                    text('manufacturer'), text('model'), quantity, price,
                    text('availability').lower(), retrieved, text('provenance'),
                    text('asin_hint'), text('variation'), tuple(issues), text('authorization_reference'), context)

# Authorized APIs, licensed feeds and permitted URL resolvers implement products().
# No remote connector is enabled until its authorization and usage contract is reviewed.
