import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from hostbridge.application import Application
from hostbridge.errors import DomainError
from .support import RegionTest


class LedgerTests(RegionTest):
    def test_seed_accounts_and_native_exponents(self):
        accounts = self.app.accounts.list("C0001")["accounts"]
        self.assertEqual(["EUR", "USD", "GBP", "JPY", "KWD"], [a["currency"] for a in accounts])
        self.assertEqual([2540235, 125000, 68050, 250000, 125000], [a["balanceMinor"] for a in accounts])
        self.assertTrue(all(a["availableMinor"] == a["balanceMinor"] for a in accounts))

    def test_post_replay_and_durable_restart(self):
        request = self.transfer(amount=1250)
        response, replay = self.app.ledger.post(request)
        self.assertFalse(replay)
        restarted = Application(self.path / "host.sqlite3")
        again, replay = restarted.ledger.post(request)
        self.assertTrue(replay)
        self.assertEqual(response, again)
        self.assertEqual(2538985, restarted.accounts.get("1000000001")["balanceMinor"])
        self.assertEqual(2, len(restarted.ledger.journal()["entries"]))

    def test_reference_conflict_has_no_partial_effect(self):
        self.app.ledger.post(self.transfer())
        request = self.transfer(amount=101)
        self.assert_error("REFERENCE_CONFLICT", self.app.ledger.post, request)
        self.assertEqual(2, len(self.app.ledger.journal()["entries"]))

    def test_narrative_participates_in_idempotency(self):
        request = self.transfer()
        self.app.ledger.post(request)
        request["narrative"] = "Changed meaning"
        self.assert_error("REFERENCE_CONFLICT", self.app.ledger.post, request)

    def test_unbalanced_posting_is_rejected_by_cobol(self):
        request = self.transfer()
        request["entries"][1]["deltaMinor"] = 99
        self.assert_error("UNBALANCED", self.app.ledger.post, request)
        self.assertEqual([], self.app.ledger.journal()["entries"])

    def test_balance_must_be_zero_per_currency(self):
        request = self.transfer()
        request["entries"][1].update(accountId="1000000002", currency="USD")
        self.assert_error("UNBALANCED", self.app.ledger.post, request)

    def test_four_leg_currency_trade(self):
        request = {"externalReference": "FX-001", "narrative": "EUR/JPY settlement", "entries": [
            {"accountId": "1000000001", "currency": "EUR", "deltaMinor": -10000},
            {"accountId": "FX-EUR", "currency": "EUR", "deltaMinor": 10000},
            {"accountId": "FX-JPY", "currency": "JPY", "deltaMinor": -16234},
            {"accountId": "2000000003", "currency": "JPY", "deltaMinor": 16234}]}
        self.app.ledger.post(request)
        self.assertEqual(-16234, self.app.accounts.get("FX-JPY")["balanceMinor"])
        self.assertEqual(96234, self.app.accounts.get("2000000003")["balanceMinor"])
        self.assertEqual("BALANCED", self.app.reconciliation.run()["status"])

    def test_kwd_and_jpy_minor_units_are_not_cents(self):
        self.app.ledger.post(self.transfer("JPY-1", 1, "1000000004", "2000000003", "JPY"))
        self.app.ledger.post(self.transfer("KWD-1", 1, "1000000005", "2000000004", "KWD"))
        self.assertEqual(249999, self.app.accounts.get("1000000004")["balanceMinor"])
        self.assertEqual(124999, self.app.accounts.get("1000000005")["balanceMinor"])

    def test_wrong_currency_on_known_account(self):
        request = self.transfer(currency="USD")
        self.assert_error("CURRENCY_MISMATCH", self.app.ledger.post, request)

    def test_repeated_account_is_validated_as_atomic_net(self):
        request = self.transfer(amount=100)
        request["entries"].extend([
            {"accountId": "1000000001", "currency": "EUR", "deltaMinor": -50},
            {"accountId": "2000000001", "currency": "EUR", "deltaMinor": 50}])
        self.app.ledger.post(request)
        self.assertEqual(2540085, self.app.accounts.get("1000000001")["balanceMinor"])
        self.assertEqual("BALANCED", self.app.reconciliation.run()["status"])

    def test_insufficient_funds_rolls_back_both_legs(self):
        self.assert_error("INSUFFICIENT_FUNDS", self.app.ledger.post, self.transfer(amount=2540236))
        self.assertEqual(180000, self.app.accounts.get("2000000001")["balanceMinor"])
        self.assertEqual([], self.app.ledger.journal()["entries"])

    def test_missing_creditor_leaves_no_debit(self):
        self.assert_error("NOT_FOUND", self.app.ledger.post, self.transfer(creditor="9999999999"))
        self.assertEqual(2540235, self.app.accounts.get("1000000001")["balanceMinor"])

    def test_rejects_non_integer_and_boolean_money(self):
        for value in (True, 1.5, "100", None, 10**15):
            with self.subTest(value=value):
                request = self.transfer()
                request["entries"][0]["deltaMinor"] = value
                self.assert_error("INVALID_AMOUNT", self.app.ledger.post, request)

    def test_zero_and_unknown_currency_are_rejected(self):
        self.assert_error("ZERO_ENTRY", self.app.ledger.post, self.transfer(amount=0))
        self.assert_error("UNKNOWN_CURRENCY", self.app.ledger.post, self.transfer(currency="XYZ"))

    def test_journal_cursor_never_repeats_entries(self):
        for index in range(3):
            self.app.ledger.post(self.transfer(f"PAGE-{index}"))
        first = self.app.ledger.journal(limit=3)
        second = self.app.ledger.journal(after=first["nextSequence"], limit=3)
        self.assertEqual([1, 2, 3], [e["sequence"] for e in first["entries"]])
        self.assertEqual([4, 5, 6], [e["sequence"] for e in second["entries"]])
        self.assertEqual(6, self.app.ledger.journal(after=6)["nextSequence"])

    def test_reversal_is_a_new_balanced_posting(self):
        posted, _ = self.app.ledger.post(self.transfer())
        body = {"externalReference": "REV-001", "reason": "Duplicate order"}
        reverse, replay = self.app.ledger.reverse(posted["postingId"], body)
        self.assertFalse(replay)
        self.assertEqual(posted["postingId"], reverse["reversalOf"])
        self.assertEqual(2540235, self.app.accounts.get("1000000001")["balanceMinor"])
        self.assertEqual(4, len(self.app.ledger.journal()["entries"]))
        self.assertTrue(self.app.ledger.reverse(posted["postingId"], body)[1])
        self.assert_error("ALREADY_REVERSED", self.app.ledger.reverse, posted["postingId"],
                          {"externalReference": "REV-002", "reason": "Again"})

    def test_reversal_cannot_overdraw_recipient(self):
        posted, _ = self.app.ledger.post(self.transfer(amount=100))
        self.app.ledger.post(self.transfer("SPEND", 180100, "2000000001", "1000000001"))
        self.assert_error("INSUFFICIENT_FUNDS", self.app.ledger.reverse, posted["postingId"],
                          {"externalReference": "REV-FAILED", "reason": "Recall"})

    def test_concurrent_same_reference_books_once(self):
        request = self.transfer()
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(lambda _: self.app.ledger.post(copy.deepcopy(request)), range(16)))
        self.assertEqual(1, sum(not replay for _, replay in results))
        self.assertEqual(1, len({response["postingId"] for response, _ in results}))
        self.assertEqual(2, len(self.app.ledger.journal()["entries"]))

    def test_concurrent_debits_cannot_overspend(self):
        def spend(index):
            try:
                self.app.ledger.post(self.transfer(f"RACE-{index}", 70000, "2000000001", "1000000001"))
                return "BOOKED"
            except DomainError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=6) as workers:
            outcomes = list(workers.map(spend, range(6)))
        self.assertEqual(2, outcomes.count("BOOKED"))
        self.assertEqual(4, outcomes.count("INSUFFICIENT_FUNDS"))
        self.assertEqual(40000, self.app.accounts.get("2000000001")["availableMinor"])

    def test_database_enforces_journal_immutability(self):
        self.app.ledger.post(self.transfer())
        for query in ("UPDATE journal SET delta_minor=1", "DELETE FROM journal"):
            with self.assertRaises(sqlite3.IntegrityError):
                with self.app.database.write() as db:
                    db.execute(query)

    def test_live_posting_requires_cobol_module(self):
        self.app.cobol.binary_dir = self.path / "missing"
        self.assert_error("HOST_PROGRAM_UNAVAILABLE", self.app.ledger.post, self.transfer())
        self.assertEqual([], self.app.ledger.journal()["entries"])

    def test_seed_never_resets_balance_after_restart(self):
        self.app.ledger.post(self.transfer(amount=735))
        self.app.database.initialize()
        self.assertEqual(2539500, self.app.accounts.get("1000000001")["balanceMinor"])
