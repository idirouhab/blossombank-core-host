import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hostbridge.httpserver import RegionServer
from .support import RegionTest


class HttpTests(RegionTest):
    def setUp(self):
        super().setUp()
        self.server = RegionServer(("127.0.0.1", 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_address[1])
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, body=None, content_type="application/json"):
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        request = Request(self.base + path, data=body, headers={"Content-Type": content_type})
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read()), response.headers

    def test_health_and_account_contract(self):
        status, health, headers = self.request("/health")
        self.assertEqual(200, status)
        self.assertEqual("UP", health["status"])
        self.assertEqual("no-store", headers["Cache-Control"])
        status, data, _ = self.request("/v1/accounts?customerId=C0001")
        self.assertEqual(200, status)
        self.assertEqual(5, len(data["accounts"]))
        self.assertIs(type(data["accounts"][0]["balanceMinor"]), int)

    def test_post_and_replay_status_codes(self):
        status, original, _ = self.request("/v1/postings", self.transfer())
        self.assertEqual(201, status)
        status, replay, _ = self.request("/v1/postings", self.transfer())
        self.assertEqual(200, status)
        self.assertEqual(original, replay)
        status, conflict, _ = self.request("/v1/postings", self.transfer(amount=101))
        self.assertEqual(409, status)
        self.assertEqual("REFERENCE_CONFLICT", conflict["error"]["code"])

    def test_validation_error_contract(self):
        status, response, _ = self.request("/v1/postings", self.transfer(amount=999999999))
        self.assertEqual(409, status)
        self.assertEqual("INSUFFICIENT_FUNDS", response["error"]["code"])
        self.assertIsInstance(response["error"]["message"], str)

    def test_invalid_json_and_duplicate_keys_are_rejected(self):
        for body in (b"{", b'{"a":1,"a":2}', b'{"amount":NaN}', b"[]"):
            with self.subTest(body=body):
                status, response, _ = self.request("/v1/postings", body)
                self.assertEqual(400, status)
                self.assertIn("error", response)

    def test_content_type_and_missing_account(self):
        self.assertEqual(415, self.request("/v1/postings", b"{}", "text/plain")[0])
        self.assertEqual(404, self.request("/v1/accounts/not-an-account")[0])
        self.assertEqual(404, self.request("/missing")[0])

    def test_journal_and_reference_lookup(self):
        _, posted, _ = self.request("/v1/postings", self.transfer())
        status, result, _ = self.request("/v1/journal?after=0&limit=1")
        self.assertEqual(200, status)
        self.assertEqual(1, result["nextSequence"])
        self.assertEqual(posted["postingId"], result["entries"][0]["postingId"])
        _, lookup, _ = self.request("/v1/postings/by-reference?reference=TEST-001")
        self.assertEqual(posted, lookup)

    def test_duplicate_query_and_invalid_pagination(self):
        self.assertEqual(400, self.request("/v1/accounts?customerId=C0001&customerId=C0002")[0])
        for suffix in ("after=-1", "limit=2001", "limit=0", "after=cat"):
            self.assertEqual(400, self.request("/v1/journal?" + suffix)[0])
