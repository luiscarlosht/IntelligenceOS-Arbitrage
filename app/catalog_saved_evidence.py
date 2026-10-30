"""Read-only scoped saved catalog evidence inventory."""
import hashlib
from pathlib import Path
from app.sheets_candidate_plan import read_json, MARKETPLACE
from app.observations import fingerprint
from app.normalization import timestamp
DETAIL_DATA = 'summaries,identifiers,relationships,attributes'
REPORT_PATTERNS = ('candidates-*.json', 'candidate-details-*.json')

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def saved_evidence(paths: list[Path]) -> tuple[dict, set, set]:
    """Only successful, scoped, source-bound catalog evidence can be reused."""
    cache, blocked, searched, conflicts = {}, set(), set(), set()
    for path in paths:
        report, _ = read_json(path)
        stored_details = report.get('manifest', {}).get('mode') in ('stored_missing_catalog_details', 'reviewed_shortlist_details')
        if report.get('is_mock') is not False or (report.get('manifest', {}).get('marketplace_id') != MARKETPLACE and not stored_details):
            continue
        evidence_rows = []
        for parent in report.get('rows', []):
            if 'candidate_outcomes' in parent:
                evidence_rows.extend(dict(parent, **{k: v for k, v in child.items()
                    if k not in ('source',)}) for child in parent['candidate_outcomes'])
            else:
                evidence_rows.append(parent)
        for row in evidence_rows:
            source = row.get('source') or {}
            context = source.get('source_context') or {}
            selected = (row.get('search') or {}).get('selected_asin')
            attempts = [a for a in report.get('attempts', []) if
                        a.get('ordinal') == row.get('ordinal') or (stored_details and
                        a.get('kind') == 'detail' and a.get('asin') == selected)]
            specs = [s for s in report['manifest'].get('requests', []) if s.get('ordinal') == row.get('ordinal')]
            if source.get('retailer') == 'Walmart' and any(a.get('kind') == 'search' for a in attempts):
                searched.add(context.get('retailer_item_id'))
            details = [a for a in attempts if a.get('kind') == 'detail']
            if not selected or not details:
                continue
            blocked.add(selected)
            detail = row.get('detail') or {}
            catalog = (detail.get('value') or {}).get('catalog') or {}
            scoped = (len(specs) == 1 and specs[0].get('source_fingerprint') == fingerprint(source)
                      and specs[0].get('detail', {}).get('params', {}).get('marketplaceIds') == MARKETPLACE)
            if stored_details:
                scoped = row.get('source_fingerprint') == fingerprint(source) and any(
                    r.get('kind') == 'catalog_detail' and r.get('asin') == selected
                    and row.get('record_id') in r.get('source_record_ids', [])
                    and r.get('params', {}).get('marketplaceIds') == MARKETPLACE
                    for r in report['manifest'].get('requests', []))
            if (not scoped or len(details) != 1 or details[0].get('status') != 'response_received'
                    or detail.get('is_mock') is not False or catalog.get('is_mock') is not False
                    or catalog.get('asin') != selected or timestamp(detail.get('observed_at')) is None):
                continue
            if selected in cache and fingerprint(cache[selected]['value']) != fingerprint(detail['value']):
                conflicts.add(selected)
                del cache[selected]
            if selected not in conflicts:
                cache[selected] = detail
    return cache, blocked, searched

