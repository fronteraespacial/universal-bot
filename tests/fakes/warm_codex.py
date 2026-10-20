"""Fake de `codex app-server`: JSON-RPC por stdio con turn/steer y turn/interrupt."""
import json, os, sys, threading, time

lock = threading.Lock()
state = {"turn": None, "steer": None, "stop": False}


def out(msg):
    with lock:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


def delta(text):
    out({"method": "item/agentMessage/delta", "params": {"delta": text}})


def run_turn(turn_id, text):
    out({"method": "turn/started", "params": {"turn": {"id": turn_id}}})
    if "LONG" not in text:
        delta("O"); delta("K")
        out({"method": "turn/completed", "params": {"turn": {"id": turn_id, "status": "completed"}}})
        return
    for n in range(1, 400):
        if state["stop"]:
            out({"method": "turn/completed", "params": {"turn": {"id": turn_id, "status": "interrupted"}}})
            return
        if state["steer"]:
            delta(" STEERED")
            out({"method": "turn/completed", "params": {"turn": {"id": turn_id, "status": "completed"}}})
            return
        delta(f"{n} ")
        time.sleep(0.02)


for line in sys.stdin:
    msg = json.loads(line)
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method == "initialize":
        out({"id": mid, "result": {"userAgent": "fake"}})
    elif method == "thread/start":
        out({"id": mid, "result": {"thread": {"id": "th-1"}}})
    elif method == "turn/start":
        if os.environ.get("FAKE_DIE_ON_TURN"):
            sys.exit(3)
        state.update(turn="tu-1", steer=None, stop=False)
        out({"id": mid, "result": {"turn": {"id": "tu-1"}}})
        text = params["input"][0]["text"]
        threading.Thread(target=run_turn, args=("tu-1", text), daemon=True).start()
    elif method == "turn/steer":
        if params.get("expectedTurnId") != state["turn"]:
            out({"id": mid, "error": {"code": -32600, "message": "no active turn"}})
            continue
        state["steer"] = params["input"][0]["text"]
        out({"id": mid, "result": {"turnId": state["turn"]}})
    elif method == "turn/interrupt":
        state["stop"] = True
        out({"id": mid, "result": {}})
    elif mid is not None:
        out({"id": mid, "error": {"code": -32601, "message": "Method not found"}})
