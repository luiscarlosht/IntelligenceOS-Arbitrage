"""Manually invoked Amazon US catalog pilot; never registered with the job runner."""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import errno
import getpass
import json
import os
from pathlib import Path
import signal
import ssl
import stat
import warnings
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, HTTPSHandler, build_opener

from app.amazon_diagnostics import (AmazonFailure, ResponseDocument, MAX_ERROR_BYTES,
    bounded_error_codes, failure_metadata)
from app.amazon_catalog import ASIN, MARKETPLACE, INCLUDED_DATA, parse_catalog
from app.models import MarketplaceListing
from app.provider_contracts import Evidence
from app.provider_runtime import ProviderFailure
from app.ops_notifications import NoRedirect

DIRECTORY = Path.home() / '.intelligenceos-arbitrage-amazon'
FIELDS = ('client_id', 'client_secret', 'refresh_token')
MAX_BYTES = 1024 * 1024


@contextmanager
def operation(name: str):
    """Attach a fixed operation label; never retain exception text in diagnostics."""
    try:
        yield
    except (Exception, KeyboardInterrupt) as error:
        if not hasattr(error, '_amazon_operation'):
            error._amazon_operation = name
        raise


def failure_diagnostic(error: BaseException) -> str:
    number = getattr(error, 'errno', None)
    extra = failure_metadata(error)
    suffix = (' http_status=' + str(extra['http_status'])
              + ' amazon_error_codes=' + ','.join(extra['amazon_error_codes'])
              + ' reason=' + extra['reason']
              + (' validation_label=' + extra['validation_label'] if extra.get('validation_label') else '')) if isinstance(error, AmazonFailure) else ''
    return ('Amazon operation failed; no retry. operation='
            + getattr(error, '_amazon_operation', 'pilot')
            + ' exception=' + type(error).__name__
            + ' errno=' + (str(number) if type(number) is int else 'none') + suffix)


def private_directory(path: Path) -> int:
    """Return a pinned, owner-only directory descriptor, rejecting symlinks."""
    with operation('directory_location_check'):
        repository = Path(__file__).resolve().parent.parent
        if path.resolve().is_relative_to(repository):
            raise ValueError('Amazon private storage must be outside the repository')
    with operation('directory_create'):
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    with operation('directory_open'):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with operation('directory_security_check'):
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError('Private directory ownership or permissions invalid')
    except BaseException:
        os.close(fd)
        raise
    return fd


def create_file(directory: int, name: str) -> int:
    return os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                   0o600, dir_fd=directory)


