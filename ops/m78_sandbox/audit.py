"""Read-only M78 metadata audit. Never stages evidence or starts a unit."""
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess

BASE = Path('/mnt/intelligenceos_data/arbitrage/sandbox/m78')


def inspect(base: Path) -> dict:
    report = {'readiness': 'FAIL', 'target_security': 'NOT_TESTED',
              'server_changes': 'NONE', 'issues': [], 'counts': {}, 'acls': []}
    def node(path):
        info = path.lstat()
        attrs = os.listxattr(path, follow_symlinks=False)
        if any(x in attrs for x in ('system.posix_acl_access', 'system.posix_acl_default')):
            report['acls'].append(str(path))
        if (not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
                or info.st_mode & 0o7022 or info.st_uid != 0
                or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
            report['issues'].append({'path': str(path), 'uid': info.st_uid,
                                     'mode': oct(stat.S_IMODE(info.st_mode)), 'links': info.st_nlink})
    for path in reversed([base, *base.parents]):
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise ValueError('audit ancestor must be a real directory')
        node(path)
    for name in ('app', 'ops', 'dependencies'):
        folder = base / name
        node(folder)
        if not stat.S_ISDIR(folder.lstat().st_mode):
            raise ValueError('audit source must be a real directory')
        counts = {'files': 0, 'py': 0, 'pyc': 0}
        for parent, dirs, files in os.walk(folder, followlinks=False):
            for child in dirs + files:
                path = Path(parent) / child
                node(path)
                if path.is_file() and not path.is_symlink():
                    counts['files'] += 1
                    if path.suffix in ('.py', '.pyc'):
                        counts[path.suffix[1:]] += 1
        report['counts'][name] = counts
    # Do not enumerate evidence/output or inspect their contents.
    for name in ('evidence', 'output'):
        info = (base / name).lstat()
        report[name] = {'uid': info.st_uid, 'gid': info.st_gid,
                        'mode': oct(stat.S_IMODE(info.st_mode)),
                        'xattrs': os.listxattr(base / name, follow_symlinks=False)}
    return report


def main() -> None:
    report = inspect(BASE)
    account = pwd.getpwnam('intelligenceos-m78')
    report['account'] = {'uid': account.pw_uid, 'gid': account.pw_gid, 'shell': account.pw_shell}
    report['uid_map'] = Path('/proc/self/uid_map').read_text()
    report['gid_map'] = Path('/proc/self/gid_map').read_text()
    report['user_namespace'] = os.readlink('/proc/self/ns/user')
    report['volume_mounted'] = os.path.ismount('/mnt/intelligenceos_data')
    for name, cmd in {'mounts': ['findmnt', '-R', '/mnt/intelligenceos_data'],
                      'systemd': ['systemd', '--version'],
                      'account_processes': ['pgrep', '-u', str(account.pw_uid)]}.items():
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        report[name] = {'returncode': result.returncode, 'stdout': result.stdout}
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
