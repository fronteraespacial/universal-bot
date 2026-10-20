"""Sesión pegajosa: activar, resolver, salir, expirar y sobrevivir un reinicio."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.fake_discord import FakeDiscord
from universal_bot.code_mode.models import Location, ProjectState, SessionStatus
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.code_mode.session_manager import SessionManager

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
GUILD = 42
CHANNEL = 100
ACTIVATOR = 7
DEV = 8
STRANGER = 9
PIN_TEXT = "Modo programación activo."
EXIT_LABEL = "Salir de modo programación"
WARN_TEXT = "El modo programación está por vencer."
EXIT_FORBIDDEN = "No podés salir de este modo."
ACTIVATE_FORBIDDEN = "No tenés permiso para activar el modo código."
EXIT_OK = "Salimos de modo programación. El trabajo quedó guardado; reactivá para seguir."


def loc(thread_id=None) -> Location:
    return Location(GUILD, CHANNEL, thread_id)


def make(tmp_path, clock=None, config=None):
    clock = clock or FakeClock(T0)
    discord = FakeDiscord()
    config = config or CodeModeConfig()
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = tmp_path / "mode.sqlite"
    ledger = ProjectLedger(db, clock)
    manager = SessionManager(db, clock, discord, config, ledger)
    return SimpleNamespace(
        clock=clock, discord=discord, config=config, db=db, ledger=ledger, manager=manager
    )


def test_manual_phrase_with_permission_activates_and_pins_exit(tmp_path):
    env = make(tmp_path)
    result = env.manager.handle_text(loc(), ACTIVATOR, ("@dev",), "pasemos a modo código")
    assert result.ok is True
    assert result.reason == "activated"
    session = env.manager.resolve(loc())
    assert session is not None
    assert session.status == SessionStatus.ACTIVE
    assert session.activation == "manual_phrase"
    assert session.activated_by == ACTIVATOR
    assert session.until == T0 + timedelta(hours=4)
    assert session.warn_at == T0 + timedelta(hours=4) - timedelta(minutes=10)
    assert session.pinned_message_id is not None
    pin = env.discord.messages[-1]
    assert pin.content == PIN_TEXT
    assert _buttons(pin) == ((f"ublab:exit:{session.id}", EXIT_LABEL),)
    assert (CHANNEL, session.pinned_message_id, None) in env.discord.pins


def _buttons(message):
    return tuple((button.custom_id, button.label) for button in message.buttons)


def test_command_durations(tmp_path):
    cases = (
        ("/modo-codigo", timedelta(hours=4)),
        ("/modo-codigo 1h", timedelta(hours=1)),
        ("/modo-codigo 4h", timedelta(hours=4)),
    )
    for index, (text, delta) in enumerate(cases):
        env = make(tmp_path / str(index))
        result = env.manager.handle_text(loc(), ACTIVATOR, ("@dev",), text)
        assert result.ok is True
        assert result.session.activation == "command"
        assert result.session.until == T0 + delta
        assert result.session.warn_at == result.session.until - timedelta(minutes=10)


def test_command_until_exit_has_no_deadline(tmp_path):
    env = make(tmp_path)
    result = env.manager.handle_text(loc(), ACTIVATOR, ("@admin",), "/modo-codigo until_exit")
    assert result.ok is True
    assert result.session.until is None
    assert result.session.warn_at is None
    assert result.session.status == SessionStatus.ACTIVE


def test_manual_phrase_without_permission_does_not_activate(tmp_path):
    env = make(tmp_path)
    result = env.manager.handle_text(loc(), STRANGER, (), "pasemos a modo código")
    assert result.ok is False
    assert result.reason == "forbidden"
    assert result.session is None
    assert env.manager.resolve(loc()) is None
    assert env.discord.ephemeral == [(STRANGER, ACTIVATE_FORBIDDEN)]
    assert env.discord.pins == []


def test_second_activate_extends_the_same_session(tmp_path):
    env = make(tmp_path)
    first = env.manager.activate(loc(), ACTIVATOR, ("@dev",), "1h", "button")
    env.clock.advance(minutes=30)
    second = env.manager.activate(loc(), DEV, ("@dev",), "4h", "button")
    assert first.ok is True
    assert second.ok is True
    assert second.reason == "extended"
    assert second.session.id == first.session.id
    assert second.session.since == first.session.since
    assert second.session.until == T0 + timedelta(minutes=30) + timedelta(hours=4)
    assert second.session.warn_at == second.session.until - timedelta(minutes=10)
    assert second.session.activated_by == ACTIVATOR
    assert env.manager.resolve(loc()).status == SessionStatus.ACTIVE


def test_child_thread_inherits_channel_until_it_has_its_own(tmp_path):
    env = make(tmp_path)
    channel = env.manager.activate(loc(), ACTIVATOR, ("@dev",), "until_exit", "manual_phrase")
    assert env.manager.resolve(loc(99)).id == channel.session.id
    own = env.manager.activate(loc(99), ACTIVATOR, ("@dev",), "1h", "button")
    assert own.session.id != channel.session.id
    assert env.manager.resolve(loc(99)).id == own.session.id
    assert env.manager.resolve(loc()).id == channel.session.id
    exited = env.manager.exit(loc(99), ACTIVATOR, ())
    assert exited.reason == "exited"
    assert env.manager.resolve(loc(99)).id == channel.session.id
    assert env.manager.resolve(loc()).status == SessionStatus.ACTIVE
    assert env.manager.get(own.session.id).status == SessionStatus.EXITED


def test_exit_on_thread_does_not_stop_channel_session(tmp_path):
    env = make(tmp_path)
    channel = env.manager.activate(loc(), ACTIVATOR, ("@dev",), "until_exit", "button")
    thread = env.manager.activate(loc(50), DEV, ("@dev",), "until_exit", "button")
    env.manager.exit(loc(), ACTIVATOR, ())
    assert env.manager.get(channel.session.id).status == SessionStatus.EXITED
    assert env.manager.resolve(loc(50)).id == thread.session.id
    assert env.manager.resolve(loc(50)).status == SessionStatus.ACTIVE


@pytest.mark.parametrize(
    ("actor_id", "roles", "reason"),
    [
        (ACTIVATOR, (), "exited"),
        (STRANGER, ("@dev",), "exited"),
        (STRANGER, ("@admin",), "exited"),
        (STRANGER, (), "forbidden"),
        (STRANGER, ("@everyone",), "forbidden"),
    ],
)
def test_who_can_exit(tmp_path, actor_id, roles, reason):
    env = make(tmp_path)
    created = env.manager.activate(loc(), ACTIVATOR, ("@dev",), "4h", "button")
    result = env.manager.exit(loc(), actor_id, roles)
    assert result.reason == reason
    status = env.manager.get(created.session.id).status
    if reason == "exited":
        assert status == SessionStatus.EXITED
        assert env.discord.ephemeral == []
        assert env.discord.messages[-1].content == EXIT_OK
        assert (CHANNEL, created.session.pinned_message_id, None) in env.discord.unpins
    else:
        assert status == SessionStatus.ACTIVE
        assert result.session.until == created.session.until
        assert env.discord.ephemeral == [(actor_id, EXIT_FORBIDDEN)]
        assert env.discord.unpins == []


def test_exit_checkpoints_running_project(tmp_path):
    env = make(tmp_path)
    project = env.ledger.create_project(
        guild_id=GUILD,
        requester_id=ACTIVATOR,
        state=ProjectState.RUNNING,
        title_plain="Turnos",
    )
    env.manager.activate(
        loc(), ACTIVATOR, ("@dev",), "4h", "proposal_here", project_id=project.id
    )
    result = env.manager.exit(loc(), ACTIVATOR, ())
    assert result.reason == "exited"
    assert result.resume_token is not None
    assert result.resume_token.startswith("resume-")
    saved = env.ledger.get_project(project.id)
    assert saved.state == ProjectState.PAUSED
    checkpoint = env.ledger.last_checkpoint(project.id)
    assert checkpoint.resume_token == result.resume_token


def test_exit_does_not_pause_mid_commit(tmp_path):
    env = make(tmp_path)
    project = env.ledger.create_project(
        guild_id=GUILD,
        requester_id=ACTIVATOR,
        state=ProjectState.LAB_RUNNING,
        title_plain="Turnos",
    )
    env.manager.activate(
        loc(), ACTIVATOR, ("@dev",), "4h", "button", project_id=project.id
    )
    env.ledger.begin_commit(project.id)
    deferred = env.manager.exit(loc(), ACTIVATOR, ("@dev",))
    assert deferred.reason == "deferred"
    assert deferred.resume_token is None
    assert env.ledger.get_project(project.id).state == ProjectState.LAB_RUNNING
    assert env.manager.resolve(loc()).status == SessionStatus.ACTIVE
    done = env.manager.finish_atomic_step(project.id)
    assert done.reason == "exited"
    assert done.resume_token.startswith("resume-")
    assert env.ledger.get_project(project.id).state == ProjectState.PAUSED
    assert env.manager.resolve(loc()) is None
    assert env.manager.get(done.session.id).status == SessionStatus.EXITED


def test_exit_keeps_waiting_human_project_open(tmp_path):
    env = make(tmp_path)
    project = env.ledger.create_project(
        guild_id=GUILD,
        requester_id=ACTIVATOR,
        state=ProjectState.WAITING_HUMAN,
        title_plain="Turnos",
    )
    env.manager.activate(
        loc(), ACTIVATOR, ("@dev",), "until_exit", "button", project_id=project.id
    )
    result = env.manager.exit(loc(), ACTIVATOR, ())
    assert result.reason == "exited"
    assert result.resume_token is None
    assert env.ledger.get_project(project.id).state == ProjectState.WAITING_HUMAN
    assert env.ledger.last_checkpoint(project.id) is None


def test_tick_warns_then_expires_and_checkpoints(tmp_path):
    env = make(tmp_path)
    project = env.ledger.create_project(
        guild_id=GUILD,
        requester_id=ACTIVATOR,
        state=ProjectState.RUNNING,
        title_plain="Turnos",
    )
    created = env.manager.activate(
        loc(), ACTIVATOR, ("@dev",), "1h", "button", project_id=project.id
    )
    env.clock.advance(minutes=49)
    assert env.manager.tick() == ()
    assert env.manager.get(created.session.id).status == SessionStatus.ACTIVE
    env.clock.advance(minutes=1)
    assert env.manager.tick() == ("warned",)
    session = env.manager.get(created.session.id)
    assert session.status == SessionStatus.ACTIVE
    warning = env.discord.messages[-1]
    assert warning.content == WARN_TEXT
    assert _buttons(warning) == (
        (f"ublab:extend:{session.id}", "Extender"),
        (f"ublab:exit:{session.id}", "Salir ahora"),
    )
    env.clock.advance(minutes=10)
    assert env.manager.tick() == ("expired",)
    assert env.manager.get(created.session.id).status == SessionStatus.EXPIRED
    assert env.ledger.get_project(project.id).state == ProjectState.PAUSED
    assert env.ledger.last_checkpoint(project.id).resume_token.startswith("resume-")
    assert (CHANNEL, created.session.pinned_message_id, None) in env.discord.unpins
    assert env.manager.resolve(loc()) is None


def test_restart_keeps_active_session_and_reregisters_pin(tmp_path):
    env = make(tmp_path)
    created = env.manager.activate(loc(), ACTIVATOR, ("@dev",), "4h", "command")
    revived_discord = FakeDiscord()
    revived = SessionManager(env.db, env.clock, revived_discord, env.config, env.ledger)
    session = revived.resolve(loc())
    assert session.id == created.session.id
    assert session.status == SessionStatus.ACTIVE
    assert session.until == created.session.until
    assert revived_discord.views == [f"ublab:exit:{session.id}"]


def test_restart_expires_session_that_elapsed_while_down(tmp_path):
    env = make(tmp_path)
    project = env.ledger.create_project(
        guild_id=GUILD,
        requester_id=ACTIVATOR,
        state=ProjectState.RUNNING,
        title_plain="Turnos",
    )
    created = env.manager.activate(
        loc(), ACTIVATOR, ("@dev",), "1h", "button", project_id=project.id
    )
    later = FakeClock(T0 + timedelta(hours=2))
    ledger = ProjectLedger(env.db, later)
    revived = SessionManager(env.db, later, FakeDiscord(), env.config, ledger)
    assert revived.resolve(loc()) is None
    assert revived.get(created.session.id).status == SessionStatus.EXPIRED
    assert ledger.get_project(project.id).state == ProjectState.PAUSED


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("gracias", "basic_cli"),
        ("¿qué hora es?", "basic_cli"),
        ("hola", "basic_cli"),
        ("donde esta el README", "basic_cli"),
        ("typo en recieve", "basic_cli"),
        ("", "basic_cli"),
        ("refactor del store", "code_cli"),
        ("bug en el lock que no se libera", "code_cli"),
        ("feature nueva de reservas", "code_cli"),
        ("agregá logs al worker", "code_cli"),
    ],
)
def test_route_inside_mode_keeps_session(tmp_path, text, kind):
    env = make(tmp_path)
    created = env.manager.activate(loc(), ACTIVATOR, ("@dev",), "4h", "button")
    decision = env.manager.route(loc(), text)
    assert decision.kind == kind
    assert decision.session.id == created.session.id
    assert env.manager.resolve(loc()).status == SessionStatus.ACTIVE


def test_route_outside_mode_is_outside(tmp_path):
    env = make(tmp_path)
    decision = env.manager.route(loc(), "refactor del store")
    assert decision.kind == "outside"
    assert decision.session is None
