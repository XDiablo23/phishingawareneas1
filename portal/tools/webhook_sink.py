"""
Tiny local webhook sink for testing the ticket integration end-to-end.
Run it, point the portal's ticket webhook at http://127.0.0.1:8199/hook, and
GET http://127.0.0.1:8199/ to see how many tickets arrived (and the last one).
Returns 200 + a fake ticket id to any POST, mimicking a ticketing inbound hook.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

HITS = []


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("content-length", 0) or 0)
        body = self.rfile.read(n).decode("utf-8", "replace") if n else ""
        HITS.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true,"id":"TICKET-DEMO-1"}')

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(
            {"hits": len(HITS), "last": HITS[-1] if HITS else None}).encode())

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("webhook sink on http://127.0.0.1:8199 (POST /hook)")
    HTTPServer(("127.0.0.1", 8199), H).serve_forever()
