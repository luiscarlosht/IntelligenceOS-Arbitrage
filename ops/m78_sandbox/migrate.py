"""Check by default; --apply requires separate operator deployment approval.

Preserves app/, ops/, dependencies/, evidence/ and output/ in place. Creates
verified copies in code/ and deps/ without replacing any existing file.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import shutil
import stat
import subprocess

BASE = Path('/mnt/intelligenceos_data/arbitrage/sandbox/m78')
ACL_KEYS = {'system.posix_acl_access', 'system.posix_acl_default'}


def secure(path: Path, owner: int = 0, private: bool = False) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise ValueError(f'unsafe file type: {path}')
    if info.st_uid != owner or info.st_mode & (0o077 if private else 0o022):
        raise ValueError(f'unsafe ownership/mode: {path}')
    if info.st_mode & 0o7000 or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
        raise ValueError(f'special mode or hardlink: {path}')
    if ACL_KEYS.intersection(os.listxattr(path, follow_symlinks=False)):
        raise ValueError(f'extended/default ACL rejected: {path}')


def mountpoints() -> set[Path]:
    return {Path(re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), row.split()[4]))
            for row in Path('/proc/self/mountinfo').read_text().splitlines()}


def walk(path: Path, owner: int = 0, private: bool = False) -> dict[str, str]:
    secure(path, owner, private)
    if not path.is_dir():
        raise ValueError(f'directory required: {path}')
    mounted = mountpoints()
    if path in mounted:
        raise ValueError(f'nested mount rejected: {path}')
    files = {}
    for parent, dirs, names in os.walk(path, followlinks=False):
        for name in dirs + names:
            item = Path(parent) / name
            secure(item, owner, private)
            if item in mounted or item.stat().st_dev != path.stat().st_dev:
                raise ValueError(f'nested mount rejected: {item}')
            if item.is_file():
                files[item.relative_to(path).as_posix()] = digest(item)
    return files


def source_inventory(files: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Omit only canonical app/ops caches with a verified source counterpart.

    walk() has already checked every cache's metadata. Cache bytes are never
    trusted, imported, copied or deleted; dependency inventory remains exact.
    """
    caches = []
    for name in files:
        path = PurePosixPath(name)
        if path.parts[0] not in ('app', 'ops') or path.suffix != '.pyc':
            continue
        match = re.fullmatch(r'(.+)\.cpython-312(?:\.opt-[12])?\.pyc', path.name)
        if path.parent.name != '__pycache__' or match is None:
            raise ValueError('noncanonical Python cache rejected')
        source = str(path.parent.parent / (match[1] + '.py'))
        if source not in files:
            raise ValueError('orphan Python cache rejected')
        caches.append(name)
    return {k: v for k, v in files.items() if k not in caches}, sorted(caches)


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest(path: Path) -> dict[str, str]:
    secure(path)
    for parent in path.parents:
        secure(parent)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate manifest path')
            result[key] = value
        return result
    data = json.loads(path.read_text(), object_pairs_hook=unique)
    if not isinstance(data, dict):
        raise ValueError('manifest must map relative paths to SHA-256 strings')
    for name, value in data.items():
        parts = PurePosixPath(name)
        if (not parts.parts or parts.is_absolute() or '..' in parts.parts or str(parts) != name
                or parts.parts[0] not in ('app', 'ops', 'dependencies')
                or not isinstance(value, str) or len(value) != 64
                or any(c not in '0123456789abcdef' for c in value)):
            raise ValueError('invalid manifest entry')
    return data


