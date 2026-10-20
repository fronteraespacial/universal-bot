"""Tres recorridos de punta a punta con FakeDiscord y SQLite en tmp."""

from datetime import datetime, timezone

from universal_bot.code_mode.app import CodeModeApp
from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.fake_discord import FakeDiscord
from universal_bot.code_mode.models import Location, ProjectState

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
GUILD = 1
CHANNEL = 100
ACTIVATOR = 7
DEV = 8
FORBIDDEN = "No podés aprobar esto."


def make(tmp_path):
    discord = FakeDiscord()
    app = CodeModeApp(tmp_path / "mode.sqlite", discord, FakeClock(T0), CodeModeConfig())
    return app, discord


def loc():
    return Location(GUILD, CHANNEL, None)


def test_manual_phrase_stays_sticky_until_an_authorized_exit(tmp_path):
    app, _discord = make(tmp_path)
    opened = app.handle_text(loc(), ACTIVATOR, ("@dev",), "pasemos a modo código")
    assert opened.ok is True
    assert app.proposer_calls == 0
    for index in range(3):
        app.handle_request(
            loc(),
            ACTIVATOR,
            ("@dev",),
            text="agregá logs al worker",
            tier="T2",
            confidence=0.95,
            request_id=f"t{index}",
        )
    assert app.proposer_calls == 0
    exited = app.exit(loc(), ACTIVATOR, ("@dev",))
    assert exited.ok is True
    app.handle_request(
        loc(),
        ACTIVATOR,
        ("@dev",),
        text="ahora sí",
        tier="T2",
        confidence=0.95,
        request_id="after",
    )
    assert app.proposer_calls == 1


def test_thread_project_reaches_done_with_zero_approval_clicks(tmp_path):
    app, discord = make(tmp_path)
    app.handle_request(
        loc(),
        ACTIVATOR,
        ("@dev",),
        text="quiero un slug",
        tier="T2",
        confidence=0.93,
        request_id="req-1",
    )
    assert app.proposer_calls == 1
    project = app.choose("req-1", "create_thread", ACTIVATOR, ("@dev",))
    assert project.state == ProjectState.DONE
    assert project.requires_production is False
    assert app.last_plan.lab_evidence[0].verdict == "APPROVE"
    assert app.last_plan.lab_evidence[0].evidence_class == "running"
    for mark in ("SANDBOX_CHECK", "LAB_RUNNING", "PLAN_READY"):
        assert mark in app.trace
    assert "PENDING_PROD_APPROVAL" not in app.trace
    assert app.blocking_asks == 0
    custom_ids = [button.custom_id for message in discord.messages for button in message.buttons]
    assert not any("aprob" in custom_id or custom_id.startswith("ublab:prod") for custom_id in custom_ids)


def test_t3_deploy_rejects_the_requester_and_accepts_a_dev(tmp_path):
    app, discord = make(tmp_path)
    app.handle_request(
        loc(),
        ACTIVATOR,
        ("@dev",),
        text="publicar el slug",
        tier="T3",
        confidence=0.99,
        request_id="req-t3",
    )
    pending = app.choose("req-t3", "create_thread", ACTIVATOR, ("@dev",), deploy=True)
    assert pending.state == ProjectState.PENDING_PROD_APPROVAL
    denied = app.approve_production(pending.id, ACTIVATOR, ())
    assert denied.accepted is False
    assert app.project(pending.id).state == ProjectState.PENDING_PROD_APPROVAL
    assert any(text == FORBIDDEN for _user, text in discord.ephemeral)
    accepted = app.approve_production(pending.id, DEV, ("@dev",))
    assert accepted.accepted is True
    assert app.project(pending.id).state == ProjectState.DONE
    assert "DEPLOYING" in app.trace
    assert "PENDING_PROD_APPROVAL" in app.trace
