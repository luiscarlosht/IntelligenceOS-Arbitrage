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

    def __post_init__(self):
        import math
        for value in (self.minimum_roi, self.minimum_profit, self.interval):
            if not math.isfinite(value) or value < 0:
                raise ValueError('Thresholds and interval must be finite and nonnegative')
        if self.smtp_security not in ('starttls', 'ssl'):
            raise ValueError('SMTP_SECURITY must be starttls or ssl')
        if not 1 <= self.smtp_port <= 65535:
            raise ValueError('Invalid SMTP_PORT')
        if bool(self.smtp_user) != bool(self.smtp_password):
            raise ValueError('SMTP_USER and SMTP_PASSWORD must be configured together')
        if self.email_to and not (self.smtp_host and self.email_from):
            raise ValueError('Email requires SMTP_HOST and EMAIL_FROM')
        if self.input.resolve() == self.output.resolve() or self.database.resolve() in (self.input.resolve(), self.output.resolve()):
            raise ValueError('Input, output and database paths must differ')

    @classmethod
    def from_env(cls):
        e = os.environ
        return cls(
            input=Path(e.get('ARBITRAGE_INPUT', ROOT / 'sample_data/candidates.csv')),
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
        )
