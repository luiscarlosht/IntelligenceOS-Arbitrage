"""Read-only, pinned M80 import across code revisions; live gates remain strict."""
from datetime import datetime
from pathlib import Path
from app.evidence_io import digest, json_write, pinned, safe
from app.m80_journal import inspect
from app.m80_evidence import analyze
from app.m80_contract import source
from app.observations import fingerprint


def load_ledger(path:Path,expected_sha:str,as_of:datetime) -> dict:
    if digest(path)!=expected_sha:raise ValueError('Reviewed original M80 ledger SHA-256 required')
    snapshot=inspect(path,historical=True)
    binding=snapshot['binding'];synthetic=binding.get('synthetic')
    if type(synthetic) is not bool:raise ValueError('Explicit synthetic/live provenance required')
    if not synthetic and binding.get('authorization_sha256') in (None,'0'*64):raise ValueError('Live permission provenance missing')
    report=analyze(snapshot,as_of)
    # Preserve original observation content independently of today's freshness gates.
    frames=snapshot['responses'].values()
    times=[datetime.fromisoformat(v['observed_at']) for v in frames]
    recorded_at=max(times) if times else as_of
    report['historical_rows']=analyze(snapshot,recorded_at)['rows']
    if digest(path)!=expected_sha:raise ValueError('Ledger changed during read-only import')
    report.update(handoff_sha256=binding['plan']['handoff_sha256'],schema=1,evidence_sha256=expected_sha,source_kind='SYNTHETIC' if synthetic else 'AUTHORIZED_LIVE',
                  source_code_sha256=binding['plan']['implementation_sha256'])
    return report


def readiness(handoff:Path,expected_sha:str,output:Path) -> dict:
    data,targets,sha=source(handoff,expected_sha)
    output=safe(output)
    protected={handoff.resolve().parent,*(Path(name).resolve().parent for name in data.get('input_sha256',{}))}
    if output.is_relative_to('/mnt') or any(output.is_relative_to(root) for root in protected):
        raise ValueError('Checklist must stay outside historical evidence/deployment volumes')
    value=dict(schema=1,mode='M81_OFFLINE_OWNER_READINESS',source_handoff_sha256=sha,
        asins=[r['asin'] for r in targets],http_maximum=42,
        checks={'m79_scope':'PASS','exact_twenty':'PASS','exclusions_and_identity_flags':'PASS',
                'credential_values':'NOT_ACCESSED','owner_account_binding':'NOT_INSPECTED',
                'provider_roles_and_quotas':'OWNER_REVIEW_REQUIRED','live_authorization':'NOT_GRANTED',
                'server_changes':'NOT_AUTHORIZED','actual_live_requests':0},
        blockers=['Review source/ASIN and code pins','Confirm canonical account metadata without credential disclosure',
            'Confirm role/usage/cooldown and retention approvals','Issue fresh interactive M80 permission',
            'Run once only after explicit live authorization; never reset a claim'],
        source_universe_count=len(data['all_asins']),execution_authorized=False)
    json_write(output,value)
    return value
