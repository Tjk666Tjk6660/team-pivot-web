"""CLI test fixtures: mock RPC server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


@pytest.fixture
def mock_rpc_server():
    """Local HTTP server simulating EC's RPC endpoint.

    Yields dict with:
      - url: "http://127.0.0.1:<port>"
      - received: list of captured requests [{body, auth, path}]
    """
    received = []
    response_data = [{"result": {"status": "ok"}}]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            auth = self.headers.get("Authorization", "")
            received.append({"body": body, "auth": auth, "path": self.path})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_data[0]).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield {
            "url": url,
            "received": received,
            "set_response": lambda data: response_data.__setitem__(0, data),
        }
    finally:
        server.shutdown()
        server.server_close()
