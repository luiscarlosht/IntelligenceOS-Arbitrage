"""M67 controlled Listings Restrictions: offline by default; no auto follow-on."""
import argparse
import json
from pathlib import Path

from app.m67_policy import preflight, LEDGER


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('preflight','report','import-results','execute'))
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--catalog', type=Path, action='append', default=[])
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--private-dir', type=Path, default=Path.home()/'.intelligenceos-arbitrage-amazon')
    parser.add_argument('--authorization', type=Path)
    parser.add_argument('--authorization-sha256')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--csv-dir', type=Path, help='Existing empty output directory; report action only')
    args = parser.parse_args(argv)
    try:
        if args.execute and args.action != 'execute':
            raise ValueError('Execution flag only applies to execute action')
        if args.csv_dir and args.action != 'report':
            raise ValueError('CSV export only applies to report action')
        if args.action == 'preflight':
            result = preflight(args.manifest,args.manifest_sha256,args.catalog,args.store,args.private_dir)
        elif args.action == 'report':
            from app.m67_reporting import report
            result = report(args.manifest,args.manifest_sha256,args.store,args.private_dir/LEDGER)
        elif args.action == 'import-results':
            from app.m67_reporting import import_results
            from app.m67_state import secure
            from app.m66_verification import VerificationStore
            secure(args.store)
            store = VerificationStore(args.store)
            try:
                result = import_results(args.manifest,args.manifest_sha256,store,args.private_dir/LEDGER)
            finally:
                store.db.close()
        else:
            if not args.execute or not args.authorization or not args.authorization_sha256:
                raise ValueError('Separate authorization, digest and execute flag required')
            from app.m67_execution import execute
            result = execute(args.manifest,args.manifest_sha256,args.catalog,args.store,args.private_dir,
                             args.authorization,args.authorization_sha256,execution_flag=args.execute)
        if args.output:
            from app.m65 import write_json
            write_json(args.output, result)
        if args.csv_dir:
            from app.m66_experiments import export
            export(result,args.csv_dir)
        # Only fixed schemas returned above; exceptions are never serialized.
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if result.get('ready',True) else 2
    except (Exception, KeyboardInterrupt):
        print('M67_BLOCKED: validation, authorization, storage or execution failed; no automatic retry')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
