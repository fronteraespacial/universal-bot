"""El detalle técnico espera el hilo y no cae al canal."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.file_outbox import FileOutboxDiscordPort
from universal_bot.code_mode.models import Project, ProjectMode, ProjectState
from universal_bot.code_mode.stage_router import StageRouter

T0 = datetime(2026, 10, 20, 18, 35, 1, tzinfo=timezone.utc)
CHANNEL = 100
DETAIL = "Resultado: 40 segundos de audio"
THREAD_ID = 501


def project() -> Project:
    return Project(
        id="P-1",
        guild_id=10,
        requester_id=200,
        origin_message_id=301,
        slug="eco",
        title_plain="Eco",
        tier="T2",
        work_type="evolving-product",
        mode=ProjectMode.CHANNEL,
        state=ProjectState.LAB_RUNNING,
        channel_id=CHANNEL,
        root_thread_id=None,
        run_id="R-1",
        wave="O1",
        sandbox_id=None,
        last_security_check=None,
        requires_production=False,
        created_at=T0,
        updated_at=T0,
    )


def make_spool(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "outbox").mkdir()
    return path


def sends(spool: Path) -> list[dict]:
    found = []
    outbox = spool / "outbox"
    for folder in (outbox, outbox / "done"):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            if path.name.endswith(".result.json"):
                continue
            body = json.loads(path.read_text(encoding="utf-8"))
            if body.get("op") == "send":
                found.append(body)
    return found


def technical_on_channel(bodies: list[dict]) -> list[dict]:
    prefixed = f"[02-lab] {DETAIL}"
    return [
        body
        for body in bodies
        if body.get("channel_id") == CHANNEL and body.get("content") in {DETAIL, prefixed}
    ]


def port(spool: Path, clock: FakeClock, sleeper) -> FileOutboxDiscordPort:
    return FileOutboxDiscordPort(
        spool,
        clock=clock,
        sleeper=sleeper,
        timeout_s=2,
        poll_interval_s=1,
        defer_results=True,
    )


@pytest.mark.parametrize("ok", (None, False))
def test_without_a_thread_result_the_channel_gets_zero_technical_sends(tmp_path, ok):
    spool = make_spool(tmp_path / "spool")
    clock = FakeClock(T0)

    def sleeper(_seconds: float) -> None:
        clock.advance(seconds=1)
        if ok is None:
            return
        outbox = spool / "outbox"
        for path in outbox.glob("*.json"):
            if path.name.endswith(".result.json"):
                continue
            body = json.loads(path.read_text(encoding="utf-8"))
            if body.get("op") != "thread":
                continue
            result = {"version": 1, "op_id": body["op_id"], "ok": False, "ts": 1.0, "error": "boom"}
            (outbox / f"{body['op_id']}.result.json").write_text(json.dumps(result), encoding="utf-8")

    router = StageRouter(port(spool, clock, sleeper), db_path=tmp_path / "mode.sqlite")
    router.post(project(), "02-lab", DETAIL)
    assert technical_on_channel(sends(spool)) == []


def test_detail_goes_to_the_thread_when_the_result_arrives(tmp_path):
    spool = make_spool(tmp_path / "spool")
    clock = FakeClock(T0)
    db = tmp_path / "mode.sqlite"

    def sleeper(_seconds: float) -> None:
        clock.advance(seconds=1)

    router = StageRouter(port(spool, clock, sleeper), db_path=db)
    router.post(project(), "02-lab", DETAIL)
    assert technical_on_channel(sends(spool)) == []
    thread = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (spool / "outbox").glob("*.json")
        if path.name.endswith("-thread.json") or json.loads(path.read_text(encoding="utf-8")).get("op") == "thread"
    )
    result = {"version": 1, "op_id": thread["op_id"], "ok": True, "ts": 1.0, "thread_id": THREAD_ID}
    (spool / "outbox" / f"{thread['op_id']}.result.json").write_text(json.dumps(result), encoding="utf-8")
    StageRouter(port(spool, clock, sleeper), db_path=db).flush_pending()
    delivered = [
        body
        for body in sends(spool)
        if body.get("content") == DETAIL and body.get("channel_id") == THREAD_ID
    ]
    assert delivered == [
        {
            "version": 1,
            "op_id": delivered[0]["op_id"],
            "op": "send",
            "allowed_mentions": {"parse": [], "replied_user": False},
            "channel_id": THREAD_ID,
            "content": DETAIL,
        }
    ]
    assert technical_on_channel(sends(spool)) == []
