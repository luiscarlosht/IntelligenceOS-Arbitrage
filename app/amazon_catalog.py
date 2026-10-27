"""Conservative Catalog Items mappings; no network or inferred identity."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import re

from app.marketplace import match_listings
from app.models import MarketplaceListing, Match, RetailProduct
from app.normalization import gtin
from app.provider_contracts import Evidence
from app.provider_runtime import ProviderFailure

ASIN = 'B002XQ1R06'
MARKETPLACE = 'ATVPDKIKX0DER'
INCLUDED_DATA = 'summaries,identifiers,relationships'


@dataclass(frozen=True)
class CatalogIdentifier:
    identifier_type: str
    value: str
    normalized_gtin: str


@dataclass(frozen=True)
class CatalogRelationship:
    relationship_type: str
    parent_asins: tuple[str, ...]
    child_asins: tuple[str, ...]
    theme: str
    theme_attributes: tuple[str, ...]


@dataclass(frozen=True)
class AmazonCatalogListing(MarketplaceListing):
    title: str = ''
    identifiers: tuple[CatalogIdentifier, ...] = ()
    relationships: tuple[CatalogRelationship, ...] = ()
    item_classification: str = ''
    mapping_issues: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()


def clean_text(value: object, secrets: tuple[str, ...] = ()) -> str:
    if not isinstance(value, str):
        return ''
    for secret in secrets:
        if secret:
            value = value.replace(secret, '[REDACTED]')
    return ''.join(c for c in value if c.isprintable()).strip()[:512]


def marketplace_row(data: dict, key: str) -> dict | None:
    rows = data.get(key, [])
    if not isinstance(rows, list):
        raise ProviderFailure('Invalid catalog dataset')
    matches = [r for r in rows if isinstance(r, dict) and r.get('marketplaceId') == MARKETPLACE]
    if len(matches) > 1:
        raise ProviderFailure('Ambiguous catalog marketplace')
    return matches[0] if matches else None


def parse_catalog(data: dict, *, is_mock: bool, secrets: tuple[str, ...] = (),
                  expected_asin: str = ASIN) -> Evidence[MarketplaceListing]:
    if not isinstance(expected_asin, str) or not re.fullmatch(r'[A-Z0-9]{10}', expected_asin):
        raise ProviderFailure('Invalid requested ASIN')
    if data.get('asin') != expected_asin:
        raise ProviderFailure('Catalog ASIN mismatch')
    summary = marketplace_row(data, 'summaries')
    if summary is None:
        raise ProviderFailure('US catalog summary missing')
    issues: list[str] = []
    quantity = summary.get('packageQuantity')
    if quantity is not None and (type(quantity) is not int or quantity <= 0):
        quantity = None
        issues.append('Invalid package quantity')
    identifiers = []
    id_row = marketplace_row(data, 'identifiers')
    id_values = id_row.get('identifiers', []) if id_row else []
    if not isinstance(id_values, list):
        raise ProviderFailure('Invalid identifiers')
    for row in id_values:
        if not isinstance(row, dict):
            raise ProviderFailure('Invalid identifier')
        kind = clean_text(row.get('identifierType'), secrets)
        value = clean_text(row.get('identifier'), secrets)
        canonical = ''
        if kind in ('UPC', 'EAN', 'GTIN'):
            expected = {'UPC': (12,), 'EAN': (8, 13), 'GTIN': (14,)}[kind]
            try:
                if len(value) not in expected:
                    raise ValueError('Identifier length')
                canonical = gtin(value)
            except ValueError:
                issues.append('Invalid GTIN identifier')
        identifiers.append(CatalogIdentifier(kind, value, canonical))
    canonical_ids = {identifier.normalized_gtin for identifier in identifiers if identifier.normalized_gtin}
    if len(canonical_ids) > 1:
        issues.append('Ambiguous GTIN identifiers')
    relationships = []
    rel_row = marketplace_row(data, 'relationships')
    rel_values = rel_row.get('relationships', []) if rel_row else []
    if not isinstance(rel_values, list):
        raise ProviderFailure('Invalid relationships')
    for row in rel_values:
        if not isinstance(row, dict):
            raise ProviderFailure('Invalid relationship')
        def asins(key):
            values = row.get(key, [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not re.fullmatch(r'[A-Z0-9]{10}', v) for v in values):
                raise ProviderFailure('Invalid relationship ASINs')
            return tuple(values)
        theme = row.get('variationTheme') or {}
        if not isinstance(theme, dict) or not isinstance(theme.get('attributes', []), list):
            raise ProviderFailure('Invalid variation theme')
        relationships.append(CatalogRelationship(clean_text(row.get('type'), secrets),
            asins('parentAsins'), asins('childAsins'), clean_text(theme.get('theme'), secrets),
            tuple(clean_text(v, secrets) for v in theme.get('attributes', []))))
    classification = clean_text(summary.get('itemClassification'), secrets)
    variation_values = {key: clean_text(summary.get(key), secrets) for key in ('color', 'size', 'style')}
    variation_values = {key: value for key, value in variation_values.items() if value}
    variation = json.dumps(variation_values, sort_keys=True) if variation_values else ''
    # Never call absent relationships a standalone/no-variation product. Preserve
    # unsupported theme dimensions as missing, rather than equating two variants.
    if rel_row is None:
        issues.append('Variation relationships unavailable')
        variation = ''
    for relationship in relationships:
        if relationship.relationship_type == 'VARIATION':
            if relationship.child_asins or classification == 'VARIATION_PARENT':
                issues.append('Variation parent is not a verified purchasable child')
                variation = ''
            if not relationship.theme_attributes or any(key not in variation_values for key in relationship.theme_attributes):
                issues.append('Variation theme values incomplete')
                variation = ''
        elif relationship.relationship_type == 'PACKAGE_HIERARCHY':
            issues.append('Package hierarchy requires source verification')
        else:
            issues.append('Unknown relationship type')
    if classification == 'VARIATION_PARENT':
        variation = ''
        if 'Variation parent is not a verified purchasable child' not in issues:
            issues.append('Variation parent is not a verified purchasable child')
    now = datetime.now(timezone.utc)
    provenance = 'Amazon SP-API Catalog Items 2022-04-01; US; ' + INCLUDED_DATA
    text = lambda key: clean_text(summary.get(key), secrets)
    fields = dict(title=text('itemName'), gtin=next(iter(canonical_ids)) if len(canonical_ids) == 1 else '',
                  manufacturer=text('manufacturer'), model=text('modelNumber'),
                  package_quantity=quantity, variation=variation)
    missing = tuple(key for key, value in fields.items() if value is None or value == '')
    listing = AmazonCatalogListing(asin=expected_asin, **fields, seller_eligible=None, sale_price=None,
        costs={'referral_fee': None, 'fulfillment_fee': None}, retrieved_at=now, provenance=provenance,
        is_mock=is_mock, identifiers=tuple(identifiers), relationships=tuple(relationships),
        item_classification=classification, mapping_issues=tuple(dict.fromkeys(issues)), missing_fields=missing)
    return Evidence(listing, now, provenance, is_mock=is_mock)


class AmazonCatalogAdapter:
    """Reuse existing catalog and matching contracts without registering a live provider."""
    def __init__(self, catalog: Evidence[MarketplaceListing]):
        self.catalog = catalog

    def candidates(self, product: RetailProduct) -> tuple[Evidence[MarketplaceListing], ...]:
        return (self.catalog,) if self.catalog.value is not None else ()

    def match(self, product: RetailProduct) -> Match:
        if self.catalog.value is None:
            return Match(None, False, Decimal('0'), ('Catalog evidence missing',))
        result = match_listings(product, (self.catalog.value,))
        issues = getattr(self.catalog.value, 'mapping_issues', ())
        if issues:
            return Match(result.listing, False, Decimal('0'), result.reasons + issues)
        return result
