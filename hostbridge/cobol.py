import os
import subprocess

from .config import CURRENCIES, ROOT
from .errors import DomainError


class CobolRegion:
    """Line-oriented local equivalent of the LINK bridge used by BLSONL1."""

    def __init__(self, binary_dir=None):
        self.binary_dir = binary_dir or ROOT / "build" / "bin"

    def verify(self):
        for name in ("entrychk", "balctl", "intrcalc", "legacyamt", "acctunld"):
            if not os.access(self.binary_dir / name, os.X_OK):
                raise RuntimeError(f"Missing COBOL module {name}; run ./build.sh")
        self.balance([{"currency": "EUR", "deltaMinor": 0}])

    def _call(self, module, payload):
        try:
            process = subprocess.run([str(self.binary_dir / module)], input=payload,
                                     capture_output=True, text=True, timeout=5, check=True)
        except (subprocess.SubprocessError, OSError) as exc:
            raise DomainError("HOST_PROGRAM_UNAVAILABLE", f"Host module {module} unavailable", 503) from exc
        fields = process.stdout.strip().split("|")
        if len(fields) < 2:
            raise DomainError("HOST_PROTOCOL_ERROR", f"Unexpected response from {module}", 503)
        if fields[0] != "OK":
            status = 409 if fields[0] in {"INSUFFICIENT_FUNDS", "DEBIT_BLOCKED", "ACCOUNT_CLOSED", "BALANCE_OVERFLOW"} else 400
            raise DomainError(fields[0], " | ".join(fields[1:]), status)
        return fields[1:]

    def account(self, row, delta, available, currency, debit_allowed=True):
        fields = [row["status"], "Y" if row["internal"] else "N", currency,
                  row["currency"], CURRENCIES[currency], row["ledger_minor"],
                  available, delta, "Y" if debit_allowed else "N"]
        result = self._call("entrychk", "|".join(map(str, fields)) + "\n")
        return int(result[0])

    def balance(self, entries):
        payload = "".join(f'{e["currency"]}|{e["deltaMinor"]}\n' for e in entries) + "END\n"
        return int(self._call("balctl", payload)[0])

    def interest(self, balance, annual_bps, days=1, basis=365):
        if type(balance) is not int or abs(balance) > 999_999_999_999:
            raise DomainError("BAD_BALANCE", "Interest balance exceeds host range")
        if type(annual_bps) is not int or not 0 <= annual_bps <= 50000:
            raise DomainError("BAD_RATE", "Annual basis points out of range")
        if type(days) is not int or not 1 <= days <= 366:
            raise DomainError("BAD_PERIOD", "Accrual days out of range")
        return int(self._call("intrcalc", f"{balance}|{annual_bps}|{days}|{basis}\n")[0])

    def clearing_amount(self, display_amount):
        if not isinstance(display_amount, str) or len(display_amount) > 20 or "\n" in display_amount:
            raise DomainError("BAD_AMOUNT", "Clearing amount has an invalid width")
        return int(self._call("legacyamt", display_amount + "\n")[0])
