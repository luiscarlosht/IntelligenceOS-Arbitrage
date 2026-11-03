"""Offline synthetic adversarial archives; real pinned wheels exercised in CI."""
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import zipfile
import pytest
from ops.m78_sandbox import wheel_profile as w
from ops.m78_sandbox.inventory import wheel_manifest


def archive(package, version, change=None):
    dist = f'{package}-{version}.dist-info'
    files = {
        f'{package}/__init__.py': b'synthetic source\n',
        f'{dist}/METADATA': f'Name: {package}\nVersion: {version}\n'.encode() +
            (b'Requires-Dist: et-xmlfile\n' if package == 'openpyxl' else b''),
        f'{dist}/WHEEL': b'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
    }
    if change == 'metadata': files[f'{dist}/METADATA'] = b'Name: other\nVersion: 9\n'
    if change == 'purelib': files[f'{dist}/WHEEL'] = b'Root-Is-Purelib: false\n'
    if change == 'requires': files[f'{dist}/METADATA'] += b'Requires-Dist: unexpected\n'
    extras = {'traversal': '../escape', 'absolute': '/escape', 'backslash': package + '/bad\\path',
              'bytecode': package + '/a.pyc', 'cache': package + '/__pycache__/a.py',
              'pth': package + '/hook.pth', 'native': package + '/hook.so',
              'data': package + '-1.data/scripts/hook', 'foreign': 'other/__init__.py'}
    if change in extras: files[extras[change]] = b'refuse'
    record = f'{dist}/RECORD'
    out = io.StringIO(newline='')
    writer = csv.writer(out, lineterminator='\n')
    for name, raw in files.items():
        sha = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
        writer.writerow([name, sha, str(len(raw))])
    writer.writerow([record, '', ''])
    files[record] = out.getvalue().encode()
    if change == 'record': files[f'{package}/__init__.py'] += b'drift'
    if change == 'missing_record': del files[record]
    if change == 'duplicate_record': files[record] += files[record].splitlines(keepends=True)[0]
    if change == 'record_self': files[record] = files[record].replace(b'RECORD,,', b'RECORD,sha256=bad,9')
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w') as z:
        for name, raw in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = ((stat.S_IFLNK | 0o777) if change == 'symlink' and name.endswith('__init__.py')
                                  else (stat.S_IFREG | 0o644)) << 16
            z.writestr(info, raw)
        if change == 'duplicate':
            with pytest.warns(UserWarning): z.writestr(f'{package}/__init__.py', b'duplicate')
    return result.getvalue()


@pytest.fixture
def wheels(tmp_path, monkeypatch):
    house = tmp_path / 'wheels'
    house.mkdir()
    pins = {}
    for filename in w.WHEELS:
        package = filename.split('-')[0]
        raw = archive(package, w.PACKAGES[package])
        (house / filename).write_bytes(raw)
        pins[filename] = hashlib.sha256(raw).hexdigest()
    # Synthetic pins are only fixture inputs, never deployment trust records.
    monkeypatch.setattr(w, 'WHEELS', pins)
    return house


@pytest.mark.parametrize('change', ['traversal', 'absolute', 'backslash', 'bytecode', 'cache', 'pth', 'native',
                                    'data', 'foreign', 'metadata', 'purelib', 'requires', 'record',
                                    'missing_record', 'duplicate_record', 'record_self', 'symlink', 'duplicate'])
def test_adversarial_wheel_rejected(change):
    with pytest.raises(ValueError):
        w.wheel_files(archive('openpyxl', '3.1.5', change), 'openpyxl', '3.1.5')


@pytest.mark.parametrize('change', ['drift', 'missing', 'extra', 'symlink', 'hardlink'])
def test_independent_artifact_verification(wheels, change):
    path = wheels / next(iter(w.WHEELS))
    if change == 'drift': path.write_bytes(path.read_bytes() + b'changed')
    elif change == 'missing': path.unlink()
    elif change == 'extra': (wheels / 'unapproved.whl').touch()
    elif change == 'symlink':
        raw = path.read_bytes()
        path.unlink()
        target = wheels.parent / 'outside'
        target.write_bytes(raw)
        path.symlink_to(target)
    else: os.link(path, wheels.parent / 'outside')
    with pytest.raises(ValueError): w.authenticated_files(wheels)


