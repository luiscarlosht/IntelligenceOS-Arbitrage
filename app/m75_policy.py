"""Pinned M75 scope and offline preflight. No credential-value reads or dispatch."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.m65_intelligence import sha256 as source_sha256
from app.m67_state import secure
from app.m70_sources import file_hash
from app.m72_policy import account, cooldowns
from app.m73_evidence import document
from app.m74 import implementation as m74_implementation, validate as validate_plan
from app.m74_evidence import verify
from app.m74_plan import BUDGET, OPERATION, NEW_QUERIES, parameters, build
from app.m71_manifest import queries, HOST, PATH
from app.observations import fingerprint

CANONICAL_SHA256='e9119972fd0257d9da5f1dbb1518567c859001d0a957946a0f846b9d26931105'
MANIFEST_SHA256='ae34d1d5df28f40f905bb80778fd3b5b4f6e61dd41ca1887607d18d585af283f'
COMPLETION_SHA256='0224671c5011e26182c7f117516149d83cb97c1a77b4f362e59b2627005a815a'
CONTRACT_SHA256='5170814e9f774df7dc20f148d20319cf2de2ea928df466219d3415110d3f90fe'
REGISTRY='m75-catalog-discovery.sqlite3'
RESULTS='m75-catalog-expansion-output'
TIMEOUT=120
M74_FILES={'M74_discovery_plan.xlsx','M74_planning_report.json','M74_query_manifest.json',
 'M74_M75_contract_proposal.json','M74_executive_summary.json','M74_budget_scenarios.json',
 'M74_history_summary.json','M74_coverage_overlap.json'} | {f'M74_{name}.csv' for name in
 ('summary','queries','coverage','overlap','intent_gaps','diversity','budgets','exclusions','conflicts','m75_contract')}


def implementation() -> dict:
    from app.m72_policy import implementation as prior
    root=Path(__file__).parent
    names=('m75.py','m75_policy.py','m75_authorization.py','m75_registry.py','m75_transport.py',
           'm75_execution.py','m75_reporting.py')
    if any((root/n).is_symlink() for n in names):raise ValueError('Regular implementation source files required')
    return dict(prior(),**m74_implementation(),**{n:source_sha256(root/n) for n in names})


def requests() -> list[dict]:
    old=queries()
    selected=[(old[9]['id'],old[9]['keywords'])]
    selected += [(f'm74-n{i:03}',phrase) for i,(_,phrase) in enumerate(NEW_QUERIES,1)]
    selected += [(q['id'],q['keywords']) for q in old[10:19]]
    if len(selected)!=20:raise ValueError('Exactly twenty reviewed queries required')
    return [dict(slot=i+2,query_id=q,method='GET',host=HOST,path=PATH,parameters=parameters(phrase))
            for i,(q,phrase) in enumerate(selected)]


def completion(directory: Path) -> dict:
    secure(directory,directory=True)
    doc=document(directory/'M74_evidence_digests.json',COMPLETION_SHA256)
    if (set(doc)!={'schema','mode','execution_authorized','input_sha256','implementation_sha256','manifest_sha256','output_sha256'}
            or type(doc['schema']) is not int or doc['schema']!=1 or doc['mode']!='M74_COMPLETED_OFFLINE_PLAN'
            or doc['execution_authorized'] is not False or doc['manifest_sha256']!=CANONICAL_SHA256
            or doc['implementation_sha256']!=m74_implementation() or set(doc['output_sha256'])!=M74_FILES):
        raise ValueError('Exact completed M74 evidence and implementation required')
    for name,digest in doc['output_sha256'].items():
        secure(directory/name)
        if file_hash(directory/name)!=digest:raise ValueError('M74 report drift')
    document(directory/'M74_query_manifest.json',MANIFEST_SHA256)
    document(directory/'M74_M75_contract_proposal.json',CONTRACT_SHA256)
    return doc


def credential_metadata(private: Path) -> str:
    path=private/'credentials.json';secure(path)
    s=path.stat()
    return fingerprint(dict(device=s.st_dev,inode=s.st_ino,size=s.st_size,mtime_ns=s.st_mtime_ns,
                            mode=s.st_mode,uid=s.st_uid,nlink=s.st_nlink))


@dataclass
class Prepared:
    report: dict
    manifest: dict
    baseline: set[str]
    guard: Callable[[],None]


def preflight(m74_dir: Path, evidence: dict) -> Prepared:
    private=evidence['private'];secure(private,directory=True)
    secure(private/'candidate-execution.lock')
    if (private/REGISTRY).exists() or (private/REGISTRY).is_symlink():
        raise ValueError('Any existing M75 registry permanently blocks replay')
    if (private/RESULTS).exists() or (private/RESULTS).is_symlink():raise ValueError('Output requires reconciliation')
    done=completion(m74_dir)
    prior,source,frozen,binding,hashes,unchanged=verify(**evidence)
    if hashes!=done['input_sha256']:raise ValueError('Original M74 source chain drift')
    expected=build(prior,source,frozen,binding,hashes,m74_implementation())
    plan=document(m74_dir/'M74_planning_report.json')
    if plan!=expected:raise ValueError('Exact M74 plan and contract required')
    validate_plan(plan)
    manifest=document(m74_dir/'M74_query_manifest.json')
    contract=document(m74_dir/'M74_M75_contract_proposal.json')
    if manifest!=plan['manifest'] or contract!=plan['contract'] or contract['keyword_requests']!=requests():
        raise ValueError('Reviewed first twenty requests only')
    context,account_digest=account(private)
    if binding!=account_digest or contract['account_binding_sha256']!=binding:
        raise ValueError('Original account scope required')
    code=implementation();metadata=credential_metadata(private);saved=cooldowns(private)
    from app.m70_plan import plan as pacing_plan
    pacing=pacing_plan()['configured_limits']
    if pacing!=frozen['pacing']:raise ValueError('Frozen conservative pacing required')
    report=dict(schema=1,mode='M75_OFFLINE_PREFLIGHT',operation_id=OPERATION,registry=REGISTRY,
        manifest_sha256=CANONICAL_SHA256,manifest_file_sha256=MANIFEST_SHA256,
        completion_file_sha256=COMPLETION_SHA256,contract_file_sha256=CONTRACT_SHA256,
        implementation_sha256=code,implementation_digest=fingerprint(code),evidence_sha256=fingerprint(hashes),
        input_sha256=hashes,account_reference=context['account_reference'],marketplace_id=context['marketplace_id'],
        account_binding_sha256=binding,credential_metadata_sha256=metadata,
        credential_content_verification='DEFERRED_UNTIL_NEW_OWNER_AUTHORIZATION',
        requests=requests(),budget=dict(BUDGET),baseline_asins=len(prior['catalog']),
        baseline_report_sha256=hashes['m73:M73_report.json'],
        exclusions=manifest['permanently_excluded_asins'],previously_checked_asins=manifest['previously_checked_asins'],
        pacing=pacing,saved_cooldowns=saved,hard_timeout_seconds=TIMEOUT,socket_timeout_seconds=10,
        execution_authorized=False,actual_requests=0,actual_authentication=0,new_reservations=0)
    def guard():
        # Only immutable reads here: safe under the already held exclusive lock.
        unchanged()
        if (completion(m74_dir)!=done or implementation()!=code or account(private)!=(context,account_digest)
                or credential_metadata(private)!=metadata or cooldowns(private)!=saved
                or pacing_plan()['configured_limits']!=pacing):
            raise ValueError('Current evidence/code/account/pacing drift')
    guard()
    return Prepared(deepcopy(report),deepcopy(manifest),{p['asin'] for p in prior['catalog']},guard)
