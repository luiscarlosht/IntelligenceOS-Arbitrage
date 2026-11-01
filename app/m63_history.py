"""Read-only, fail-closed historical attempt audit; never opens credentials."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote

from app.catalog_saved_evidence import saved_evidence

ASIN = re.compile(r'[A-Z0-9]{10}')
PATTERNS = ('candidate-*.json', 'candidates-*.json', 'catalog-*.json',
            'saved-target-restrictions-*.json', 'selected-validation-*.json',
            'pricing-*.json', 'm60-*.json', 'm63-eligibility-*.json')
EXCLUSIONS = {'B0B1L79X41', 'B0G1MJ24B4'}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(directory: Path) -> dict:
    """Include failed/reserved detail, pricing, fee and restriction attempts.

    Non-search per-ASIN attempts are conservatively excluded even when not an
    eligibility operation. Search-result mentions alone are never attempts.
    Report contents/identifiers other than ASINs never enter the audit output.
    """
    blocked = set(EXCLUSIONS)
    inventory = []
    paths = sorted({p for pattern in PATTERNS for p in directory.glob(pattern)})
    if len(paths) > 500:
        raise ValueError('Historical report bound exceeded')
    for path in paths:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('Unsafe historical report')
        doc = json.loads(path.read_bytes())
        if not isinstance(doc, dict):
            raise ValueError('Invalid historical report')
        inventory.append(dict(file=path.name, sha256=sha256(path)))
        if doc.get('is_mock') is True:
            continue
        if path.name=='m63-eligibility-authorization-01.json':
            for asin in doc.get('asins',[]):
                if not isinstance(asin,str) or not ASIN.fullmatch(asin):
                    raise ValueError('Invalid permanent M63 eligibility reservation')
                blocked.add(asin)
        for attempt in doc.get('attempts', []):
            kind = attempt.get('kind') or attempt.get('stage')
            asin = attempt.get('asin')
            if kind not in ('authentication', 'search', 'lwa_exchange') and isinstance(asin, str) and ASIN.fullmatch(asin):
                blocked.add(asin)
        # Standalone pilots, including interrupted pre-response reservations.
        asin = doc.get('asin')
        if isinstance(asin, str) and ASIN.fullmatch(asin):
            if doc.get('requests_attempted', 0) or doc.get('attempts') or doc.get('stages'):
                blocked.add(asin)
        for row in doc.get('rows', []):
            asin = row.get('asin')
            if not isinstance(asin, str) or not ASIN.fullmatch(asin):
                continue
            for name in ('restrictions', 'pricing', 'fees', 'detail'):
                value = row.get(name) or {}
                if value.get('status') not in (None, 'not_attempted', 'not_requested', 'skipped_missing_price'):
                    blocked.add(asin)
    # Older M58 detail attempts are ordinal-bound and have no ASIN on the
    # attempt itself. Reuse their source/selected-ASIN-aware audit rather than
    # treating absent attempt.asin as proof that the product was never checked.
    ordinal_reports=[p for p in paths if p.name.startswith(('candidates-','candidate-details-'))]
    if ordinal_reports:
        _, detail_attempts, _ = saved_evidence(ordinal_reports)
        blocked.update(detail_attempts)
    ledger = directory / 'candidate-executions.sqlite3'
    operations = []
    if ledger.exists():
        if ledger.is_symlink() or not ledger.is_file():
            raise ValueError('Unsafe historical ledger')
        with sqlite3.connect('file:' + quote(str(ledger.resolve()), safe='/') + '?mode=ro', uri=True) as db:
            # SQL projection intentionally excludes checkpoint JSON/private context.
            for kind, asin, state in db.execute('SELECT kind,asin,state FROM candidate_operations ORDER BY request_key'):
                if kind not in ('authentication', 'search') and isinstance(asin, str) and ASIN.fullmatch(asin):
                    blocked.add(asin)
                    operations.append(dict(kind=kind, asin=asin, state=state))
    return dict(schema=1, reports=inventory, ledger_operations=operations,
                excluded_asins=sorted(blocked), immutable_exclusions=sorted(EXCLUSIONS),
                policy='all non-search per-ASIN attempts, including reservations and failures')
