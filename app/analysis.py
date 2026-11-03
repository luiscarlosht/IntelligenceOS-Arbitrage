"""Manual analysis CLI; offline/read-only by default. No Amazon/Keepa transport."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path

from app.amazon_evaluation import EvaluationPolicy
from app.amazon_research_queue import QueueClient
from app.analysis_adapters import ManualAmazon, ManualKeepa, SheetsEvidence
from app.analysis_engine import analyze_record, remember
from app.analysis_sheets import preview, publish


def load(path):
    if path.stat().st_size > 4*1024*1024:
        raise ValueError('Input exceeds 4 MiB')
    return json.loads(path.read_text())


def output(path, report):
    text=json.dumps(report,indent=2,allow_nan=False)+'\n'
    if path:
        # Never overwrite existing reports or historical evidence.
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:
            stream.write(text)
    else:
        print(text,end='')


def client(writable=False):
    path=Path(os.environ['ARBITRAGE_SHEETS_CREDENTIAL_FILE'])
    if not path.is_absolute() or 'WeinsteinAgent' in path.parts:
        raise ValueError('Existing dedicated absolute credential path required')
    return QueueClient(path,writable=writable)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--input',type=Path)
    source.add_argument('--sheets',action='store_true',help='Read existing manual evidence, no writes')
    source.add_argument('--publish-preview',type=Path)
    parser.add_argument('--approved',action='store_true',help='Operator confirms prior approval to publish this preview')
    parser.add_argument('--keepa-manual',type=Path)
    parser.add_argument('--sheets-preview',action='store_true',help='Read output snapshot and emit proposed batch, no writes')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--history',type=Path,help='Explicit separate private append-only analysis history')
    parser.add_argument('--as-of')
    parser.add_argument('--minimum-profit',type=Decimal,default=Decimal('5'))
    parser.add_argument('--minimum-roi',type=Decimal,default=Decimal('50'))
    args=parser.parse_args(argv)
    if args.publish_preview:
        if (not args.approved or args.keepa_manual or args.sheets_preview or args.history or args.as_of):
            parser.error('Publication requires --approved and a saved preview; no analysis overrides')
        proposal=load(args.publish_preview)
        with Path('/tmp/arbitrage-analysis-publication.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=publish(client(True),proposal,datetime.now(timezone.utc),approved=args.approved)
        output(args.output,result)
        return
    if args.approved or args.sheets and args.keepa_manual:
        parser.error('--approved requires publication; Keepa patches require local --input')
    now=datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc)
    policy=EvaluationPolicy(args.minimum_profit,args.minimum_roi)
    connection=client() if args.sheets or args.sheets_preview else None
    records=SheetsEvidence(connection).records() if args.sheets else ManualAmazon(load(args.input)).records()
    if args.keepa_manual:
        records=ManualKeepa(load(args.keepa_manual)).merge(records)
    if args.sheets_preview:
        result=preview(connection,records,now,policy,from_sheets=args.sheets)
        reports=result['reports']
    else:
        reports=[analyze_record(r,now,policy) for r in records]
        result=dict(mode='read_only_analysis',records=reports,purchase_authorized=False)
    output(args.output,result)
    if args.history:
        remember(args.history,reports)


if __name__ == '__main__':
    main()
