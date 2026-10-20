"""Runtime de modo código contra el spool del puente. No abre Discord."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from universal_bot.code_mode.answers import consume_answers
from universal_bot.code_mode.app import CodeModeApp
from universal_bot.code_mode.ask_bridge import AskBridge
from universal_bot.code_mode.clock import SystemClock
from universal_bot.code_mode.config import CodeModeConfig, load_runtime_config
from universal_bot.code_mode.file_outbox import FileOutboxDiscordPort
from universal_bot.code_mode.heartbeat import touch_heartbeat
from universal_bot.code_mode.inbox_flow import apply_clicks
from universal_bot.code_mode.inbox_job import load_inbox_job
from universal_bot.store import JobStore

_PROCESSED = {"accepted", "done", "paused", "error", "running", "waiting_human", "skipped"}


def run_once(spool: Path, *, db_path: Path, clock, on_job=None, role_lookup=None, lab_runner=None, config=None, sleeper=None) -> dict:
    root = Path(spool)
    for name in ("inbox", "outbox", "answers"):
        (root / name).mkdir(parents=True, exist_ok=True)
    touch_heartbeat(root, clock)
    chosen = config or CodeModeConfig()
    port = _port(root, clock)
    app = CodeModeApp(db_path, port, clock, chosen, lab_runner=lab_runner)
    bridge = AskBridge(db_path, JobStore(db_path), port, clock, app.ledger, chosen)
    app.ask_bridge = bridge
    app.stages.flush_pending()
    bridge.tick()
    app.sessions.tick()
    clicks = consume_answers(
        root,
        clock=clock,
        ask_bridge=bridge,
        projects=app.ledger,
        role_lookup=role_lookup,
    )
    apply_clicks(app, root, clicks)
    processed, skipped = _consume_inbox(root, clock, on_job, app)
    return {"processed": processed, "skipped": skipped, "answers": len(clicks)}


def build_lab_runner(clock, *, lab_root, routing_policy, lab_timeout, maverick_timeout, max_labs, allow_network=False):
    from universal_bot.code_mode import lab_runner

    root = Path(lab_root) if lab_root else Path(os.environ.get("UBLAB_LAB_ROOT") or "/tmp/ub-labcode")
    if routing_policy:
        policy = Path(routing_policy)
    else:
        raw = os.environ.get("UBLAB_ROUTING_POLICY", "")
        policy = Path(raw) if raw else Path()
    timeout = 900.0 if lab_timeout is None else float(lab_timeout)
    maverick = 300.0 if maverick_timeout is None else float(maverick_timeout)
    if max_labs is None:
        cap_t2, cap_t3 = 2, 3
    else:
        cap_t2 = cap_t3 = int(max_labs)
    return lab_runner.LabRunner(
        clock=clock,
        lab_root=root,
        routing_policy=policy,
        timeout_s=timeout,
        maverick_timeout_s=maverick,
        max_labs_t2=cap_t2,
        max_labs_t3=cap_t3,
        allow_network=bool(allow_network),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="universal_bot.labcode_runtime")
    parser.add_argument("--spool", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--db", default=None)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--lab-root", default=None)
    parser.add_argument("--routing-policy", default=None)
    parser.add_argument("--lab-timeout", default=None)
    parser.add_argument("--maverick-timeout", default=None)
    parser.add_argument("--max-labs", default=None)
    parser.add_argument("--lab-allow-network", action="store_true")
    args = parser.parse_args(argv)
    spool = Path(args.spool)
    db_path = Path(args.db) if args.db else spool / "runtime.sqlite"
    clock = SystemClock()
    config = load_runtime_config()
    runner = build_lab_runner(
        clock,
        lab_root=args.lab_root or config.lab_root or None,
        routing_policy=args.routing_policy or config.routing_policy or None,
        lab_timeout=args.lab_timeout,
        maverick_timeout=args.maverick_timeout,
        max_labs=args.max_labs,
        allow_network=args.lab_allow_network or config.allow_network,
    )
    if args.once:
        run_once(spool, db_path=db_path, clock=clock, lab_runner=runner, config=config)
        return 0
    while True:
        run_once(spool, db_path=db_path, clock=SystemClock(), lab_runner=runner, config=config)
        time.sleep(min(max(args.interval, 1.0), 20.0))


def _port(spool: Path, clock) -> FileOutboxDiscordPort:
    def sleeper(_seconds: float) -> None:
        raise RuntimeError("run_once no espera operaciones del puente")

    return FileOutboxDiscordPort(spool, clock=clock, sleeper=sleeper, timeout_s=0, defer_results=True)


def _consume_inbox(spool: Path, clock, on_job, app) -> tuple[int, int]:
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
        try:
            app.handle_job(job, job_dir)
        except Exception as exc:  # un job roto no tumba el runtime
            _mark_error(job_dir, job, clock, state, exc)
            processed += 1
            continue
        if not _read_state(job_dir).get("status"):
            _mark_done(job_dir, job, clock, state)
        processed += 1
    return processed, skipped


def _read_state(job_dir: Path) -> dict:
    path = job_dir / "state.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _mark_error(job_dir: Path, job, clock, state: dict, exc: Exception) -> None:
    state.update(
        {
            "version": 1,
            "status": "error",
            "updated_ts": clock.now().timestamp(),
            "summary": "falló el procesamiento del pedido",
            "active_step": state.get("active_step"),
            "error": type(exc).__name__,
            "op_ids": list(state.get("op_ids") or []),
            "location_key": job.location_key,
            "session_key": job.session_key,
        }
    )
    (job_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")


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
