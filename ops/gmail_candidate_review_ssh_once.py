"""Single explicitly authorized candidate-review delivery; no retry."""
import argparse,hashlib,json,os,re,resource,shlex,signal,sys
from pathlib import Path
from datetime import datetime,timezone
from email.message import EmailMessage
from email.utils import formatdate,make_msgid
from app.gmail_api import send_message
from ops.gmail_stage_tracking import StageTracker

root=Path(__file__).resolve().parents[1]
SENDER_CONFIG=Path('/root/.bashrc')
base=Path('/root/.intelligenceos-arbitrage-amazon')
stem='candidates-cabbbda426bff05faff0b6d8f051e62bde21fa927efafe9fc347e9380ee24f11'
report=base/(stem+'.json'); workbook=base/(stem+'.xlsx')
marker=root/'var/diagnostics/gmail-ebay-candidate-review-ssh-1.attempted'
stages=root/'var/diagnostics/gmail-ebay-candidate-review-ssh-1.stages.jsonl'
outcome_path=root/'var/diagnostics/gmail-ebay-candidate-review-ssh-1.outcome.json'

def check_report():
    data=json.loads(report.read_text())
    if not (data['status']=='succeeded' and data['live_requests']==21 and len(data['attempts'])==21):
        raise ValueError('Candidate report or message verification failed')
    if not (not data['is_mock'] and len(data['rows'])==10):
        raise ValueError('Candidate report or message verification failed')
    if not (all(r['status']=='ambiguous' and r['exact'] is False for r in data['rows'])):
        raise ValueError('Candidate report or message verification failed')
    if not (workbook.is_file() and not workbook.is_symlink()):
        raise ValueError('Candidate report or message verification failed')
    content=workbook.read_bytes();digest=hashlib.sha256(content).hexdigest()
    if not (digest=='d6a7697436f2766eb776809842dccfcee087b08272d8ba18fa77e6892b495716'):
        raise ValueError('Candidate report or message verification failed')
    return content,digest


def execute():
    content,digest=check_report()
    addresses={}
    # Select the existing nonsecret sender assignment without loading SMTP passwords
    # or executing shell configuration. Delivery uses only the existing OAuth loader.
    for line in SENDER_CONFIG.open():
        match=re.match(r'^\s*(?:export\s+)?(EMAIL_FROM|SMTP_USER|SMTP_USERNAME)=(.*)$',line.rstrip('\n'))
        if match:
            words=shlex.split(match[2],comments=True)
            if len(words)==1:addresses[match[1]]=words[0]
    senders=set(addresses.values())
    if not (len(senders)==1):
        raise ValueError('Candidate report or message verification failed')
    sender=next(iter(senders))
    if not (re.fullmatch(r'[A-Za-z0-9._%+\-]+@gmail\.com',sender,re.I)):
        raise ValueError('Candidate report or message verification failed')
    # A permanent exclusive reservation precedes OAuth refresh or message submission.
    if stages.exists() or outcome_path.exists():
        raise FileExistsError('Attempt evidence already exists')
    fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump(dict(reserved_at=datetime.now(timezone.utc).isoformat(),
                       purpose='Proof of concept — candidate review',workbook_sha256=digest,
                       automatic_retry=False,maximum_messages=1),f)
        f.flush();os.fsync(f.fileno())
    result_fd=os.open(outcome_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    os.close(os.open(stages,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600))
    tracker=StageTracker(stages)
    result=dict(status='reserved',acceptance_observed=False,submission_started=False,automatic_retry=False)
    def persist():
        os.lseek(result_fd,0,os.SEEK_SET)
        payload=(json.dumps(result)+'\n').encode();os.write(result_fd,payload);os.ftruncate(result_fd,len(payload));os.fsync(result_fd)
    persist()
    def deadline(*_):raise TimeoutError()
    previous=signal.signal(signal.SIGALRM,deadline);signal.alarm(90)
    try:
        tracker('message_construction','started')
        message=EmailMessage()
        message['From']=sender
        message['To']='luiscarloshernandez@hotmail.com'
        message['Subject']='Proof of concept — candidate review | eBay to Amazon'
        message['Date']=formatdate(localtime=False)
        message['Message-ID']=make_msgid()
        message.set_content('Proof of concept — candidate review\n\n'
            'Attached is the real eBay-to-Amazon candidate-review workbook from the successful 21-request Amazon catalog run.\n\n'
            '• 10 real eBay listings reviewed.\n'
            '• 10 ambiguous Amazon candidates; 0 confirmed exact product matches.\n'
            '• Profitability is not yet established.\n\n'
            'Successful API execution does not verify product identity. Source identifiers, package contents/count and variation evidence still require validation.\n\n'
            'This is a proof of concept for candidate review, not a purchase recommendation.\n')
        message.add_attachment(content,maintype='application',
            subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename='eBay-Amazon-Candidate-Review.xlsx')
        if not (len(list(message.iter_attachments()))==1):
            raise ValueError('Candidate report or message verification failed')
        tracker('message_construction','completed')
        send_message(message,Path('/root/.config/arbitrage-gmail/token.json'),observe=tracker)
        result['status']='gmail_accepted' if tracker.acceptance_observed else 'acceptance_not_observed'
    except (Exception,KeyboardInterrupt):
        result['status']='submission_uncertain' if tracker.submission_started else 'failed_before_submission'
    finally:
        signal.alarm(0);signal.signal(signal.SIGALRM,previous)
        result.update(acceptance_observed=tracker.acceptance_observed,submission_started=tracker.submission_started,
                      last_completed_stage=tracker.last_completed,finished_at=datetime.now(timezone.utc).isoformat(),
                      report_preserved=hashlib.sha256(workbook.read_bytes()).hexdigest()==digest)
        persist();os.close(result_fd)
    print(json.dumps(result))
    return 0 if result['acceptance_observed'] else 1

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check',action='store_true',help='Offline verification; no credentials or send')
    modes.add_argument('--send',action='store_true',help='One fresh attempt, only from an interactive terminal')
    args=parser.parse_args()
    try:
        if args.check:
            _,digest=check_report()
            if any(p.exists() for p in (marker,stages,outcome_path)):
                raise FileExistsError()
            print(json.dumps(dict(status='verified_offline',workbook_sha256=digest,
                                  recipient='luiscarloshernandez@hotmail.com',attempt='ssh-1',
                                  maximum_messages=1,automatic_retry=False,credentials_read=False)))
            return 0
        if not sys.stdin.isatty():
            raise ValueError('Interactive SSH terminal required')
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        return execute()
    except (Exception,KeyboardInterrupt):
        print(json.dumps(dict(status='stopped_without_retry',automatic_retry=False)))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