def migrate(base: Path, expected: dict[str, str], probe: Path, uid: int,
            apply: bool = False, counts: tuple[int, int] = (127, 401)) -> dict:
    # Root-owned ancestors prevent service-user path replacement. Never repair
    # ownership, modes or ACLs automatically; a failed check requires review.
    for path in [base, *base.parents]:
        secure(path)
    secure(probe)
    for name in ('evidence', 'output'):
        path = base / name
        secure(path, uid if name == 'output' else 0, name == 'output')
        if path.stat().st_dev != base.stat().st_dev:
            raise ValueError(f'cross-device staging rejected: {path}')
        if name == 'evidence' and path.stat().st_mode & 0o005 != 0o005:
            raise ValueError('empty evidence directory requires non-owner read/traverse for the probe')
        if not path.is_dir() or any(path.iterdir()):
            raise ValueError(f'{name} must be an empty directory; contents untouched')
    actual = {}
    for name in ('app', 'ops', 'dependencies'):
        if (base / name).stat().st_dev != base.stat().st_dev:
            raise ValueError('original artifacts must be on the dedicated volume')
        actual.update({f'{name}/{key}': value for key, value in walk(base / name).items()})
    actual, caches = source_inventory(actual)
    if actual != expected:
        raise ValueError('original artifacts differ from trusted manifest (including extra files)')
    code = {k: v for k, v in actual.items() if not k.startswith('dependencies/')}
    deps = {k.removeprefix('dependencies/'): v for k, v in actual.items() if k.startswith('dependencies/')}
    if len(code) != counts[0] or len(deps) != counts[1] or any(not k.endswith('.py') for k in code):
        raise ValueError('verified artifact counts/types differ from expected profile')
    planned = {'code': code, 'deps': deps}
    # Preflight every destination before any mutation; partial copies may be
    # resumed only if every already-present file matches the approved manifest.
    for name, wanted in planned.items():
        dest = base / name
        if dest.exists() or dest.is_symlink():
            present = walk(dest)
            if any(key not in wanted or wanted[key] != value for key, value in present.items()):
                raise ValueError(f'conflicting destination: {dest}')
    root = base / 'root'
    if root.exists() or root.is_symlink():
        contents = walk(root)
        if any(name != 'probe.py' or sha != hashlib.sha256(b'').hexdigest()
               for name, sha in contents.items()):
            raise ValueError('root contains payload files rather than empty mountpoints')
    target_probe = base / 'probe.py'
    if target_probe.exists() or target_probe.is_symlink():
        secure(target_probe)
        if not target_probe.is_file() or digest(target_probe) != digest(probe):
            raise ValueError('existing probe differs; no overwrite permitted')
    needed = 0
    for name, wanted in planned.items():
        for relative in wanted:
            if not (base / name / relative).exists():
                source = base / (relative if name == 'code' else 'dependencies/' + relative)
                needed += source.stat().st_size
    if not target_probe.exists():
        needed += probe.stat().st_size
    if shutil.disk_usage(base).free < needed + 256 * 1024 * 1024:
        raise ValueError('insufficient free space for copies plus 256 MiB safety reserve')
    if apply:
        for name in ('root', 'code', 'deps'):
            (base / name).mkdir(mode=0o755, exist_ok=True)
        for name, wanted in planned.items():
            for relative, sha in sorted(wanted.items()):
                dest = base / name / relative
                dest.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                secure(dest.parent)
                source = base / (relative if name == 'code' else 'dependencies/' + relative)
                if not dest.exists():
                    # xb is exclusive: no symlink/overwrite fallback. A crash
                    # leaving a partial file causes refusal on the next check.
                    with source.open('rb') as src, dest.open('xb') as out:
                        os.chmod(dest, 0o444)
                        for chunk in iter(lambda: src.read(1024 * 1024), b''):
                            out.write(chunk)
                        out.flush()
                        os.fsync(out.fileno())
                if digest(dest) != sha:
                    raise ValueError('copy integrity failure; stop and preserve artifacts')
        if not target_probe.exists():
            with probe.open('rb') as src, target_probe.open('xb') as out:
                os.chmod(target_probe, 0o444)
                out.write(src.read())
                out.flush()
                os.fsync(out.fileno())
        # Recheck sources, destinations, ACLs, ownership and empty evidence/output.
        migrate(base, expected, probe, uid, False, counts)
        for name, wanted in planned.items():
            if walk(base / name) != wanted:
                raise ValueError('incomplete copy')
    return {'migration': 'PASS' if apply else 'PREFLIGHT_PASS', 'code_files': len(code),
            'dependency_files': len(deps), 'evidence': 'EMPTY_UNTOUCHED',
            'originals': 'PRESERVED', 'preserved_untrusted_caches': caches, 'target_isolation': 'NOT_TESTED',
            'production_ready': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True,
                        help='independently trusted root-owned JSON manifest; never regenerate from untrusted staging')
    parser.add_argument('--apply', action='store_true', help='mutates sandbox; requires explicit owner approval')
    args = parser.parse_args()
    if os.geteuid() != 0 or not os.path.ismount('/mnt/intelligenceos_data'):
        parser.error('root and mounted dedicated volume required')
    account = pwd.getpwnam('intelligenceos-m78')
    if account.pw_uid == 0 or account.pw_gid == 0 or account.pw_shell not in ('/usr/sbin/nologin', '/bin/false'):
        parser.error('dedicated non-login non-root account required')
    idle = subprocess.run(['/usr/bin/pgrep', '-u', str(account.pw_uid)],
                          capture_output=True, check=False)
    if idle.returncode != 1:
        parser.error('service account must have no active processes; do not kill jobs automatically')
    if args.apply:
        os.umask(0o022)  # New directories remain traversable by the service UID.
    print(json.dumps(migrate(BASE, manifest(args.manifest), Path(__file__).with_name('probe.py'),
                             account.pw_uid, args.apply), sort_keys=True))


if __name__ == '__main__':
    main()
