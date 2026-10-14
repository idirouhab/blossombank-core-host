from collections import defaultdict


def reconcile_connection(db):
    failures = []
    positions = []
    for row in db.execute("""SELECT a.account_id,a.currency,a.ledger_minor,a.opening_minor,
            coalesce(sum(j.delta_minor),0) AS movement
            FROM account_master a LEFT JOIN journal j USING(account_id)
            GROUP BY a.account_id ORDER BY a.account_id"""):
        expected = row["opening_minor"] + row["movement"]
        positions.append({"accountId": row["account_id"], "currency": row["currency"],
                          "ledgerMinor": row["ledger_minor"], "reconstructedMinor": expected})
        if expected != row["ledger_minor"]:
            failures.append({"code": "BALANCE_DRIFT", "accountId": row["account_id"],
                             "differenceMinor": row["ledger_minor"] - expected})
    for row in db.execute("SELECT posting_id,currency,sum(delta_minor) AS net FROM journal GROUP BY posting_id,currency HAVING net != 0"):
        failures.append({"code": "POSTING_UNBALANCED", "postingId": row["posting_id"],
                         "currency": row["currency"], "differenceMinor": row["net"]})
    # Reconstruct every journal running balance, including repeated-account entries.
    running = {r["account_id"]: r["opening_minor"] for r in db.execute("SELECT account_id,opening_minor FROM account_master")}
    for row in db.execute("SELECT * FROM journal ORDER BY sequence"):
        running[row["account_id"]] += row["delta_minor"]
        if running[row["account_id"]] != row["resulting_balance"]:
            failures.append({"code": "RUNNING_BALANCE_DRIFT", "sequence": row["sequence"]})
    totals = defaultdict(int)
    for row in db.execute("SELECT currency,delta_minor FROM journal"):
        totals[row["currency"]] += row["delta_minor"]
    integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        failures.append({"code": "DATABASE_INTEGRITY", "detail": integrity})
    foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        failures.append({"code": "DATABASE_FOREIGN_KEYS", "count": len(foreign_keys)})
    return {"status": "BALANCED" if not failures else "BREAKS", "positions": positions,
            "currencyMovementMinor": dict(totals), "breaks": failures,
            "lastSequence": db.execute("SELECT coalesce(max(sequence),0) FROM journal").fetchone()[0]}


class Reconciliation:
    def __init__(self, database):
        self.database = database

    def run(self):
        with self.database.read() as db:
            return reconcile_connection(db)
