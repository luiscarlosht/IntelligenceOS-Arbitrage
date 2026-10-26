"""Environment-only configuration; no credentials are persisted in history."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class Config:
    input: Path
    output: Path
    database: Path
    minimum_roi: float = 50
    minimum_profit: float = 5
    interval: float = 0
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: str = ''
    email_from: str = ''
    email_to: tuple[str, ...] = ()
    smtp_security: str = 'starttls'
    email_transport: str = 'smtp'
    gmail_token_file: Path | None = None
    gmail_stage_file: Path | None = None
    mode: str = 'legacy'
    amazon_provider: str = 'mock'
    amazon_fixture: Path = ROOT / 'sample_data/amazon_mock.json'
    minimum_monthly_sales: int = 30
    maximum_offers: int = 15
    maximum_data_age_hours: float = 24
    inventory_budget: float = 500
    top_count: int = 20
    maximum_candidates: int = 10000

    def __post_init__(self):
        import math
        if self.mode not in ('legacy', 'discovery'): raise ValueError('ARBITRAGE_MODE must be legacy or discovery')
        if self.amazon_provider != 'mock': raise ValueError('Only the mock Amazon provider is currently supported')
        for value in (self.maximum_data_age_hours, self.inventory_budget):
            if not math.isfinite(value) or value <= 0: raise ValueError('Data age and inventory budget must be positive and finite')
        for value in (self.minimum_monthly_sales, self.maximum_offers, self.top_count, self.maximum_candidates):
            if type(value) is not int or value < 0: raise ValueError('Counts must be nonnegative integers')
        if self.top_count == 0 or self.maximum_candidates == 0: raise ValueError('Output and candidate limits must be positive')
        if self.mode == 'discovery' and self.amazon_fixture.resolve() in (self.output.resolve(), self.database.resolve(), self.input.resolve()):
            raise ValueError('Marketplace fixture must use a separate input path')
        for value in (self.minimum_roi, self.minimum_profit, self.interval):
            if not math.isfinite(value) or value < 0:
                raise ValueError('Thresholds and interval must be finite and nonnegative')
        if self.smtp_security not in ('starttls', 'ssl'):
            raise ValueError('SMTP_SECURITY must be starttls or ssl')
        if not 1 <= self.smtp_port <= 65535:
            raise ValueError('Invalid SMTP_PORT')
        if bool(self.smtp_user) != bool(self.smtp_password):
            raise ValueError('SMTP_USER and SMTP_PASSWORD must be configured together')
        if self.email_transport not in ('smtp', 'gmail_api'):
            raise ValueError('ARBITRAGE_EMAIL_TRANSPORT must be smtp or gmail_api')
        if self.email_to and self.email_transport == 'gmail_api' and not (self.gmail_token_file and self.email_from):
            raise ValueError('Gmail API requires ARBITRAGE_GMAIL_TOKEN_FILE and EMAIL_FROM')
        if self.email_to and self.email_transport == 'smtp' and not (self.smtp_host and self.email_from):
            raise ValueError('Email requires SMTP_HOST and EMAIL_FROM')
        if self.input.resolve() == self.output.resolve() or self.database.resolve() in (self.input.resolve(), self.output.resolve()):
            raise ValueError('Input, output and database paths must differ')

    @classmethod
    def from_env(cls):
        e = os.environ
        return cls(
            input=Path(e.get('ARBITRAGE_INPUT', ROOT / ('sample_data/discovery.csv' if e.get('ARBITRAGE_MODE') == 'discovery' else 'sample_data/candidates.csv'))),
            output=Path(e.get('ARBITRAGE_REPORT', ROOT / 'var/opportunities.xlsx')),
            database=Path(e.get('ARBITRAGE_DB', ROOT / 'var/history.sqlite3')),
            minimum_roi=float(e.get('MINIMUM_ROI', '50')),
            minimum_profit=float(e.get('MINIMUM_PROFIT', '5')),
            interval=float(e.get('JOB_INTERVAL_SECONDS', '0')),
            smtp_host=e.get('SMTP_HOST', ''), smtp_port=int(e.get('SMTP_PORT', '587')),
            smtp_user=e.get('SMTP_USER', ''), smtp_password=e.get('SMTP_PASSWORD', ''),
            email_from=e.get('EMAIL_FROM', ''),
            email_to=tuple(x.strip() for x in e.get('EMAIL_TO', '').split(',') if x.strip()),
            smtp_security=e.get('SMTP_SECURITY', 'starttls'),
            email_transport=e.get('ARBITRAGE_EMAIL_TRANSPORT', 'smtp'),
            gmail_token_file=Path(e['ARBITRAGE_GMAIL_TOKEN_FILE']) if e.get('ARBITRAGE_GMAIL_TOKEN_FILE') else None,
            gmail_stage_file=Path(e['ARBITRAGE_GMAIL_STAGE_FILE']) if e.get('ARBITRAGE_GMAIL_STAGE_FILE') else None,
            mode=e.get('ARBITRAGE_MODE', 'legacy'),
            amazon_provider=e.get('AMAZON_PROVIDER', 'mock'),
            amazon_fixture=Path(e.get('AMAZON_MOCK_FILE', ROOT / 'sample_data/amazon_mock.json')),
            minimum_monthly_sales=int(e.get('MINIMUM_MONTHLY_SALES', '30')),
            maximum_offers=int(e.get('MAXIMUM_OFFERS', '15')),
            maximum_data_age_hours=float(e.get('MAXIMUM_DATA_AGE_HOURS', '24')),
            inventory_budget=float(e.get('INVENTORY_BUDGET', '500')),
            top_count=int(e.get('TOP_OPPORTUNITIES', '20')),
            maximum_candidates=int(e.get('MAXIMUM_CANDIDATES', '10000')),
        )
