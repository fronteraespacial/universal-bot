"""Humo real del modo warm: arranque, dos 'OK' y un steer a mitad de turno. Uso:
    python scripts/warm_smoke.py --cli grok --model grok-4.7 --effort low --workdir <dir temporal>
Imprime una línea JSON con latencias. No imprime credenciales."""

import argparse
import json
import threading
import time
from pathlib import Path

from universal_bot.code_mode.warm import CAPABILITIES, WarmError, make_session

COUNT = (
    "Contá del 1 al 200. Por CADA número ejecutá un comando shell separado: echo N >> {f} "
    "(una llamada a herramienta por número, nunca en lote ni loop). No pares hasta 200."
)
STEER = "solo hasta 20. Si no llegaste a 20 seguí hasta 20; si ya pasaste, no escribas más números. Después ejecutá echo STEERED >> {f} y terminá."


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--steer-timeout", type=float, default=150)
    ap.add_argument("--no-steer", action="store_true")
    args = ap.parse_args()
    work = Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)
    out = {"cli": args.cli, "model": args.model, "capabilities": CAPABILITIES[args.cli].__dict__}
    session = make_session(args.cli, args.model, cwd=work, effort=args.effort)
    t0 = time.monotonic()
    try:
        session.start()
        out["start_ms"] = int((time.monotonic() - t0) * 1000)
        for n in (1, 2):
            r = session.prompt("Respondé solo OK", timeout_s=60)
            out[f"ok{n}"] = {"status": r.status, "text": r.text.strip()[:20], "first_ms": r.first_token_ms, "total_ms": r.duration_ms}
        if not args.no_steer:
            target = work / "count.txt"
            target.unlink(missing_ok=True)
            box = {}
            th = threading.Thread(target=lambda: box.setdefault("r", session.prompt(COUNT.format(f=target), timeout_s=args.steer_timeout)))
            ts = time.monotonic()
            th.start()
            lines = lambda: target.read_text().split() if target.exists() else []
            while time.monotonic() - ts < 90 and len(lines()) < 3 and th.is_alive():
                time.sleep(0.2)
            before = len(lines())
            sent_at = time.monotonic() - ts
            outcome = session.steer(STEER.format(f=target))
            th.join(args.steer_timeout + 10)
            r = box.get("r")
            final = lines()
            out["steer"] = {
                "sent_at_s": round(sent_at, 1), "lines_before": before, "outcome": outcome,
                "status": getattr(r, "status", None), "steered": getattr(r, "steered", None),
                "total_s": round((r.duration_ms if r else 0) / 1000, 1), "n_lines": len(final), "last": final[-3:],
                "steered_marker": "STEERED" in final,
            }
    except WarmError as exc:
        out["error"] = exc.code
    finally:
        session.close()
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
