#!/usr/bin/env python3
"""Fake de la TUI real de agy en modo crudo (cbreak): aviso de Verbosity que se cierra con Esc, caja `>` entre
separadores, Enter manda (en `Queue` se encola si hay un turno), alt+m manda ya (Send Immediately)."""
import os, select, sys, termios, threading, time, tty

LOG = os.environ.get("FAKE_AGY_LOG")
BAR = "─" * 60
lock = threading.Lock()
state = {"busy": False, "notice": True, "steers": [], "queued": []}


def log(text):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def out(text):
    with lock:
        sys.stdout.write(text.replace("\n", "\r\n")); sys.stdout.flush()


def box():
    out(f"{BAR}\n>\n{BAR}\n? for shortcuts                Gemini 3.8 Flash · low\n")


def turn(text):
    state["busy"] = True
    if "LONG" in text:
        for _ in range(60):
            time.sleep(0.05)
            if state["steers"]:
                break
    else:
        time.sleep(0.3)
    reply = f"Respuesta a: {text}" + (f" steered:{'|'.join(state['steers'])}" if state["steers"] else "")
    state["steers"].clear()
    out(reply + "\n")
    state["busy"] = False
    box()


def deliver(text, immediate):
    log(("IMMEDIATE:" if immediate else "ENTER:") + text)
    if state["busy"]:
        if immediate:
            state["steers"].append(text); out(f"● steer: {text}\n")
        else:
            state["queued"].append(text); out(f"(en cola) {text}\n")
        return
    threading.Thread(target=turn, args=(text,), daemon=True).start()


fd = sys.stdin.fileno()
old = termios.tcgetattr(fd)
tty.setcbreak(fd)
try:
    out("Antigravity CLI (fake raw)\n")
    out("┃ Verbosity now defaults to medium\n┃ esc to dismiss\n")
    box()
    buf = ""
    while True:
        ch = os.read(fd, 1).decode("utf-8", "ignore")
        if ch == "\x1b":
            ready, _, _ = select.select([fd], [], [], 0.05)
            nxt = os.read(fd, 1).decode() if ready else ""
            if nxt == "m":
                deliver(buf, True); buf = ""
            else:
                if state["notice"]:
                    state["notice"] = False; log("ESC"); out("(aviso cerrado)\n")
                buf += nxt
            continue
        if ch in ("\r", "\n"):
            text, buf = buf, ""
            if text:
                deliver(text, False)
            continue
        buf += ch
        out(ch)
        if ch == " " and False:
            pass
finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
