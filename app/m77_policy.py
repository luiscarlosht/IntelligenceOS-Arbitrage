"""M77 immutable evidence reconciliation and credential-free preflight."""
from copy import deepcopy
from pathlib import Path

from app.m65_intelligence import sha256, US
from app.m67_state import secure
from app.m70_sources import file_hash
from app.m71_manifest import HOST, PATH
from app.m72_policy import account, cooldowns
from app.m73_evidence import document
from app.m74_plan import parameters
from app.m75_policy import Prepared, credential_metadata
from app.m76_evidence import load, CHECKPOINT
from app.m76_analysis import analyze
from app.observations import fingerprint

OPERATION='M77-US-CATALOG-EXPLORE31-ONCE'
REGISTRY='m77-catalog-discovery.sqlite3'
RESULTS='m77-catalog-expansion-output'
TIMEOUT=180
COMPLETION_SHA256='0e8c1840d7f9860c36422baa5d828bfc9d29493bac77d2c80af71daf0b67577b'
CONTRACT_SHA256='cf722824164e02b2ffeb08ffd479660747b553a687a6eb49403197d999792435'
BUDGET=dict(authentication=1,keyword=31,total=32,identifier=0,additional_pages=0,retries=0,
            refreshes=0,eligibility=0,pricing=0,fees=0,fba=0,retailer=0,listings=0,purchases=0,approvals=0)
# All 31 original definitions reviewed in rank order; no generated/substituted phrases.
KEYWORDS=(
 'travel toothbrush case','garden plant labels','aquarium cleaning brush','beading storage tray',
 'tea infuser basket','vacuum storage bag','book binding rings','swimming ear plug case',
 'microfiber applicator pad','sanding block','silicone scalp brush','watering can rose',
 'bird cage perch','craft cutting mat','dough scraper','closet shelf separator',
 'reusable notebook cover','resistance band handles','car visor clip','woodworking marking gauge',
 'reusable shower cap','garden kneeling pad','pet travel bowl','felting needle holder',
 'reusable baking liner','bedside storage caddy','desktop card holder','camping utensil pouch',
 'automotive trim tool','tool roll pouch','cosmetic brush holder')


def requests():
    return [dict(slot=i+2,query_id=f'q{i+20:03}',method='GET',host=HOST,path=PATH,
                 parameters=parameters(words)) for i,words in enumerate(KEYWORDS)]


CANONICAL_SHA256=fingerprint(requests())
MANIFEST_SHA256=CANONICAL_SHA256


def implementation():
    root=Path(__file__).parent
    paths=sorted(root.glob('*.py'))
    if any(p.is_symlink() for p in paths) or (root.parent/'ops/m77_offline.py').is_symlink():raise ValueError('Regular implementation required')
    return {p.name:sha256(p) for p in paths} | {'ops/m77_offline.py':sha256(root.parent/'ops/m77_offline.py')}


