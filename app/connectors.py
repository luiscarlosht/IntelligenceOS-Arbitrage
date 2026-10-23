"""Authorized input boundary. No automatic URL fetching or scraping."""
import csv
from pathlib import Path
from typing import Iterable, Protocol
from app.models import RetailProduct
from app.normalization import gtin, integer, money, timestamp, http_url

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
                yield RetailProduct(text('retailer'), text('name'), url, normalized_gtin,
                    text('manufacturer'), text('model'), quantity, price,
                    text('availability').lower(), retrieved, text('provenance'),
                    text('asin_hint'), text('variation'), tuple(issues))

# Authorized APIs, licensed feeds and permitted URL resolvers implement products().
# No remote connector is enabled until its authorization and usage contract is reviewed.
