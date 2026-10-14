import hashlib
import json

from . import validation as v
from .clock import utcnow
from .database import audit
from .errors import DomainError, Missing
from .reconciliation import reconcile_connection


class Daybook:
    def __init__(self, database):
        self.database = database

    def list(self):
        with self.database.read() as db:
            return {"days": [dict(row) for row in db.execute("SELECT * FROM day_control ORDER BY business_date DESC LIMIT 90")]}

    def close(self, day):
        v.iso_date(day)
        with self.database.write() as db:
            current = db.execute("SELECT * FROM day_control WHERE business_date=?", (day,)).fetchone()
            if not current:
                raise Missing("Business day")
            if current["state"] == "CLOSED":
                return dict(current)
            reconciliation = reconcile_connection(db)
            if reconciliation["breaks"]:
                raise DomainError("CONTROL_BREAK", "Resolve ledger control breaks before closing", 409)
            snapshot = []
            for row in db.execute("SELECT * FROM account_master ORDER BY account_id").fetchall():
                turnover = db.execute("""SELECT
                    coalesce(sum(CASE WHEN j.delta_minor < 0 THEN -j.delta_minor ELSE 0 END),0),
                    coalesce(sum(CASE WHEN j.delta_minor > 0 THEN j.delta_minor ELSE 0 END),0)
                    FROM journal j JOIN posting p USING(posting_id)
                    WHERE j.account_id=? AND p.business_date=?""", (row["account_id"], day)).fetchone()
                record = (day, row["account_id"], row["currency"], row["ledger_minor"], turnover[0], turnover[1])
                db.execute("INSERT INTO balance_snapshot VALUES (?,?,?,?,?,?)", record)
                snapshot.append(record)
            digest = hashlib.sha256(json.dumps(snapshot, separators=(",", ":")).encode()).hexdigest()
            db.execute("UPDATE day_control SET state='CLOSED',closed_at=?,cutoff_sequence=?,control_hash=? WHERE business_date=?",
                       (utcnow(), reconciliation["lastSequence"], digest, day))
            audit(db, "DAYEND", "DAY_CLOSED", day, {"controlHash": digest, "accounts": len(snapshot)})
            return dict(db.execute("SELECT * FROM day_control WHERE business_date=?", (day,)).fetchone())

    def open(self, day):
        v.iso_date(day)
        with self.database.write() as db:
            current = db.execute("SELECT * FROM day_control ORDER BY business_date DESC LIMIT 1").fetchone()
            if current and current["business_date"] == day and current["state"] == "OPEN":
                return dict(current)
            if current and current["state"] == "OPEN":
                raise DomainError("DAY_STILL_OPEN", "Close the existing business day first", 409)
            if current and day <= current["business_date"]:
                raise DomainError("DATE_REGRESSION", "Business date must move forward", 409)
            db.execute("INSERT INTO day_control VALUES (?,'OPEN',?,NULL,NULL,NULL)", (day, utcnow()))
            audit(db, "DAYEND", "DAY_OPENED", day, {})
            return dict(db.execute("SELECT * FROM day_control WHERE business_date=?", (day,)).fetchone())

    def snapshot(self, day):
        v.iso_date(day)
        with self.database.read() as db:
            current = db.execute("SELECT state FROM day_control WHERE business_date=?", (day,)).fetchone()
            if not current:
                raise Missing("Business day")
            if current[0] != "CLOSED":
                raise DomainError("DAY_NOT_CLOSED", "Snapshot is available after day close", 409)
            return {"businessDate": day, "accounts": [dict(row) for row in db.execute(
                "SELECT * FROM balance_snapshot WHERE business_date=? ORDER BY account_id", (day,))]}
