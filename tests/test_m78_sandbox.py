from pathlib import Path
import importlib.util
import pytest

spec = importlib.util.spec_from_file_location('sandbox_launcher', Path(__file__).parents[1] / 'ops/m78_sandbox/launch.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_required_boundaries():
    cmd = launcher.command('verify', 'net:[123]', 1234, 1234)
    for prop in ('PrivateNetwork=yes', 'PrivateUsers=yes', 'ProtectSystem=strict',
                 'NoNewPrivileges=yes', 'CapabilityBoundingSet=', 'User=1234',
                 'IPAddressDeny=any', 'RestrictNamespaces=yes'):
        assert prop in cmd
    assert cmd[-5:-1] == ['/probe.py', 'net:[123]', '1234', '1234']
    assert not any('/root:' in value or '/mnt:/mnt' in value for value in cmd)


def test_missing_stage_fails_closed(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        launcher.checked(tmp_path / 'missing', 1234)


def test_symlink_stage_rejected(tmp_path):
    path = tmp_path / 'linked'
    path.symlink_to('/usr')
    with pytest.raises(ValueError, match='symlink'):
        launcher.checked(path, 1234)


def test_service_writable_code_rejected(tmp_path):
    path = tmp_path / 'code'
    path.mkdir(mode=0o777)
    path.chmod(0o777)
    with pytest.raises(ValueError, match='unsafe'):
        launcher.checked(path, 1234)


def test_nonroot_launcher_refused(monkeypatch):
    monkeypatch.setattr(launcher.os, 'geteuid', lambda: 1234)
    import sys
    monkeypatch.setattr(sys, 'argv', ['launch.py', 'verify'])
    with pytest.raises(SystemExit) as error:
        launcher.main()
    assert error.value.code != 0


def test_failed_probe_never_runs_analysis(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import sys
    (tmp_path / 'root').mkdir()
    monkeypatch.setattr(launcher, 'BASE', tmp_path)
    monkeypatch.setattr(launcher.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(launcher.os, 'readlink', lambda _: 'net:[123]')
    monkeypatch.setattr(launcher.os.path, 'ismount', lambda _: True)
    monkeypatch.setattr(launcher.pwd, 'getpwnam', lambda _: SimpleNamespace(
        pw_uid=1234, pw_gid=1234, pw_shell='/usr/sbin/nologin'))
    monkeypatch.setattr(launcher, 'checked', lambda *args: None)
    monkeypatch.setattr(sys, 'argv', ['launch.py', 'run'])
    calls = []
    def failed(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(launcher.subprocess, 'run', failed)
    assert launcher.main() == 1
    assert len(calls) == 1
    assert '/probe.py' in calls[0]
    assert 'ops.m78_offline' not in calls[0]


def test_unmounted_volume_refused(monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'argv', ['launch.py', 'verify'])
    monkeypatch.setattr(launcher.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(launcher.os.path, 'ismount', lambda _: False)
    with pytest.raises(ValueError, match='not mounted'):
        launcher.main()


def test_same_device_stage_mount_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, 'mountpoints', lambda: {tmp_path})
    with pytest.raises(ValueError, match='nested mount'):
        launcher.checked(tmp_path, 1234)
