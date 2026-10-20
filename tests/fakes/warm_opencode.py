"""Fake de `opencode serve` v2: basic auth, /api/session, prompt con delivery steer, interrupt y SSE."""
import base64, json, os, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PASSWORD = os.environ.get("OPENCODE_SERVER_PASSWORD") or "fake-printed-password"
PRINT_PASSWORD = not os.environ.get("OPENCODE_SERVER_PASSWORD") or os.environ.get("FAKE_IGNORE_ENV_PASSWORD")
if os.environ.get("FAKE_IGNORE_ENV_PASSWORD"):
    PASSWORD = "fake-printed-password"
events = []
cond = threading.Condition()
sessions = {}


def emit(kind, sid, **extra):
    with cond:
        events.append({"type": kind, "properties": {"sessionID": sid, **extra}})
        cond.notify_all()


def execute(sid, text):
    s = sessions[sid]
    emit("session.execution.started", sid)
    if "LONG" in text:
        for n in range(1, 400):
            if s["interrupt"]:
                emit("session.execution.failed", sid, error="interrupted")
                return
            if s["steer"]:
                emit("session.inbox.delivered", sid)
                text = s["steer"]
                break
            emit("session.text.delta", sid, delta=f"{n} ")
            time.sleep(0.02)
    answer = "STEERED" if "CAMBIO DE INSTRUCCIÓN" in text else "OK"
    emit("session.text.delta", sid, delta=answer)
    s["messages"].insert(0, {"type": "assistant", "content": [{"type": "text", "text": answer}]})
    emit("session.execution.succeeded", sid)


class H(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _auth(self):
        want = "Basic " + base64.b64encode(f"opencode:{PASSWORD}".encode()).decode()
        if self.headers.get("Authorization") != want:
            self.send_response(401); self.end_headers(); return False
        return True

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._auth():
            return
        if self.path == "/api/event":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            seen = len(events)
            while True:
                with cond:
                    cond.wait_for(lambda: len(events) > seen, timeout=1)
                    batch = events[seen:]
                    seen = len(events)
                try:
                    for e in batch:
                        self.wfile.write(f"data: {json.dumps(e)}\n\n".encode())
                    self.wfile.flush()
                except OSError:
                    return
        if self.path.startswith("/api/session/") and self.path.endswith("/message"):
            sid = self.path.split("/")[3]
            return self._json(200, {"data": sessions[sid]["messages"]})
        self._json(404, {})

    def do_POST(self):
        if not self._auth():
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        parts = self.path.split("/")
        if self.path == "/api/session":
            sid = "ses_" + uuid.uuid4().hex[:8]
            sessions[sid] = {"messages": [], "steer": None, "interrupt": False, "model": body.get("model")}
            return self._json(200, {"data": {"id": sid}})
        if len(parts) == 5 and parts[4] == "prompt":
            sid = parts[3]
            if body.get("delivery") == "steer":
                sessions[sid]["steer"] = body["text"]
                emit("session.inbox.enqueued", sid)
                return self._json(200, {"data": {"delivery": "steer"}})
            sessions[sid].update(steer=None, interrupt=False)
            threading.Thread(target=execute, args=(sid, body["text"]), daemon=True).start()
            return self._json(200, {"data": {"delivery": "queue"}})
        if len(parts) == 5 and parts[4] == "interrupt":
            sessions[parts[3]]["interrupt"] = True
            return self._json(200, {"data": True})
        self._json(404, {})


port = int(sys.argv[sys.argv.index("--port") + 1])
server = ThreadingHTTPServer(("127.0.0.1", port), H)
print(f"server listening on http://127.0.0.1:{port}", flush=True)
if PRINT_PASSWORD:
    print(f"server password {PASSWORD}", flush=True)
server.serve_forever()
