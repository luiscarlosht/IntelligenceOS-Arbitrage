"""Dormant verified-TLS Keepa transport. Code gate is false; no key is loaded."""
import gzip
import io
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener, HTTPSHandler
import ssl
from typing import Callable

from app import keepa_adapter
from app.keepa_adapter import KeepaRequest, KeepaResponse
from app.ops_notifications import NoRedirect
from app.provider_runtime import ProviderFailure


class KeepaHttpTransport:
    is_mock = False

    def __init__(self, key_loader: Callable[[], str]):
        self._key_loader = key_loader

    def product(self, request: KeepaRequest, *, timeout_seconds: float,
                maximum_bytes: int) -> KeepaResponse:
        if not keepa_adapter.LIVE_CALLS_ENABLED:
            raise ProviderFailure('Live Keepa calls disabled')
        # Unreachable in this release; future activation requires permission review.
        try:
            key = self._key_loader()
            if not isinstance(key, str) or not key.strip(): raise ValueError('API key required')
            params = dict(key=key, domain=request.domain, asin=request.asin,
                          update=request.update, history=request.history, days=request.days)
            req = Request('https://api.keepa.com/product?' + urlencode(params),
                          headers={'Accept-Encoding': 'gzip', 'Accept': 'application/json'})
            opener = build_opener(ProxyHandler({}), NoRedirect(),
                                  HTTPSHandler(context=ssl.create_default_context()))
            try:
                response = opener.open(req, timeout=timeout_seconds)
            except HTTPError as error:
                response = error
            with response:
                if 300 <= response.code < 400: raise ValueError('Redirect rejected')
                wire = response.read(maximum_bytes + 1)
                if len(wire) > maximum_bytes: raise ValueError('Wire response exceeds bound')
                encoding = response.headers.get('Content-Encoding', '').lower()
                if encoding == 'gzip':
                    with gzip.GzipFile(fileobj=io.BytesIO(wire)) as compressed:
                        body = compressed.read(maximum_bytes + 1)
                elif encoding in ('', 'identity'):
                    body = wire
                else:
                    raise ValueError('Unsupported content encoding')
                if len(body) > maximum_bytes: raise ValueError('Decoded response exceeds bound')
                return KeepaResponse(response.code, body)
        except TimeoutError:
            raise TimeoutError('Keepa transport timeout') from None
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise TimeoutError('Keepa transport timeout') from None
            raise ProviderFailure('Keepa transport failed') from None
        except Exception:
            # Never expose urllib exceptions: Keepa puts the API key in its URL.
            raise ProviderFailure('Keepa transport failed') from None
