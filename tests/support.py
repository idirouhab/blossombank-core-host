import tempfile
import unittest
from pathlib import Path

from hostbridge.application import Application
from hostbridge.errors import DomainError


class RegionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="blossom-host-test-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)
        self.app = Application(self.path / "host.sqlite3")

    def transfer(self, reference="TEST-001", amount=100, debtor="1000000001", creditor="2000000001", currency="EUR"):
        return {"externalReference": reference, "narrative": "Account transfer",
                "entries": [{"accountId": debtor, "currency": currency, "deltaMinor": -amount},
                            {"accountId": creditor, "currency": currency, "deltaMinor": amount}]}

    def assert_error(self, code, function, *args, **kwargs):
        with self.assertRaises(DomainError) as captured:
            function(*args, **kwargs)
        self.assertEqual(code, captured.exception.code)
        return captured.exception
