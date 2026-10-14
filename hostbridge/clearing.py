import csv
import hashlib
import io
import json
import uuid

from .clock import utcnow
from .database import audit
from .errors import DomainError


class Clearing:
    REQUIRED = {"reference", "debtor", "creditor", "currency", "amount", "narrative"}

    def __init__(self, database, ledger):
        self.database = database
        self.ledger = ledger

    def import_file(self, path):
        data = path.read_bytes()
        if len(data) > 10_000_000:
            raise DomainError("FILE_TOO_LARGE", "Clearing input exceeds region allocation")
        digest = hashlib.sha256(data).hexdigest()
        try:
            reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        except UnicodeError:
            raise DomainError("BAD_ENCODING", "Clearing input must be UTF-8") from None
        if not reader.fieldnames or not self.REQUIRED.issubset(reader.fieldnames):
            raise DomainError("BAD_HEADER", "Missing required clearing columns")
        with self.database.write() as db:
            existing = db.execute("SELECT * FROM batch_run WHERE job_name='CLR021' AND input_digest=?", (digest,)).fetchone()
            if existing and existing["state"] == "COMPLETED":
                return json.loads(existing["report_json"])
            if existing and existing["state"] == "RUNNING":
                raise DomainError("BATCH_RUNNING", "Input is already running; inspect the job before reset", 409)
            run_id = existing["run_id"] if existing else "BR-" + uuid.uuid4().hex
            if existing:
                db.execute("UPDATE batch_run SET state='RUNNING',started_at=?,completed_at=NULL WHERE run_id=?", (utcnow(), run_id))
                db.execute("DELETE FROM batch_reject WHERE run_id=?", (run_id,))
            else:
                db.execute("INSERT INTO batch_run(run_id,job_name,input_digest,started_at,state) VALUES (?,'CLR021',?,?,'RUNNING')",
                           (run_id, digest, utcnow()))
        accepted = replayed = 0
        rejects = []
        try:
            for line_number, row in enumerate(reader, start=2):
                try:
                    amount = self.ledger.cobol.clearing_amount(row["amount"])
                    if amount <= 0:
                        raise DomainError("BAD_AMOUNT", "Clearing amount must be positive")
                    request = {"externalReference": "CLR:" + row["reference"], "narrative": row["narrative"],
                               "entries": [{"accountId": row["debtor"], "currency": row["currency"], "deltaMinor": -amount},
                                           {"accountId": row["creditor"], "currency": row["currency"], "deltaMinor": amount}]}
                    _, replay = self.ledger.post(request, source="CLR021")
                    accepted += 1
                    replayed += int(replay)
                except DomainError as exc:
                    rejects.append({"line": line_number, "code": exc.code, "message": exc.message})
                    with self.database.write() as db:
                        db.execute("INSERT INTO batch_reject VALUES (?,?,?,?)", (run_id, line_number, json.dumps(row), exc.code))
            report = {"runId": run_id, "jobName": "CLR021", "accepted": accepted,
                      "replayed": replayed, "rejected": len(rejects), "rejects": rejects}
            with self.database.write() as db:
                db.execute("""UPDATE batch_run SET state='COMPLETED',completed_at=?,accepted_count=?,rejected_count=?,report_json=?
                    WHERE run_id=?""", (utcnow(), accepted, len(rejects), json.dumps(report), run_id))
                audit(db, "CLR021", "BATCH_COMPLETED", run_id, report)
            return report
        except BaseException:
            with self.database.write() as db:
                db.execute("UPDATE batch_run SET state='FAILED',completed_at=? WHERE run_id=?", (utcnow(), run_id))
            raise

    def list_runs(self):
        with self.database.read() as db:
            return {"runs": [dict(row) for row in db.execute("SELECT * FROM batch_run ORDER BY started_at DESC LIMIT 100")]}

    def recover(self, run_id):
        with self.database.write() as db:
            row = db.execute("SELECT state FROM batch_run WHERE run_id=?", (run_id,)).fetchone()
            if not row or row[0] != "RUNNING":
                raise DomainError("INVALID_RUN", "Only an abandoned RUNNING job can be recovered", 409)
            db.execute("UPDATE batch_run SET state='FAILED',completed_at=? WHERE run_id=?", (utcnow(), run_id))
            audit(db, "OPERATOR", "BATCH_RESET", run_id, {})
            return {"runId": run_id, "state": "FAILED"}
