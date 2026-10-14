from .accounts import Accounts
from .authorisations import Authorisations
from .clearing import Clearing
from .cobol import CobolRegion
from .database import Database
from .daybook import Daybook
from .interest import Interest
from .ledger import Ledger
from .reconciliation import Reconciliation
from .statements import Statements
from .unload import AccountUnload


class Application:
    def __init__(self, database_path=None):
        self.database = Database(database_path)
        self.database.initialize()
        self.cobol = CobolRegion()
        self.cobol.verify()
        self.accounts = Accounts(self.database)
        self.ledger = Ledger(self.database, self.cobol)
        self.holds = Authorisations(self.database, self.ledger)
        self.daybook = Daybook(self.database)
        self.interest = Interest(self.database, self.ledger)
        self.statements = Statements(self.database)
        self.clearing = Clearing(self.database, self.ledger)
        self.reconciliation = Reconciliation(self.database)
        self.unload = AccountUnload(self.database, self.cobol)

    def health(self):
        with self.database.read() as db:
            day = db.execute("SELECT business_date,state FROM day_control ORDER BY business_date DESC LIMIT 1").fetchone()
            version = db.execute("SELECT max(version) FROM schema_version").fetchone()[0]
            return {"status": "UP", "service": "BLSONL1", "region": "BLSONL1",
                    "database": "available", "cobol": "loaded", "schemaVersion": version,
                    "businessDate": day[0] if day else None, "dayState": day[1] if day else "NONE"}
