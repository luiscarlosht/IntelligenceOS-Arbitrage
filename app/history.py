"""SQLite job audit trail, including failed executions."""
import sqlite3
from datetime import datetime, timezone

class History:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                status TEXT NOT NULL, candidates INTEGER DEFAULT 0,
                review_candidates INTEGER DEFAULT 0, report_path TEXT, error_type TEXT)""")

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def start(self):
        with self.connect() as db:
            return db.execute('INSERT INTO runs(started_at,status) VALUES (?,?)',
                              (datetime.now(timezone.utc).isoformat(), 'running')).lastrowid

    def finish(self, run_id, status, candidates=0, reviews=0, report=None, error=None):
        with self.connect() as db:
            db.execute('UPDATE runs SET finished_at=?,status=?,candidates=?,review_candidates=?,report_path=?,error_type=? WHERE id=?',
                       (datetime.now(timezone.utc).isoformat(), status, candidates, reviews,
                        str(report) if report else None, error, run_id))
