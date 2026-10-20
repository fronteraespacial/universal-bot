"""Cuota de grok sin gastar: abre la TUI de grok en un tmux aparte, escribe `/usage` (modal local, sin llamada al
modelo), lee "Weekly limit" y escribe un archivo de cuota fuera del repo para el selector del MAIN y del lab.

Por qué: `cli_quota grok_cli` usa el access token guardado en el auth del CLI sin refrescarlo; cuando vence (cada
~6 h) da HTTP 401 hasta que el CLI vuelve a arrancar. La TUI refresca el token al iniciar y su `/usage` muestra el
porcentaje usado del límite semanal.

Uso (cron, cada 15–30 min): python -m universal_bot.code_mode.grok_quota --out <archivo>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

_PLAN = re.compile(r"Weekly limit\s*\(([^)]+)\)")
_PCT = re.compile(r"[█░▏▎▍▌▋▊▉ ]+\s(\d{1,3})%")
_RESETS = re.compile(r"Resets:\s*([^│]+?)\s*(?:│|$)", re.M)


def parse_usage_screen(text: str) -> dict | None:
    plan = _PLAN.search(text or "")
    if not plan:
        return None
    tail = text[plan.end():]
    pct = _PCT.search(tail)
    if not pct:
        return None
    used = int(pct.group(1)) / 100
    resets = _RESETS.search(tail)
    return {"used": round(used, 2), "grok_remaining": round(1 - used, 2), "plan": plan.group(1).strip(),
            "resets": resets.group(1).strip() if resets else None}


def write_quota_file(out, usage: dict, *, now: float | None = None) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = {**usage, "as_of": time.time() if now is None else now, "source": "grok /usage"}
    fd, tmp = tempfile.mkstemp(dir=out.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(tmp, out)
    return out


def probe_grok_usage(argv, *, out, cwd, timeout_s: float = 40.0, settle_s: float = 1.0) -> dict | None:
    """Una TUI de grok en un tmux propio: espera la caja `❯`, manda `/usage`, lee el modal, cierra todo."""
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    sock = f"ub-grokq-{os.getpid()}-{uuid.uuid4().hex[:6]}"

    def tmux(*args):
        return subprocess.run(["tmux", "-L", sock, *args], capture_output=True, text=True, check=False).stdout

    deadline = time.monotonic() + timeout_s
    usage = None
    tmux("new-session", "-d", "-s", "q", "-x", "200", "-y", "50", "-c", str(cwd), " ".join(shlex.quote(a) for a in argv))
    try:
        while time.monotonic() < deadline and "❯" not in tmux("capture-pane", "-p", "-t", "q"):
            time.sleep(0.2)
        if time.monotonic() >= deadline:
            return None
        time.sleep(settle_s)
        tmux("send-keys", "-t", "q", "-l", "/usage")
        time.sleep(0.3)
        tmux("send-keys", "-t", "q", "Enter")
        while time.monotonic() < deadline:
            usage = parse_usage_screen(tmux("capture-pane", "-p", "-t", "q"))
            if usage:
                break
            time.sleep(0.3)
        tmux("send-keys", "-t", "q", "Escape")
    finally:
        tmux("kill-server")
        base = os.environ.get("TMUX_TMPDIR") or "/tmp"
        (Path(base) / f"tmux-{os.getuid()}" / sock).unlink(missing_ok=True)
    if usage:
        write_quota_file(out, usage)
    return usage


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Escribe la cuota de grok (de /usage) en un archivo JSON")
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=float, default=40.0)
    args = parser.parse_args(argv)
    work = Path(tempfile.mkdtemp(prefix="ub-grokq-"))
    usage = probe_grok_usage(["grok", "--cwd", str(work)], out=args.out, cwd=work, timeout_s=args.timeout)
    print(json.dumps(usage or {"error": "sin dato"}, ensure_ascii=False))
    return 0 if usage else 1


if __name__ == "__main__":
    raise SystemExit(main())
