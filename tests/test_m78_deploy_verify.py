import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location('m78_deploy_verify', Path(__file__).parents[1] / 'ops/m78_sandbox/deploy_verify.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.mark.parametrize('apply,migration_ok,probe,expected,calls_expected', [
    (False, True, None, 0, 1),
    (True, False, None, 1, 1),
    (True, True, {'network': False}, 1, 2),
    (True, True, {}, 1, 2),
    (True, True, {'network': True}, 1, 2),
    (True, True, dict.fromkeys(m.REQUIRED_CHECKS, 1), 1, 2),
    (True, True, dict.fromkeys(m.REQUIRED_CHECKS, True), 0, 2),
])
def test_approval_and_failure_gates(monkeypatch, capsys, apply, migration_ok, probe, expected, calls_expected):
    args = ['deploy_verify.py', '--manifest', '/reviewed/manifest.json']
    if apply:
        args.append('--apply')
    monkeypatch.setattr(sys, 'argv', args)
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        if len(calls) == 1:
            return SimpleNamespace(returncode=0 if migration_ok else 1, stdout=json.dumps({'migration': 'PASS' if apply else 'PREFLIGHT_PASS'}))
        return SimpleNamespace(returncode=0, stdout=json.dumps(probe))
    monkeypatch.setattr(m.subprocess, 'run', run)
    assert m.main() == expected
    assert len(calls) == calls_expected
    report = json.loads(capsys.readouterr().out)
    assert report['production_execution'] == 'NOT_RUN'
    assert report['production_readiness'] != 'PASS'
    assert not any('ops.m78_offline' in item for cmd in calls for item in cmd)


@pytest.mark.parametrize('stdout', ['invalid json', '{}', '{"migration":"PREFLIGHT_PASS"}'])
def test_invalid_migration_result_never_starts_probe(monkeypatch, capsys, stdout):
    monkeypatch.setattr(sys, 'argv', ['deploy_verify.py', '--manifest', '/reviewed/manifest.json', '--apply'])
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=stdout)
    monkeypatch.setattr(m.subprocess, 'run', run)
    assert m.main() == 1
    assert len(calls) == 1
    assert json.loads(capsys.readouterr().out)['target_security'] == 'NOT_RUN'
