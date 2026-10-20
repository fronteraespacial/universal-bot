"""Propuesta de pasar a modo código. Una sola vez por pedido."""

from __future__ import annotations

from universal_bot.code_mode.clock import Clock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.discord_port import DiscordPort
from universal_bot.code_mode.models import Location
from universal_bot.code_mode.session_manager import SessionManager


class Proposer:
    def __init__(
        self,
        discord: DiscordPort,
        sessions: SessionManager,
        config: CodeModeConfig,
        clock: Clock,
    ):
        self.discord = discord
        self.sessions = sessions
        self.config = config
        self.clock = clock

    def propose(self, request_id: str, tier: str, confidence: float, location: Location, actor_id: int):
        raise NotImplementedError("propose")

    def choose(self, request_id: str, option: str, actor_id: int, actor_roles: tuple[str, ...], duration: str | None = None):
        raise NotImplementedError("choose")

    def activate_manual(self, location: Location, actor_id: int, actor_roles: tuple[str, ...], text: str):
        raise NotImplementedError("activate_manual")
