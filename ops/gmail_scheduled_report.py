"""Opt-in one-report job for the proposed Gmail unit; never installs schedules."""
import os

from app.config import Config
from app.orchestrator import main as report_main


def validate_preparation() -> None:
    """Require explicit activation and OAuth readiness before any job or network."""
    if os.environ.get('ARBITRAGE_GMAIL_SCHEDULE_ENABLED') != 'true':
        raise ValueError('Scheduled Gmail delivery is disabled')
    if os.environ.get('ARBITRAGE_GMAIL_OAUTH_READY') != 'true':
        raise ValueError('Operator OAuth publishing and fresh consent review required')
    config = Config.from_env()
    if (config.email_transport != 'gmail_api' or not config.email_to or
            not config.gmail_token_file or not config.gmail_stage_file or config.interval != 0):
        raise ValueError('One-shot Gmail delivery configuration required')


def main() -> int:
    try:
        validate_preparation()
    except (ValueError, OSError):
        print('Gmail schedule preflight blocked; review activation, OAuth readiness and configuration.')
        return 1
    report_main()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
