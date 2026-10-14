from datetime import date, timedelta
from pathlib import Path

from hostbridge.application import Application
from .support import RegionTest


class DayEndTests(RegionTest):
    def current_day(self):
        return self.app.health()["businessDate"]

    def following_day(self, day):
        return (date.fromisoformat(day) + timedelta(days=1)).isoformat()

    def test_close_snapshots_and_blocks_further_posting(self):
        self.app.ledger.post(self.transfer(amount=1234))
        day = self.current_day()
        closed = self.app.daybook.close(day)
        self.assertEqual("CLOSED", closed["state"])
        self.assertEqual(2, closed["cutoff_sequence"])
        self.assertEqual(closed, self.app.daybook.close(day))
        self.assert_error("REGION_CLOSED", self.app.ledger.post, self.transfer("AFTER-CLOSE"))
        records = self.app.daybook.snapshot(day)["accounts"]
        record = next(r for r in records if r["account_id"] == "1000000001")
        self.assertEqual(1234, record["debit_turnover"])
        self.assertEqual(2539001, record["balance_minor"])

    def test_new_day_requires_previous_close_and_moves_forward(self):
        day = self.current_day()
        tomorrow = self.following_day(day)
        self.assert_error("DAY_STILL_OPEN", self.app.daybook.open, tomorrow)
        self.app.daybook.close(day)
        self.assert_error("DATE_REGRESSION", self.app.daybook.open, day)
        self.app.daybook.open(tomorrow)
        posted, _ = self.app.ledger.post(self.transfer())
        self.assertEqual(tomorrow, posted["businessDate"])

    def test_reconciliation_detects_master_drift_and_blocks_close(self):
        with self.app.database.write() as db:
            db.execute("UPDATE account_master SET ledger_minor=ledger_minor+1 WHERE account_id='1000000001'")
        report = self.app.reconciliation.run()
        self.assertEqual("BREAKS", report["status"])
        self.assertEqual("BALANCE_DRIFT", report["breaks"][0]["code"])
        self.assert_error("CONTROL_BREAK", self.app.daybook.close, self.current_day())

    def test_backup_contains_consistent_committed_ledger(self):
        self.app.ledger.post(self.transfer())
        destination = self.path / "snapshot.sqlite3"
        self.app.database.backup(destination)
        restored = Application(destination)
        self.assertEqual(self.app.ledger.journal(), restored.ledger.journal())
        self.assertEqual("BALANCED", restored.reconciliation.run()["status"])

    def test_accrual_requires_snapshot_and_is_idempotent(self):
        day = self.current_day()
        self.assert_error("DAY_NOT_CLOSED", self.app.interest.accrue, day)
        self.app.daybook.close(day)
        result = self.app.interest.accrue(day)
        self.assertEqual(9, result["newAccruals"])
        self.assertEqual(0, self.app.interest.accrue(day)["newAccruals"])
        self.assertGreater(result["microByCurrency"]["USD"], 0)

    def test_interest_fraction_is_carried_into_later_settlement(self):
        self.app.interest.products["FX02"]["annual_credit_bps"] = "365"
        day = self.current_day()
        self.app.daybook.close(day)
        self.app.interest.accrue(day)
        tomorrow = self.following_day(day)
        self.app.daybook.open(tomorrow)
        result = self.app.interest.settle(day)
        usd = next(r for r in result["settlements"] if r["accountId"] == "1000000002")
        self.assertEqual(12, usd["amountMinor"])
        self.assertEqual(500000, usd["carryMicro"])
        self.assertEqual([], self.app.interest.settle(day)["settlements"])
        self.app.daybook.close(tomorrow)
        self.app.interest.accrue(tomorrow)
        self.app.daybook.open(self.following_day(tomorrow))
        result = self.app.interest.settle(tomorrow)
        usd = next(r for r in result["settlements"] if r["accountId"] == "1000000002")
        self.assertEqual(13, usd["amountMinor"])
        self.assertEqual(1200, usd["carryMicro"])
        self.assertEqual("BALANCED", self.app.reconciliation.run()["status"])

    def test_zero_minor_settlement_preserves_fraction(self):
        day = self.current_day()
        self.app.daybook.close(day)
        self.app.interest.accrue(day)
        result = self.app.interest.settle(day)
        self.assertTrue(all(row["postingId"] is None for row in result["settlements"]))
        self.assertTrue(any(row["carryMicro"] > 0 for row in result["settlements"]))
        self.assertEqual([], self.app.ledger.journal()["entries"])

    def test_cobol_interest_uses_integer_micro_units(self):
        self.assertEqual(15000000, self.app.cobol.interest(365000, 150))
        self.assertEqual(-15000000, self.app.cobol.interest(-365000, 150))
        self.assert_error("BAD_BASIS", self.app.cobol.interest, 1000, 100, basis=364)

    def test_binary_unload_uses_packed_decimal_copybook(self):
        self.app.ledger.post(self.transfer())
        destination = self.path / "AC01.UNLOAD"
        manifest = self.app.unload.export(destination)
        self.assertEqual(9, manifest["records"])
        self.assertEqual(84 * 9, destination.stat().st_size)
        payload = destination.read_bytes()
        self.assertEqual(b"07800421000000001", payload[:17])
        self.assertEqual(b"EUR0", payload[33:37])
        self.assertEqual(bytes.fromhex("0000002540135c"), payload[37:44])
        self.assertEqual(2, manifest["cutoffSequence"])
        self.assertTrue(destination.with_suffix(".UNLOAD.manifest.json").exists())


