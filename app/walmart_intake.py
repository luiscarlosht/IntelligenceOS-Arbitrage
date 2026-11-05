"""Offline human-reviewed browser observations in the existing M87 format."""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from urllib.parse import urlsplit

from app.evidence_io import digest, json_write, offline, pinned, publication, safe
from app.walmart_evidence import normalize
from app.normalization import gtin


def text(value: object) -> bool:
    return (isinstance(value, str) and 0 < len(value.strip()) <= 2000
            and value.strip().upper() not in ('UNKNOWN', 'TODO', 'UNVERIFIED')
            and not any(ord(c) < 32 for c in value))


def money(value: object, *, positive: bool = False) -> None:
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,9}(\.\d{1,2})?', value):
        raise ValueError('USD amount must be a decimal string with at most two places')
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError('Invalid USD amount') from None
    if not amount.is_finite() or amount < 0 or positive and amount == 0:
        raise ValueError('Invalid USD amount')


def validate(batch: dict, now: datetime, base: Path) -> dict:
    """Validate local attestations, not retailer truth or Amazon equivalence."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Aware evaluation time required')
    if (batch.get('name') != 'm88-real-six-pilot' or batch.get('batch_kind') != 'NEW_PILOT'
            or batch.get('purchase_authorized') is not False):
        raise ValueError('New M88 pilot with purchase_authorized=false required')
    normalize(batch)  # Existing six-row, unique ID and shipping-basis contract.
    result = deepcopy(batch)
    for index, row in enumerate(result['observations'], 1):
        prefix = f'Observation {index}: '
        if row.get('human_reviewed') is not True or not text(row.get('reviewer')):
            raise ValueError(prefix + 'human review and reviewer required')
        if 'amazon' in row:
            raise ValueError(prefix + 'source-only intake cannot assert Amazon evidence')
        product = row['walmart_product']
        for key in ('brand', 'gtin', 'model', 'size'):
            value = product.get(key)
            if value != 'UNKNOWN' and not text(value):
                raise ValueError(prefix + key + ' must be observed text or UNKNOWN')
        if product.get('gtin') != 'UNKNOWN':
            gtin(product['gtin'])
        url = urlsplit(product.get('url') or '')
        if (url.scheme != 'https' or url.netloc not in ('walmart.com', 'www.walmart.com')
                or url.query or url.fragment or not re.fullmatch(
                    r'/ip/(?:[^/]+/)?' + re.escape(product['walmart_item_id']), url.path)):
            raise ValueError(prefix + 'canonical Walmart URL/item ID mismatch')
        for key in ('title', 'variation', 'seller', 'shipping_availability', 'source_reference'):
            if not text(product.get(key)):
                raise ValueError(prefix + key + ' required')
        if type(product.get('pack_quantity')) is not int or not 1 <= product['pack_quantity'] <= 100000:
            raise ValueError(prefix + 'positive integer sellable pack quantity required')
        try:
            observed = datetime.fromisoformat(product['observed_at'])
            if observed.tzinfo is None or observed.utcoffset() is None:
                raise ValueError()
            if not now - timedelta(hours=24) <= observed <= now:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError(prefix + 'aware observation within the last 24 hours required') from None
        evidence = row.get('source_evidence', {})
        if not text(evidence.get('path')) or not text(evidence.get('description')):
            raise ValueError(prefix + 'saved browser evidence path and description required')
        path = safe(base / evidence['path'])
        if digest(path) != evidence.get('sha256'):
            raise ValueError(prefix + 'saved browser evidence hash mismatch')
        metadata = dict(source='human_reviewed_walmart_browser',
                        source_reference=product['source_reference'], observed_at=product['observed_at'],
                        confidence='MEDIUM', verified=True)
        product.update(metadata)
        acquisition = row.get('acquisition', {})
        if set(acquisition) != {'purchase', 'retailer_shipping'}:
            raise ValueError(prefix + 'only purchase and retailer_shipping belong in source intake')
        for key in ('purchase', 'retailer_shipping'):
            observation = acquisition.get(key, {})
            if set(observation) != {'value', 'currency'} or observation['currency'] != 'USD':
                raise ValueError(prefix + 'USD value/currency required')
            if key == 'retailer_shipping' and observation['value'] is None:
                observation['value'] = 'UNKNOWN'
            else:
                money(observation['value'], positive=key == 'purchase')
            observation.update(metadata)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    source = safe(args.input)
    with publication(args.output, [source]) as stage:
        with offline(reads=[source], writes=[stage]):
            batch = validate(pinned(source, args.sha256), datetime.now(timezone.utc), source.parent)
            batch['source_inventory'] = [dict(path=str(source), sha256=args.sha256,
                                              role='human-reviewed browser intake')]
            json_write(stage / 'm87-batch.json', batch)
            if digest(source) != args.sha256:
                raise ValueError('Source changed during import')
            for row in batch['observations']:
                evidence = row['source_evidence']
                if digest(source.parent / evidence['path']) != evidence['sha256']:
                    raise ValueError('Browser evidence changed during import')
            json_write(stage / 'validation.json', dict(status='VALIDATED_HUMAN_ATTESTATIONS',
                products=6, purchase_authorized=False, network_requests=0,
                amazon_match_status='UNRESOLVED', source_sha256=args.sha256))


if __name__ == '__main__':
    main()
