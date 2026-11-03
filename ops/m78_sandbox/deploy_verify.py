"""Approved target procedure: migration then synthetic probe; never M78 analysis."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='requires prior explicit server-change approval')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    report = {'timestamp': datetime.now(timezone.utc).isoformat(),
              'migration': 'NOT_RUN', 'target_security': 'NOT_RUN',
              'production_readiness': 'FAIL', 'production_execution': 'NOT_RUN'}
    cmd = ['/usr/bin/python3', str(here / 'migrate.py'), '--manifest', str(args.manifest)]
    if args.apply:
        cmd.append('--apply')
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode:
        report['migration'] = 'FAIL'
        # Avoid dumping file contents or environment on failure. Operator gets
        # reason via rerunning the failed check directly after review.
        report['failure'] = 'Migration refused; inspect staging/manifest/ACLs. No probe launched.'
        print(json.dumps(report, indent=2))
        return 1
    report['migration'] = json.loads(result.stdout)
    if not args.apply:
        report['approval_gate'] = 'Preflight only; server-change approval required for --apply'
        print(json.dumps(report, indent=2))
        return 0
    result = subprocess.run(['/usr/bin/python3', str(here / 'launch.py'), 'verify'],
                            capture_output=True, text=True, check=False)
    try:
        checks = json.loads(result.stdout)
    except json.JSONDecodeError:
        checks = {}
    passed = (result.returncode == 0 and isinstance(checks, dict) and bool(checks)
              and all(value is True for value in checks.values()))
    report['target_security'] = 'PASS' if passed else 'FAIL'
    report['checks'] = checks
    report['production_readiness'] = 'PENDING_OWNER_REVIEW' if passed else 'FAIL'
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
