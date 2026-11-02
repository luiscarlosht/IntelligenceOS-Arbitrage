"""Offline verification of completed M73 outputs and their original source chain."""
from pathlib import Path
import re

from app.m67_state import secure
from app.m70_sources import file_hash, source_manifest
from app.m72_policy import REGISTRY, history_files
from app.m72_registry import inspect
from app.m73 import TABLES
from app.m73_analysis import analyze
from app.m73_evidence import document, load

BASELINE = dict(real_asins=377, baseline_asins=197, m72_asins=180, remaining_asins=623,
                permanent_exclusions=97, previously_checked_asins=40,
                combined_conflict_asins=31, research_reviewable=305)
M73_FILES = {'M73_report.json', 'M73_summary.json', 'M73_review.xlsx', 'M73_audit.csv', 'M73_summary.csv'} | {
    f'M73_{name}.csv' for name in TABLES}


def verify_manifest(directory: Path, digest: str) -> dict:
    secure(directory, directory=True)
    path = directory/'M73_output_digests.json'; secure(path)
    doc = document(path, digest)
    if not isinstance(doc, dict) or set(doc) != M73_FILES:
        raise ValueError('Complete exact M73 output manifest required')
    for name, expected in doc.items():
        if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
            raise ValueError('Explicit file digest required')
        secure(directory/name)
        if file_hash(directory/name) != expected:
            raise ValueError('M73 output digest mismatch')
    return doc


def verify(m73_dir: Path, m73_digests_sha256: str, baseline_dir: Path,
           baseline_report_sha256: str, proposal: Path, private: Path, checkpoint: str,
           sources: Path, summary: Path, store: Path, m67_manifest: Path, m67_sha256: str):
    digests = verify_manifest(m73_dir, m73_digests_sha256)
    entries, _ = source_manifest(sources)
    paths = dict(baseline=baseline_dir/'M70_catalog_1000.csv', baseline_report=baseline_dir/'M70_report.json',
        proposal=proposal, registry=private/REGISTRY, m72_sources=sources, m72_summary=summary,
        m72_pages=entries[0]['path'], store=store, m67_manifest=m67_manifest)
    hashes = {k:file_hash(p) for k,p in paths.items()}
    hashes['historical_inventory'] = history_files(private, store, m67_manifest)
    evidence = load(paths['baseline'], paths['baseline_report'], baseline_report_sha256, proposal,
                    paths['registry'], checkpoint, sources, summary, store, private, m67_manifest, m67_sha256)
    saved = document(m73_dir/'M73_report.json', digests['M73_report.json'])
    # In-memory comparison only: never invoke M73 export or regenerate old reports.
    expected = analyze(evidence)
    expected['input_sha256'] = hashes
    expected['summary']['count_reconciliation'] = 'baseline + M72 distinct - cross-cohort duplicates'
    if saved != expected or document(m73_dir/'M73_summary.json') != saved['summary']:
        raise ValueError('M73 contents do not reproduce validated source observations')
    if any(saved['summary'].get(k) != v for k,v in BASELINE.items()):
        raise ValueError('Reviewed M73 baseline changed')
    frozen = document(proposal)
    binding = inspect(paths['registry'])['binding']['preflight']
    evidence_hashes = dict(hashes, m73_completion_manifest=m73_digests_sha256,
                           **{f'm73:{k}':v for k,v in digests.items()})
    def unchanged():
        current = {k:file_hash(p) for k,p in paths.items()}
        current['historical_inventory'] = history_files(private, store, m67_manifest)
        if current != hashes or verify_manifest(m73_dir, m73_digests_sha256) != digests:
            raise ValueError('Original evidence changed during planning')
    unchanged()
    return saved, evidence, frozen, binding['account_binding_sha256'], evidence_hashes, unchanged
