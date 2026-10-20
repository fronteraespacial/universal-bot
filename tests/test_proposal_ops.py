"""Los botones de la propuesta encolan operaciones reales del puente."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from universal_bot.code_mode.app import CodeModeApp
from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.file_outbox import FileOutboxDiscordPort
from universal_bot.code_mode.inbox_flow import apply_clicks
from universal_bot.code_mode.inbox_job import load_inbox_job
from universal_bot.code_mode.lab_runner import LabOutcome
from universal_bot.code_mode.models import LabEvidence, Location
from universal_bot.code_mode.answers import consume_answers

T0 = datetime(2026, 10, 20, 18, 35, 1, tzinfo=timezone.utc)
CHANNEL = 100
GUILD = 10
JULIAN = 200
CATEGORY = 300
PROJECTS = 400
NEW_CHANNEL = 902
NEW_THREAD = 901
PROMPT = "refactor del store"
SLUG = "p-refactor-del-store"
EXIT = "Salir de modo programación"


class FakeLabs:
    def run_hypothesis(self, **kwargs):
        evidence = LabEvidence(
            id="LE-1",
            project_id=kwargs["project_id"],
            lab_path="/tmp/lab",
            role="lab-runner",
            hypothesis=kwargs["hypothesis"],
            commands=("python probe.py",),
            result="40 segundos",
            artifacts=("probe.txt",),
            verdict="APPROVE",
            evidence_class="running",
            security_check_ref="SC-1",
            started_at=T0,
            finished_at=T0,
            timed_out=False,
        )
        return (LabOutcome(evidence, True, None),)

    def consult_maverick(self, **kwargs):
        del kwargs
        return "CONSULT: propone, no decide."


def make_spool(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name in ("inbox", "outbox", "answers"):
        (path / name).mkdir()
    return path


def write_job(spool: Path) -> Path:
    payload = {
        "version": 1,
        "job_id": "job-1",
        "instance": "fe-labcode",
        "source": "discord",
        "guild_id": str(GUILD),
        "channel_id": str(CHANNEL),
        "thread_id": None,
        "parent_channel_id": str(CHANNEL),
        "message_id": "555",
        "author": {"id": str(JULIAN), "display_name": "alguien"},
        "author_context": "test",
        "content_raw": PROMPT,
        "prompt": PROMPT,
        "attachments": [],
        "audio_transcripts": [],
        "previous_messages": [],
        "location_key": f"{GUILD}:{CHANNEL}",
        "session_key": f"{GUILD}:{CHANNEL}",
        "created_ts": 1000.0,
        "deadline_ts": 2800.0,
        "button_prefix": "ublab:",
        "reply_to_message_id": 555,
        "outbox_dir": str(spool / "outbox"),
        "answers_dir": str(spool / "answers"),
    }
    job_dir = spool / "inbox" / "lc_555"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(json.dumps(payload), encoding="utf-8")
    (job_dir / "prompt.txt").write_text(PROMPT, encoding="utf-8")
    return job_dir


def completing(spool: Path):
    def sleeper(_seconds: float) -> None:
        outbox = spool / "outbox"
        for path in list(outbox.glob("*.json")):
            if path.name.endswith(".result.json"):
                continue
            op = json.loads(path.read_text(encoding="utf-8"))
            if (outbox / f"{op['op_id']}.result.json").is_file():
                continue
            result = {"version": 1, "op_id": op["op_id"], "ok": True, "ts": 1.0}
            if op["op"] == "thread":
                result["thread_id"] = NEW_THREAD if op["name"].startswith("p-") else 501
            elif op["op"] == "create_channel":
                result["channel_id"] = NEW_CHANNEL
            else:
                result["message_id"] = 900
            (outbox / f"{op['op_id']}.result.json").write_text(json.dumps(result), encoding="utf-8")

    return sleeper


def bodies(spool: Path) -> list[dict]:
    found = []
    outbox = spool / "outbox"
    for folder in (outbox, outbox / "done"):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            if path.name.endswith(".result.json"):
                continue
            found.append(json.loads(path.read_text(encoding="utf-8")))
    return found


def click(spool: Path, opt: str) -> None:
    answer = {
        "version": 1,
        "kind": "propose",
        "id": "job-1",
        "opt": opt,
        "user_id": str(JULIAN),
        "channel_id": str(CHANNEL),
        "message_id": "3",
        "interaction_id": "ix",
        "ts": 1.0,
    }
    (spool / "answers" / "propose__job-1.json").write_text(json.dumps(answer), encoding="utf-8")


def drive(tmp_path, opt: str, *, projects_channel_id: int | None = PROJECTS):
    spool = make_spool(tmp_path / "spool")
    clock = FakeClock(T0)
    config = CodeModeConfig(
        allowed_channels=(CHANNEL, NEW_CHANNEL, PROJECTS),
        admin_category_id=CATEGORY,
        projects_channel_id=projects_channel_id,
        role_map=((str(JULIAN), ("@dev", "@admin")),),
    )
    port = FileOutboxDiscordPort(
        spool,
        clock=clock,
        sleeper=completing(spool),
        timeout_s=5,
        poll_interval_s=1,
        admin_category_id=CATEGORY,
        named_channels={"proyectos": PROJECTS},
    )
    app = CodeModeApp(tmp_path / "mode.sqlite", port, clock, config, lab_runner=FakeLabs())
    job_dir = write_job(spool)
    job = load_inbox_job(job_dir)
    app.handle_job(job, job_dir)
    click(spool, opt)
    clicks = consume_answers(spool, clock=clock)
    apply_clicks(app, spool, clicks)
    return app, spool


def _labels(op: dict) -> list[str]:
    found = []
    for row in op.get("components") or []:
        for item in row.get("components") or []:
            if "label" in item:
                found.append(item["label"])
    return found


def exit_and_pin(ops: list[dict], target: int) -> None:
    exit_msgs = [
        op
        for op in ops
        if op["op"] == "send" and op.get("channel_id") == target and EXIT in _labels(op)
    ]
    assert len(exit_msgs) == 1
    pins = [op for op in ops if op["op"] == "pin" and op.get("channel_id") == target and op.get("message_id") == 900]
    assert len(pins) == 1


@pytest.mark.parametrize(
    ("opt", "until"),
    (
        ("here_1h", T0 + timedelta(hours=1)),
        ("here_4h", T0 + timedelta(hours=4)),
        ("here_until_exit", None),
    ),
)
def test_here_keeps_the_session_and_pins_the_exit_button(tmp_path, opt, until):
    app, spool = drive(tmp_path, opt)
    session = app.sessions.resolve(Location(GUILD, CHANNEL))
    assert session is not None
    assert session.status == "ACTIVE"
    assert session.until == until
    assert session.thread_id is None
    exit_and_pin(bodies(spool), CHANNEL)


def test_create_channel_moves_the_session_after_the_result(tmp_path):
    app, spool = drive(tmp_path, "create_channel")
    ops = bodies(spool)
    created = [op for op in ops if op["op"] == "create_channel"]
    assert len(created) == 1
    assert created[0]["name"] == SLUG
    assert created[0]["parent_id"] == CATEGORY
    assert created[0]["allowed_mentions"] == {"parse": [], "replied_user": False}
    assert app.sessions.resolve(Location(GUILD, CHANNEL)) is None
    moved = app.sessions.resolve(Location(GUILD, NEW_CHANNEL))
    assert moved is not None
    assert moved.status == "ACTIVE"
    assert moved.until is None
    assert moved.thread_id is None
    exit_and_pin(ops, NEW_CHANNEL)
    threads = [op["name"] for op in ops if op["op"] == "thread"]
    assert threads == ["02-lab", "03-plan"]
    assert {op["channel_id"] for op in ops if op["op"] == "thread"} == {NEW_CHANNEL}


def test_create_thread_moves_the_session_to_the_projects_channel(tmp_path):
    app, spool = drive(tmp_path, "create_thread")
    ops = bodies(spool)
    opened = [op for op in ops if op["op"] == "thread" and op.get("name") == SLUG]
    assert len(opened) == 1
    assert opened[0]["channel_id"] == PROJECTS
    assert opened[0]["name"] == SLUG
    assert opened[0]["allowed_mentions"] == {"parse": [], "replied_user": False}
    assert app.sessions.resolve(Location(GUILD, CHANNEL)) is None
    moved = app.sessions.resolve(Location(GUILD, PROJECTS, NEW_THREAD))
    assert moved is not None
    assert moved.status == "ACTIVE"
    assert moved.until is None
    exit_and_pin(ops, NEW_THREAD)


def test_create_thread_uses_the_current_channel_when_projects_is_unset(tmp_path):
    app, spool = drive(tmp_path, "create_thread", projects_channel_id=None)
    ops = bodies(spool)
    opened = [op for op in ops if op["op"] == "thread" and op.get("name") == SLUG]
    assert len(opened) == 1
    assert opened[0]["channel_id"] == CHANNEL
    moved = app.sessions.resolve(Location(GUILD, CHANNEL, NEW_THREAD))
    assert moved is not None
    assert moved.status == "ACTIVE"
    assert moved.until is None
    assert app.sessions.resolve(Location(GUILD, CHANNEL, None)) is None
