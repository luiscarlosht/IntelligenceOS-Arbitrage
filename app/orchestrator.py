"""Sequential configurable jobs; SQLite history and JSON operational events."""
import json
import logging
import signal
import threading
from datetime import datetime, timezone
from app.config import Config
from app.history import History
from app.mailer import send_report
from app.pipeline import load_candidates, evaluate, report

log = logging.getLogger('arbitrage')

class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({'time': datetime.now(timezone.utc).isoformat(),
                           'level': record.levelname, 'event': record.getMessage(),
                           'run_id': getattr(record, 'run_id', None),
                           'error_type': getattr(record, 'error_type', None)})

def run_job(config):
    history = History(config.database)
    run_id = history.start()
    rows = []
    generated = False
    log.info('job_started', extra={'run_id': run_id})
    try:
        rows = [evaluate(r, config.minimum_roi, config.minimum_profit) for r in load_candidates(config.input)]
        report(rows, config.output)
        generated = True
        send_report(config, config.output, run_id)
        history.finish(run_id, 'succeeded', len(rows), sum(r['status'] == 'REVIEW' for r in rows), config.output)
        log.info('job_succeeded', extra={'run_id': run_id})
        return run_id
    except Exception as exc:
        history.finish(run_id, 'failed', len(rows), sum(r['status'] == 'REVIEW' for r in rows),
                       config.output if generated else None, type(exc).__name__)
        # Avoid logging exception messages that could contain SMTP credentials or input data.
        log.error('job_failed', extra={'run_id': run_id, 'error_type': type(exc).__name__})
        raise

def serve(config, stop):
    while not stop.is_set():
        try:
            run_job(config)
        except Exception:
            if not config.interval: raise
        if not config.interval or stop.wait(config.interval): break

def main():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    log.handlers[:] = [handler]
    log.setLevel(logging.INFO)
    log.propagate = False
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    try:
        serve(Config.from_env(), stop)
    except Exception as exc:
        log.error('process_failed', extra={'error_type': type(exc).__name__})
        raise SystemExit(1) from None

if __name__ == '__main__':
    main()
