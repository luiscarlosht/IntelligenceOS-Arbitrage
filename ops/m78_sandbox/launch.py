"""Fail-closed systemd sandbox. Run only after approved installation on target."""
import argparse
import os
from pathlib import Path
import pwd
import stat
import subprocess

BASE = Path('/mnt/intelligenceos_data/arbitrage/sandbox/m78')


def checked(path: Path, uid: int, writable: bool = False) -> str:
    for item in [path, *path.parents]:
        st = item.lstat()
        if stat.S_ISLNK(st.st_mode):
            raise ValueError(f'symlink rejected: {item}')
        if item != path or not writable:
            if st.st_uid != 0 or st.st_mode & 0o022:
                raise ValueError(f'unsafe ownership/mode: {item}')
    if writable and (path.stat().st_uid != uid or path.stat().st_mode & 0o077):
        raise ValueError('output must be private and service-owned')
    if not writable:
        for item in path.rglob('*'):
            st = item.lstat()
            if stat.S_ISLNK(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
                raise ValueError(f'unsafe staged file: {item}')
    return str(path)


def command(mode: str, host_net: str, uid: int, gid: int) -> list[str]:
    props = {
        'User': str(uid), 'Group': str(gid), 'SupplementaryGroups': '',
        'RootDirectory': str(BASE / 'root'), 'WorkingDirectory': '/app',
        'PrivateNetwork': 'yes', 'PrivateUsers': 'yes', 'PrivateDevices': 'yes',
        'ProtectSystem': 'strict', 'ProtectHome': 'yes', 'NoNewPrivileges': 'yes',
        'CapabilityBoundingSet': '', 'AmbientCapabilities': '',
        'RestrictAddressFamilies': 'AF_UNIX AF_INET AF_INET6 AF_NETLINK',
        'IPAddressDeny': 'any', 'RestrictNamespaces': 'yes',
        'RestrictSUIDSGID': 'yes', 'LockPersonality': 'yes',
        'ProtectKernelTunables': 'yes', 'ProtectKernelModules': 'yes',
        'ProtectControlGroups': 'yes', 'ProtectProc': 'invisible',
        'ProcSubset': 'pid', 'UMask': '0077', 'TasksMax': '32',
        'MemoryMax': '768M', 'RuntimeMaxSec': '300',
        'ReadWritePaths': '/output',
        'BindReadOnlyPaths': ' '.join(['/usr', '/lib', '-/lib64',
            f'{BASE}/code:/app', f'{BASE}/deps:/deps',
            f'{BASE}/evidence:/evidence', f'{BASE}/probe.py:/probe.py']),
        'BindPaths': f'{BASE}/output:/output',
    }
    cmd = ['systemd-run', '--quiet', '--wait', '--pipe', '--collect',
           '--service-type=exec', '--unit=intelligenceos-m78-sandbox',
           '--setenv=PYTHONPATH=/app:/deps', '--setenv=PYTHONDONTWRITEBYTECODE=1',
           '--setenv=PYTHONNOUSERSITE=1']
    for key, value in props.items():
        cmd += ['--property', f'{key}={value}']
    cmd += ['/usr/bin/env', '-i', 'PATH=/usr/bin:/bin',
            'PYTHONPATH=/app:/deps', 'PYTHONDONTWRITEBYTECODE=1',
            'PYTHONNOUSERSITE=1', '/usr/bin/python3', '-B']
    if mode == 'verify':
        cmd += ['/probe.py', host_net, str(uid)]
    else:
        cmd += ['-m', 'ops.m78_offline', '--catalog', '/evidence/M76_catalog.csv',
                '--annotations', '/evidence/annotations.json', '--sources',
                '/evidence/M77_M70_sources.json', '--output', '/output/report']
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['verify', 'run'])
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('launcher requires root; payload always uses dedicated service UID')
    account = pwd.getpwnam('intelligenceos-m78')
    if account.pw_uid == 0 or account.pw_gid == 0 or account.pw_shell not in ('/usr/sbin/nologin', '/bin/false'):
        raise ValueError('dedicated non-login account required')
    for name in ('root', 'code', 'deps', 'evidence', 'probe.py'):
        checked(BASE / name, account.pw_uid)
    checked(BASE / 'output', account.pw_uid, True)
    if any((BASE / 'root').iterdir()):
        raise ValueError('root directory must be empty before launch')
    host_net = os.readlink('/proc/self/ns/net')
    clean_env = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin'}
    verified = subprocess.run(command('verify', host_net, account.pw_uid, account.pw_gid),
                              check=False, env=clean_env).returncode
    if verified or args.mode == 'verify':
        return verified
    return subprocess.run(command('run', host_net, account.pw_uid, account.pw_gid),
                          check=False, env=clean_env).returncode


if __name__ == '__main__':
    raise SystemExit(main())