def enter_credentials(path: Path = DIRECTORY) -> None:
    # Text read/write mode (r+) rejects nonseekable terminals. This stream is
    # output-only; getpass opens the controlling terminal separately for input.
    with operation('terminal_open'):
        terminal = open('/dev/tty', 'w')
    with terminal:
        with operation('terminal_isatty'):
            if not terminal.isatty():
                raise ValueError('Hidden terminal input required')
        directory = private_directory(path)
        try:
            with operation('credential_existence_check'):
                try:
                    os.stat('credentials.json', dir_fd=directory, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise FileExistsError(errno.EEXIST, 'Credential file already exists')
            with operation('hidden_prompt'):
                with warnings.catch_warnings():
                    warnings.simplefilter('error', getpass.GetPassWarning)
                    values = {name: getpass.getpass(name + ': ', stream=terminal) for name in FIELDS}
            with operation('credential_input_validation'):
                if any(not v.strip() or len(v) > 8192 or '\n' in v or '\r' in v for v in values.values()):
                    raise ValueError('Invalid credential input')
            with operation('credential_file_create'):
                output_fd = create_file(directory, 'credentials.json')
            with operation('credential_file_write'):
                with os.fdopen(output_fd, 'w') as output:
                    json.dump(values, output)
                    output.flush()
                    os.fsync(output.fileno())
        finally:
            os.close(directory)


def load_credentials(directory: int) -> dict:
    fd = os.open('credentials.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd) as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise ValueError('Invalid credential file security')
        data = source.read(32769)
    if len(data) > 32768:
        raise ValueError('Credential file too large')
    values = json.loads(data)
    if not isinstance(values, dict) or set(values) != set(FIELDS) or any(
            not isinstance(v, str) or not v.strip() or len(v) > 8192 or '\r' in v or '\n' in v
            for v in values.values()):
        raise ValueError('Invalid credential file')
    return values


def request_json(request: Request) -> dict:
    """Verified TLS, no proxies/redirects/retries; only safe HTTP/code metadata."""
    status = None
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(request, timeout=10) as response:
            status = response.status
            if status != 200:
                body = response.read(MAX_ERROR_BYTES + 1)
                raise AmazonFailure('Amazon response rejected', reason='http_error', http_status=status,
                                    codes=bounded_error_codes(body))
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise AmazonFailure('Amazon response exceeds bound', reason='response_too_large', http_status=status)
            try:
                result = json.loads(body)
            except (ValueError, UnicodeError):
                raise AmazonFailure('Amazon response invalid', reason='invalid_json', http_status=status) from None
            if not isinstance(result, dict):
                raise AmazonFailure('Amazon response invalid', reason='invalid_response', http_status=status)
            return ResponseDocument(result, status)
    except HTTPError as error:
        status = error.code
        try:
            try:
                codes = bounded_error_codes(error.read(MAX_ERROR_BYTES + 1))
            except Exception:
                codes = ()
        finally:
            error.close()
        message = {400: 'invalid_request', 401: 'unauthorized', 403: 'forbidden',
                   404: 'not_found', 429: 'throttled'}.get(status, 'http_failure')
        raise AmazonFailure(message, reason='http_error', http_status=status, codes=codes) from None
    except AmazonFailure:
        raise
    except Exception:
        raise AmazonFailure('Amazon transport or response failed', reason='transport_error', http_status=status) from None


def exchange_token(credentials: dict, transport=request_json) -> str:
    token = transport(Request('https://api.amazon.com/auth/o2/token',
        data=urlencode({'grant_type': 'refresh_token', **credentials}).encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'}))
    access = token.get('access_token')
    if (not isinstance(access, str) or not access or len(access) > 2048
            or '\r' in access or '\n' in access or str(token.get('token_type', '')).lower() != 'bearer'):
        raise ProviderFailure('Invalid token response')
    return access


def amazon_request(access: str, path: str, params: dict | None = None, body: dict | None = None) -> Request:
    url = 'https://sellingpartnerapi-na.amazon.com' + path
    if params:
        url += '?' + urlencode(params)
    headers = {'x-amz-access-token': access, 'x-amz-date': datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
               'User-Agent': 'IntelligenceOSArbitrage/0.3 (Language=Python/3.12)'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    return Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)


def catalog_request(access: str) -> Request:
    return amazon_request(access, '/catalog/2022-04-01/items/' + ASIN,
                          {'marketplaceIds': MARKETPLACE, 'includedData': INCLUDED_DATA})


def catalog_once(credentials: dict, transport=request_json, *, is_mock: bool = False) -> Evidence[MarketplaceListing]:
    access = exchange_token(credentials, transport)
    return parse_catalog(transport(catalog_request(access)), is_mock=is_mock,
                         secrets=(*credentials.values(), access))


def deadline(signum, frame):
    raise TimeoutError('Pilot deadline exceeded')


def run_pilot(path: Path = DIRECTORY) -> None:
    directory = private_directory(path)
    try:
        # Reserve the report before reading credentials or calling Amazon; never overwrite.
        with os.fdopen(create_file(directory, 'catalog-pilot.json'), 'w') as output:
            report = {'status': 'failed', 'reason': 'pilot_interrupted_no_retry'}
            previous = signal.signal(signal.SIGALRM, deadline)
            signal.alarm(30)
            try:
                evidence = catalog_once(load_credentials(directory))
                report = {'status': 'success', 'marketplace_id': MARKETPLACE, 'catalog': asdict(evidence)}
            except Exception:
                report = {'status': 'failed', 'reason': 'pilot_failed_no_retry'}
                raise
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous)
                json.dump(report, output, default=lambda v: v.isoformat(), indent=2)
                output.flush()
                os.fsync(output.fileno())
    finally:
        os.close(directory)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('credentials', 'pilot', 'details', 'pricing-diagnostic', 'pricing-shape-diagnostic', 'pricing-selected-pilot'))
    parser.add_argument('--fee-price', help='Proposed USD FBA sale price; required for details')
    parser.add_argument('--asin', help='One operator-selected Amazon US ASIN; required only for pricing-selected-pilot')
    args = parser.parse_args()
    if (args.action == 'pricing-selected-pilot') != (args.asin is not None):
        parser.error('--asin is required only with pricing-selected-pilot')
    if (args.action == 'details') != (args.fee_price is not None):
        parser.error('--fee-price is required only with details')
    try:
        if args.action == 'credentials':
            enter_credentials()
        elif args.action == 'pilot':
            run_pilot()
        elif args.action in ('pricing-diagnostic', 'pricing-shape-diagnostic', 'pricing-selected-pilot'):
            from app.amazon_pricing_diagnostic import run_pricing_diagnostic
            if args.action == 'pricing-selected-pilot':
                run_pricing_diagnostic(selected_asin=args.asin)
            elif args.action == 'pricing-shape-diagnostic':
                run_pricing_diagnostic(shape_only=True)
            else:
                run_pricing_diagnostic()
        else:
            from app.amazon_details import run_details, proposed_price
            run_details(proposed_price(args.fee_price))
    except (Exception, KeyboardInterrupt) as error:
        print(failure_diagnostic(error))
        return 1
    print('Amazon operation completed; private file created.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
