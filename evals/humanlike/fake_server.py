"""A local OpenAI-compatible endpoint for dry runs of the eval (``--fake``): no key, no network.

It streams a fixed two-line reply that echoes the last user message, and answers
non-streaming requests (memory extraction, appraisal) with an empty JSON list. It
checks that the driver, timing, and report work; it says nothing about the model.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIRST_CONTENT_DELAY = 0.3


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802 (http.server naming)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        users = [m["content"] for m in body.get("messages", []) if m.get("role") == "user"]
        if not body.get("stream"):
            out = json.dumps({"choices": [{"message": {"content": "[]"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        time.sleep(FIRST_CONTENT_DELAY)
        last = users[-1] if users else ""
        reply = f"[neutral] 收到：{last[:8]}\n嗯"
        for piece in (reply[:6], reply[6:]):
            chunk = {"choices": [{"delta": {"content": piece}}]}
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def start() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"
