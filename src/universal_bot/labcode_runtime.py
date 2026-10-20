"""Runtime de modo código contra el spool del puente. No abre Discord."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from universal_bot.code_mode.answers import consume_answers
from universal_bot.code_mode.ask_bridge import AskBridge
from universal_bot.code_mode.clock import SystemClock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.file_outbox import FileOutboxDiscordPort
from universal_bot.code_mode.heartbeat import touch_heartbeat
from universal_bot.code_mode.inbox_job import load_inbox_job
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.store import JobStore

_PROCESSED = {"accepted", "done", "paused", "error", "running"}


def run_once(spool: Path, *, db_path: Path, clock, on_job=None, role_lookup=None, lab_runner=None, config=None) -> dict:
    root = Path(spool)
    for name in ("inbox", "outbox", "answers"):
        (root / name).mkdir(parents=True, exist_ok=True)
    touch_heartbeat(root, clock)
    ledger = ProjectLedger(db_path, clock)
    bridge = AskBridge(
        db_path,
        JobStore(db_path),
        _port(root, clock),
        clock,
        ledger,
        CodeModeConfig(),
    )
    clicks = consume_answers(
        root,
        clock=clock,
        ask_bridge=bridge,
        projects=ledger,
        role_lookup=role_lookup,
    )
    processed, skipped = _consume_inbox(root, clock, on_job)
    return {"processed": processed, "skipped": skipped, "answers": len(clicks)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="universal_bot.labcode_runtime")
    parser.add_argument("--spool", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--db", default=None)
    parser.add_argument("--interval", type=float, default=10)
    args = parser.parse_args(argv)
    spool = Path(args.spool)
    db_path = Path(args.db) if args.db else spool / "runtime.sqlite"
    if args.once:
        run_once(spool, db_path=db_path, clock=SystemClock())
        return 0
    while True:
        run_once(spool, db_path=db_path, clock=SystemClock())
        time.sleep(min(max(args.interval, 1.0), 20.0))


def _port(spool: Path, clock) -> FileOutboxDiscordPort:
    def sleeper(_seconds: float) -> None:
        raise RuntimeError("run_once no espera operaciones del puente")

    return FileOutboxDiscordPort(spool, clock=clock, sleeper=sleeper, timeout_s=0)


def _consume_inbox(spool: Path, clock, on_job) -> tuple[int, int]:
    processed = 0
    skipped = 0
    for job_json in sorted((spool / "inbox").glob("*/job.json")):
        job_dir = job_json.parent
        state = _read_state(job_dir)
        if state.get("status") in _PROCESSED:
            skipped += 1
            continue
        job = load_inbox_job(job_dir)
        if on_job is not None:
            on_job(job)
        _mark_done(job_dir, job, clock, state)
        processed += 1
    return processed, skipped


def _read_state(job_dir: Path) -> dict:
    path = job_dir / "state.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _mark_done(job_dir: Path, job, clock, state: dict) -> None:
    state.update(
        {
            "version": 1,
            "status": "done",
            "updated_ts": clock.now().timestamp(),
            "summary": job.prompt[:180],
            "active_step": state.get("active_step"),
            "error": None,
            "op_ids": list(state.get("op_ids") or []),
            "location_key": job.location_key,
            "session_key": job.session_key,
        }
    )
    (job_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
