from decimal import Decimal

from . import validation as v
from .accounts import account_row
from .config import CURRENCIES


def amount_text(minor, exponent):
    return f"{Decimal(minor).scaleb(-exponent):.{exponent}f}"


class Statements:
    def __init__(self, database):
        self.database = database

    def generate(self, account_id, start, end):
        v.iso_date(start)
        v.iso_date(end)
        if start > end:
            from .errors import DomainError
            raise DomainError("INVALID_RANGE", "Statement start must precede end")
        with self.database.read() as db:
            account = account_row(db, account_id)
            exponent = CURRENCIES[account["currency"]]
            before = db.execute("""SELECT coalesce(sum(j.delta_minor),0) FROM journal j
                JOIN posting p USING(posting_id) WHERE j.account_id=? AND p.business_date<?""", (account_id, start)).fetchone()[0]
            balance = account["opening_minor"] + before
            opening = balance
            lines = []
            credit = debit = 0
            for row in db.execute("""SELECT j.*,p.business_date,p.narrative,p.external_reference
                    FROM journal j JOIN posting p USING(posting_id)
                    WHERE j.account_id=? AND p.business_date>=? AND p.business_date<=?
                    ORDER BY j.sequence""", (account_id, start, end)):
                delta = row["delta_minor"]
                balance += delta
                credit += max(0, delta)
                debit += max(0, -delta)
                lines.append({"sequence": row["sequence"], "date": row["business_date"],
                              "reference": row["external_reference"], "narrative": row["narrative"],
                              "deltaMinor": delta, "amount": amount_text(delta, exponent),
                              "balanceMinor": balance, "balance": amount_text(balance, exponent)})
            return {"accountId": account_id, "currency": account["currency"], "exponent": exponent,
                    "from": start, "to": end, "openingMinor": opening, "closingMinor": balance,
                    "debitsMinor": debit, "creditsMinor": credit, "lines": lines}

    def print_spool(self, account_id, start, end):
        statement = self.generate(account_id, start, end)
        output = ["1BLOSSOMBANK CUSTOMER ADVICE       FORM ST-04",
                  f' ACCOUNT {account_id:<12}   PERIOD {start} - {end}',
                  f' CURRENCY {statement["currency"]}             OFFICE 0042',
                  ' DATE        REFERENCE                 AMOUNT          BALANCE',
                  f' OPENING                                       {amount_text(statement["openingMinor"], 2):>15}']
        for line in statement["lines"]:
            output.append(f' {line["date"]}  {line["reference"][:24]:<24} {amount_text(line["deltaMinor"], 2):>14} {amount_text(line["balanceMinor"], 2):>14}')
        output.append(f' CLOSING                                       {amount_text(statement["closingMinor"], 2):>15}')
        return "\n".join(output) + "\n"
