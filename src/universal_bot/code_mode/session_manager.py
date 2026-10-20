"""Sesión pegajosa de modo código por ubicación."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from universal_bot.code_mode.clock import Clock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.discord_port import DiscordPort
from universal_bot.code_mode.models import CodeModeSession, Location
from universal_bot.code_mode.projects import ProjectLedger


@dataclass(frozen=True)
class ActivateResult:
    ok: bool
    reason: str
    session: CodeModeSession | None


@dataclass(frozen=True)
class ExitResult:
    ok: bool
    reason: str
    session: CodeModeSession | None
    resume_token: str | None = None


@dataclass(frozen=True)
class RouteDecision:
    kind: str
    session: CodeModeSession | None


class SessionManager:
    def __init__(
        self,
        db_path: Path | str,
        clock: Clock,
        discord: DiscordPort,
        config: CodeModeConfig,
        projects: ProjectLedger,
    ):
        raise NotImplementedError("SessionManager")

    def activate(
        self,
        location: Location,
        actor_id: int,
        actor_roles: tuple[str, ...],
        duration: str,
        activation: str,
        project_id: str | None = None,
    ) -> ActivateResult:
        raise NotImplementedError("activate")

    def handle_text(
        self,
        location: Location,
        actor_id: int,
        actor_roles: tuple[str, ...],
        text: str,
    ) -> ActivateResult:
        raise NotImplementedError("handle_text")

    def resolve(self, location: Location) -> CodeModeSession | None:
        raise NotImplementedError("resolve")

    def get(self, session_id: str) -> CodeModeSession | None:
        raise NotImplementedError("get")

    def exit(
        self,
        location: Location,
        actor_id: int,
        actor_roles: tuple[str, ...],
    ) -> ExitResult:
        raise NotImplementedError("exit")

    def finish_atomic_step(self, project_id: str) -> ExitResult | None:
        raise NotImplementedError("finish_atomic_step")

    def tick(self) -> tuple[str, ...]:
        raise NotImplementedError("tick")

    def route(self, location: Location, text: str) -> RouteDecision:
        raise NotImplementedError("route")
