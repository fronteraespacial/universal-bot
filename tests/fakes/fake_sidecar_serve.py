#!/usr/bin/env python3
"""Fake del sidecar cursor-sdk en modo --serve (contrato v2): JSONL por stdin, una línea por evento con `id`."""
import json, os, sys, threading, time

log = os.environ.get("FAKE_SIDECAR_LOG")
mode = os.environ.get("FAKE_SIDECAR", "ok")
lock = threading.Lock()
runs = {}
turns = {}


def emit(obj):
    with lock:
        sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()


def record(entry):
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({**entry, "pid": os.getpid(), "argv": sys.argv[1:]}) + "\n")


def run(msg):
    rid, sid = msg["id"], msg.get("session_id")
    state = runs[rid]
    if mode == "rate":
        emit({"id": rid, "session_id": sid, "type": "error", "ok": False, "code": "USAGE_LIMIT", "message": "limit", "fallback": True, "exit_code": 8})
        return
    if "LONG" in msg["prompt"]:
        for _ in range(200):
            time.sleep(0.05)
            if state["cancel"]:
                emit({"id": rid, "session_id": sid, "type": "error", "ok": False, "code": "CANCELLED", "message": "cancelado", "fallback": False, "exit_code": 10})
                return
            if state["steers"]:
                break
    turns[sid] = turns.get(sid, 0) + 1
    last = msg["prompt"].strip().splitlines()[-1]
    text = f"Respuesta a: {last}" + (f" steered:{'|'.join(state['steers'])}" if state["steers"] else "")
    emit({"id": rid, "session_id": sid, "type": "result", "ok": True, "text": text + '\nACCION: {"tipo": "ninguna"}',
          "usage": {"inputTokens": 10, "outputTokens": 2, "cacheReadTokens": 5, "totalTokens": 17}, "duration_ms": 5,
          "agent_id": f"agent-{sid}", "turn": turns[sid], "model": msg.get("model")})


for line in sys.stdin:
    if not line.strip():
        continue
    msg = json.loads(line)
    record({"msg": msg})
    op = msg.get("op", "run")
    if op == "run":
        runs[msg["id"]] = {"steers": [], "cancel": False}
        threading.Thread(target=run, args=(msg,), daemon=True).start()
    elif op == "steer":
        state = runs.get(msg["target"])
        if state is not None:
            state["steers"].append(msg["text"])
        emit({"id": msg["id"], "target": msg["target"], "type": "steer", "ok": state is not None, "outcome": "complete_delivered"})
    elif op == "cancel":
        state = runs.get(msg["target"])
        if state is not None:
            state["cancel"] = True
        emit({"id": msg["id"], "type": "ack", "op": "cancel", "ok": state is not None})
    elif op == "shutdown":
        break
