import json
import logging
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from .errors import DomainError, Missing

LOG = logging.getLogger("host.online")
MAX_BODY = 131072


def first(query, name, default=None):
    values = query.get(name)
    if values is None:
        return default
    if len(values) != 1:
        raise DomainError("INVALID_QUERY", f"{name} must occur once")
    return values[0]


class RegionServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, application):
        self.application = application
        super().__init__(address, HostHandler)


class HostHandler(BaseHTTPRequestHandler):
    server_version = "BlossomHost/7.14"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        request_id = uuid.uuid4().hex
        try:
            parts = urlsplit(self.path)
            path = unquote(parts.path)
            query = parse_qs(parts.query, keep_blank_values=True)
            if method == "GET":
                response, status = self._get(path, query)
            else:
                response, status = self._post(path, self._body())
        except DomainError as exc:
            response, status = exc.response(), exc.status
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception:
            LOG.exception("request failed request_id=%s", request_id)
            response, status = {"error": {"code": "HOST_ERROR", "message": "Host request failed", "requestId": request_id}}, 500
        self._respond(response, status, request_id)

    def _body(self):
        if self.headers.get("Transfer-Encoding"):
            raise DomainError("INVALID_BODY", "Transfer encoding is not supported")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise DomainError("CONTENT_TYPE", "Use application/json", 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise DomainError("INVALID_BODY", "Invalid content length") from None
        if not 0 < length <= MAX_BODY:
            raise DomainError("INVALID_BODY", "JSON body is missing or exceeds 128 KiB")
        data = self.rfile.read(length)
        if len(data) != length:
            raise DomainError("INVALID_BODY", "Incomplete request body")
        try:
            def no_constant(value):
                raise ValueError(value)
            def no_duplicates(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Duplicate object key")
                    result[key] = value
                return result
            result = json.loads(data, parse_constant=no_constant, object_pairs_hook=no_duplicates)
        except (ValueError, UnicodeError, RecursionError):
            raise DomainError("INVALID_JSON", "Malformed JSON request") from None
        if not isinstance(result, dict):
            raise DomainError("INVALID_REQUEST", "Request body must be an object")
        return result

    def _get(self, path, query):
        app = self.server.application
        if path == "/health":
            return app.health(), 200
        if path == "/v1/accounts":
            return app.accounts.list(first(query, "customerId")), 200
        if path == "/v1/journal":
            return app.ledger.journal(first(query, "after", 0), first(query, "limit", 500), first(query, "accountId")), 200
        if path == "/v1/postings/by-reference":
            return app.ledger.by_reference(first(query, "reference")), 200
        if path == "/v1/admin/reconciliation":
            return app.reconciliation.run(), 200
        if path == "/v1/admin/days":
            return app.daybook.list(), 200
        if path == "/v1/admin/batch-runs":
            return app.clearing.list_runs(), 200
        if path == "/v1/aliases/resolve":
            return app.accounts.resolve(first(query, "alias"), first(query, "channel", "OFFICE")), 200
        matched = re.fullmatch(r"/v1/accounts/([^/]+)(?:/(holds|accruals|statement))?", path)
        if matched:
            account_id, subresource = matched.groups()
            if subresource == "holds":
                return app.holds.list(account_id), 200
            if subresource == "accruals":
                return app.interest.list(account_id), 200
            if subresource == "statement":
                return app.statements.generate(account_id, first(query, "from"), first(query, "to")), 200
            return app.accounts.get(account_id), 200
        matched = re.fullmatch(r"/v1/(postings|holds)/([^/]+)", path)
        if matched:
            resource, key = matched.groups()
            return (app.ledger.get(key) if resource == "postings" else app.holds.get(key)), 200
        matched = re.fullmatch(r"/v1/admin/days/([^/]+)/snapshot", path)
        if matched:
            return app.daybook.snapshot(matched.group(1)), 200
        raise Missing("Endpoint")

    def _post(self, path, body):
        app = self.server.application
        if path == "/v1/postings":
            response, replay = app.ledger.post(body)
            return response, 200 if replay else 201
        if path == "/v1/holds":
            response, replay = app.holds.create(body)
            return response, 200 if replay else 201
        if path == "/v1/accounts":
            return app.accounts.open(body), 201
        if path == "/v1/admin/holds/expire":
            return app.holds.expire(), 200
        if path == "/v1/admin/days/open":
            return app.daybook.open(body.get("businessDate")), 200
        if path == "/v1/admin/days/close":
            return app.daybook.close(body.get("businessDate")), 200
        if path == "/v1/admin/interest/accrue":
            return app.interest.accrue(body.get("businessDate")), 200
        if path == "/v1/admin/interest/settle":
            return app.interest.settle(body.get("throughDate")), 200
        matched = re.fullmatch(r"/v1/accounts/([^/]+)/(restrictions|liens)", path)
        if matched:
            account_id, operation = matched.groups()
            if operation == "restrictions":
                return app.accounts.restrict(account_id, body), 200
            return app.accounts.add_lien(account_id, body), 201
        matched = re.fullmatch(r"/v1/liens/([^/]+)/release", path)
        if matched:
            return app.accounts.release_lien(matched.group(1)), 200
        matched = re.fullmatch(r"/v1/postings/([^/]+)/reverse", path)
        if matched:
            response, replay = app.ledger.reverse(matched.group(1), body)
            return response, 200 if replay else 201
        matched = re.fullmatch(r"/v1/holds/([^/]+)/(capture|release)", path)
        if matched:
            hold_id, operation = matched.groups()
            if operation == "release":
                return app.holds.release(hold_id), 200
            response, replay = app.holds.capture(hold_id, body)
            return response, 200 if replay else 201
        raise Missing("Endpoint")

    def _respond(self, response, status, request_id):
        payload = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Request-Id", request_id)
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, template, *args):
        LOG.info("%s %s", self.client_address[0], template % args)
