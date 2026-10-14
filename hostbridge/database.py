import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from .clock import business_date, utcnow
from .config import ROOT, runtime_dir


SEED_ACCOUNTS = (
    ("1000000001", "C0001", "EUR", 2540235, "CA01"),
    ("1000000002", "C0001", "USD", 125000, "FX02"),
    ("1000000003", "C0001", "GBP", 68050, "FX02"),
    ("1000000004", "C0001", "JPY", 250000, "FX02"),
    ("1000000005", "C0001", "KWD", 125000, "FX02"),
    ("2000000001", "C0002", "EUR", 180000, "CA01"),
    ("2000000002", "C0002", "USD", 45000, "FX02"),
    ("2000000003", "C0002", "JPY", 80000, "FX02"),
    ("2000000004", "C0002", "KWD", 55000, "FX02"),
)


class Database:
    def __init__(self, path=None):
        self.path = path or runtime_dir() / "host.sqlite3"
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def read(self):
        db = self.connect()
        try:
            # A consistent snapshot is needed for accounts + pending holds.
            db.execute("BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def write(self):
        db = self.connect()
        try:
            # Reserve the writer before reading available balances.
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        with closing(self.connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, installed_at TEXT NOT NULL)")
            installed = {r[0] for r in db.execute("SELECT version FROM schema_version")}
            for path in sorted((ROOT / "db" / "migrations").glob("*.sql")):
                version = int(path.name.split("_", 1)[0])
                if version in installed:
                    continue
                sql = path.read_text()
                timestamp = utcnow()
                try:
                    db.executescript(f"BEGIN IMMEDIATE;\n{sql}\nINSERT INTO schema_version VALUES ({version},'{timestamp}');\nCOMMIT;")
                except BaseException:
                    db.rollback()
                    raise
        self._seed()

    def _seed(self):
        with self.write() as db:
            # Seeding is an installation step, never a restore of missing accounts.
            if db.execute("SELECT 1 FROM parameter_override WHERE parameter_group='INSTALL'").fetchone():
                return
            for account, customer, currency, balance, product in SEED_ACCOUNTS:
                db.execute("""INSERT INTO account_master
                    (account_id,customer_id,currency,product_code,ledger_minor,opening_minor,opened_on)
                    VALUES (?,?,?,?,?,?,?)""", (account, customer, currency, product, balance, balance, "2008-04-11"))
                db.execute("INSERT INTO account_alias VALUES (?,?,?,NULL)", ("0780042" + account, account, "OFFICE"))
            for currency in ("EUR", "USD", "GBP", "JPY", "KWD"):
                db.execute("""INSERT INTO account_master
                    (account_id,customer_id,currency,product_code,ledger_minor,opening_minor,opened_on,internal)
                    VALUES (?,?,?,'NOST',0,0,'2005-01-03',1)""", ("FX-" + currency, "INTERNAL", currency))
            for customer in ("C0001", "C0002"):
                db.execute("INSERT INTO customer_flags(customer_id) VALUES (?)", (customer,))
            db.execute("INSERT INTO day_control VALUES (?,'OPEN',?,NULL,NULL,NULL)", (business_date(), utcnow()))
            db.execute("INSERT INTO parameter_override VALUES ('INSTALL','SEED','v1',?)", (business_date(),))
            audit(db, "INSTALL", "REGION_CREATED", "BLSONL1", {"accounts": len(SEED_ACCOUNTS)})

    def backup(self, destination):
        import pathlib
        target = pathlib.Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        source = self.connect()
        backup = sqlite3.connect(target)
        try:
            source.backup(backup)
        finally:
            backup.close()
            source.close()
        return str(target)


def audit(db, actor, action, resource, detail):
    db.execute("INSERT INTO audit_event(happened_at,actor,action,resource,detail_json) VALUES (?,?,?,?,?)",
               (utcnow(), actor, action, resource, json.dumps(detail, sort_keys=True, separators=(",", ":"))))