def completion(directory: Path,m74_dir: Path,evidence: dict):
    secure(directory,directory=True)
    done=document(directory/'M76_evidence_manifest.json',COMPLETION_SHA256)
    code=implementation()
    if (done['schema']!=1 or done['mode']!='M76_COMPLETED_OFFLINE_CONSOLIDATION'
            or done['checkpoint_sha256']!=CHECKPOINT or done['execution_authorized'] is not False
            or any(code.get(k)!=v for k,v in done['implementation_sha256'].items())):
        raise ValueError('Original M76 implementation/checkpoint required')
    expected={'M76_catalog_review.xlsx','M76_executive_summary.md','M76_report.json','M76_summary.json',
              'M76_M77_proposal.json','M76_identity_gaps_conflicts.json','M76_historical_annotations.json'}|{
              f'M76_{n}.csv' for n in ('catalog','identity_gaps','conflicts','annotations','coverage','m77_queries','m77_scenarios','summary')}
    if set(p.name for p in directory.iterdir())!=expected|{'M76_evidence_manifest.json','M76_digest_report.txt'}:
        raise ValueError('Exact original M76 directory inventory required')
    if set(done['output_sha256'])!=expected:raise ValueError('Exact M76 output inventory required')
    for name,digest in done['output_sha256'].items():
        secure(directory/name)
        if file_hash(directory/name)!=digest:raise ValueError('M76 output drift')
    digest_text='M76_evidence_manifest.json  '+COMPLETION_SHA256+'\n'+''.join(
        f'{name}  {value}\n' for name,value in done['output_sha256'].items())
    secure(directory/'M76_digest_report.txt')
    if (directory/'M76_digest_report.txt').read_text()!=digest_text:raise ValueError('M76 digest report drift')
    proposal=document(directory/'M76_M77_proposal.json',CONTRACT_SHA256)
    if [(q['rank'],q['query_id'],q['keywords']) for q in proposal['queries']]!=[
            (i+1,r['query_id'],r['parameters']['keywords']) for i,r in enumerate(requests())]:
        raise ValueError('All 31 reviewed ordered definitions required')
    inputs={k:v for k,v in evidence.items() if k!='m74_dir'}
    prior,observations,pages,manifest,hashes,coverage,unchanged=load(m74_dir,**inputs)
    if done['input_sha256']!=hashes:raise ValueError('M76 original input binding required')
    report=analyze(prior,observations,pages,manifest,hashes['m73:M73_report.json'])
    report['source_coverage']=dict(m73=prior['source_coverage'],m75=coverage)
    if (document(directory/'M76_report.json')!=report or fingerprint(report)!=done['report_sha256']
            or report['proposal']!=proposal or report['summary']['real_asins']!=777):
        raise ValueError('M76 original contents do not reproduce')
    before={p.name:file_hash(p) for p in directory.iterdir() if p.is_file()}
    def guard():
        unchanged()
        if {p.name:file_hash(p) for p in directory.iterdir() if p.is_file()}!=before:
            raise ValueError('M76 evidence drift')
    guard()
    return dict(report=report,manifest=dict(manifest,manifest_sha256=CANONICAL_SHA256),guard=guard,
                hashes=dict(hashes,**{f'm76:{k}':v for k,v in before.items()}))


def preflight(m76_dir: Path,evidence: dict,*,_recovery: bool=False):
    private=evidence['private'];secure(private,directory=True);secure(private/'candidate-execution.lock')
    for name in (REGISTRY,RESULTS):
        if not _recovery and ((private/name).exists() or (private/name).is_symlink()):raise ValueError('Permanent M77 no replay')
    historical=completion(m76_dir,evidence['m74_dir'],evidence)
    context,binding=account(private)
    code=implementation();metadata=credential_metadata(private);saved=cooldowns(private)
    from app.m70_plan import plan
    pacing=plan()['configured_limits']
    frozen=document(evidence['proposal'])
    if pacing!=frozen['pacing']:raise ValueError('Frozen conservative pacing required')
    # M75's validated account binding must still be current.
    from app.m75_registry import inspect
    from app.m75_policy import REGISTRY as PRIOR_REGISTRY
    if inspect(private/PRIOR_REGISTRY)['binding']['preflight']['account_binding_sha256']!=binding:
        raise ValueError('Original account required')
    hashes=historical['hashes'];manifest=historical['manifest']
    report=dict(schema=1,mode='M77_OFFLINE_PREFLIGHT',operation_id=OPERATION,registry=REGISTRY,
        manifest_sha256=CANONICAL_SHA256,manifest_file_sha256=MANIFEST_SHA256,
        completion_file_sha256=COMPLETION_SHA256,contract_file_sha256=CONTRACT_SHA256,
        implementation_sha256=code,implementation_digest=fingerprint(code),input_sha256=hashes,
        evidence_sha256=fingerprint(hashes),account_reference=context['account_reference'],marketplace_id=US,
        account_binding_sha256=binding,credential_metadata_sha256=metadata,
        credential_content_verification='DEFERRED_UNTIL_NEW_OWNER_AUTHORIZATION',requests=requests(),budget=dict(BUDGET),
        maximum_raw_observations=620,baseline_asins=777,remaining_asins=223,
        baseline_report_sha256=hashes['m76:M76_report.json'],exclusions=manifest['permanently_excluded_asins'],
        previously_checked_asins=manifest['previously_checked_asins'],pacing=pacing,saved_cooldowns=saved,
        hard_timeout_seconds=TIMEOUT,socket_timeout_seconds=10,execution_authorized=False,
        actual_requests=0,actual_authentication=0,new_reservations=0)
    def guard():
        historical['guard']()
        if (implementation()!=code or account(private)!=(context,binding) or credential_metadata(private)!=metadata
                or cooldowns(private)!=saved or plan()['configured_limits']!=pacing):
            raise ValueError('Evidence/code/account/credential metadata/pacing drift')
    guard()
    return Prepared(deepcopy(report),deepcopy(manifest),{p['asin'] for p in historical['report']['catalog']},guard)
