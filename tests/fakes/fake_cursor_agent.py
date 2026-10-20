#!/usr/bin/env python3
"""Fake de `cursor-agent -p ... <prompt>`: contesta la última línea; con LONG tarda."""
import json, os, sys, time

prompt = sys.argv[-1]
log = os.environ.get("FAKE_CA_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": sys.argv[1:-1], "prompt": prompt}) + "\n")
if "LONG" in prompt.splitlines()[-1]:
    time.sleep(5)
print(f"Respuesta a: {prompt.strip().splitlines()[-1]}\nACCION: {{\"tipo\": \"ninguna\"}}", flush=True)
