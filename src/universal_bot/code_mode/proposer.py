"""Propuesta de pasar a modo código. Una sola vez por pedido."""

from __future__ import annotations

from dataclasses import dataclass, replace

from universal_bot.code_mode.clock import Clock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.custom_id import build_custom_id
from universal_bot.code_mode.discord_port import Button, DiscordPort
from universal_bot.code_mode.models import CodeModeSession, Location
from universal_bot.code_mode.session_manager import ActivateResult, SessionManager

PROMPT = "¿Pasamos a modo programación?"
_OPTION_LABELS = {
    "create_channel": "Crear un canal para el proyecto",
    "create_thread": "Crear un hilo de proyecto en #proyectos",
    "decline": "No, resolvelo como siempre",
}
_DURATION_LABELS = {
    "1h": "Programar acá mismo · 1 h",
    "4h": "Programar acá mismo · 4 h",
    "until_exit": "Programar acá mismo · hasta que salga",
}


@dataclass(frozen=True)
class Proposal:
    request_id: str
    tier: str
    options: tuple[str, ...]
    duration_options: tuple[str, ...]
    location: Location
    message_id: int | None = None


@dataclass(frozen=True)
class Choice:
    kind: str
    override_tier: str | None
    session: CodeModeSession | None
    mode: str | None = None


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
        self._proposals: dict[str, Proposal] = {}

    def propose(
        self,
        request_id: str,
        tier: str,
        confidence: float,
        location: Location,
        actor_id: int,
    ) -> Proposal | None:
        del actor_id
        if tier not in self.config.propose_tiers:
            return None
        if confidence < self.config.proposal_threshold:
            return None
        existing = self._proposals.get(request_id)
        if existing is not None:
            return existing
        options = ["create_thread", "here", "decline"]
        if self.config.allow_channels:
            options.insert(0, "create_channel")
        proposal = Proposal(
            request_id=request_id,
            tier=tier,
            options=tuple(options),
            duration_options=self.config.duration_options,
            location=location,
        )
        message_id = self.discord.send_buttons(
            location.channel_id,
            PROMPT,
            _buttons_for(proposal),
            thread_id=location.thread_id,
        )
        stored = replace(proposal, message_id=message_id)
        self._proposals[request_id] = stored
        return stored

    def choose(
        self,
        request_id: str,
        option: str,
        actor_id: int,
        actor_roles: tuple[str, ...],
        duration: str | None = None,
    ) -> Choice:
        proposal = self._proposals[request_id]
        if option == "decline":
            return Choice("basic_cli", proposal.tier, None, None)
        if option == "here":
            result = self.sessions.activate(
                proposal.location,
                actor_id,
                actor_roles,
                duration or self.config.default_duration,
                "proposal_here",
            )
            if not result.ok:
                return Choice("forbidden", None, None, None)
            return Choice("session", None, result.session, None)
        if option == "create_channel":
            return Choice("provision", None, None, "channel")
        if option == "create_thread":
            return Choice("provision", None, None, "thread")
        raise ValueError(option)

    def activate_manual(
        self,
        location: Location,
        actor_id: int,
        actor_roles: tuple[str, ...],
        text: str,
    ) -> ActivateResult:
        return self.sessions.handle_text(location, actor_id, actor_roles, text)


def _buttons_for(proposal: Proposal) -> tuple[Button, ...]:
    buttons: list[Button] = []
    for option in proposal.options:
        if option == "here":
            for duration in proposal.duration_options:
                buttons.append(
                    Button(
                        build_custom_id("propose", proposal.request_id, f"here_{duration}"),
                        _DURATION_LABELS[duration],
                    )
                )
            continue
        buttons.append(
            Button(
                build_custom_id("propose", proposal.request_id, option),
                _OPTION_LABELS[option],
            )
        )
    return tuple(buttons)