def source_repo(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()
    git('init', '-q')
    (repo / 'app').mkdir()
    (repo / 'ops').mkdir()
    for n in range(126): (repo / f'app/a{n}.py').write_bytes(b'reviewed source')
    (repo / 'ops/m78_offline.py').write_bytes(b'reviewed entry')
    git('add', '.')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
    return repo, git('rev-parse', 'HEAD')


def test_manifest_reproducible_and_git_bound(wheels, tmp_path):
    repo, rev = source_repo(tmp_path)
    first, payload = wheel_manifest(repo, rev, wheels)
    (repo / 'app/a0.py').write_bytes(b'untrusted worktree')
    second, again = wheel_manifest(repo, rev, wheels)
    assert first == second and payload == again
    assert first['files']['app/a0.py'] == hashlib.sha256(b'reviewed source').hexdigest()
    assert w.decode_manifest(json.dumps(first).encode()) == first
    assert not any(name.endswith(('.pyc', '.pyo')) for name in payload)


@pytest.mark.parametrize('change', ['legacy', 'profile', 'pins', 'bytecode', 'incomplete', 'duplicate'])
def test_manifest_no_downgrade_or_unsafe_entries(wheels, tmp_path, change):
    repo, rev = source_repo(tmp_path)
    data, _ = wheel_manifest(repo, rev, wheels)
    if change == 'legacy': data = data['files']
    elif change == 'profile': data['profile'] = 'legacy-401'
    elif change == 'pins': data['wheels'] = {}
    elif change == 'bytecode': data['files']['dependencies/openpyxl/cache.pyc'] = 'a' * 64
    elif change == 'incomplete': del data['files']['dependencies/openpyxl/__init__.py']
    raw = json.dumps(data).encode()
    if change == 'duplicate': raw = raw.replace(b'"profile":', b'"profile":"duplicate", "profile":', 1)
    with pytest.raises(ValueError): w.decode_manifest(raw)


def test_real_pinned_wheels_reproducible(tmp_path):
    location = os.environ.get('M78_TEST_WHEELHOUSE')
    if not location: pytest.skip('real pinned wheels supplied by CI acquisition step')
    repo = Path(__file__).parents[1]
    revision = 'aa549e23a84d46edc4817833d7c8cf16badc927b'
    first, files = wheel_manifest(repo, revision, Path(location))
    second, again = wheel_manifest(repo, revision, Path(location))
    assert first == second and files == again
    assert w.decode_manifest(json.dumps(first).encode()) == first
    assert not any(name.endswith(('.pyc', '.pyo')) for name in files)
    print('Pinned wheel profile:', len(files), 'dependency files; reproducible bytes verified')


def test_offline_cli_exclusive_outputs_and_reproducibility(tmp_path):
    location = os.environ.get('M78_TEST_WHEELHOUSE')
    if not location: pytest.skip('real pinned wheels supplied by CI acquisition step')
    repo = Path(__file__).parents[1]
    tool = repo / 'ops/m78_sandbox/inventory.py'
    import sys
    def command(n):
        return [sys.executable, '-B', str(tool), '--repo', str(repo), '--source-commit',
                'aa549e23a84d46edc4817833d7c8cf16badc927b', '--wheelhouse', location,
                '--output', str(tmp_path / f'manifest{n}.json'),
                '--bundle-output', str(tmp_path / f'bundle{n}')]
    for n in (1, 2): subprocess.run(command(n), check=True, capture_output=True)
    assert (tmp_path / 'manifest1.json').read_bytes() == (tmp_path / 'manifest2.json').read_bytes()
    data = w.decode_manifest((tmp_path / 'manifest1.json').read_bytes())
    for n in (1, 2):
        root = tmp_path / f'bundle{n}'
        actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in root.rglob('*') if p.is_file()}
        assert actual == data['files']
    # Import only the extracted dependencies plus stdlib; no site packages,
    # bytecode writes, application execution or network access are involved.
    script = ('import sys; sys.path.insert(0, sys.argv[1]); '
              'import openpyxl, et_xmlfile; '
              'assert openpyxl.__version__ == "3.1.5"; '
              'assert et_xmlfile.__version__ == "2.0.0"')
    subprocess.run([sys.executable, '-I', '-S', '-B', '-c', script,
                    str(tmp_path / 'bundle1/dependencies')], check=True, capture_output=True)
    assert not list((tmp_path / 'bundle1').rglob('*.pyc'))
    before = {p: p.stat().st_ino for p in tmp_path.rglob('*')}
    assert subprocess.run(command(1), capture_output=True).returncode != 0
    assert before == {p: p.stat().st_ino for p in tmp_path.rglob('*')}


def test_hash_authentication_precedes_archive_parsing(wheels, monkeypatch):
    path = wheels / sorted(w.WHEELS)[0]
    path.write_bytes(b'not even an archive')
    monkeypatch.setattr(w, 'wheel_files', lambda *args: pytest.fail('untrusted archive parsed'))
    with pytest.raises(ValueError, match='independent wheel SHA-256 mismatch'):
        w.authenticated_files(wheels)


def test_bounded_extraction(monkeypatch):
    monkeypatch.setattr(w, 'MAX_BYTES', 1)
    with pytest.raises(ValueError, match='extraction limits'):
        w.wheel_files(archive('openpyxl', '3.1.5'), 'openpyxl', '3.1.5')
