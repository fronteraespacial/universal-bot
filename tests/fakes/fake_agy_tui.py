#!/usr/bin/env python3
"""Fake de la TUI interactiva de agy: prompt '>', delega lo LONG en un subagente y queda libre; los mensajes
que llegan con el subagente vivo se le reenvían ('Messaged 1 subagent')."""
import sys, threading, time

state = {"sub": None, "steers": []}
lock = threading.Lock()


def say(text):
    with lock:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()


def prompt():
    with lock:
        sys.stdout.write("> ")
        sys.stdout.flush()


def subagent(task):
    for _ in range(30):
        time.sleep(0.1)
        if state["steers"]:
            break
    say(f"subagente terminó: {task}" + (f" steered:{'|'.join(state['steers'])}" if state["steers"] else ""))
    state["sub"] = None
    prompt()


say("Antigravity CLI (fake)")
prompt()
for line in sys.stdin:
    text = line.strip()
    if not text:
        prompt(); continue
    if state["sub"] is not None:
        state["steers"].append(text)
        say(f"● Messaged 1 subagent: {text}")
        prompt(); continue
    if "LONG" in text:
        state["sub"] = threading.Thread(target=subagent, args=(text,), daemon=True)
        state["sub"].start()
        say("Spawned 1 subagent")
        prompt(); continue
    time.sleep(0.3)
    say(f"Respuesta a: {text}")
    prompt()
