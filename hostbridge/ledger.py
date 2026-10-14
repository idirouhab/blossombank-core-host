import hashlib
import json
import uuid
from collections import defaultdict

from . import validation as v
from .accounts import account_row, available
from .clock import utcnow
from .config import MAX_ENTRIES, load_products
from .database import audit
from .errors import DomainError, Missing


def normalize_posting(body):
    v.object_body(body)
    reference = v.identifier(body.get("externalReference"), "externalReference")
    narrative = v.text(body.get("narrative"), "narrative")
    entries = body.get("entries")
    if not isinstance(entries, list) or not 2 <= len(entries) <= MAX_ENTRIES:
        raise DomainError("INVALID_ENTRIES", f"Posting requires between 2 and {MAX_ENTRIES} entries")
    normalized = []
    for entry in entries:
        v.object_body(entry)
        delta = v.minor(entry.get("deltaMinor"), "deltaMinor")
        if delta == 0:
            raise DomainError("ZERO_ENTRY", "Zero-value journal entries are not allowed")
        normalized.append({"accountId": v.identifier(entry.get("accountId"), "accountId"),
                           "currency": v.currency(entry.get("currency")), "deltaMinor": delta})
    return {"externalReference": reference, "narrative": narrative, "entries": normalized}


def posting_hash(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def posting_response(db, posting_id):
    row = db.execute("SELECT * FROM posting WHERE posting_id=?", (posting_id,)).fetchone()
    if row is None:
        raise Missing("Posting")
    entries = [{"accountId": r["account_id"], "currency": r["currency"], "deltaMinor": r["delta_minor"]}
               for r in db.execute("SELECT * FROM journal WHERE posting_id=? ORDER BY ordinal", (posting_id,))]
    result = {"postingId": posting_id, "externalReference": row["external_reference"],
              "status": "BOOKED", "bookedAt": row["booked_at"], "entries": entries,
              "businessDate": row["business_date"], "narrative": row["narrative"]}
    if row["reversal_of"]:
        result["reversalOf"] = row["reversal_of"]
    return result


class Ledger:
    def __init__(self, database, cobol):
        self.database = database
        self.cobol = cobol
        self.products = load_products()

    def post(self, body, source="ONLINE"):
        body = normalize_posting(body)
        with self.database.write() as db:
            return self._book(db, body, source=source)

    def _book(self, db, body, source="ONLINE", reversal_of=None):
        digest = posting_hash(body)
        previous = db.execute("SELECT posting_id,request_hash,reversal_of FROM posting WHERE external_reference=?",
                              (body["externalReference"],)).fetchone()
        if previous:
            if previous["request_hash"] != digest or previous["reversal_of"] != reversal_of:
                raise DomainError("REFERENCE_CONFLICT", "External reference was already booked with another payload", 409)
            return posting_response(db, previous["posting_id"]), True
        # Per-currency control totals are calculated in BALCTL. Converting totals
        # to the region base currency would hide an unbalanced currency leg.
        self.cobol.balance(body["entries"])
        totals = defaultdict(int)
        account_currencies = {}
        for entry in body["entries"]:
            account_id = entry["accountId"]
            if account_id in account_currencies and account_currencies[account_id] != entry["currency"]:
                raise DomainError("CURRENCY_MISMATCH", "An account cannot be posted in two currencies")
            account_currencies[account_id] = entry["currency"]
            totals[account_id] += entry["deltaMinor"]
        ending = {}
        balances = {}
        instant = utcnow()
        for account_id, delta in totals.items():
            row = account_row(db, account_id)
            product = self.products.get(row["product_code"], {})
            allowed = not row["debit_block"] and product.get("debit_enabled") == "Y"
            ending[account_id] = self.cobol.account(row, delta, available(db, row, instant),
                                                   account_currencies[account_id], allowed)
            balances[account_id] = row["ledger_minor"]
        day = db.execute("SELECT business_date FROM day_control WHERE state='OPEN' ORDER BY business_date DESC LIMIT 1").fetchone()
        if day is None:
            raise DomainError("REGION_CLOSED", "Open a business day before posting", 409)
        if reversal_of and db.execute("SELECT 1 FROM posting WHERE reversal_of=?", (reversal_of,)).fetchone():
            raise DomainError("ALREADY_REVERSED", "Posting has already been reversed", 409)
        posting_id = "HP-" + uuid.uuid4().hex
        db.execute("""INSERT INTO posting
            (posting_id,external_reference,request_hash,booked_at,business_date,narrative,source,reversal_of)
            VALUES (?,?,?,?,?,?,?,?)""", (posting_id, body["externalReference"], digest, instant, day[0],
                                          body["narrative"], source, reversal_of))
        for ordinal, entry in enumerate(body["entries"], start=1):
            account_id = entry["accountId"]
            balances[account_id] += entry["deltaMinor"]
            db.execute("""INSERT INTO journal
                (posting_id,ordinal,account_id,currency,delta_minor,resulting_balance)
                VALUES (?,?,?,?,?,?)""", (posting_id, ordinal, account_id, entry["currency"],
                                            entry["deltaMinor"], balances[account_id]))
        for account_id, balance in ending.items():
            db.execute("UPDATE account_master SET ledger_minor=?,last_activity=?,revision=revision+1 WHERE account_id=?",
                       (balance, instant, account_id))
        audit(db, source, "POSTING_BOOKED", posting_id, {"reference": body["externalReference"], "entryCount": len(body["entries"])})
        return posting_response(db, posting_id), False

    def get(self, posting_id):
        with self.database.read() as db:
            return posting_response(db, posting_id)

    def by_reference(self, reference):
        with self.database.read() as db:
            row = db.execute("SELECT posting_id FROM posting WHERE external_reference=?", (reference,)).fetchone()
            if not row:
                raise Missing("Posting")
            return posting_response(db, row[0])

    def reverse(self, posting_id, body):
        v.object_body(body)
        reference = v.identifier(body.get("externalReference"), "externalReference")
        reason = v.text(body.get("reason"), "reason", 100)
        if not reason:
            raise DomainError("REASON_REQUIRED", "Reversal requires a reason")
        with self.database.write() as db:
            original = posting_response(db, posting_id)
            if original.get("reversalOf"):
                raise DomainError("REVERSAL_OF_REVERSAL", "A reversal cannot itself be reversed", 409)
            request = {"externalReference": reference, "narrative": "REV " + reason,
                       "entries": [dict(entry, deltaMinor=-entry["deltaMinor"]) for entry in original["entries"]]}
            return self._book(db, request, source="CONTROL", reversal_of=posting_id)

    def journal(self, after=0, limit=500, account_id=None):
        after = v.page_integer(after, "after", 0)
        limit = v.page_integer(limit, "limit", 500, 2000)
        if limit == 0:
            raise DomainError("INVALID_QUERY", "limit must be positive")
        where = "j.sequence>?"
        params = [after]
        if account_id:
            where += " AND j.account_id=?"
            params.append(account_id)
        params.append(limit)
        with self.database.read() as db:
            rows = db.execute(f"""SELECT j.*,p.external_reference,p.booked_at,p.narrative,p.business_date
                FROM journal j JOIN posting p USING(posting_id)
                WHERE {where} ORDER BY j.sequence LIMIT ?""", params).fetchall()
            entries = [{"sequence": r["sequence"], "postingId": r["posting_id"],
                        "externalReference": r["external_reference"], "accountId": r["account_id"],
                        "currency": r["currency"], "deltaMinor": r["delta_minor"],
                        "bookedAt": r["booked_at"], "narrative": r["narrative"],
                        "businessDate": r["business_date"]} for r in rows]
            return {"entries": entries, "nextSequence": entries[-1]["sequence"] if entries else after}
