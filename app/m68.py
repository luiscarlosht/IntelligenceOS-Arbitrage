"""Offline M67 authorization preparation/validation. No execution action exists."""
import argparse
import json
from pathlib import Path

from app import m68_authorization as authorization


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # Unknown arguments may themselves contain a mistakenly supplied ID.
        self.exit(2, 'M68_BLOCKED_OFFLINE_ONLY: invalid command arguments\n')


def main(argv=None) -> int:
    parser = PrivateArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare','validate'))
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--catalog', type=Path, action='append', required=True)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--private-dir', type=Path, default=authorization.PRIVATE)
    parser.add_argument('--preflight', type=Path, required=True)
    parser.add_argument('--name', default='m68-authorization-m66-20.json')
    parser.add_argument('--review-reference')
    parser.add_argument('--authorization-sha256')
    parser.add_argument('--receipt-sha256')
    args = parser.parse_args(argv)
    try:
        common = (args.manifest,args.manifest_sha256,args.catalog,args.store,args.private_dir,args.preflight,args.name)
        if args.action == 'prepare':
            if not args.review_reference or args.authorization_sha256 or args.receipt_sha256:
                raise ValueError('Explicit review reference required')
            result = authorization.prepare(*common,args.review_reference)
        else:
            if not args.authorization_sha256 or not args.receipt_sha256 or args.review_reference:
                raise ValueError('Separate reviewed artifact and receipt digests required')
            result = authorization.validate(*common,args.authorization_sha256,args.receipt_sha256)
        # Never print artifact contents, private paths, seller IDs or exception text.
        print(json.dumps(result,sort_keys=True))
        return 0
    except (Exception,KeyboardInterrupt):
        print('M68_BLOCKED_OFFLINE_ONLY: review inputs, confirmation, storage or validity failed')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
