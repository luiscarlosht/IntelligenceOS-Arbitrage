"""Local dispatcher; an external heartbeat receiver detects VM silence."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from datetime import datetime, timezone

from app.healthcheck import check
from app.ops_notifications import deliver, read_config
from app.storage_budget import exclusive_backup


def unit_issues(run=subprocess.run) -> list[str]:
    issues = []
    for kind in ('', '-backup', '-monitor'):
        service = 'intelligenceos-arbitrage' + kind
        try:
            result = run(['systemctl', 'show', service + '.service',
                          '-p', 'LoadState', '-p', 'Result', '-p', 'ActiveState', '--no-pager'],
                         capture_output=True, text=True, timeout=5, check=True)
            fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
            if fields.get('LoadState') != 'loaded' or fields.get('Result') != 'success' or fields.get('ActiveState') == 'failed':
                issues.append('unit_failed_or_unavailable')
            run(['systemctl', 'is-active', '--quiet', service + '.timer'],
                capture_output=True, timeout=5, check=True)
        except (OSError, subprocess.SubprocessError):
            issues.append('unit_failed_or_unavailable')
    return sorted(set(issues))


def dispatch(history: Path, backups: Path, state_directory: Path, config_path: Path) -> list[str]:
    # Validate before any network request; unknown/unavailable state cannot ping success.
    config = read_config(config_path)
    if state_directory.is_symlink() or state_directory.stat().st_mode & 0o077:
        raise ValueError('Dispatcher state must be private')
    with exclusive_backup(state_directory):
        state_path = state_directory / 'delivery.json'
        if state_path.is_symlink():
            raise ValueError('Invalid delivery state')
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        issues = check(history, backups, datetime.now(timezone.utc)) + unit_issues()
        result = deliver(config, bool(issues), time.time(), state)
        descriptor, name = tempfile.mkstemp(dir=state_directory, prefix='.delivery-')
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(result['state'], stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, state_path)
        finally:
            temporary.unlink(missing_ok=True)
        return sorted(set(issues + result['issues']))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', required=True, type=Path)
    parser.add_argument('--backups', required=True, type=Path)
    parser.add_argument('--state-directory', required=True, type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--send', action='store_true')
    args = parser.parse_args()
    try:
        if args.send:
            if args.config is None:
                raise ValueError('Configuration required for explicit send mode')
            issues = dispatch(args.history, args.backups, args.state_directory, args.config)
        else:
            # Dry run never reads credentials, writes state or sends notifications.
            issues = check(args.history, args.backups, datetime.now(timezone.utc)) + unit_issues()
        print(json.dumps({'event': 'operations_dispatch', 'send_enabled': args.send, 'issues': issues}))
        raise SystemExit(bool(issues))
    except Exception:
        print(json.dumps({'event': 'operations_dispatch_failed'}))
        raise SystemExit(2) from None


if __name__ == '__main__':
    main()
