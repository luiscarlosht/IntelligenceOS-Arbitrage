"""Build an inventory offline from pinned Git objects and independent dependency records.

Never reads the sandbox. Pins must be authenticated independently by the reviewer.
The output is a candidate until its provenance and digest receive operator review.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess


def build(repo: Path, revision: str, record: Path, record_sha256: str) -> dict[str, str]:
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('full reviewed Git commit SHA required')
    raw = record.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record_sha256:
        raise ValueError('independent dependency record digest mismatch')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate dependency path')
            result[key] = value
        return result
    deps = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(deps, dict) or len(deps) != 401:
        raise ValueError('401 independently verified dependency records required')
    for name, digest in deps.items():
        path = PurePosixPath(name)
        if (not name.startswith('dependencies/') or len(path.parts) < 2 or str(path) != name or '..' in path.parts
                or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
            raise ValueError('invalid dependency record')
    def git(*args):
        return subprocess.check_output(
            ['/usr/bin/git', '--no-replace-objects', '-C', str(repo), *args],
            env={'PATH': os.defpath, 'GIT_CONFIG_NOSYSTEM': '1',
                 'GIT_CONFIG_GLOBAL': '/dev/null'}, stderr=subprocess.PIPE)
    git('cat-file', '-e', revision + '^{commit}')
    git('fsck', '--strict', '--no-reflogs', revision)
    entries = git('ls-tree', '-rz', '--full-tree', revision, '--', 'app', 'ops/m78_offline.py')
    code = {}
    for entry in entries.split(b'\0'):
        if not entry:
            continue
        meta, raw_name = entry.split(b'\t', 1)
        mode, kind, oid = meta.split()
        name = raw_name.decode('utf-8')
        if not name.endswith('.py'):
            continue
        if mode not in (b'100644', b'100755') or kind != b'blob':
            raise ValueError('source must be a regular Git blob')
        code[name] = hashlib.sha256(git('cat-file', 'blob', oid.decode())).hexdigest()
    if len(code) != 127 or 'ops/m78_offline.py' not in code:
        raise ValueError('reviewed revision must contain 126 app and one ops Python file')
    return dict(sorted((code | deps).items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--dependency-record', type=Path, required=True)
    parser.add_argument('--dependency-record-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    inventory = build(args.repo, args.source_commit, args.dependency_record,
                      args.dependency_record_sha256)
    with args.output.open('x') as stream:
        stream.write(json.dumps(inventory, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'files': len(inventory), 'source_commit': args.source_commit,
                      'dependency_record_sha256': args.dependency_record_sha256,
                      'manifest_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      'trust': 'REQUIRES_INDEPENDENT_PROVENANCE_REVIEW'}))


if __name__ == '__main__':
    main()
