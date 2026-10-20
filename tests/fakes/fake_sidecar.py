#!/usr/bin/env python3
"""Fake del sidecar cursor-sdk (contrato v1): request JSON por stdin, JSONL por stdout."""
import json, os, sys, time
from pathlib import Path

req = json.loads(sys.stdin.read())
log = os.environ.get("FAKE_SIDECAR_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"request": req, "argv": sys.argv[1:]}) + "\n")
mode = os.environ.get("FAKE_SIDECAR", "ok")
cwd = Path(req.get("cwd") or ".")


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()


if mode == "rate":
    emit({"type": "error", "ok": False, "code": "USAGE_LIMIT", "message": "limit", "fallback": True, "exit_code": 8}); sys.exit(8)
steers = []
if mode == "slow" or "LONG" in req["prompt"]:
    steer_file = cwd / req["steer_file"] if req.get("steer_file") else None
    cancel_file = cwd / req["cancel_file"] if req.get("cancel_file") else None
    seen = 0
    for _ in range(200):
        time.sleep(0.05)
        if cancel_file and cancel_file.exists():
            emit({"type": "error", "ok": False, "code": "CANCELLED", "message": "cancelado", "fallback": False, "exit_code": 10}); sys.exit(10)
        if steer_file and steer_file.exists():
            lines = steer_file.read_text(encoding="utf-8").splitlines()
            for line in lines[seen:]:
                steers.append(json.loads(line)["text"])
                emit({"type": "steer", "ok": True, "outcome": "complete_delivered", "text_len": len(line)})
            seen = len(lines)
            if steers:
                break
last = req["prompt"].strip().splitlines()[-1]
text = f"Respuesta a: {last}" + (f" steered:{'|'.join(steers)}" if steers else "")
emit({"type": "result", "ok": True, "text": text + '\nACCION: {"tipo": "ninguna"}', "usage": {}, "duration_ms": 5, "run_id": "run-fake", "model": req.get("model")})
