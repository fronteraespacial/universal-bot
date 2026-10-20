"""Alta de canal o hilo de proyecto, con tope, permisos y slug único."""

from datetime import datetime, timezone
from types import SimpleNamespace

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import CodeModeConfig, RolePolicy
from universal_bot.code_mode.discord_port import Overwrite
from universal_bot.code_mode.fake_discord import FakeDiscord
from universal_bot.code_mode.models import Location, ProjectMode, ProjectState, SessionStatus
from universal_bot.code_mode.project_provisioner import ProjectProvisioner
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.code_mode.session_manager import SessionManager

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
GUILD = 42
ACTOR = 7
ORIGIN = 100


def make(tmp_path, config=None, manage_channels=True):
    clock = FakeClock(T0)
    discord = FakeDiscord()
    discord.permissions["manage_channels"] = manage_channels
    config = config or CodeModeConfig()
    db = tmp_path / "mode.sqlite"
    ledger = ProjectLedger(db, clock)
    sessions = SessionManager(db, clock, discord, config, ledger)
    provisioner = ProjectProvisioner(discord, sessions, ledger, config, clock)
    return SimpleNamespace(
        clock=clock,
        discord=discord,
        config=config,
        ledger=ledger,
        sessions=sessions,
        provisioner=provisioner,
    )


def provision(env, *, title="Reservas API", mode=ProjectMode.CHANNEL, roles=("@dev",), actor_id=ACTOR):
    return env.provisioner.provision(
        guild_id=GUILD,
        actor_id=actor_id,
        actor_roles=roles,
        requester_id=actor_id,
        title=title,
        tier="T2",
        mode=mode,
        origin_channel_id=ORIGIN,
    )


def test_role_without_permission_asks_admin_and_does_not_create_channel(tmp_path):
    env = make(tmp_path)
    result = provision(env, roles=())
    assert result.state == "pending_admin"
    assert result.project.state == ProjectState.PENDING_ADMIN
    assert result.session is None
    assert env.discord.create_channel_calls == 0
    assert env.discord.threads == []
    assert env.discord.channels == []
    assert [(message.channel_id, message.content) for message in env.discord.messages] == [
        (ORIGIN, "Se lo pasé a un admin."),
        (800, "¿Crear el proyecto Reservas API?"),
    ]
    saved = env.ledger.get_project(result.project.id)
    assert saved.state == ProjectState.PENDING_ADMIN


def test_thread_without_permission_also_asks_admin(tmp_path):
    env = make(tmp_path, CodeModeConfig(roles=RolePolicy(can_start_thread=("@dev",))))
    result = provision(env, mode=ProjectMode.THREAD, roles=())
    assert result.state == "pending_admin"
    assert env.discord.create_channel_calls == 0
    assert env.discord.threads == []


def test_full_channel_cap_offers_a_thread(tmp_path):
    env = make(tmp_path, CodeModeConfig(max_open_projects=1))
    env.ledger.create_project(
        guild_id=GUILD,
        requester_id=ACTOR,
        mode=ProjectMode.CHANNEL,
        state=ProjectState.RUNNING,
        slug="otro",
        title_plain="Otro",
    )
    result = provision(env)
    assert result.state == "offer_thread"
    assert result.project is None
    assert result.session is None
    assert env.discord.create_channel_calls == 0
    assert env.discord.messages[-1].content == "Llegamos al tope de canales. Lo podemos abrir como hilo."


def test_missing_manage_channels_degrades_to_thread(tmp_path):
    env = make(tmp_path, manage_channels=False)
    result = provision(env)
    assert result.state == "provisioned"
    assert result.project.mode == ProjectMode.THREAD
    assert result.project.slug == "reservas-api"
    assert result.project.state == ProjectState.PROVISIONING
    assert env.discord.create_channel_calls == 0
    assert env.discord.threads[0].name == "p-reservas-api"
    assert env.discord.threads[0].channel_id == 700
    session = env.sessions.resolve(Location(GUILD, 700, result.project.root_thread_id))
    assert session.id == result.session.id
    assert session.status == SessionStatus.ACTIVE
    assert session.until is None
    assert session.activation == "project_thread"
    assert session.project_id == result.project.id


def test_channel_is_unique_and_opens_an_unbounded_session(tmp_path):
    env = make(tmp_path)
    first = provision(env, title="Reservas API")
    second = provision(env, title="Reservas API")
    third = provision(env, title="Diseño UI")
    assert first.project.slug == "reservas-api"
    assert second.project.slug == "reservas-api-2"
    assert third.project.slug == "diseno-ui"
    assert [channel.name for channel in env.discord.channels] == [
        "p-reservas-api",
        "p-reservas-api-2",
        "p-diseno-ui",
    ]
    assert env.discord.channels[0].category_name == "Proyectos"
    assert env.discord.channels[0].overwrites == (
        Overwrite(
            target=f"user:{ACTOR}",
            allow=("view_channel", "send_messages", "read_message_history"),
        ),
    )
    session = env.sessions.resolve(Location(GUILD, first.project.channel_id, None))
    assert session.status == SessionStatus.ACTIVE
    assert session.until is None
    assert session.activation == "project_channel"
    assert session.project_id == first.project.id
    assert first.project.state == ProjectState.PROVISIONING


def test_thread_mode_uses_the_projects_channel(tmp_path):
    env = make(tmp_path)
    result = provision(env, mode=ProjectMode.THREAD, roles=())
    assert result.state == "provisioned"
    assert result.project.mode == ProjectMode.THREAD
    assert env.discord.create_channel_calls == 0
    assert env.discord.threads[0].channel_id == 700
    assert env.discord.threads[0].name == "p-reservas-api"
    assert result.session.until is None
    assert result.session.activation == "project_thread"
