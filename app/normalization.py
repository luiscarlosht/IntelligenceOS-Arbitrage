"""Conservative identifiers and values; never invent missing evidence."""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit


def money(value) -> Decimal | None:
    if value is None or str(value).strip() == '': return None
    try:
        result = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError('Invalid monetary value') from None
    if not result.is_finite() or result < 0:
        raise ValueError('Monetary values must be finite and nonnegative')
    return result


def integer(value) -> int | None:
    if value is None or str(value).strip() == '': return None
    if not re.fullmatch(r'[0-9]+', str(value).strip()): raise ValueError('Invalid nonnegative integer')
    return int(str(value).strip())


def gtin(value: str) -> str:
    value = (value or '').strip()
    if not value: return ''
    if not re.fullmatch(r'(?:[0-9]{8}|[0-9]{12}|[0-9]{13}|[0-9]{14})', value):
        raise ValueError('GTIN must contain 8, 12, 13 or 14 digits')
    expected = (10 - sum(int(c) * (3 if i % 2 == 0 else 1)
                        for i, c in enumerate(reversed(value[:-1]))) % 10) % 10
    if int(value[-1]) != expected: raise ValueError('GTIN checksum mismatch')
    return value.zfill(14)


def timestamp(value: str) -> datetime | None:
    if not value or not value.strip(): return None
    try:
        result = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Invalid retrieval timestamp') from None
    if result.tzinfo is None: raise ValueError('Retrieval timestamp requires a timezone')
    return result


def http_url(value: str) -> bool:
    try:
        url = urlsplit(value)
        return url.scheme in ('http', 'https') and bool(url.hostname) and not (url.username or url.password)
    except ValueError:
        return False


def identity(value: str) -> str:
    # Case and whitespace only; punctuation can distinguish models or variations.
    return ' '.join(value.casefold().split())
