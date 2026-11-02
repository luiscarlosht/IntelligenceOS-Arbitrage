"""Read-only validation of original M73 and completed, non-replayable M75."""
from pathlib import Path
import tempfile

from app.m70_sources import file_hash, source_manifest, ingest
from app.m73_evidence import document
from app.m74_evidence import verify
from app.m74_plan import build
from app.m74 import implementation as m74_implementation
from app.m75_policy import completion, requests, REGISTRY, RESULTS, CANONICAL_SHA256, implementation as m75_implementation
from app.m75_registry import inspect
from app.m75_reporting import export as reproduce
from app.observations import fingerprint

CHECKPOINT = '27003995ccec549ea0d61e3b9597b24eab39fcba6ffb7e547ac64ed67dfb8454'


def load(m74_dir: Path, **kwargs):
    prior, evidence, frozen, account, hashes, guard = verify(**kwargs)
    done = completion(m74_dir)
    if done['input_sha256'] != hashes:
        raise ValueError('M74 original input chain mismatch')
    plan = build(prior, evidence, frozen, account, hashes, m74_implementation())
    if document(m74_dir/'M74_planning_report.json') != plan:
        raise ValueError('Original M74 plan mismatch')
    manifest = document(m74_dir/'M74_query_manifest.json')
    if manifest != plan['manifest']:
        raise ValueError('M74 manifest mismatch')
    private = kwargs['private']; directory = private/RESULTS
    paths = dict(m75_registry=private/REGISTRY, m75_digests=directory/'M75_output_digests.json',
                 m75_sources=directory/'M75_M70_sources.json', m75_pages=directory/'M75_catalog_pages.json',
                 m75_summary=directory/'M75_summary.json')
    before = {k:file_hash(p) for k,p in paths.items()}
    digests = document(paths['m75_digests'])
    if digests != {p.name:before[k] for k,p in paths.items() if k not in ('m75_registry','m75_digests')}:
        raise ValueError('Exact complete M75 output inventory required')
    snapshot = inspect(paths['m75_registry'])
    preflight = snapshot['binding']['preflight']
    if (snapshot['status'] != 'COMPLETED_NO_REPLAY' or snapshot['checkpoint_sha256'] != CHECKPOINT
            or snapshot['requests_consumed'] != 21 or snapshot['uncertain_slots'] or len(snapshot['pages']) != 20
            or preflight['implementation_sha256'] != m75_implementation()
            or preflight['implementation_digest'] != fingerprint(m75_implementation())
            or preflight['manifest_sha256'] != CANONICAL_SHA256 or preflight['requests'] != requests()
            or preflight['input_sha256'] != hashes or preflight['baseline_report_sha256'] != hashes['m73:M73_report.json']
            or preflight['baseline_asins'] != 377 or preflight['exclusions'] != evidence['excluded']
            or preflight['previously_checked_asins'] != evidence['checked']):
        raise ValueError('Original completed M75 binding/checkpoint required')
    entries, _ = source_manifest(paths['m75_sources'])
    if (len(entries) != 1 or entries[0]['adapter'] != 'amazon_catalog_pages'
            or entries[0]['path'].resolve() != paths['m75_pages'].resolve()):
        raise ValueError('Original M75 M70-compatible source required')
    # Recompute in a new temporary directory only; never write historical outputs.
    with tempfile.TemporaryDirectory(prefix='m76-reconcile-') as temp:
        out = Path(temp)/'recomputed'
        reproduce(snapshot, manifest, {p['asin'] for p in prior['catalog']}, out)
        if any(file_hash(out/p.name) != before[k] for k,p in paths.items()
               if k not in ('m75_registry','m75_digests')):
            raise ValueError('M75 source/pages/summary do not reproduce registry')
    observations, coverage = ingest(paths['m75_sources'])
    summary = document(paths['m75_summary'])
    expected = dict(distinct_new_asins=400, distinct_observed_asins=400, duplicate_observations=0,
                    catalog_identity_complete=76, identity_conflicts=18, identity_complete=0)
    if any(summary.get(k) != v for k,v in expected.items()) or any(s['rejected'] for s in coverage['sources']):
        raise ValueError('Reviewed M75 counts/coverage changed')
    def unchanged():
        guard()
        if completion(m74_dir) != done or {k:file_hash(p) for k,p in paths.items()} != before:
            raise ValueError('Historical evidence drift')
    unchanged()
    return prior, observations, snapshot['pages'], manifest, dict(hashes, **before,
        m74_completion=file_hash(m74_dir/'M74_evidence_digests.json')), coverage, unchanged
