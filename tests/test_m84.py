from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import pytest
from ops import intelligence_release as r
from ops.m78_sandbox.wheel_profile import WHEELS

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def wheels():
    path=Path(os.environ.get('M78_TEST_WHEELHOUSE','/tmp/m78-ci-wheels'))
    if not path.is_dir():pytest.skip('Independent pinned wheel artifacts supplied by CI')
    return path


@pytest.fixture
def built(tmp_path,wheels):
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    output=tmp_path/'release'
    result=r.build(ROOT,commit,wheels,output)
    return output,result,commit,wheels


def test_release_reproducible_and_isolated_entrypoint(built,tmp_path):
    output,result,commit,wheels=built
    second=tmp_path/'second';other=r.build(ROOT,commit,wheels,second)
    assert result==other
    assert (output/'manifest.json').read_bytes()==(second/'manifest.json').read_bytes()
    check=r.inspect_release(output,result['manifest_sha256'],ROOT,commit,wheels)
    assert check['integrity']=='PASS' and not check['deployment_authorized']
    assert not list(output.rglob('*.pyc')) and not list(output.rglob('*.pth'))
    assert 'runtime/app/decision_pipeline.py' in json.loads((output/'manifest.json').read_text())['files']
    env={'PATH':os.defpath,'INTELLIGENCE_RELEASE_SHA256':result['manifest_sha256']}
    command=[sys.executable,'-I','-S','-B',str(output/'run.py'),'--help']
    response=subprocess.run(command,capture_output=True,text=True,env=env)
    assert response.returncode==0,response.stderr
    assert '--manifest-sha256' in response.stdout
    env['INTELLIGENCE_RELEASE_SHA256']='0'*64
    assert subprocess.run(command,capture_output=True,env=env).returncode!=0
    assert subprocess.run([sys.executable,str(output/'run.py'),'--help'],capture_output=True,env=env).returncode!=0


@pytest.mark.parametrize('mutation',['source','extra','bytecode','symlink','hardlink','manifest'])
def test_release_tampering_rejected(built,tmp_path,mutation):
    output,result,commit,wheels=built
    if mutation=='source':(output/'runtime/app/decision_pipeline.py').write_text('raise RuntimeError')
    if mutation=='extra':(output/'extra.txt').write_text('unexpected')
    if mutation=='bytecode':(output/'runtime/app/cache.pyc').write_bytes(b'unsafe')
    if mutation=='symlink':(output/'linked').symlink_to(output/'run.py')
    if mutation=='hardlink':os.link(output/'run.py',output/'linked')
    if mutation=='manifest':(output/'manifest.json').write_text('{}')
    with pytest.raises(ValueError):r.inspect_release(output,result['manifest_sha256'],ROOT,commit,wheels)


def test_no_legacy_or_unpinned_wheel_fallback(tmp_path):
    with pytest.raises(ValueError):r.source(ROOT,'main')
    with pytest.raises((ValueError,subprocess.CalledProcessError)):r.build(ROOT,'0'*40,tmp_path,tmp_path/'bad')
    from ops.m78_sandbox.wheel_profile import authenticated_files
    empty=tmp_path/'wheels';empty.mkdir()
    with pytest.raises(ValueError):authenticated_files(empty)
    for name in WHEELS:(empty/name).write_bytes(b'not an authenticated wheel')
    with pytest.raises(ValueError):authenticated_files(empty)


def test_readonly_host_preflight_never_grants_deployment(monkeypatch):
    # Fake all /mnt and /proc reads; this test never audits the real server.
    monkeypatch.setattr(Path,'lstat',lambda self:(_ for _ in ()).throw(OSError('fixture unavailable')))
    monkeypatch.setattr(Path,'exists',lambda self:False)
    monkeypatch.setattr(Path,'is_symlink',lambda self:False)
    monkeypatch.setattr(Path,'read_text',lambda self,*a,**k:'')
    monkeypatch.setattr(Path,'glob',lambda self,*a:[])
    report=r.host_preflight()
    assert report['readiness']=='FAIL' and report['target_security']=='NOT_TESTED'
    assert not report['deployment_authorized'] and report['issues']


def test_offline_configuration_cannot_enable_network_or_escape_layout(tmp_path):
    from app.evidence_io import digest,json_write
    value=dict(schema=1,mode='OFFLINE_REPORT_ONLY',release=str(r.DESTINATION/'release'),release_sha256='1'*64,
        manifest=str(r.STATE_ROOT/'inputs/manifest.json'),manifest_sha256='2'*64,
        history=str(r.STATE_ROOT/'state/observations.sqlite3'),output=str(r.STATE_ROOT/'reports/review-001'),as_of='2026-11-03T12:00:00+00:00')
    path=tmp_path/'config.json';json_write(path,value)
    assert r.configuration(path,digest(path))['configuration']=='PASS'
    assert not r.configuration(path,digest(path))['deployment_authorized']
    for key,new in (('mode','LIVE'),('output',str(r.DESTINATION/'release')),('history','/mnt/intelligenceos_data/arbitrage/sandbox/m78/state.db'),('network',True)):
        changed=dict(value);changed[key]=new;candidate=tmp_path/(key+'.json');json_write(candidate,changed)
        with pytest.raises(ValueError):r.configuration(candidate,digest(candidate))


def test_reporting_errors_are_redacted_and_nonzero(tmp_path,capsys):
    from app.decision_pipeline import main
    assert main(['--manifest',str(tmp_path/'missing-private-path.json'),'--manifest-sha256','0'*64,
        '--history',str(tmp_path/'state/db'),'--output',str(tmp_path/'out'),'--as-of','2026-11-03T12:00:00+00:00'])==1
    captured=capsys.readouterr()
    assert 'FAIL_CLOSED' in captured.err and 'missing-private-path' not in captured.err and 'Traceback' not in captured.err


def test_preflight_command_has_no_excel_or_site_dependency():
    result=subprocess.run([sys.executable,'-S','-B','-m','ops.intelligence_release','--help'],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'host-preflight' in result.stdout


def test_reviewed_source_names_are_not_authority_artifact_paths(tmp_path,monkeypatch):
    # Test only the Git-source boundary without claiming fake dependencies are authenticated.
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    wheels=tmp_path/'fixture-wheels';wheels.mkdir()
    monkeypatch.setattr(r,'authenticated_files',lambda path:{'openpyxl/__init__.py':b'# SYNTHETIC TEST DOUBLE ONLY\n'})
    output=tmp_path/'release';result=r.build(ROOT,commit,wheels,output)
    assert (output/'runtime/app/m77_authorization.py').is_file()
    assert r.inspect_release(output,result['manifest_sha256'],ROOT,commit,wheels)['integrity']=='PASS'
    (output/'runtime/app/m77_authorization.py').write_text('# changed')
    with pytest.raises(ValueError):r.inspect_release(output,result['manifest_sha256'],ROOT,commit,wheels)
