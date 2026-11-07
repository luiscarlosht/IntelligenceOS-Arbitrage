"""Pure request specification and conservative parser; intentionally no transport."""
from app.amazon_catalog import MARKETPLACE
from app.m96 import ASIN


def request_spec(asin: str) -> dict:
    if not ASIN.fullmatch(asin):
        raise ValueError('Invalid ASIN')
    return {'method': 'GET', 'path': '/fba/inbound/v1/eligibility/itemPreview',
            'params': {'asin': asin, 'marketplaceIds': [MARKETPLACE], 'program': 'INBOUND'}}


def parse_preview(document: dict, asin: str) -> str:
    """A preview is independent of New-condition listing permission and economics."""
    request_spec(asin)
    if not isinstance(document, dict) or document.get('errors'):
        return 'UNKNOWN'
    payload = document.get('payload')
    if not isinstance(payload, dict):
        return 'UNKNOWN'
    if (payload.get('asin') != asin or payload.get('marketplaceId') != MARKETPLACE
            or payload.get('program') != 'INBOUND'
            or type(payload.get('isEligibleForProgram')) is not bool):
        return 'UNKNOWN'
    reasons = payload.get('ineligibilityReasonList', [])
    if not isinstance(reasons, list) or any(not isinstance(r, str) for r in reasons):
        return 'UNKNOWN'
    if payload['isEligibleForProgram']:
        return 'UNKNOWN' if reasons else 'ELIGIBLE_PREVIEW'
    return 'INELIGIBLE_PREVIEW'
