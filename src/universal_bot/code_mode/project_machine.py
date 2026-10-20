"""Transiciones legales de Project. Lo que no está en la tabla no pasa."""

from __future__ import annotations

from universal_bot.code_mode.models import ProjectState


class IllegalTransition(ValueError):
    """Ese cambio de estado no existe."""


def transition(current: ProjectState, target: ProjectState) -> ProjectState:
    raise NotImplementedError("transition")
