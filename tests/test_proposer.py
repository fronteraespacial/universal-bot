"""Propuesta de modo código: umbral, cuatro opciones y una sola vez por pedido."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.fake_discord import FakeDiscord
from universal_bot.code_mode.models import Location, SessionStatus
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.code_mode.proposer import Proposer
from universal_bot.code_mode.session_manager import SessionManager

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
ACTIVATOR = 7
PROMPT = "¿Pasamos a modo programación?"


def loc() -> Location:
    return Location(42, 100, None)


def make(tmp_path, config=None):
    clock = FakeClock(T0)
    discord = FakeDiscord()
    config = config or CodeModeConfig()
    db = tmp_path / "mode.sqlite"
    ledger = ProjectLedger(db, clock)
    sessions = SessionManager(db, clock, discord, config, ledger)
    proposer = Proposer(discord, sessions, config, clock)
    return SimpleNamespace(
        clock=clock,
        discord=discord,
        config=config,
        sessions=sessions,
        proposer=proposer,
    )


def buttons(message):
    return tuple((button.custom_id, button.label) for button in message.buttons)


def test_tiers_and_confidence_gate(tmp_path):
    cases = (
        ("T0", 1.0, False),
        ("T1", 1.0, False),
        ("T2", 0.79, False),
        ("T2", 0.8, True),
        ("T3", 0.8, True),
        ("T3", 0.79, False),
        ("T4", 1.0, False),
    )
    for index, (tier, confidence, proposes) in enumerate(cases):
        env = make(tmp_path / str(index))
        proposal = env.proposer.propose(f"req-{index}", tier, confidence, loc(), ACTIVATOR)
        if proposes:
            assert proposal is not None
            assert proposal.tier == tier
            assert proposal.options == ("create_channel", "create_thread", "here", "decline")
        else:
            assert proposal is None
            assert env.discord.messages == []


def test_t2_proposal_lists_four_options_and_the_duration_selector(tmp_path):
    env = make(tmp_path)
    proposal = env.proposer.propose("req-1", "T2", 0.91, loc(), ACTIVATOR)
    assert proposal.options == ("create_channel", "create_thread", "here", "decline")
    assert proposal.duration_options == ("1h", "4h", "until_exit")
    assert env.discord.messages[-1].content == PROMPT
    assert buttons(env.discord.messages[-1]) == (
        ("ublab:propose:req-1:create_channel", "Crear un canal para el proyecto"),
        ("ublab:propose:req-1:create_thread", "Crear un hilo de proyecto en #proyectos"),
        ("ublab:propose:req-1:here_1h", "Programar acá mismo · 1 h"),
        ("ublab:propose:req-1:here_4h", "Programar acá mismo · 4 h"),
        ("ublab:propose:req-1:here_until_exit", "Programar acá mismo · hasta que salga"),
        ("ublab:propose:req-1:decline", "No, resolvelo como siempre"),
    )


def test_allow_channels_false_hides_create_channel(tmp_path):
    env = make(tmp_path, CodeModeConfig(allow_channels=False))
    proposal = env.proposer.propose("req-1", "T3", 0.9, loc(), ACTIVATOR)
    assert proposal.options == ("create_thread", "here", "decline")
    assert buttons(env.discord.messages[-1]) == (
        ("ublab:propose:req-1:create_thread", "Crear un hilo de proyecto en #proyectos"),
        ("ublab:propose:req-1:here_1h", "Programar acá mismo · 1 h"),
        ("ublab:propose:req-1:here_4h", "Programar acá mismo · 4 h"),
        ("ublab:propose:req-1:here_until_exit", "Programar acá mismo · hasta que salga"),
        ("ublab:propose:req-1:decline", "No, resolvelo como siempre"),
    )


def test_propose_once_per_request(tmp_path):
    env = make(tmp_path)
    first = env.proposer.propose("req-1", "T2", 0.9, loc(), ACTIVATOR)
    second = env.proposer.propose("req-1", "T2", 0.9, loc(), ACTIVATOR)
    other = env.proposer.propose("req-2", "T2", 0.9, loc(), ACTIVATOR)
    assert second.options == first.options
    assert second.message_id == first.message_id
    assert other.request_id == "req-2"
    with_buttons = [message for message in env.discord.messages if message.buttons]
    assert len(with_buttons) == 2
    assert with_buttons[0].message_id == first.message_id
    assert with_buttons[1].message_id == other.message_id


def test_here_opens_session_with_default_duration(tmp_path):
    env = make(tmp_path)
    env.proposer.propose("req-1", "T2", 0.9, loc(), ACTIVATOR)
    choice = env.proposer.choose("req-1", "here", ACTIVATOR, ("@dev",))
    assert choice.kind == "session"
    assert choice.override_tier is None
    assert choice.session.activation == "proposal_here"
    assert choice.session.status == SessionStatus.ACTIVE
    assert choice.session.until == T0 + timedelta(hours=4)
    assert env.sessions.resolve(loc()).id == choice.session.id


def test_here_without_permission_does_not_open_session(tmp_path):
    env = make(tmp_path)
    env.proposer.propose("req-1", "T2", 0.9, loc(), ACTIVATOR)
    choice = env.proposer.choose("req-1", "here", 9, ())
    assert choice.kind == "forbidden"
    assert choice.session is None
    assert env.sessions.resolve(loc()) is None


def test_decline_routes_to_basic_cli_with_override_tier(tmp_path):
    env = make(tmp_path)
    env.proposer.propose("req-1", "T3", 0.95, loc(), ACTIVATOR)
    choice = env.proposer.choose("req-1", "decline", ACTIVATOR, ("@dev",))
    assert choice.kind == "basic_cli"
    assert choice.override_tier == "T3"
    assert choice.session is None
    assert env.sessions.resolve(loc()) is None


def test_configured_tiers_can_exclude_t2(tmp_path):
    env = make(tmp_path, CodeModeConfig(propose_tiers=("T3",)))
    assert env.proposer.propose("req-1", "T2", 0.99, loc(), ACTIVATOR) is None
    proposal = env.proposer.propose("req-2", "T3", 0.99, loc(), ACTIVATOR)
    assert proposal.options[0] == "create_channel"


def test_manual_command_activates_through_the_proposer(tmp_path):
    env = make(tmp_path)
    result = env.proposer.activate_manual(loc(), ACTIVATOR, ("@dev",), "/modo-codigo 1h")
    assert result.ok is True
    assert result.session.activation == "command"
    assert result.session.until == T0 + timedelta(hours=1)


def test_custom_threshold_is_inclusive(tmp_path):
    env = make(tmp_path, CodeModeConfig(proposal_threshold=0.95))
    assert env.proposer.propose("low", "T2", 0.94, loc(), ACTIVATOR) is None
    assert env.proposer.propose("eq", "T2", 0.95, loc(), ACTIVATOR) is not None
