"""Levanta, frena y consulta el runtime de modo código. No abre Discord."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def main(argv: list[str] | None = None) -> int | str:
    parser = argparse.ArgumentParser(prog="universal_bot.labcode_service")
    parser.add_argument("command", choices=("start", "stop", "status"))
    parser.add_argument("--spool", required=True)
    parser.add_argument("--db", default=None)
    parser.add_argument("--log", default=None)
    parser.add_argument("--pidfile", default=None)
    parser.add_argument("--interval", default="10")
    args = parser.parse_args(argv)
    root = _repo_root()
    spool = Path(args.spool)
    db = Path(args.db) if args.db else root / "state" / "labcode.sqlite"
    log = Path(args.log) if args.log else root / "state" / "labcode.log"
    pidfile = Path(args.pidfile) if args.pidfile else root / "state" / "labcode.pid"
    if args.command == "start":
        return _start(spool, db, log, pidfile, args.interval)
    if args.command == "stop":
        return _stop(pidfile)
    return _status(spool, pidfile)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _start(spool: Path, db: Path, log: Path, pidfile: Path, interval: str) -> int:
    if _alive(pidfile):
        return 0
    log.parent.mkdir(parents=True, exist_ok=True)
    db.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "universal_bot.labcode_runtime",
                "--spool",
                str(spool),
                "--db",
                str(db),
                "--interval",
                str(interval),
            ],
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        handle.close()
    pidfile.write_text(str(proc.pid), encoding="utf-8")
    return 0


def _stop(pidfile: Path) -> int:
    pid = _pid(pidfile)
    if pid is None:
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pidfile.unlink(missing_ok=True)
        return 0
    deadline = time.time() + 5
    while time.time() < deadline and _running(pid):
        time.sleep(0.05)
    if _running(pid):
        os.kill(pid, signal.SIGKILL)
    pidfile.unlink(missing_ok=True)
    return 0


def _status(spool: Path, pidfile: Path) -> str:
    if not _alive(pidfile):
        return "detenido"
    age = _heartbeat_age(spool)
    if age is None:
        return "activo edad=ausente"
    return f"activo edad={age:.0f}s"


def _heartbeat_age(spool: Path) -> float | None:
    path = spool / "runtime.heartbeat"
    if not path.is_file():
        return None
    stamped = datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamped).total_seconds()


def _pid(pidfile: Path) -> int | None:
    if not pidfile.is_file():
        return None
    text = pidfile.read_text(encoding="utf-8").strip()
    if not text.isdigit():
        return None
    return int(text)


def _alive(pidfile: Path) -> bool:
    pid = _pid(pidfile)
    return pid is not None and _running(pid)


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


if __name__ == "__main__":
    result = main()
    if isinstance(result, str):
        print(result)
        raise SystemExit(0)
    raise SystemExit(result)