class ClearingTests(RegionTest):
    def feed(self, lines, name="clearing.csv"):
        path = self.path / name
        path.write_text("reference,debtor,creditor,currency,amount,narrative\n" + "\n".join(lines) + "\n")
        return path

    def test_clearing_posts_valid_lines_and_retains_rejects(self):
        path = self.feed(["001,1000000001,2000000001,EUR,12.50,Settlement",
                          "002,1000000001,2000000001,EUR,999999.99,Too large"])
        result = self.app.clearing.import_file(path)
        self.assertEqual(1, result["accepted"])
        self.assertEqual(1, result["rejected"])
        self.assertEqual("INSUFFICIENT_FUNDS", result["rejects"][0]["code"])
        self.assertEqual(2538985, self.app.accounts.get("1000000001")["balanceMinor"])
        self.assertEqual(result, self.app.clearing.import_file(path))
        self.assertEqual(2, len(self.app.ledger.journal()["entries"]))

    def test_reference_dedupes_across_different_input_files(self):
        first = self.feed(["001,1000000001,2000000001,EUR,12.50,Settlement"])
        second = self.feed(["001,1000000001,2000000001,EUR,12.50,Settlement",
                            "002,1000000001,2000000001,EUR,2.00,Settlement"], "second.csv")
        self.app.clearing.import_file(first)
        result = self.app.clearing.import_file(second)
        self.assertEqual(2, result["accepted"])
        self.assertEqual(1, result["replayed"])
        self.assertEqual(4, len(self.app.ledger.journal()["entries"]))

    def test_clr021_retains_two_place_amount_card_behavior(self):
        path = self.feed(["JPY01,1000000004,2000000003,JPY,12.50,Advice"])
        self.app.clearing.import_file(path)
        self.assertEqual(248750, self.app.accounts.get("1000000004")["balanceMinor"])

    def test_cobol_clearing_rounds_to_two_places(self):
        self.assertEqual(235, self.app.cobol.clearing_amount("2.345"))
        self.assertEqual(-235, self.app.cobol.clearing_amount("-2.345"))
        self.assert_error("BAD_AMOUNT", self.app.cobol.clearing_amount, "hello")

    def test_header_required_before_job_is_created(self):
        path = self.path / "bad.csv"
        path.write_text("account,value\n1000000001,10\n")
        self.assert_error("BAD_HEADER", self.app.clearing.import_file, path)
        self.assertEqual([], self.app.clearing.list_runs()["runs"])


class StatementTests(RegionTest):
    def test_native_statement_uses_currency_exponent(self):
        self.app.ledger.post(self.transfer("KWD-ADVICE", 1001, "1000000005", "2000000004", "KWD"))
        day = self.app.health()["businessDate"]
        result = self.app.statements.generate("1000000005", day, day)
        self.assertEqual(3, result["exponent"])
        self.assertEqual("-1.001", result["lines"][0]["amount"])
        self.assertEqual("123.999", result["lines"][0]["balance"])

    def test_statement_opening_includes_prior_business_day(self):
        day = self.app.health()["businessDate"]
        self.app.ledger.post(self.transfer("DAY1", 100))
        self.app.daybook.close(day)
        tomorrow = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        self.app.daybook.open(tomorrow)
        self.app.ledger.post(self.transfer("DAY2", 300))
        result = self.app.statements.generate("1000000001", tomorrow, tomorrow)
        self.assertEqual(2540135, result["openingMinor"])
        self.assertEqual(2539835, result["closingMinor"])
        self.assertEqual(1, len(result["lines"]))

    def test_st04_spool_preserves_its_print_field(self):
        day = self.app.health()["businessDate"]
        spool = self.app.statements.print_spool("1000000004", day, day)
        self.assertIn("CURRENCY JPY", spool)
        self.assertIn("2500.00", spool)

    def test_inverted_range_is_rejected(self):
        self.assert_error("INVALID_RANGE", self.app.statements.generate, "1000000001", "2025-03-01", "2025-02-01")
