#!/usr/bin/env python3
"""Fake de la TUI de grok: caja de entrada '❯'; `/usage` abre el modal con el límite semanal (sin llamar al modelo)."""
import os, sys
from pathlib import Path
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "grok_usage_modal.txt"
log = os.environ.get("FAKE_GROK_LOG")
def box():
    sys.stdout.write("  ╭────────────╮\n  │ ❯          │\n  ╰────────────╯\n"); sys.stdout.flush()
sys.stdout.write("Grok Build (fake)\n"); box()
for line in sys.stdin:
    text = line.strip()
    if log:
        open(log, "a").write(text + "\n")
    if text == "/usage":
        sys.stdout.write(FIXTURE.read_text(encoding="utf-8") + "\n"); sys.stdout.flush()
    elif text:
        sys.stdout.write("MODEL CALL\n"); box()
