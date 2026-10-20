"""Deudas de la fase 1: ticks del runtime, hilos que sobreviven y prod T3."""

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from universal_bot.code_mode.ask_bridge import AskBridge
from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import ApprovalPolicy, CodeModeConfig
from universal_bot.code_mode.fake_discord import FakeDiscord
from universal_bot.code_mode.models import Location, Project, ProjectMode, ProjectState
from universal_bot.code_mode.prod_gate import can_approve
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.code_mode.session_manager import WARN_TEXT, SessionManager
from universal_bot.code_mode.stage_router import StageRouter
from universal_bot.labcode_runtime import run_once
from universal_bot.store import JobStore

T0 = datetime(2026, 10, 20, 18, 35, 1, tzinfo=timezone.utc)
REQUESTER = 7
DEV = 8
OTHER = 9
CHANNEL = 100
GUILD = 42


def project(**overrides) -> Project:
    base = Project(
        id="P-1",
        guild_id=GUILD,
        requester_id=REQUESTER,
        origin_message_id=1,
        slug="reservas",
        title_plain="Reservas",
        tier="T3",
        work_type="evolving-product",
        mode=ProjectMode.CHANNEL,
        state=ProjectState.PENDING_PROD_APPROVAL,
        channel_id=CHANNEL,
        root_thread_id=None,
        run_id="R-1",
        wave="O1",
        sandbox_id=None,
        last_security_check=None,
        requires_production=True,
        created_at=T0,
        updated_at=T0,
    )
    return replace(base, **overrides)


def make_spool(path):
    path.mkdir(parents=True, exist_ok=True)
    for name in ("inbox", "outbox", "answers"):
        (path / name).mkdir()
    return path


@pytest.mark.parametrize(
    ("production_t3", "user_id", "roles", "accepted"),
    [
        ("dev", REQUESTER, (), False),
        ("dev", DEV, ("@dev",), True),
        ("requester", REQUESTER, (), True),
        ("requester", DEV, ("@dev",), False),
        ("requester|dev", REQUESTER, (), True),
        ("requester|dev", DEV, ("@dev",), True),
        ("requester|dev", OTHER, (), False),
        ("otro", DEV, ("@dev",), False),
    ],
)
def test_t3_approval_uses_production_t3(production_t3, user_id, roles, accepted):
    approvals = ApprovalPolicy(production_t3=production_t3)
    assert can_approve(project(), user_id, roles, approvals) is accepted


def test_run_once_sends_the_ask_reminder(tmp_path):
    spool = make_spool(tmp_path / "spool")
    db = tmp_path / "mode.sqlite"
    clock = FakeClock(T0)
    ledger = ProjectLedger(db, clock)
    item = ledger.create_project(guild_id=GUILD, requester_id=REQUESTER, state=ProjectState.RUNNING)
    bridge = AskBridge(db, JobStore(db), FakeDiscord(), clock, ledger, CodeModeConfig())
    bridge.ask(
        project_id=item.id,
        stage_key="03-plan",
        kind="sandbox_check_failed",
        prompt_plain="¿Seguimos?",
        options=("seguir",),
        allowed_approvers=(REQUESTER,),
        job_id=None,
        resume_token="resume-abc",
        channel_id=CHANNEL,
        thread_id=None,
    )
    clock.advance(hours=4)
    run_once(spool, db_path=db, clock=clock)
    bodies = [json.loads(path.read_text(encoding="utf-8")) for path in (spool / "outbox").glob("*.json")]
    assert any(body.get("content") == "Recordatorio: ¿Seguimos?" for body in bodies)


def test_run_once_warns_before_the_session_expires(tmp_path):
    spool = make_spool(tmp_path / "spool")
    db = tmp_path / "mode.sqlite"
    clock = FakeClock(T0)
    ledger = ProjectLedger(db, clock)
    ledger.create_project(id="P-warn", guild_id=GUILD, requester_id=REQUESTER, state=ProjectState.RUNNING)
    manager = SessionManager(db, clock, FakeDiscord(), CodeModeConfig(), ledger)
    manager.activate(Location(GUILD, CHANNEL), REQUESTER, ("@dev",), "1h", "button", project_id="P-warn")
    clock.advance(minutes=50)
    run_once(spool, db_path=db, clock=clock)
    bodies = [json.loads(path.read_text(encoding="utf-8")) for path in (spool / "outbox").glob("*.json")]
    assert any(body.get("content") == WARN_TEXT for body in bodies)


def test_stage_thread_survives_a_new_router(tmp_path):
    discord = FakeDiscord()
    db = tmp_path / "stages.sqlite"
    router = StageRouter(discord, db_path=db)
    item = project(id="P-stage", state=ProjectState.LAB_RUNNING, requires_production=False)
    first = router.post(item, "02-lab", "detalle tecnico")
    assert first.created_thread is True
    thread_id = discord.threads[0].id
    revived = StageRouter(FakeDiscord(), db_path=db)
    again = revived.enter(item, "02-lab")
    assert again.thread_id == thread_id
    assert again.created_thread is False
    assert revived.discord.threads == []


def test_run_once_expires_a_due_session(tmp_path):
    spool = make_spool(tmp_path / "spool")
    db = tmp_path / "mode.sqlite"
    clock = FakeClock(T0)
    ledger = ProjectLedger(db, clock)
    item = ledger.create_project(id="P-due", guild_id=GUILD, requester_id=REQUESTER, state=ProjectState.RUNNING)
    manager = SessionManager(db, clock, FakeDiscord(), CodeModeConfig(), ledger)
    opened = manager.activate(Location(GUILD, CHANNEL), REQUESTER, ("@dev",), "1h", "button", project_id=item.id)
    clock.advance(hours=1)
    run_once(spool, db_path=db, clock=clock)
    revived = SessionManager(db, clock, FakeDiscord(), CodeModeConfig(), ProjectLedger(db, clock))
    assert revived.get(opened.session.id).status == "EXPIRED"
    token = ProjectLedger(db, clock).last_checkpoint(item.id)
    assert token is not None
    assert token.resume_token.startswith("resume-")


def test_expired_session_does_not_warn_again(tmp_path):
    clock = FakeClock(T0)
    db = tmp_path / "mode.sqlite"
    discord = FakeDiscord()
    ledger = ProjectLedger(db, clock)
    item = ledger.create_project(
        id="P-exp",
        guild_id=GUILD,
        requester_id=REQUESTER,
        state=ProjectState.RUNNING,
    )
    manager = SessionManager(db, clock, discord, CodeModeConfig(), ledger)
    opened = manager.activate(Location(GUILD, CHANNEL), REQUESTER, ("@dev",), "1h", "button", project_id=item.id)
    clock.advance(hours=1)
    assert manager.tick() == ("expired",)
    assert manager.get(opened.session.id).status == "EXPIRED"
    token = ledger.last_checkpoint(item.id)
    assert token is not None
    assert token.resume_token.startswith("resume-")
    sent = [message.content for message in discord.messages]
    assert WARN_TEXT not in sent
    assert manager.tick() == ()
    assert [message.content for message in discord.messages] == sent
