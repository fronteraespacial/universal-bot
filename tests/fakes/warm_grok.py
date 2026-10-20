"""Fake de `grok agent stdio` (ACP): session/prompt encolado, sin steer; session/cancel corta."""
import json, os, sys, threading, time

lock = threading.Lock()
state = {"cancel": False, "interject": None}


def out(msg):
    msg["jsonrpc"] = "2.0"
    with lock:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


def chunk(sid, text):
    out({"method": "session/update", "params": {"sessionId": sid, "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}}})


def run(mid, sid, text):
    if "LONG" in text:
        for n in range(1, 400):
            if state["cancel"]:
                out({"id": mid, "result": {"stopReason": "cancelled"}})
                return
            if state["interject"]:
                text = state["interject"]
                break
            chunk(sid, f"{n} ")
            time.sleep(0.02)
    chunk(sid, "STEERED" if "CAMBIO DE INSTRUCCIÓN" in text else "OK")
    out({"id": mid, "result": {"stopReason": "end_turn", "_meta": {"usage": {"inputTokens": 10, "outputTokens": 1}}}})


for line in sys.stdin:
    msg = json.loads(line)
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method == "initialize":
        out({"id": mid, "result": {"protocolVersion": 1, "authMethods": [{"id": "cached_token"}]}})
    elif method == "session/new":
        out({"id": mid, "result": {"sessionId": "s-1"}})
    elif method == "session/prompt":
        if os.environ.get("FAKE_DIE_ON_TURN"):
            sys.exit(3)
        state["cancel"] = False
        state["interject"] = None
        text = params["prompt"][0]["text"]
        threading.Thread(target=run, args=(mid, params["sessionId"], text), daemon=True).start()
    elif method == "_x.ai/interject" and not os.environ.get("FAKE_GROK_NO_INTERJECT"):
        if "sessionId" not in params or "text" not in params:
            out({"id": mid, "error": {"code": -32602, "message": "missing field"}})
            continue
        state["interject"] = "CAMBIO DE INSTRUCCIÓN: " + params["text"]
        out({"id": mid, "result": {"result": {"status": "queued"}}})
    elif method == "session/cancel":
        state["cancel"] = True
    elif mid is not None:
        out({"id": mid, "error": {"code": -32601, "message": "Method not found"}})
