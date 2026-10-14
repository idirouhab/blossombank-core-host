import uuid
from datetime import datetime, timezone

from . import validation as v
from .accounts import account_row, available
from .clock import parse_instant, utcnow
from .database import audit
from .errors import DomainError, Missing
from .ledger import normalize_posting, posting_response


def serialize_hold(row, now=None):
    state = row["status"]
    if state == "ACTIVE" and row["expires_at"] <= (now or utcnow()):
        state = "EXPIRED"
    return {"holdId": row["hold_id"], "externalReference": row["external_reference"],
            "accountId": row["account_id"], "currency": row["currency"],
            "amountMinor": row["amount_minor"], "reason": row["reason"],
            "status": state, "createdAt": row["created_at"], "expiresAt": row["expires_at"],
            "postingId": row["posting_id"]}


class Authorisations:
    def __init__(self, database, ledger):
        self.database = database
        self.ledger = ledger

    def create(self, body):
        v.object_body(body)
        account_id = v.identifier(body.get("accountId"), "accountId")
        reference = v.identifier(body.get("externalReference"), "externalReference")
        ccy = v.currency(body.get("currency"))
        amount = v.minor(body.get("amountMinor"), "amountMinor", positive=True)
        reason = v.text(body.get("reason"), "reason", 80)
        try:
            expiration = parse_instant(body.get("expiresAt"))
        except (ValueError, TypeError):
            raise DomainError("INVALID_EXPIRY", "expiresAt must be an ISO timestamp with timezone") from None
        expires_at = expiration.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self.database.write() as db:
            previous = db.execute("SELECT * FROM hold WHERE external_reference=?", (reference,)).fetchone()
            if previous:
                matches = (previous["account_id"] == account_id and previous["amount_minor"] == amount
                           and previous["currency"] == ccy and previous["reason"] == reason
                           and previous["expires_at"] == expires_at)
                if not matches:
                    raise DomainError("REFERENCE_CONFLICT", "Hold reference already has a different payload", 409)
                return serialize_hold(previous), True
            remaining = (expiration - datetime.now(timezone.utc)).total_seconds()
            if not 0 < remaining <= 31 * 86400:
                raise DomainError("INVALID_EXPIRY", "Hold must expire within the next 31 days")
            row = account_row(db, account_id)
            if row["internal"]:
                raise DomainError("CONTROL_ACCOUNT", "Authorisations require a retail account", 409)
            self.ledger.cobol.account(row, -amount, available(db, row), ccy,
                                     not row["debit_block"] and self.ledger.products[row["product_code"]]["debit_enabled"] == "Y")
            hold_id = "AH-" + uuid.uuid4().hex
            db.execute("""INSERT INTO hold(hold_id,external_reference,account_id,currency,amount_minor,reason,status,created_at,expires_at)
                VALUES (?,?,?,?,?,?,'ACTIVE',?,?)""", (hold_id, reference, account_id, ccy, amount, reason, utcnow(), expires_at))
            audit(db, "AUTH", "HOLD_CREATED", account_id, {"holdId": hold_id, "amountMinor": amount})
            return serialize_hold(db.execute("SELECT * FROM hold WHERE hold_id=?", (hold_id,)).fetchone()), False

    def list(self, account_id):
        with self.database.read() as db:
            account_row(db, account_id)
            now = utcnow()
            return {"holds": [serialize_hold(row, now) for row in db.execute(
                "SELECT * FROM hold WHERE account_id=? ORDER BY created_at", (account_id,))]}

    def get(self, hold_id):
        with self.database.read() as db:
            row = db.execute("SELECT * FROM hold WHERE hold_id=?", (hold_id,)).fetchone()
            if not row:
                raise Missing("Hold")
            return serialize_hold(row)

    def release(self, hold_id):
        with self.database.write() as db:
            row = db.execute("SELECT * FROM hold WHERE hold_id=?", (hold_id,)).fetchone()
            if not row:
                raise Missing("Hold")
            if row["status"] == "CAPTURED":
                raise DomainError("HOLD_CAPTURED", "Captured hold cannot be released", 409)
            if row["status"] == "ACTIVE":
                status = "EXPIRED" if row["expires_at"] <= utcnow() else "RELEASED"
                db.execute("UPDATE hold SET status=?,completed_at=? WHERE hold_id=?", (status, utcnow(), hold_id))
                audit(db, "AUTH", "HOLD_RELEASED", row["account_id"], {"holdId": hold_id, "status": status})
            return serialize_hold(db.execute("SELECT * FROM hold WHERE hold_id=?", (hold_id,)).fetchone())

    def capture(self, hold_id, body):
        v.object_body(body)
        creditor = v.identifier(body.get("creditorAccount"), "creditorAccount")
        reference = v.identifier(body.get("externalReference"), "externalReference")
        narrative = v.text(body.get("narrative"), "narrative")
        with self.database.write() as db:
            row = db.execute("SELECT * FROM hold WHERE hold_id=?", (hold_id,)).fetchone()
            if not row:
                raise Missing("Hold")
            request = normalize_posting({"externalReference": reference, "narrative": narrative,
                "entries": [{"accountId": row["account_id"], "currency": row["currency"], "deltaMinor": -row["amount_minor"]},
                            {"accountId": creditor, "currency": row["currency"], "deltaMinor": row["amount_minor"]}]})
            if row["status"] == "CAPTURED":
                posted = posting_response(db, row["posting_id"])
                if posted["externalReference"] != reference or posted["entries"] != request["entries"] or posted["narrative"] != narrative:
                    raise DomainError("REFERENCE_CONFLICT", "Capture request differs from completed capture", 409)
                return posted, True
            if row["status"] != "ACTIVE" or row["expires_at"] <= utcnow():
                raise DomainError("HOLD_NOT_ACTIVE", "Hold is no longer active", 409)
            if creditor == row["account_id"]:
                raise DomainError("SAME_ACCOUNT", "Capture creditor must differ from debtor")
            # Release and debit share the same transaction. Failure restores the hold.
            db.execute("UPDATE hold SET status='CAPTURED',completed_at=? WHERE hold_id=?", (utcnow(), hold_id))
            response, replay = self.ledger._book(db, request, source="AUTH")
            if replay:
                raise DomainError("REFERENCE_CONFLICT", "Capture reference belongs to an existing posting", 409)
            db.execute("UPDATE hold SET posting_id=? WHERE hold_id=?", (response["postingId"], hold_id))
            audit(db, "AUTH", "HOLD_CAPTURED", row["account_id"], {"holdId": hold_id, "postingId": response["postingId"]})
            return response, False

    def expire(self):
        with self.database.write() as db:
            now = utcnow()
            rows = db.execute("SELECT hold_id,account_id FROM hold WHERE status='ACTIVE' AND expires_at<=?", (now,)).fetchall()
            for row in rows:
                db.execute("UPDATE hold SET status='EXPIRED',completed_at=? WHERE hold_id=?", (now, row["hold_id"]))
                audit(db, "BATCH", "HOLD_EXPIRED", row["account_id"], {"holdId": row["hold_id"]})
            return {"expiredCount": len(rows)}
