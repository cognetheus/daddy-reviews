"""R8.04b local model challenge wire protocol."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from daddy_reviews.agents import AgentRuntimeError
from daddy_reviews.independent_challenge import local_challenge_provider


def test_dedicated_ollama_challenge_provider_and_no_redirect():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            requests.append(body)
            if body["model"] == "redirect":
                self.send_response(302)
                self.send_header("Location", "https://example.invalid/leak")
                self.end_headers()
                return
            reply = json.dumps({
                "message": {"content": json.dumps({
                    "kind": "final", "verdict": "uncertain",
                    "reason": "Need concrete counterexample", "citations": ["E1"]})}
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        provider = local_challenge_provider("challenge-test", base, 3)
        turn = provider("code-quality", [{"role": "user", "content": "hypothesis"}])
        assert turn["verdict"] == "uncertain"
        assert "counterexample" in requests[0]["messages"][0]["content"]
        assert "source citation" in requests[0]["messages"][0]["content"]
        assert requests[0]["format"] == "json" and requests[0]["stream"] is False
        with pytest.raises(AgentRuntimeError):
            local_challenge_provider("redirect", base, 3)(
                "code-quality", [{"role": "user", "content": "secret"}])
        with pytest.raises(AgentRuntimeError):
            local_challenge_provider("test", "https://example.invalid", 3)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
