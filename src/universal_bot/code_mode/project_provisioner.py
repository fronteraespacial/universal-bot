"""Crea el canal o el hilo de un proyecto, o se lo pregunta a un admin."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from universal_bot.code_mode.clock import Clock
from universal_bot.code_mode.config import CodeModeConfig, role_allowed
from universal_bot.code_mode.discord_port import DiscordPort, Overwrite
from universal_bot.code_mode.models import CodeModeSession, Location, Project, ProjectMode, ProjectState
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.code_mode.session_manager import SessionManager

_CHANNEL_ALLOW = ("view_channel", "send_messages", "read_message_history")
OFFER_THREAD = "Llegamos al tope de canales. Lo podemos abrir como hilo."
ASKED_ADMIN = "Se lo pasé a un admin."


@dataclass(frozen=True)
class ProvisionResult:
    state: str
    project: Project | None
    session: CodeModeSession | None


class ProjectProvisioner:
    def __init__(
        self,
        discord: DiscordPort,
        sessions: SessionManager,
        projects: ProjectLedger,
        config: CodeModeConfig,
        clock: Clock,
    ):
        self.discord = discord
        self.sessions = sessions
        self.projects = projects
        self.config = config
        self.clock = clock

    def provision(
        self,
        *,
        guild_id: int,
        actor_id: int,
        actor_roles: tuple[str, ...],
        requester_id: int,
        title: str,
        tier: str,
        mode: ProjectMode,
        origin_channel_id: int,
    ) -> ProvisionResult:
        mode = ProjectMode(mode)
        if not _role_can(self.config, mode, actor_roles):
            return self._ask_admin(
                guild_id=guild_id,
                requester_id=requester_id,
                title=title,
                tier=tier,
                mode=mode,
                origin_channel_id=origin_channel_id,
            )
        if mode == ProjectMode.CHANNEL and not self.discord.check_permissions(guild_id, "manage_channels"):
            mode = ProjectMode.THREAD
        if mode == ProjectMode.CHANNEL and self._channel_cap_full(guild_id):
            self.discord.send(origin_channel_id, OFFER_THREAD)
            return ProvisionResult("offer_thread", None, None)
        return self._open(
            guild_id=guild_id,
            actor_id=actor_id,
            actor_roles=actor_roles,
            requester_id=requester_id,
            title=title,
            tier=tier,
            mode=mode,
        )

    def _ask_admin(self, *, guild_id, requester_id, title, tier, mode, origin_channel_id) -> ProvisionResult:
        project = self._save_project(
            guild_id=guild_id,
            requester_id=requester_id,
            title=title,
            tier=tier,
            mode=mode,
            state=ProjectState.PENDING_ADMIN,
            channel_id=None,
            root_thread_id=None,
        )
        self.discord.send(origin_channel_id, ASKED_ADMIN)
        admin_id = self.discord.channel_id_by_name(guild_id, self.config.roles.admin_review_channel)
        self.discord.send(admin_id, f"¿Crear el proyecto {title}?")
        return ProvisionResult("pending_admin", project, None)

    def _open(self, *, guild_id, actor_id, actor_roles, requester_id, title, tier, mode) -> ProvisionResult:
        slug = _next_slug(_slugify(title), set(self.projects.slugs(guild_id)))
        name = f"{self.config.channel_prefix}{slug}"
        if mode == ProjectMode.CHANNEL:
            channel_id = self.discord.create_channel(
                guild_id,
                name,
                category_name=self.config.projects_category,
                overwrites=(
                    Overwrite(target=f"user:{actor_id}", allow=_CHANNEL_ALLOW),
                ),
            )
            thread_id = None
            activation = "project_channel"
        else:
            channel_id = self.discord.channel_id_by_name(guild_id, self.config.projects_channel)
            thread_id = self.discord.create_thread(channel_id, name)
            activation = "project_thread"
        project = self._save_project(
            guild_id=guild_id,
            requester_id=requester_id,
            title=title,
            tier=tier,
            mode=mode,
            state=ProjectState.PROVISIONING,
            channel_id=channel_id,
            root_thread_id=thread_id,
            slug=slug,
        )
        opened = self.sessions.activate(
            Location(guild_id, channel_id, thread_id),
            actor_id,
            actor_roles,
            "until_exit",
            activation,
            project_id=project.id,
            bypass_role_check=True,
        )
        return ProvisionResult("provisioned", project, opened.session)

    def _save_project(self, *, guild_id, requester_id, title, tier, mode, state, channel_id, root_thread_id, slug=None):
        return self.projects.create_project(
            guild_id=guild_id,
            requester_id=requester_id,
            title_plain=title,
            slug=slug or _next_slug(_slugify(title), set(self.projects.slugs(guild_id))),
            tier=tier,
            mode=mode,
            state=state,
            channel_id=channel_id,
            root_thread_id=root_thread_id,
        )

    def _channel_cap_full(self, guild_id: int) -> bool:
        return self.projects.count_open_channel_projects(guild_id) >= self.config.max_open_projects


def _role_can(config: CodeModeConfig, mode: ProjectMode, actor_roles: tuple[str, ...]) -> bool:
    if mode == ProjectMode.CHANNEL:
        return role_allowed(config.roles.can_start_project, actor_roles)
    return role_allowed(config.roles.can_start_thread, actor_roles)


def _slugify(title: str) -> str:
    folded = unicodedata.normalize("NFKD", title)
    ascii_text = "".join(char for char in folded if not unicodedata.combining(char)).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug or "proyecto"


def _next_slug(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    number = 2
    while f"{base}-{number}" in taken:
        number += 1
    return f"{base}-{number}"
