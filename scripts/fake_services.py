"""Stand-ins for Google Sheets, Slack, Gmail and an SMS bridge, used to run the
n8n workflows end to end on a laptop. Everything is kept in memory and every
request is recorded so a test can assert on what the workflow tried to do.

    python scripts/fake_services.py        # listens on 127.0.0.1:18770
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
TABLE: dict[str, dict] = {}
CALLS: list[dict] = []


def record(kind: str, body):
    with LOCK:
        CALLS.append({"kind": kind, "body": body})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output quiet
        pass

    def _json(self, obj, status=200):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/calls":
            with LOCK:
                return self._json(CALLS)
        if self.path == "/table":
            with LOCK:
                return self._json(TABLE)
        if self.path == "/sheets/all":
            with LOCK:
                return self._json(list(TABLE.values()))
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n).decode() if n else ""
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"_raw": raw}
        path = self.path

        if path == "/reset":
            with LOCK:
                TABLE.clear()
                CALLS.clear()
            return self._json({"ok": True})
        if path == "/sheets/seed":
            with LOCK:
                for row in body["rows"]:
                    TABLE[row["ticket_id"]] = row
            return self._json({"ok": True, "rows": len(TABLE)})
        if path == "/sheets/append":
            with LOCK:
                TABLE[body["ticket_id"]] = {k: v for k, v in body.items() if k != "triage"}
            record("sheets.append", body["ticket_id"])
            return self._json(body)
        if path == "/sheets/lookup":
            with LOCK:
                row = TABLE.get(body.get("ticket_id"), {})
            return self._json(row)
        if path == "/sheets/update":
            with LOCK:
                TABLE.setdefault(body["ticket_id"], {}).update(body)
            record("sheets.update", body)
            return self._json({"ok": True})
        if path in ("/slack/chat.postMessage", "/slack/views.open", "/slack/response", "/gmail/labels", "/gmail/reply", "/sms"):
            record(path.lstrip("/"), body)
            return self._json({"ok": True, "ts": "1.0"})
        self._json({"error": "not found"}, 404)


def serve(port=18770):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18770
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"fake services on :{port}")
    srv.serve_forever()
