"""Fresh installation tests use only synthetic temporary trees."""
import importlib.util
import os
from pathlib import Path
import sys
import pytest

HERE = Path(__file__).parents[1] / 'ops/m78_sandbox'
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('m78_install', HERE / 'install.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
sys.path.pop(0)


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    tmp_path.chmod(0o755)
    mounts = m.mountpoints
    monkeypatch.setattr(m, 'mountpoints', lambda: mounts() - set(tmp_path.parents))
    secure = m.secure
    exempt = set(tmp_path.parents)
    monkeypatch.setattr(m, 'secure', lambda p, owner=0, private=False: None if p in exempt
                        else secure(p, os.getuid() if owner == 0 else owner, private))
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    expected = {}
    for name in ('app/a.py', 'ops/b.py', 'dependencies/d.py', 'dependencies/d.pyc'):
        path = bundle / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'independently approved synthetic bytes')
        expected[name] = m.digest(path)
    probe = tmp_path / 'probe.py'
    probe.write_text('synthetic probe')
    base = tmp_path / 'm78-isolated'
    def run(apply=False):
        return m.install(base, bundle, expected, probe, os.getuid(), os.getgid(), apply, (2, 2))
    return base, bundle, expected, run


def test_fresh_preflight_apply_and_idempotence(fresh):
    base, bundle, _, run = fresh
    originals = {p: (p.stat().st_ino, p.read_bytes()) for p in bundle.rglob('*') if p.is_file()}
    assert run()['migration'] == 'PREFLIGHT_PASS'
    assert not base.exists()
    assert run(True)['migration'] == 'PASS'
    assert (base / 'deps/d.pyc').read_bytes() == (bundle / 'dependencies/d.pyc').read_bytes()
    before = {p: p.stat().st_ino for p in base.rglob('*')}
    assert run(True)['migration'] == 'PASS'
    assert before == {p: p.stat().st_ino for p in base.rglob('*')}
    assert originals == {p: (p.stat().st_ino, p.read_bytes()) for p in originals}
    assert not any((base / 'evidence').iterdir())
    assert (base / 'output').stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('change', ['drift', 'extra', 'missing', 'cache', 'symlink', 'hardlink', 'acl', 'acl_error', 'mount', 'space'])
def test_bundle_fail_closed(fresh, monkeypatch, change):
    base, bundle, _, run = fresh
    source = bundle / 'dependencies/d.pyc'
    if change == 'drift': source.write_bytes(b'changed')
    elif change == 'extra': (bundle / 'dependencies/extra').touch()
    elif change == 'missing': source.unlink()
    elif change == 'cache': (bundle / 'app/a.pyc').touch()
    elif change == 'symlink':
        source.unlink()
        source.symlink_to('d.py')
    elif change == 'hardlink': os.link(source, bundle / 'dependencies/link')
    elif change in ('acl', 'acl_error'):
        original = os.listxattr
        def attrs(path, **kw):
            if path == source:
                if change == 'acl_error': raise OSError('ACL inspection denied')
                return ['system.posix_acl_access']
            return original(path, **kw)
        monkeypatch.setattr(os, 'listxattr', attrs)
    elif change == 'mount':
        monkeypatch.setattr(sys.modules['migrate'], 'mountpoints', lambda: {source})
    else:
        from types import SimpleNamespace
        monkeypatch.setattr(m.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    with pytest.raises((ValueError, OSError)):
        run(True)
    assert not base.exists()


@pytest.mark.parametrize('where', ['parent', 'bundle', 'destination'])
def test_acl_boundaries(fresh, monkeypatch, where):
    base, bundle, _, run = fresh
    if where == 'destination': base.mkdir()
    target = {'parent': base.parent, 'bundle': bundle, 'destination': base}[where]
    original = os.listxattr
    monkeypatch.setattr(os, 'listxattr', lambda p, **kw: ['system.posix_acl_default']
                        if p == target else original(p, **kw))
    with pytest.raises(ValueError, match='ACL'):
        run(True)
    assert not (base / 'code').exists()


def test_old_acl_sandbox_is_never_accessed(fresh, monkeypatch):
    base, _, _, run = fresh
    old = base.parent / 'sandbox'
    old.mkdir()
    sentinel = old / 'm77-registry'
    sentinel.write_bytes(b'preserve evidence and registry')
    inode = sentinel.stat().st_ino
    original = os.listxattr
    def attrs(path, **kw):
        assert old not in Path(path).parents and Path(path) != old
        return original(path, **kw)
    monkeypatch.setattr(os, 'listxattr', attrs)
    assert run(True)['existing_sandbox'] == 'NOT_ACCESSED'
    assert sentinel.stat().st_ino == inode
    assert sentinel.read_bytes() == b'preserve evidence and registry'


@pytest.mark.parametrize('conflict', ['deps/d.pyc', 'evidence/private', 'output/private', 'root/payload'])
def test_existing_conflicts_preserved(fresh, conflict):
    base, _, _, run = fresh
    run(True)
    target = base / conflict
    if target.exists(): target.chmod(0o644)
    target.write_bytes(b'preserve conflicting artifact')
    inode = target.stat().st_ino
    with pytest.raises(ValueError): run(True)
    assert target.stat().st_ino == inode
    assert target.read_bytes() == b'preserve conflicting artifact'


def test_matching_partial_install_resumes(fresh):
    base, bundle, _, run = fresh
    target = base / 'code/app/a.py'
    target.parent.mkdir(parents=True)
    target.write_bytes((bundle / 'app/a.py').read_bytes())
    inode = target.stat().st_ino
    run(True)
    assert target.stat().st_ino == inode


def test_fixed_paths_and_wrapper():
    expected = '/mnt/intelligenceos_data/arbitrage/m78-isolated'
    for name in ('install.py', 'launch.py', 'migrate.py', 'audit.py'):
        assert expected in (HERE / name).read_text()
        assert '/arbitrage/sandbox/m78' not in (HERE / name).read_text()
    text = (HERE / 'deploy_verify.py').read_text()
    assert "here / 'install.py'" in text
    assert "here / 'migrate.py'" not in text
    assert 'exit 1' in (HERE / 'prepare.sh').read_text()


def test_same_device_destination_mount_refused(fresh, monkeypatch):
    base, _, _, run = fresh
    base.mkdir()
    monkeypatch.setattr(m, 'mountpoints', lambda: {base})
    with pytest.raises(ValueError, match='mount'): run(True)
    assert not (base / 'code').exists()


def test_empty_systemd_mountpoints_remain_idempotent(fresh):
    base, _, _, run = fresh
    run(True)
    (base / 'root/usr').mkdir()
    (base / 'root/probe.py').touch()
    assert run(True)['migration'] == 'PASS'


def test_destination_symlink_refused(fresh):
    base, bundle, _, run = fresh
    base.symlink_to(bundle, target_is_directory=True)
    with pytest.raises(ValueError): run(True)
    assert not (bundle / 'code').exists()


def test_wrong_profile_refused(fresh):
    base, _, expected, run = fresh
    expected.pop('dependencies/d.pyc')
    with pytest.raises(ValueError): run(True)
    assert not base.exists()


def test_walk_inspection_error_is_fatal(fresh, monkeypatch):
    base, _, _, run = fresh
    def denied(*args, **kw):
        kw['onerror'](PermissionError('cannot enumerate'))
        return iter(())
    monkeypatch.setattr(os, 'walk', denied)
    with pytest.raises(PermissionError): run(True)
    assert not base.exists()
