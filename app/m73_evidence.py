"""Read-only M73 evidence binding. No credentials, authorization or transport."""
from pathlib import Path
import tempfile

from app.m67_state import readonly, secure
from app.m70 import export as export_baseline
from app.m70_discovery import implementation as baseline_implementation
from app.m70_sources import file_hash, strict_json, ingest, source_manifest
from app.m71_manifest import prepare, validate
from app.m72_policy import PROPOSAL_SHA256, MANIFEST_SHA256, OPERATION
from app.m72_registry import inspect
from app.observations import fingerprint


def document(path: Path, digest: str | None = None):
    actual = file_hash(path)
    if digest is not None and actual != digest:
        raise ValueError('Evidence digest mismatch')
    result = strict_json(path)
    if file_hash(path) != actual:
        raise ValueError('Evidence changed while reading')
    return result


def load(baseline: Path, baseline_report: Path, baseline_digest: str, proposal: Path,
         registry: Path, checkpoint: str, sources: Path, summary: Path,
         store: Path, private: Path, m67_manifest: Path, m67_digest: str) -> dict:
    # Refuse missing locks; historical readers must never bootstrap state here.
    secure(private/'candidate-execution.lock')
    # Inspect the original durable chain before parsing any catalog records.
    snapshot = inspect(registry)
    completion = document(summary)
    if (snapshot['status'] != 'COMPLETED_NO_REPLAY' or snapshot['requests_consumed'] != 10
            or snapshot['uncertain_slots'] or snapshot['checkpoint_sha256'] != checkpoint
            or completion.get('checkpoint_sha256') != checkpoint
            or completion.get('status') != snapshot['status'] or completion.get('requests_consumed') != 10
            or completion.get('operation_id') != OPERATION or completion.get('proposal_sha256') != PROPOSAL_SHA256):
        raise ValueError('Exact completed ten-request checkpoint required')
    frozen = document(proposal, MANIFEST_SHA256)
    validate(frozen)
    if frozen['proposal_sha256'] != PROPOSAL_SHA256 or frozen != prepare(private, store, m67_manifest, m67_digest):
        raise ValueError('Frozen proposal/current immutable history mismatch')
    binding = snapshot['binding']['preflight']
    if (binding['proposal_sha256'] != PROPOSAL_SHA256 or binding['manifest_file_sha256'] != MANIFEST_SHA256
            or binding['excluded_asins_sha256'] != fingerprint(frozen['excluded_asins'])
            or binding['history_evidence_sha256'] != frozen['history_evidence_sha256']
            or binding['queries'] != frozen['queries'][:9]
            or file_hash(baseline) != binding['baseline_file_sha256']):
        raise ValueError('Operation/proposal/baseline binding mismatch')
    entries, _ = source_manifest(sources)
    if len(entries) != 1 or entries[0]['adapter'] != 'amazon_catalog_pages':
        raise ValueError('Single original authorized Catalog export required')
    pages_doc = document(entries[0]['path'])
    if (pages_doc.get('operation_id') != OPERATION or pages_doc.get('proposal_sha256') != PROPOSAL_SHA256
            or pages_doc.get('status') != 'COMPLETED_NO_REPLAY' or pages_doc.get('pages') != snapshot['pages']
            or len(snapshot['pages']) != 9):
        raise ValueError('Saved pages must equal durable operation responses')
    from app.m71_adapter import parameters, validate_page
    db = readonly(registry)
    try:
        import json
        attempts = [(slot, json.loads(text)) for slot, text in db.execute(
            "SELECT slot,payload FROM m72_events WHERE kind='ATTEMPT' ORDER BY slot")]
        for slot, event in attempts:
            phase = 'authentication' if slot == 1 else 'keyword'
            params = {} if slot == 1 else parameters(frozen['queries'][slot-2])
            if event['request_sha256'] != fingerprint(dict(slot=slot, phase=phase, parameters=params)):
                raise ValueError('Request intent differs from frozen sequence')
    finally:
        db.close()
    for slot, page in enumerate(snapshot['pages'], 2):
        if (page.get('request_slot') != slot or page.get('query_reference') != frozen['queries'][slot-2]['id']
                or page.get('page_index') != 0 or page.get('page_token') is not None
                or page.get('proposal_sha256') != PROPOSAL_SHA256 or page.get('operation_id') != OPERATION):
            raise ValueError('Original first-nine page scope required')
        validate_page(dict(items=page['items'], pagination=page['pagination']), prior_tokens=set())
    prior = document(baseline_report, baseline_digest)
    if prior.get('mode') != 'M70_OFFLINE_REPORT' or any(prior.get(k) is True for k in ('is_mock','is_synthetic','is_generated')):
        raise ValueError('Original real M70 report required')
    if (prior.get('implementation_sha256') != baseline_implementation()
            or any(any(p.get(k) is True for k in ('is_mock','is_synthetic','is_generated')) for p in prior['catalog'])):
        raise ValueError('Unchanged real baseline implementation and records required')
    # Re-export unchanged M70 data: the operation-bound CSV authenticates all
    # exported identity values/flags and ASIN membership, not just a row count.
    with tempfile.TemporaryDirectory(prefix='m73-baseline-') as temp:
        out = Path(temp)/'baseline'
        export_baseline(prior, out)
        if file_hash(out/'M70_catalog_1000.csv') != file_hash(baseline):
            raise ValueError('M70 report does not reproduce original baseline')
    excluded = frozen['excluded_asins']; checked = frozen['checked_eligibility_asins']
    if len(excluded) != 97 or len(checked) != 40 or not set(checked) <= set(excluded):
        raise ValueError('All historical safeguards required')
    if prior['history']['excluded_asins'] != excluded:
        raise ValueError('Baseline historical exclusions differ')
    observations, coverage = ingest(sources)
    if any(s['rejected'] for s in coverage['sources']) or any(o['role'] != 'amazon' for o in observations):
        raise ValueError('Every operation record must import as real Amazon evidence')
    return dict(baseline=prior['catalog'], observations=observations,
                coverage=dict(baseline=prior['source_coverage'], m72=coverage),
                excluded=excluded, checked=checked, completion=completion, checkpoint=checkpoint, pages=snapshot['pages'],
                baseline_digest=baseline_digest, pages_digest=entries[0]['sha256'])
