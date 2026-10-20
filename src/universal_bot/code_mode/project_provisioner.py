"""Crea el canal o el hilo de un proyecto, o se lo pregunta a un admin."""

from __future__ import annotations

from universal_bot.code_mode.clock import Clock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.discord_port import DiscordPort
from universal_bot.code_mode.models import ProjectMode
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.code_mode.session_manager import SessionManager


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

    def provision(self, **kwargs):
        raise NotImplementedError("provision")
