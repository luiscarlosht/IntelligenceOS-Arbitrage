"""Run only the M77 dry-run with process-wide network/credential read prohibition.

Usage: .venv/bin/python -m ops.m77_offline [app.m77 dry-run options]
No authorization or execution action is accepted.
"""
import os
from pathlib import Path
import sys


def prohibit(event,args):
    if event.startswith('socket.'):
        raise PermissionError('M77 offline network prohibition')
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        name=os.fsdecode(args[0]).lower()
        if ('credentials.json' in name or 'owner-authorization' in name or name.endswith('/.env')):
            raise PermissionError('M77 offline credential/owner-artifact prohibition')


def main(argv=None):
    sys.addaudithook(prohibit)
    from app.m77 import main as dry_run
    return dry_run(['dry-run',*(sys.argv[1:] if argv is None else argv)])


if __name__=='__main__':raise SystemExit(main())
