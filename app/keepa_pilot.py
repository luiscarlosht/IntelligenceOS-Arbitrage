"""Offline pilot preparation. No credentials loaded and no network calls made."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import getpass
import json
import sys
import os
from pathlib import Path
import warnings

from app import keepa_adapter
from app.keepa_adapter import KeepaRequest, MAX_RESPONSE_BYTES, history_point, keepa_time
from app.keepa_http import KeepaHttpTransport

PILOT_ASIN = 'B002XQ1R06'
ATTEMPT_MARKER = Path(__file__).resolve().parents[1] / 'var/keepa-pilot/B002XQ1R06.attempted'


def read_pilot_key() -> str:
    """Future verified no-charge runner: terminal-only, memory-only secret entry.

    Deliberately not called by this preparation CLI. Never fall back to echoed
    stdin, command arguments, production credentials or environment files.
    """
    if not sys.stdin.isatty():
        raise ValueError('Secure entry requires a private interactive terminal')
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        key = getpass.getpass('Keepa pilot API key (hidden, memory only): ')
    if not key or any(c.isspace() for c in key):
        raise ValueError('Invalid API key')
    return key


def summarize(reply, now: datetime) -> dict:
    """Allowlist output; never echo raw bodies, provider errors or URLs."""
    if not isinstance(reply.body, bytes) or len(reply.body) > MAX_RESPONSE_BYTES:
        raise ValueError('Invalid response')
    payload = json.loads(reply.body)
    if not isinstance(payload, dict):
        raise ValueError('Invalid response')
    consumed = payload.get('tokensConsumed')
    usage = consumed if type(consumed) is int and consumed >= 0 else None
    result = dict(asin=PILOT_ASIN, title=None, price_usd=None,
                  price_source=None, price_observed_at=None, product_observed_at=None,
                  fetched_at=now.isoformat(), tokens_consumed=usage,
                  fees=None, seller_eligibility=None, status='stopped',
                  actual_requests=1, maximum_tokens=1)
    if reply.status != 200 or payload.get('error') or usage not in (0, 1):
        result['status'] = 'stopped: response unsuccessful or token usage missing/exceeds cap; no retry'
        return result
    products = payload.get('products')
    if not isinstance(products, list) or len(products) > 1:
        return result
    if not products:
        result['status'] = 'no product returned; no retry'
        return result
    row = products[0]
    if not isinstance(row, dict) or row.get('asin') != PILOT_ASIN or row.get('domainId') != 1:
        return result
    result['title'] = row.get('title') if isinstance(row.get('title'), str) else None
    stamp = keepa_time(row.get('lastUpdate'))
    if stamp and stamp <= now:
        result['product_observed_at'] = stamp.isoformat()
    histories = row.get('csv')
    if isinstance(histories, list):
        # Prefer Amazon; otherwise explicitly label the marketplace NEW series.
        for index, source in ((0, 'Amazon history'), (1, 'Marketplace new history')):
            point = history_point(histories[index], now) if len(histories) > index else None
            if point and point[1] > 0:
                result.update(price_usd=f'{point[1] / 100:.2f}', price_source=source,
                              price_observed_at=point[0].isoformat())
                break
    result['status'] = 'returned historical evidence; current availability unknown'
    return result


def run_once() -> dict:
    """One authorized ASIN, one attempt for this checkout, memory-only key."""
    if not keepa_adapter.LIVE_CALLS_ENABLED:
        raise ValueError('Live Keepa calls disabled; offline preparation only')
    if ATTEMPT_MARKER.exists():
        raise ValueError('Pilot already attempted; no retry permitted')
    key = read_pilot_key()
    ATTEMPT_MARKER.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive durable reservation before network; ambiguous failures consume it.
    fd = os.open(ATTEMPT_MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as marker:
        marker.write('One-token attempt reserved; no retries. No credentials stored.\n')
        marker.flush()
        os.fsync(marker.fileno())
    try:
        reply = KeepaHttpTransport(lambda: key).pilot_product_once()
        return summarize(reply, datetime.now(timezone.utc))
    finally:
        key = ''


def prepare(asins: list[str]) -> dict:
    if len(asins) > 5 or len(set(asins)) != len(asins):
        raise ValueError('Select at most five distinct ASINs')
    requests = []
    for asin in asins:
        params = asdict(KeepaRequest(asin))
        requests.append(dict(method='GET', endpoint='https://api.keepa.com/product',
                             parameters=params, authentication='key injected privately; omitted',
                             headers={'Accept': 'application/json', 'Accept-Encoding': 'gzip'},
                             maximum_attempts=1, maximum_tokens=1))
    return dict(
        prepared_at=datetime.now(timezone.utc).isoformat(),
        status='STOPPED: no-charge account entitlement not verified',
        selected_asins=asins, requests=requests,
        maximum_requests=len(requests), maximum_tokens=len(requests),
        maximum_for_five_asins=5, actual_requests=0, tokens_consumed=0,
        selection_status='selected' if asins else 'pending user selection; no requests planned',
        live_execution_available=False,
        retry_policy='No retries, refill waits, pagination or recurring requests',
        evidence=[dict(asin=asin, status='not fetched', data_returned=None,
                       missing=['catalog', 'Amazon price', 'rank', 'monthlySold',
                                'observation timestamps', 'seller eligibility', 'fees'],
                       stale='unknown: no observations', seller_eligibility=None, fees=None)
                  for asin in asins],
        usefulness='Not yet assessed from live data. Historical catalog, Amazon price, rank and '
                   'monthlySold lower bounds may help shortlist research. They cannot establish '
                   'exact package/variation match, an assured resale price, seller eligibility, '
                   'complete fees, net profit or purchase approval.',
        limitations=['US domain only; update=-1 never refreshes Amazon data',
                     'One day of history; missing data stays unknown',
                     'No-charge access must be established outside this offline tool',
                     'Token bound assumes documented basic-request pricing',
                     'Production configuration and schedules unchanged'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asin', action='append', default=[], help='User-selected US ASIN; repeat up to five times')
    parser.add_argument('--run-once', action='store_true', help='Authorized single lookup of B002XQ1R06 with hidden key entry')
    args = parser.parse_args()
    if args.run_once:
        if args.asin:
            parser.error('--run-once fixes ASIN B002XQ1R06; omit --asin')
        try:
            # Prevent process core dumps from persisting the in-memory key.
            import resource
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            result = run_once()
        except (Exception, KeyboardInterrupt):
            print('Pilot stopped. No retry performed; usage unknown if request began.', file=sys.stderr)
            raise SystemExit(1) from None
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return
    try:
        result = prepare(args.asin)
    except ValueError:
        parser.error('Select at most five distinct uppercase alphanumeric ASINs of length ten')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
