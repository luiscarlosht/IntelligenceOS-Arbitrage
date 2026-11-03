"""Normalized manual inputs. Future providers implement the same offline boundary."""
from copy import deepcopy
import json
from typing import Protocol

from app.amazon_evaluation import mapping
from app.amazon_evaluation_sheets import HEADERS, seed, snapshot
from app.amazon_research_queue import SOURCE
from app.sheets_publisher import index

MARKET_FIELDS = ('current_price', 'historical_30d', 'historical_90d', 'sales_rank',
                 'category', 'monthly_sales', 'competing_offers', 'price_volatility')


class AnalysisProvider(Protocol):
    """Return normalized per-ASIN records; never infer fees, eligibility or demand."""
    def records(self) -> list[dict]: ...


class ManualAmazon:
    """Manual Seller Central / Revenue Calculator input in the existing PR82 schema."""
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def records(self) -> list[dict]:
        if not isinstance(self.rows, list) or not 1 <= len(self.rows) <= 1000:
            raise ValueError('1–1000 manual records required')
        keys = [r.get('asin') for r in self.rows]
        if len(keys) != len(set(keys)):
            raise ValueError('Duplicate ASIN')
        return deepcopy(self.rows)


class ManualKeepa:
    """Attach attributed market-only observations; never promote rank into sales."""
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def merge(self, records: list[dict]) -> list[dict]:
        result = ManualAmazon(records).records()
        positions = {r['asin']: r for r in result}
        seen = set()
        for patch in self.rows:
            asin = patch.get('asin')
            if asin not in positions or asin in seen or set(patch) != {'asin', 'market'}:
                raise ValueError('Unique known ASIN and market-only Keepa patch required')
            seen.add(asin)
            target = positions[asin].setdefault('market', {})
            for key, observation in patch['market'].items():
                if key not in MARKET_FIELDS or not isinstance(observation, dict):
                    raise ValueError('Unsupported Keepa observation')
                # Conflicting records are not silently replaced by a newer source.
                if key in target and target[key] != observation:
                    raise ValueError('Conflicting market observation')
                target[key] = deepcopy(observation)
        return result


class SheetsEvidence:
    """Read existing PR82 rows using its bounded reader and publisher-owned schema."""
    def __init__(self, client):
        self.client = client

    def records(self) -> list[dict]:
        self.client.select(SOURCE)
        values = snapshot(self.client, self.client.metadata())
        positions, _ = index(values, HEADERS)
        rows = []
        for asin, n in positions.items():
            row = values[n]
            if len(row) < len(HEADERS):
                raise ValueError('Incomplete evaluation row')
            record = json.loads(row[HEADERS.index('manual_evidence_json')])
            if record.get('asin') != asin:
                raise ValueError('Sheet/JSON ASIN conflict')
            expected = seed(record)
            record['input_conflicts'] = [key for key in ('eligibility_status', 'approval_requirements')
                                        if str(row[HEADERS.index(key)]) != expected[HEADERS.index(key)]]
            rows.append(record)
        return ManualAmazon(rows).records()


def legacy_market(record: dict) -> dict:
    """Keep PR82 descriptive observations; explicitly unknown metadata stays unknown."""
    market = deepcopy(mapping(record.get('market')))
    view = mapping(record.get('observations'))
    names = dict(current_price='amazon_selling_price', historical_30d='keepa_30_day_price_statistics',
        historical_90d='keepa_90_day_price_statistics', sales_rank='sales_rank', category='category',
        monthly_sales='estimated_monthly_sales', competing_offers='competing_offers')
    for key, name in names.items():
        if key in market:
            continue
        if key in ('monthly_sales', 'competing_offers') and isinstance(record.get(key), dict):
            market[key] = deepcopy(record[key])
        elif name in view:
            market[key] = dict(value=view[name], source=view.get('evidence_source', 'UNKNOWN'),
                observed_at=view.get('price_observed_at' if key == 'current_price' else 'evidence_observed_at', 'UNKNOWN'),
                confidence=view.get('data_confidence', 'UNKNOWN'), condition='UNKNOWN',
                basis=view.get('price_basis', 'UNKNOWN') if key == 'current_price' else 'UNKNOWN')
    return market
