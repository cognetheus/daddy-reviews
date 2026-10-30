"""Local-only HTTP adapter contract, no external inference service required."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest

from daddy_reviews.agents import AgentRuntimeError, local_ollama_provider


def test_ollama_wire_protocol_and_redirect_rejection():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size))
            requests.append((self.path, body))
            if body["model"] == "redirect":
                self.send_response(302)
                self.send_header("Location", "https://example.com")
                self.end_headers()
                return
            payload = json.dumps({
                "message": {"content": json.dumps({"findings": []})}
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    runner = threading.Thread(target=server.serve_forever, daemon=True)
    runner.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        provider = local_ollama_provider("test-model", base_url=base, timeout=3)
        assert provider("code-quality", "untrusted patch text") == {"findings": []}
        assert requests[0][0] == "/api/chat"
        assert requests[0][1]["stream"] is False
        assert requests[0][1]["format"] == "json"
        assert requests[0][1]["messages"][1]["role"] == "user"
        with pytest.raises(AgentRuntimeError):
            local_ollama_provider("redirect", base_url=base, timeout=3)("code-quality", "x")
    finally:
        server.shutdown()
        server.server_close()
        runner.join(timeout=2)
