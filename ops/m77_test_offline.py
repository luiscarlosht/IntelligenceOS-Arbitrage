"""Run pytest with network and production credential reads blocked in Python children.

Usage: .venv/bin/python -m ops.m77_test_offline [-q] [tests/...]
The temporary sitecustomize hook is inherited through PYTHONPATH by subprocesses.
Synthetic test credentials and authorization artifacts in temporary directories
remain permitted; production values and live owner artifacts remain prohibited.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

GUARD='''import sys,os,socket
# smtplib constructs a local greeting name even when its transport is mocked.
# Use a synthetic dotted name without performing host DNS resolution.
socket.getfqdn=lambda name='': 'offline-test.invalid'

def guard(event,args):
    if event in ('socket.connect','socket.getaddrinfo','socket.gethostbyname','socket.gethostbyaddr','socket.sendto'):
        raise PermissionError('Offline regression network prohibited')
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        path=os.fsdecode(args[0])
        if path.startswith('/root/.intelligenceos-arbitrage-amazon/') and ('credentials.json' in path or 'owner-authorization' in path):
            raise PermissionError('Production credential/owner-artifact read prohibited')
sys.addaudithook(guard)
'''


def main(argv=None):
    with tempfile.TemporaryDirectory(prefix='m77-offline-test-guard-') as directory:
        Path(directory,'sitecustomize.py').write_text(GUARD)
        env=dict(os.environ)
        env['PYTHONPATH']=os.pathsep.join((directory,str(Path(__file__).resolve().parent.parent),env.get('PYTHONPATH','')))
        return subprocess.run([sys.executable,'-m','pytest',*(sys.argv[1:] if argv is None else argv)],env=env).returncode


if __name__=='__main__':raise SystemExit(main())
