"""Fake de `agy --input-format stream-json`: multi-turno, sin steer; SIGINT corta el turno."""
import json, os, signal, sys, time

state = {"int": False}


def on_int(signum, frame):
    if os.environ.get("FAKE_AGY_DIE_ON_SIGINT"):
        os._exit(130)
    state["int"] = True


signal.signal(signal.SIGINT, on_int)


def out(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def delta(text):
    out({"step_update": {"step_type": "agent_response", "text_delta": text}})


for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("event") != "user":
        continue
    if os.environ.get("FAKE_DIE_ON_TURN"):
        sys.exit(3)
    text = msg["message"]["content"]
    state["int"] = False
    if "LONG" in text:
        status = "SUCCESS"
        for n in range(1, 400):
            if state["int"]:
                status = "INTERRUPTED"
                break
            delta(f"{n} ")
            time.sleep(0.02)
        if status == "INTERRUPTED":
            out({"event": "result", "result": {"status": "ERROR", "error": "interrupted", "response": ""}})  # forma real de agy 1.4.3
            continue
    answer = "STEERED" if "CAMBIO DE INSTRUCCIÓN" in text else "OK"
    delta(answer)
    out({"event": "result", "result": {"status": "SUCCESS", "response": answer}})
