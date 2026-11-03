"""Inventory trust comes from external pins, never from staging or a worktree."""
import hashlib
import json
from pathlib import Path
import subprocess
import pytest
from ops.m78_sandbox.inventory import build


def test_inventory_uses_committed_blobs_and_pinned_records(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args]).decode().strip()
    git('init', '-q')
    (repo / 'app').mkdir()
    (repo / 'ops').mkdir()
    for n in range(126):
        (repo / f'app/a{n}.py').write_text('reviewed source')
    (repo / 'ops/m78_offline.py').write_text('reviewed entry')
    git('add', '.')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
    revision = git('rev-parse', 'HEAD')
    record = tmp_path / 'records.json'
    record.write_text(json.dumps({f'dependencies/file{n}': 'a' * 64 for n in range(401)}))
    pin = hashlib.sha256(record.read_bytes()).hexdigest()
    (repo / 'app/a0.py').write_text('untrusted worktree changes')
    original = git('rev-parse', revision + ':app/a0.py')
    replacement = git('hash-object', '-w', 'app/a0.py')
    git('replace', original, replacement)
    inventory = build(repo, revision, record, pin)
    assert len(inventory) == 528
    assert inventory['app/a0.py'] == hashlib.sha256(b'reviewed source').hexdigest()
    with pytest.raises(ValueError, match='digest mismatch'):
        build(repo, revision, record, '0' * 64)
    with pytest.raises(ValueError, match='full reviewed'):
        build(repo, 'HEAD', record, pin)
    record.write_text(record.read_text().replace('dependencies/file0', 'dependencies/../escape'))
    with pytest.raises(ValueError, match='invalid dependency'):
        build(repo, revision, record, hashlib.sha256(record.read_bytes()).hexdigest())
