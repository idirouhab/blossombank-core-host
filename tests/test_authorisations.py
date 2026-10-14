from datetime import datetime, timedelta, timezone

from .support import RegionTest


class AuthorisationTests(RegionTest):
    def hold_request(self, amount=10000, reference="AUTH-001"):
        return {"accountId": "1000000001", "externalReference": reference, "currency": "EUR",
                "amountMinor": amount, "reason": "Hotel deposit",
                "expiresAt": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}

    def test_hold_reserves_available_without_changing_ledger(self):
        request = self.hold_request()
        hold, replay = self.app.holds.create(request)
        self.assertFalse(replay)
        account = self.app.accounts.get("1000000001")
        self.assertEqual(2540235, account["balanceMinor"])
        self.assertEqual(2530235, account["availableMinor"])
        self.assertTrue(self.app.holds.create(request)[1])
        self.assertEqual(hold["holdId"], self.app.holds.list("1000000001")["holds"][0]["holdId"])

    def test_hold_prevents_other_posting_from_spending_reserved_funds(self):
        self.app.holds.create(self.hold_request(2540000))
        self.assert_error("INSUFFICIENT_FUNDS", self.app.ledger.post, self.transfer(amount=236))

    def test_capture_atomically_replaces_hold_with_posting(self):
        hold, _ = self.app.holds.create(self.hold_request())
        body = {"creditorAccount": "2000000001", "externalReference": "CAP-001", "narrative": "Stay"}
        response, replay = self.app.holds.capture(hold["holdId"], body)
        self.assertFalse(replay)
        account = self.app.accounts.get("1000000001")
        self.assertEqual(2530235, account["balanceMinor"])
        self.assertEqual(0, account["heldMinor"])
        self.assertEqual("CAPTURED", self.app.holds.get(hold["holdId"])["status"])
        self.assertEqual((response, True), self.app.holds.capture(hold["holdId"], body))

    def test_failed_capture_restores_authorisation(self):
        hold, _ = self.app.holds.create(self.hold_request())
        self.assert_error("CURRENCY_MISMATCH", self.app.holds.capture, hold["holdId"],
                          {"creditorAccount": "2000000002", "externalReference": "CAP-FAIL"})
        self.assertEqual("ACTIVE", self.app.holds.get(hold["holdId"])["status"])
        self.assertEqual(10000, self.app.accounts.get("1000000001")["heldMinor"])

    def test_capture_does_not_adopt_unrelated_posting_reference(self):
        request = self.transfer("CAP-TAKEN", 10000)
        self.app.ledger.post(request)
        hold, _ = self.app.holds.create(self.hold_request())
        self.assert_error("REFERENCE_CONFLICT", self.app.holds.capture, hold["holdId"],
                          {"creditorAccount": "2000000001", "externalReference": "CAP-TAKEN", "narrative": "Account transfer"})
        self.assertEqual("ACTIVE", self.app.holds.get(hold["holdId"])["status"])

    def test_release_is_idempotent(self):
        hold, _ = self.app.holds.create(self.hold_request())
        self.assertEqual("RELEASED", self.app.holds.release(hold["holdId"])["status"])
        self.assertEqual("RELEASED", self.app.holds.release(hold["holdId"])["status"])
        self.assertEqual(2540235, self.app.accounts.get("1000000001")["availableMinor"])

    def test_expired_hold_does_not_wait_for_batch_to_release_funds(self):
        hold, _ = self.app.holds.create(self.hold_request())
        with self.app.database.write() as db:
            db.execute("UPDATE hold SET expires_at='2000-01-01T00:00:00.000Z' WHERE hold_id=?", (hold["holdId"],))
        self.assertEqual(0, self.app.accounts.get("1000000001")["heldMinor"])
        self.assertEqual("EXPIRED", self.app.holds.get(hold["holdId"])["status"])
        self.assertEqual(1, self.app.holds.expire()["expiredCount"])

    def test_frozen_account_accepts_credit_but_not_debit(self):
        self.app.accounts.restrict("1000000001", {"status": "FROZEN", "reason": "Case review"})
        self.assert_error("DEBIT_BLOCKED", self.app.ledger.post, self.transfer())
        self.app.ledger.post(self.transfer("CREDIT", 100, "2000000001", "1000000001"))
        self.assertEqual(2540335, self.app.accounts.get("1000000001")["balanceMinor"])

    def test_lien_reduces_available_and_authority_reference_dedupes(self):
        body = {"amountMinor": 2540200, "authorityReference": "ORDER-001"}
        lien = self.app.accounts.add_lien("1000000001", body)
        self.assertEqual(lien, self.app.accounts.add_lien("1000000001", body))
        self.assert_error("INSUFFICIENT_FUNDS", self.app.ledger.post, self.transfer(amount=36))
        self.app.accounts.release_lien(lien["lien_id"])
        self.app.ledger.post(self.transfer(amount=36))

    def test_credit_line_cannot_be_withdrawn_while_in_use(self):
        self.app.accounts.restrict("2000000001", {"overdraftMinor": 5000, "reason": "Approved facility"})
        self.app.ledger.post(self.transfer("OD", 184000, "2000000001", "1000000001"))
        account = self.app.accounts.get("2000000001")
        self.assertEqual(-4000, account["balanceMinor"])
        self.assertEqual(1000, account["availableMinor"])
        self.assert_error("CREDIT_LINE_USED", self.app.accounts.restrict, "2000000001",
                          {"overdraftMinor": 3000, "reason": "Change facility"})

    def test_empty_account_can_close_and_cannot_reopen(self):
        account = self.app.accounts.open({"accountId": "3000000001", "customerId": "C0002", "currency": "KWD"})
        self.assertEqual(0, account["balanceMinor"])
        self.app.accounts.restrict("3000000001", {"status": "CLOSED", "reason": "Customer request"})
        self.assert_error("ACCOUNT_CLOSED", self.app.accounts.restrict, "3000000001", {"status": "OPEN", "reason": "Reopen"})

    def test_funded_account_cannot_close(self):
        self.assert_error("CLOSURE_BALANCE", self.app.accounts.restrict, "1000000001", {"status": "CLOSED", "reason": "Close"})

    def test_internal_accounts_cannot_receive_retail_restrictions(self):
        self.assert_error("CONTROL_ACCOUNT", self.app.accounts.restrict, "FX-EUR", {"status": "FROZEN", "reason": "Test"})

    def test_legacy_alias_is_channel_scoped(self):
        self.assertEqual("1000000001", self.app.accounts.resolve("07800421000000001", "OFFICE")["accountId"])
        self.assert_error("NOT_FOUND", self.app.accounts.resolve, "07800421000000001", "DIGITAL")
