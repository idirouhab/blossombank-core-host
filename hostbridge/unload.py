import hashlib
import json
import subprocess
from pathlib import Path

from .accounts import encumbrances
from .clock import business_date, utcnow
from .errors import DomainError


class AccountUnload:
    def __init__(self, database, cobol):
        self.database = database
        self.cobol = cobol

    def export(self, destination):
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        records = []
        with self.database.read() as db:
            cutoff = db.execute("SELECT coalesce(max(sequence),0) FROM journal").fetchone()[0]
            active_day = db.execute("SELECT business_date FROM day_control ORDER BY business_date DESC LIMIT 1").fetchone()
            day = active_day[0] if active_day else business_date()
            for row in db.execute("SELECT * FROM account_master WHERE internal=0 ORDER BY account_id"):
                held, liens = encumbrances(db, row["account_id"])
                fields = [row["account_id"], row["customer_id"], row["product_code"], row["currency"],
                          {"OPEN": "0", "FROZEN": "7", "CLOSED": "9"}[row["status"]], row["ledger_minor"],
                          held + liens, row["overdraft_minor"], day.replace("-", ""), row["revision"], row["branch_code"]]
                if row["revision"] > 999999999 or len(row["customer_id"]) > 12:
                    raise DomainError("UNLOAD_FIELD_OVERFLOW", "Account does not fit the AC01 layout")
                records.append("|".join(map(str, fields)))
        staging = destination.with_suffix(destination.suffix + ".part")
        try:
            process = subprocess.run([str(self.cobol.binary_dir / "acctunld"), str(staging)],
                                     input="\n".join(records + ["END"]) + "\n", capture_output=True,
                                     text=True, timeout=30, check=True)
            expected = "OK|" + str(len(records)).zfill(9)
            if process.stdout.strip() != expected:
                raise DomainError("UNLOAD_CONTROL", "Unload count does not match source snapshot", 503)
            payload = staging.read_bytes()
            # AC01 is a fixed block record, with three packed-decimal monetary fields.
            if len(payload) != len(records) * 84:
                raise DomainError("UNLOAD_LENGTH", "Unexpected AC01 record length", 503)
            staging.replace(destination)
        except (subprocess.SubprocessError, OSError) as exc:
            raise DomainError("UNLOAD_FAILED", "Account unload did not complete", 503) from exc
        finally:
            staging.unlink(missing_ok=True)
        manifest = {"dataset": destination.name, "layout": "AC01-R18", "records": len(records),
                    "recordLength": 84, "sha256": hashlib.sha256(payload).hexdigest(),
                    "cutoffSequence": cutoff, "businessDate": day, "createdAt": utcnow()}
        destination.with_suffix(destination.suffix + ".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return manifest
