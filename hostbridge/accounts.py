import uuid

from . import validation as v
from .clock import utcnow, business_date
from .config import load_products
from .database import audit
from .errors import DomainError, Missing


def account_row(db, account_id):
    row = db.execute("SELECT * FROM account_master WHERE account_id=?", (account_id,)).fetchone()
    if row is None:
        raise Missing("Account")
    return row


def encumbrances(db, account_id, at=None):
    at = at or utcnow()
    held = db.execute("""SELECT coalesce(sum(amount_minor),0) FROM hold
        WHERE account_id=? AND status='ACTIVE' AND expires_at>?""", (account_id, at)).fetchone()[0]
    liens = db.execute("SELECT coalesce(sum(amount_minor),0) FROM lien WHERE account_id=? AND active=1", (account_id,)).fetchone()[0]
    return held, liens


def available(db, row, at=None):
    held, liens = encumbrances(db, row["account_id"], at)
    return row["ledger_minor"] + row["overdraft_minor"] - held - liens


def serialize_account(db, row, at=None):
    held, liens = encumbrances(db, row["account_id"], at)
    amount = row["ledger_minor"] + row["overdraft_minor"] - held - liens
    return {"accountId": row["account_id"], "customerId": row["customer_id"],
            "currency": row["currency"], "balanceMinor": row["ledger_minor"],
            "availableMinor": amount if row["internal"] else max(0, amount),
            "status": row["status"], "productCode": row["product_code"],
            "heldMinor": held, "lienMinor": liens, "overdraftMinor": row["overdraft_minor"],
            "revision": row["revision"]}


class Accounts:
    def __init__(self, database):
        self.database = database
        self.products = load_products()

    def get(self, account_id):
        with self.database.read() as db:
            return serialize_account(db, account_row(db, account_id))

    def list(self, customer_id):
        v.identifier(customer_id, "customerId")
        with self.database.read() as db:
            at = utcnow()
            return {"accounts": [serialize_account(db, row, at) for row in db.execute(
                "SELECT * FROM account_master WHERE customer_id=? ORDER BY account_id", (customer_id,))]}

    def resolve(self, alias, channel):
        with self.database.read() as db:
            row = db.execute("""SELECT account_id FROM account_alias
                WHERE alias=? AND channel=? AND (valid_until IS NULL OR valid_until>=?)""",
                (alias, channel, business_date())).fetchone()
            if not row:
                raise Missing("Account alias")
            return serialize_account(db, account_row(db, row[0]))

    def open(self, body):
        v.object_body(body)
        account_id = v.identifier(body.get("accountId"), "accountId")
        customer = v.identifier(body.get("customerId"), "customerId")
        ccy = v.currency(body.get("currency"))
        product = body.get("productCode", "FX02")
        if product not in self.products or product == "NOST" or customer == "INTERNAL":
            raise DomainError("INVALID_PRODUCT", "Product is not available for retail opening")
        if not account_id.isdigit() or len(account_id) != 10:
            raise DomainError("INVALID_ACCOUNT", "Retail accounts must contain ten digits")
        with self.database.write() as db:
            existing = db.execute("SELECT 1 FROM account_master WHERE account_id=?", (account_id,)).fetchone()
            if existing:
                raise DomainError("ACCOUNT_EXISTS", "Account number is already allocated", 409)
            db.execute("""INSERT INTO account_master
                (account_id,customer_id,currency,product_code,ledger_minor,opening_minor,opened_on)
                VALUES (?,?,?,?,0,0,?)""", (account_id, customer, ccy, product, business_date()))
            db.execute("INSERT OR IGNORE INTO customer_flags(customer_id) VALUES (?)", (customer,))
            audit(db, "OFFICE", "ACCOUNT_OPENED", account_id, {"currency": ccy, "product": product})
            return serialize_account(db, account_row(db, account_id))

    def restrict(self, account_id, body):
        v.object_body(body)
        reason = v.text(body.get("reason"), "reason", 120)
        if not reason:
            raise DomainError("REASON_REQUIRED", "An operator reason is required")
        with self.database.write() as db:
            row = account_row(db, account_id)
            if row["internal"]:
                raise DomainError("CONTROL_ACCOUNT", "Use a region change to alter control accounts", 409)
            status = body.get("status", row["status"])
            if status not in ("OPEN", "FROZEN", "CLOSED"):
                raise DomainError("INVALID_STATUS", "Unsupported account status")
            if row["status"] == "CLOSED" and status != "CLOSED":
                raise DomainError("ACCOUNT_CLOSED", "Closed account numbers cannot be reopened", 409)
            debit_block = v.text(body.get("debitBlock", row["debit_block"]), "debitBlock", 32)
            credit_line = v.minor(body.get("overdraftMinor", row["overdraft_minor"]), "overdraftMinor")
            if credit_line < 0:
                raise DomainError("INVALID_AMOUNT", "Credit line cannot be negative")
            held, liens = encumbrances(db, account_id)
            if status == "CLOSED" and (row["ledger_minor"] != 0 or held or liens):
                raise DomainError("CLOSURE_BALANCE", "Account must be empty and unencumbered", 409)
            if credit_line < row["overdraft_minor"] and row["ledger_minor"] + credit_line - held - liens < 0:
                raise DomainError("CREDIT_LINE_USED", "Cannot withdraw a utilized credit line", 409)
            db.execute("UPDATE account_master SET status=?,debit_block=?,overdraft_minor=?,revision=revision+1 WHERE account_id=?",
                       (status, debit_block, credit_line, account_id))
            audit(db, "OFFICE", "ACCOUNT_RESTRICTED", account_id,
                  {"status": status, "debitBlock": debit_block, "overdraftMinor": credit_line, "reason": reason})
            return serialize_account(db, account_row(db, account_id))

    def add_lien(self, account_id, body):
        v.object_body(body)
        amount = v.minor(body.get("amountMinor"), "amountMinor", positive=True)
        authority = v.identifier(body.get("authorityReference"), "authorityReference")
        with self.database.write() as db:
            row = account_row(db, account_id)
            if row["internal"] or row["status"] == "CLOSED":
                raise DomainError("INVALID_LIEN_ACCOUNT", "Account cannot receive a lien", 409)
            previous = db.execute("SELECT * FROM lien WHERE authority_reference=?", (authority,)).fetchone()
            if previous:
                if previous["account_id"] != account_id or previous["amount_minor"] != amount:
                    raise DomainError("REFERENCE_CONFLICT", "Authority reference already used", 409)
                return dict(previous)
            lien_id = "LN-" + uuid.uuid4().hex
            db.execute("INSERT INTO lien(lien_id,account_id,amount_minor,authority_reference,created_at) VALUES (?,?,?,?,?)",
                       (lien_id, account_id, amount, authority, utcnow()))
            audit(db, "CONTROL", "LIEN_ADDED", account_id, {"lienId": lien_id, "amountMinor": amount})
            return dict(db.execute("SELECT * FROM lien WHERE lien_id=?", (lien_id,)).fetchone())

    def release_lien(self, lien_id):
        with self.database.write() as db:
            row = db.execute("SELECT * FROM lien WHERE lien_id=?", (lien_id,)).fetchone()
            if not row:
                raise Missing("Lien")
            if row["active"]:
                db.execute("UPDATE lien SET active=0,released_at=? WHERE lien_id=?", (utcnow(), lien_id))
                audit(db, "CONTROL", "LIEN_RELEASED", row["account_id"], {"lienId": lien_id})
            return {"lienId": lien_id, "status": "RELEASED"}
