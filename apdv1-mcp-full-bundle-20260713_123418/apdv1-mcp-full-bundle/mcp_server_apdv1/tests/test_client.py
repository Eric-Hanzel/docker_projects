import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from apdv1_mcp_server.client import Apdv1ApiClient
from apdv1_mcp_server.config import Config


class Handler(BaseHTTPRequestHandler):
    last_payload = None

    def do_GET(self):
        if self.path.startswith("/healthz"):
            self._json({"ok": True})
            return
        if self.path.startswith("/status"):
            self._json({"ok": True, "queue_counts": {"pending": 0}})
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size:
            Handler.last_payload = json.loads(self.rfile.read(size).decode("utf-8"))
        if self.path == "/deploy":
            self._json({"ok": True, "request_ids": ["req-test"], "queue_counts": {"pending": 1}})
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        return

    def _json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.client = Apdv1ApiClient(Config(api_base=f"http://{host}:{port}"))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_health(self):
        self.assertEqual(self.client.health()["ok"], True)

    def test_deploy(self):
        self.assertEqual(
            self.client.deploy("https://example.com", {"license_key": "secret"})["request_ids"],
            ["req-test"],
        )
        self.assertEqual(
            Handler.last_payload,
            {"url": "https://example.com", "extras": {"license_key": "secret"}, "source": "mcp"},
        )


if __name__ == "__main__":
    unittest.main()
