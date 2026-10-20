"""run_once consume el inbox una sola vez y no abre Discord."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.models import ProjectState
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.labcode_runtime import run_once

T0 = datetime(2026, 10, 20, 18, 35, 1, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]
CHANNEL = 910001


def make_spool(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name in ("inbox", "outbox", "answers"):
        (path / name).mkdir()
    return path


def write_job(spool: Path, *, message_id: str = "555", job_id: str = "job-1", prompt: str = "hola") -> Path:
    payload = {
        "version": 1,
        "job_id": job_id,
        "instance": "fe-labcode",
        "source": "discord",
        "guild_id": "10",
        "channel_id": str(CHANNEL),
        "thread_id": None,
        "parent_channel_id": str(CHANNEL),
        "message_id": message_id,
        "author": {"id": "7", "display_name": "Julian"},
        "author_context": "julian",
        "content_raw": prompt,
        "prompt": prompt,
        "attachments": [],
        "audio_transcripts": [],
        "previous_messages": [],
        "location_key": f"10:{CHANNEL}",
        "session_key": f"10:{CHANNEL}",
        "created_ts": 1000.0,
        "deadline_ts": 2800.0,
        "button_prefix": "ublab:",
        "reply_to_message_id": None,
        "outbox_dir": str(spool / "outbox"),
        "answers_dir": str(spool / "answers"),
    }
    job_dir = spool / "inbox" / f"lc_{message_id}"
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(json.dumps(payload), encoding="utf-8")
    (job_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    return job_dir


def test_inbox_is_processed_once_and_survives_restart(tmp_path):
    spool = make_spool(tmp_path / "spool")
    job_dir = write_job(spool)
    clock = FakeClock(T0)
    seen = []
    db = tmp_path / "mode.sqlite"
    first = run_once(spool, db_path=db, clock=clock, on_job=seen.append)
    assert first["processed"] == 1
    assert first["skipped"] == 0
    assert len(seen) == 1
    assert seen[0].location.guild_id == 10
    assert seen[0].location.channel_id == CHANNEL
    assert seen[0].session_key == seen[0].location_key
    state = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "done"
    assert state["location_key"] == f"10:{CHANNEL}"
    assert (spool / "runtime.heartbeat").read_text(encoding="utf-8") == T0.isoformat()
    second = run_once(spool, db_path=db, clock=clock, on_job=seen.append)
    assert second["processed"] == 0
    assert second["skipped"] == 1
    assert len(seen) == 1
    restarted = []
    run_once(spool, db_path=db, clock=clock, on_job=restarted.append)
    assert restarted == []


def test_stop_answer_pauses_the_running_job(tmp_path):
    spool = make_spool(tmp_path / "spool")
    clock = FakeClock(T0)
    db = tmp_path / "mode.sqlite"
    ledger = ProjectLedger(db, clock)
    project = ledger.create_project(id="P-stop", guild_id=10, requester_id=7, state=ProjectState.RUNNING)
    job_dir = spool / "inbox" / "lc_1"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(json.dumps({"job_id": "job-9"}), encoding="utf-8")
    (job_dir / "state.json").write_text(
        json.dumps({"version": 1, "status": "running", "project_id": project.id, "op_ids": ["op-1"]}),
        encoding="utf-8",
    )
    answer = {
        "version": 1,
        "kind": "stop",
        "id": "job-9",
        "opt": "ahora",
        "user_id": "7",
        "channel_id": "10",
        "message_id": "1",
        "interaction_id": "ix-1",
        "ts": 1.0,
    }
    (spool / "answers" / "stop__job-9.json").write_text(json.dumps(answer), encoding="utf-8")
    seen = []
    report = run_once(spool, db_path=db, clock=clock, on_job=seen.append)
    assert seen == []
    assert report["processed"] == 0
    state = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "paused"
    assert state["project_id"] == project.id
    assert ProjectLedger(db, clock).get_project(project.id).state == ProjectState.PAUSED


def test_cli_once_exits_and_does_not_reprocess(tmp_path):
    spool = make_spool(tmp_path / "spool")
    job_dir = write_job(spool, message_id="777", job_id="job-cli", prompt="eco")
    db = tmp_path / "mode.sqlite"
    command = [
        sys.executable,
        "-m",
        "universal_bot.labcode_runtime",
        "--spool",
        str(spool),
        "--once",
        "--db",
        str(db),
    ]
    first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15, check=False)
    assert first.returncode == 0, first.stderr
    assert (spool / "runtime.heartbeat").is_file()
    state = (job_dir / "state.json").read_text(encoding="utf-8")
    assert json.loads(state)["status"] == "done"
    second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15, check=False)
    assert second.returncode == 0, second.stderr
    assert (job_dir / "state.json").read_text(encoding="utf-8") == state
