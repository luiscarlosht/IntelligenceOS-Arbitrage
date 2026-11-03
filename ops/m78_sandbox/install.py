"""Fresh isolated installation from an independently approved offline bundle.

Default is read-only. Never reads or modifies the previous sandbox.
Root concurrency and an idle dedicated account are operator prerequisites.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess

from migrate import secure, walk, digest, mountpoints, walk_error

from wheel_profile import PROFILE, decode_manifest, safe_name

BASE = Path('/mnt/intelligenceos_data/arbitrage/m78-isolated')


def boundary(path: Path) -> None:
    for node in reversed([path, *path.parents]):
        secure(node)
        if not node.is_dir():
            raise ValueError('real directory required')
        if node in mountpoints() and node not in (Path('/'), Path('/mnt/intelligenceos_data')):
            raise ValueError('unexpected ancestor mount')


def install(base: Path, bundle: Path, expected: dict[str, str], probe: Path,
            uid: int, gid: int, apply: bool = False,
            counts: tuple[int, int | None] = (127, None)) -> dict:
    if not bundle.is_absolute() or '..' in bundle.parts:
        raise ValueError('absolute canonical bundle path required')
    boundary(base.parent)
    if base.parent.stat().st_mode & 0o005 != 0o005:
        raise ValueError('destination parent requires read/traverse')
    boundary(bundle)
    if bundle == base or base in bundle.parents or bundle in base.parents:
        raise ValueError('bundle and destination must be independent')
    secure(probe)
    for parent in probe.parents:
        secure(parent)
    if not probe.is_file():
        raise ValueError('regular probe required')
    for name in expected:
        safe_name(name)
    actual = walk(bundle)
    if actual != expected:
        raise ValueError('bundle differs from trusted manifest, including extras')
    code = {k: v for k, v in actual.items() if k.startswith(('app/', 'ops/'))}
    deps = {k.removeprefix('dependencies/'): v for k, v in actual.items()
            if k.startswith('dependencies/')}
    if (len(code) != counts[0] or (counts[1] is not None and len(deps) != counts[1])
            or len(code) + len(deps) != len(actual)
            or any(not k.endswith('.py') for k in code)):
        raise ValueError('verified artifact counts/types differ from approved profile')
    planned = {'code/' + k: (bundle / k, sha) for k, sha in code.items()}
    planned.update({'deps/' + k: (bundle / 'dependencies' / k, sha) for k, sha in deps.items()})
    planned['probe.py'] = (probe, digest(probe))
    allowed_dirs = {'root', 'code', 'deps', 'evidence', 'output'}
    for name in planned:
        allowed_dirs.update(str(p) for p in Path(name).parents if str(p) != '.')
    mounted = mountpoints()
    if base.exists() or base.is_symlink():
        boundary(base)
        if base.stat().st_mode & 0o005 != 0o005:
            raise ValueError('destination requires read/traverse')
        if base.stat().st_dev != base.parent.stat().st_dev:
            raise ValueError('destination must remain on parent volume')
        # Inspect every node, including empty directories; no ACL allowlist.
        for parent, dirs, files in os.walk(base, followlinks=False, onerror=walk_error):
            for name in dirs + files:
                item = Path(parent) / name
                rel = item.relative_to(base).as_posix()
                secure(item, uid if rel == 'output' else 0, rel == 'output')
                if item in mounted or item.stat().st_dev != base.stat().st_dev:
                    raise ValueError('nested mount rejected')
                if rel == 'output' and item.stat().st_gid != gid:
                    raise ValueError('output GID mismatch')
                if item.is_dir():
                    if rel.startswith('root/'):
                        continue  # Empty systemd mountpoint directories only.
                    if rel not in allowed_dirs or item.stat().st_mode & 0o005 != (0 if rel == 'output' else 0o005):
                        raise ValueError('unexpected or inaccessible destination directory')
                elif rel == 'root/probe.py' and item.stat().st_size == 0:
                    continue
                elif rel not in planned or digest(item) != planned[rel][1]:
                    raise ValueError('conflicting destination; no overwrite permitted')
        for name in allowed_dirs.intersection({'root', 'code', 'deps', 'evidence', 'output'}):
            item = base / name
            if item.exists() and not item.is_dir():
                raise ValueError('destination directory required')
    needed = sum(src.stat().st_size for name, (src, _) in planned.items()
                 if not (base / name).exists())
    if shutil.disk_usage(base.parent).free < needed + 256 * 1024 * 1024:
        raise ValueError('insufficient free space plus 256 MiB reserve')
    if apply:
        base.mkdir(mode=0o755, exist_ok=True)
        secure(base)
        for name in ('root', 'code', 'deps', 'evidence', 'output'):
            item = base / name
            if not item.exists():
                item.mkdir(mode=0o700 if name == 'output' else 0o755)
                if name == 'output':
                    os.chown(item, uid, gid)
            secure(item, uid if name == 'output' else 0, name == 'output')
        for name, (src, sha) in sorted(planned.items()):
            dest = base / name
            dest.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            for parent in [dest.parent, *dest.parent.parents]:
                secure(parent)
            if not dest.exists():
                with src.open('rb') as source, dest.open('xb') as out:
                    os.fchmod(out.fileno(), 0o444)
                    shutil.copyfileobj(source, out)
                    out.flush()
                    os.fsync(out.fileno())
            if digest(dest) != sha:
                raise ValueError('copy integrity failure; preserve partial installation')
        install(base, bundle, expected, probe, uid, gid, False, counts)
    return {'migration': 'PASS' if apply else 'PREFLIGHT_PASS',
            'dependency_profile': PROFILE, 'installation': 'FRESH_ISOLATED', 'base': str(base),
            'code_files': len(code), 'dependency_files': len(deps),
            'target_isolation': 'NOT_TESTED', 'production_ready': False,
            'existing_sandbox': 'NOT_ACCESSED'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True,
                        help='independently approved ACL-free offline bundle; never the old sandbox')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0 or not os.path.ismount('/mnt/intelligenceos_data'):
        parser.error('root and mounted dedicated volume required')
    account = pwd.getpwnam('intelligenceos-m78')
    if (account.pw_uid, account.pw_gid) != (997, 986) or account.pw_shell not in ('/usr/sbin/nologin', '/bin/false'):
        parser.error('expected dedicated UID 997 / GID 986 and non-login shell')
    idle = subprocess.run(['/usr/bin/pgrep', '-u', '997'], capture_output=True, check=False)
    if idle.returncode != 1:
        parser.error('dedicated account must be idle; never kill existing jobs')
    if args.apply:
        os.umask(0o022)
    secure(args.manifest)
    for parent in args.manifest.parents:
        secure(parent)
    reviewed = decode_manifest(args.manifest.read_bytes())
    print(json.dumps(install(BASE, args.bundle, reviewed['files'],
                             Path(__file__).with_name('probe.py'), 997, 986, args.apply), sort_keys=True))


if __name__ == '__main__':
    main()
