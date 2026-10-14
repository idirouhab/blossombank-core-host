from collections import defaultdict

from . import validation as v
from .clock import utcnow
from .config import load_products
from .database import audit
from .errors import DomainError


class Interest:
    def __init__(self, database, ledger):
        self.database = database
        self.ledger = ledger
        self.products = load_products()

    def accrue(self, day):
        v.iso_date(day)
        with self.database.write() as db:
            control = db.execute("SELECT state FROM day_control WHERE business_date=?", (day,)).fetchone()
            if not control or control[0] != "CLOSED":
                raise DomainError("DAY_NOT_CLOSED", "Accrual requires a closed-day snapshot", 409)
            count = 0
            total = defaultdict(int)
            rows = db.execute("""SELECT s.*,a.product_code FROM balance_snapshot s JOIN account_master a USING(account_id)
                WHERE s.business_date=? AND a.internal=0 ORDER BY s.account_id""", (day,)).fetchall()
            for row in rows:
                exists = db.execute("SELECT amount_micro FROM accrual WHERE business_date=? AND account_id=?", (day, row["account_id"])).fetchone()
                if exists:
                    total[row["currency"]] += exists[0]
                    continue
                carry = db.execute("SELECT through_date FROM accrual_carry WHERE account_id=?", (row["account_id"],)).fetchone()
                if carry and carry[0] >= day:
                    raise DomainError("ACCRUAL_BACKDATE", "Cannot accrue before a completed settlement", 409)
                product = self.products[row["product_code"]]
                rate_key = "annual_credit_bps" if row["balance_minor"] >= 0 else "annual_overdraft_bps"
                rate = int(product[rate_key])
                micro = self.ledger.cobol.interest(row["balance_minor"], rate)
                db.execute("""INSERT INTO accrual
                    (business_date,account_id,currency,annual_bps,balance_minor,amount_micro)
                    VALUES (?,?,?,?,?,?)""", (day, row["account_id"], row["currency"], rate, row["balance_minor"], micro))
                total[row["currency"]] += micro
                count += 1
            if count:
                audit(db, "INTRCALC", "INTEREST_ACCRUED", day, {"accountCount": count, "microByCurrency": dict(total)})
            return {"businessDate": day, "newAccruals": count, "microByCurrency": dict(total)}

    def settle(self, through):
        v.iso_date(through)
        with self.database.write() as db:
            # One commit includes customer postings, accrual markers and fractions.
            rows = db.execute("""SELECT account_id,currency,sum(amount_micro) AS total
                FROM accrual WHERE business_date<=? AND settled_at IS NULL
                GROUP BY account_id,currency ORDER BY account_id""", (through,)).fetchall()
            results = []
            for row in rows:
                account_id = row["account_id"]
                carry = db.execute("SELECT amount_micro,through_date FROM accrual_carry WHERE account_id=?", (account_id,)).fetchone()
                if carry and carry["through_date"] > through:
                    raise DomainError("SETTLEMENT_BACKDATE", "Settlement date precedes a completed run", 409)
                micro = row["total"] + (carry["amount_micro"] if carry else 0)
                amount = (abs(micro) // 1_000_000) * (-1 if micro < 0 else 1)
                remainder = micro - amount * 1_000_000
                posting_id = None
                if amount:
                    contra = "GL-INT-" + row["currency"]
                    db.execute("""INSERT OR IGNORE INTO account_master
                        (account_id,customer_id,currency,product_code,ledger_minor,opening_minor,opened_on,internal)
                        VALUES (?,'INTERNAL',?,'NOST',0,0,?,1)""", (contra, row["currency"], through))
                    request = {"externalReference": "INT:" + through + ":" + account_id,
                               "narrative": "Interest through " + through,
                               "entries": [{"accountId": account_id, "currency": row["currency"], "deltaMinor": amount},
                                           {"accountId": contra, "currency": row["currency"], "deltaMinor": -amount}]}
                    posting, replay = self.ledger._book(db, request, source="INTEREST")
                    if replay:
                        raise DomainError("SETTLEMENT_CONFLICT", "Accrual marker disagrees with journal", 409)
                    posting_id = posting["postingId"]
                db.execute("""UPDATE accrual SET settlement_posting=?,settled_at=?
                    WHERE account_id=? AND business_date<=? AND settled_at IS NULL""", (posting_id, utcnow(), account_id, through))
                db.execute("""INSERT INTO accrual_carry VALUES (?,?,?) ON CONFLICT(account_id)
                    DO UPDATE SET amount_micro=excluded.amount_micro,through_date=excluded.through_date""",
                    (account_id, remainder, through))
                results.append({"accountId": account_id, "currency": row["currency"], "amountMinor": amount,
                                "carryMicro": remainder, "postingId": posting_id})
            if results:
                audit(db, "INTEREST", "INTEREST_SETTLED", through, {"accounts": len(results)})
            return {"throughDate": through, "settlements": results}

    def list(self, account_id):
        with self.database.read() as db:
            return {"accruals": [dict(row) for row in db.execute(
                "SELECT * FROM accrual WHERE account_id=? ORDER BY business_date", (account_id,))]}
