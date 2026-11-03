"""Only temporary synthetic files; never uses the deployed sandbox."""
import importlib.util
import os
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('m78_migrate', Path(__file__).parents[1] / 'ops/m78_sandbox/migrate.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def staged(tmp_path, monkeypatch):
    # Production rejects writable ancestors. Only the test harness's /tmp
    # ancestor is exempted; every synthetic sandbox node is checked normally.
    secure = m.secure
    harness_ancestors = set(tmp_path.parents)
    monkeypatch.setattr(m, 'secure', lambda p, owner=0, private=False: None
                        if p in harness_ancestors else secure(
                            p, os.getuid() if owner == 0 else owner, private))
    base = tmp_path / 'm78'
    base.mkdir()
    for name in ('app', 'ops', 'dependencies', 'evidence', 'output'):
        (base / name).mkdir(mode=0o700 if name == 'output' else 0o755)
    for name in ('app/a.py', 'ops/b.py', 'dependencies/d.py'):
        (base / name).write_text('synthetic fixture\n')
    probe = tmp_path / 'probe.py'
    probe.write_text('synthetic probe\n')
    expected = {name: m.digest(base / name) for name in ('app/a.py', 'ops/b.py', 'dependencies/d.py')}
    def run(apply=False):
        return m.migrate(base, expected, probe, os.getuid(), apply, (2, 1))
    return base, expected, run


def test_check_does_not_mutate_and_apply_is_idempotent(staged):
    base, expected, run = staged
    assert run()['migration'] == 'PREFLIGHT_PASS'
    assert not (base / 'code').exists()
    assert run(True)['migration'] == 'PASS'
    inodes = {p: p.stat().st_ino for p in base.rglob('*')}
    assert run(True)['migration'] == 'PASS'
    assert inodes == {p: p.stat().st_ino for p in base.rglob('*')}
    for name, sha in expected.items():
        assert m.digest(base / name) == sha
    assert not any((base / 'evidence').iterdir())


@pytest.mark.parametrize('folder', ['evidence', 'output'])
def test_nonempty_protected_directory_untouched(staged, folder):
    base, _, run = staged
    sentinel = base / folder / 'do-not-touch'
    sentinel.write_text('synthetic sentinel')
    with pytest.raises(ValueError, match='empty'):
        run(True)
    assert sentinel.read_text() == 'synthetic sentinel'
    assert not (base / 'code').exists()


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'writable', 'drift', 'extra', 'acl', 'owner'])
def test_unsafe_source_fails_before_mutation(staged, monkeypatch, kind):
    base, _, run = staged
    source = base / 'app/a.py'
    if kind == 'symlink':
        source.unlink()
        source.symlink_to('../ops/b.py')
    elif kind == 'hardlink':
        os.link(source, base / 'app/linked.py')
    elif kind == 'writable':
        source.chmod(0o666)
    elif kind == 'drift':
        source.write_text('changed')
    elif kind == 'extra':
        (base / 'app/extra.py').write_text('extra')
    elif kind == 'owner':
        original_stat = Path.lstat
        def wrong_owner(path):
            st = original_stat(path)
            if path == source:
                values = list(st)
                values[4] = 12345
                return os.stat_result(values)
            return st
        monkeypatch.setattr(Path, 'lstat', wrong_owner)
    else:
        original = os.listxattr
        monkeypatch.setattr(m.os, 'listxattr', lambda p, **kw: ['system.posix_acl_access'] if p == source else original(p, **kw))
    with pytest.raises(ValueError):
        run(True)
    assert not (base / 'code').exists()


def test_conflicting_destination_never_overwritten(staged):
    base, _, run = staged
    (base / 'deps').mkdir()
    conflict = base / 'deps/d.py'
    conflict.write_text('keep this')
    with pytest.raises(ValueError, match='conflicting'):
        run(True)
    assert conflict.read_text() == 'keep this'
    assert not (base / 'code').exists()


def test_matching_partial_migration_resumes(staged):
    base, _, run = staged
    (base / 'code/app').mkdir(parents=True)
    existing = base / 'code/app/a.py'
    existing.write_bytes((base / 'app/a.py').read_bytes())
    inode = existing.stat().st_ino
    run(True)
    assert existing.stat().st_ino == inode
    assert (base / 'deps/d.py').is_file()


def test_probe_conflict_refused_without_mutation(staged):
    base, _, run = staged
    (base / 'probe.py').write_text('older probe')
    with pytest.raises(ValueError, match='probe differs'):
        run(True)
    assert not (base / 'code').exists()
    assert (base / 'probe.py').read_text() == 'older probe'


def test_empty_mountpoints_survive_repeat_migration(staged):
    base, _, run = staged
    run(True)
    (base / 'root/usr').mkdir()
    (base / 'root/probe.py').touch()
    assert run(True)['migration'] == 'PASS'
    (base / 'root/unexpected').write_text('payload')
    with pytest.raises(ValueError, match='payload'):
        run(True)


def test_insufficient_space_stops_before_copy(staged, monkeypatch):
    from types import SimpleNamespace
    base, _, run = staged
    monkeypatch.setattr(m.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match='insufficient free space'):
        run(True)
    assert not (base / 'code').exists()
