"""One-shot allowlisted adapter. Importing it never authenticates or sends."""
from urllib.parse import urlsplit, parse_qs
from app.m65_batch import PATH
from app.m65_intelligence import US, CONDITION


class AmazonTransport:
    """Existing TLS/no-proxy/no-redirect transport; no SDK token refresh layer."""
    def __init__(self, credentials: dict, seller_id: str):
        self.credentials = credentials
        self.seller_id = seller_id
        self.access = None

    def request(self, kind: str, asin: str | None, dispatch):
        from app import amazon_pilot
        if kind == 'authentication' and asin is None and self.access is None:
            self.access = amazon_pilot.exchange_token(self.credentials, lambda req: dispatch(req))
            return None
        if kind != 'restrictions' or asin is None or not self.access:
            raise ValueError('Transport scope invalid')
        req = amazon_pilot.amazon_request(self.access, PATH, dict(asin=asin, sellerId=self.seller_id,
            marketplaceIds=US, conditionType=CONDITION, reasonLocale='en_US'))
        return dispatch(req)

    def send(self, req, kind: str, asin: str | None):
        self.validate(req, kind, asin)
        from app.amazon_pilot import _request_json
        return _request_json(req)

    def validate(self, req, kind: str, asin: str | None) -> None:
        parsed = urlsplit(req.full_url)
        if parsed.scheme != 'https' or parsed.port is not None or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('Transport URL outside allowlist')
        if kind == 'authentication':
            if (req.full_url != 'https://api.amazon.com/auth/o2/token' or req.get_method() != 'POST'
                    or parse_qs(req.data.decode(), keep_blank_values=True) !=
                    dict(grant_type=['refresh_token'], **{k:[v] for k,v in self.credentials.items()})):
                raise ValueError('Authentication scope invalid')
        elif (kind != 'restrictions' or req.get_method() != 'GET' or req.data is not None
                or parsed.netloc != 'sellingpartnerapi-na.amazon.com' or parsed.path != PATH
                or parse_qs(parsed.query, keep_blank_values=True) != dict(asin=[asin],sellerId=[self.seller_id],
                    marketplaceIds=[US],conditionType=[CONDITION],reasonLocale=['en_US'])):
            raise ValueError('Restrictions scope invalid')
