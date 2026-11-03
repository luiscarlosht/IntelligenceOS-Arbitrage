import os
from ops.m78_sandbox.audit import inspect


def test_audit_reports_caches_without_mutation_or_evidence_reads(tmp_path):
    base = tmp_path / 'sandbox'
    for name in ('app', 'ops', 'dependencies', 'evidence', 'output'):
        (base / name).mkdir(parents=True)
    (base / 'app/a.py').write_text('synthetic')
    (base / 'app/a.pyc').write_bytes(b'cache')
    (base / 'evidence/private').write_text('never read')
    before = {str(p): (p.stat().st_ino, p.stat().st_mtime_ns) for p in base.rglob('*')}
    report = inspect(base)
    assert report['counts']['app'] == {'files': 2, 'py': 1, 'pyc': 1}
    assert report['readiness'] == 'FAIL'
    assert report['server_changes'] == 'NONE'
    assert 'private' not in str(report)
    assert before == {str(p): (p.stat().st_ino, p.stat().st_mtime_ns) for p in base.rglob('*')}


def test_audit_refuses_symlink_base(tmp_path):
    import pytest
    link = tmp_path / 'linked'
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='real directory'):
        inspect(link)
