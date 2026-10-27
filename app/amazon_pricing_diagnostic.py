"""Explicit two-request US pricing diagnostic; no retries or scheduled use."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal

from app.amazon_catalog import ASIN, MARKETPLACE
from app.amazon_details import parse_pricing, serialize
from app.amazon_diagnostics import AmazonFailure, failure_metadata, response_metadata
from app.amazon_pilot import (DIRECTORY, amazon_request, create_file, deadline,
    exchange_token, load_credentials, operation, private_directory, request_json)
from app.provider_runtime import ProviderFailure

REPORT_NAME = 'pricing-diagnostic-01.json'
MAX_REQUESTS = 2


def pricing_once(credentials: dict, *, transport=request_json, is_mock: bool = False,
                 report: dict | None = None) -> dict:
    report = report if report is not None else {}
    report.update(status='running', asin=ASIN, marketplace_id=MARKETPLACE,
        item_condition='New', customer_type='Consumer', is_mock=is_mock,
        started_at=datetime.now(timezone.utc), requests_attempted=0,
        stages={'lwa_exchange': 'not_attempted', 'current_pricing': 'not_attempted'},
        response_diagnostics={}, pricing=None, fees=None, seller_eligible=None,
        purchase_approved=False)
    stage = 'lwa_exchange'

    def call(request):
        if report['requests_attempted'] >= MAX_REQUESTS:
            raise ProviderFailure('Pricing diagnostic request cap reached')
        report['requests_attempted'] += 1
        report['stages'][stage] = 'attempted'
        document = transport(request)
        report['response_diagnostics'][stage] = response_metadata(document)
        return document

    def validation_failure():
        metadata = report['response_diagnostics'].get(stage, {})
        return AmazonFailure('Amazon response validation failed', reason='response_validation_failed',
            http_status=metadata.get('http_status'), codes=tuple(metadata.get('amazon_error_codes', ())))

    try:
        with operation(stage):
            try:
                access = exchange_token(credentials, call)
            except AmazonFailure:
                raise
            except ProviderFailure:
                raise validation_failure() from None
        report['stages'][stage] = 'completed'
        stage = 'current_pricing'
        with operation(stage):
            document = call(amazon_request(access, '/products/pricing/v0/items/' + ASIN + '/offers',
                {'MarketplaceId': MARKETPLACE, 'ItemCondition': 'New', 'CustomerType': 'Consumer'}))
            try:
                report['pricing'] = asdict(parse_pricing(document, is_mock=is_mock))
            except ProviderFailure:
                raise validation_failure() from None
        report['stages'][stage] = 'completed'
        report['status'] = 'success'
        return report
    except (Exception, KeyboardInterrupt):
        report['stages'][stage] = 'failed'
        raise


def run_pricing_diagnostic(path: Path = DIRECTORY) -> None:
    directory = private_directory(path)
    try:
        # Exclusive reservation precedes credential loading and all requests.
        with operation('pricing_report_create'):
            output_fd = create_file(directory, REPORT_NAME)
        with os.fdopen(output_fd, 'w') as output:
            report = {'status': 'failed', 'requests_attempted': 0, 'pricing': None,
                      'fees': None, 'seller_eligible': None, 'purchase_approved': False}
            previous = None
            try:
                previous = signal.signal(signal.SIGALRM, deadline)
                signal.alarm(30)
                with operation('credential_load'):
                    credentials = load_credentials(directory)
                pricing_once(credentials, report=report)
            except (Exception, KeyboardInterrupt) as error:
                report.update(status='failed', reason='operation_failed_no_retry',
                    failed_operation=getattr(error, '_amazon_operation', 'pricing_diagnostic'),
                    failure_diagnostics=failure_metadata(error))
                raise
            finally:
                if previous is not None:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, previous)
                report['finished_at'] = datetime.now(timezone.utc)
                json.dump(report, output, default=serialize, indent=2)
                output.flush()
                os.fsync(output.fileno())
    finally:
        os.close(directory)
