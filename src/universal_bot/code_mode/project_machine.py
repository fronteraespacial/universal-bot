"""Transiciones legales de Project. Lo que no está en la tabla no pasa."""

from __future__ import annotations

from universal_bot.code_mode.models import ProjectState

_ALLOWED: dict[ProjectState, frozenset[ProjectState]] = {
    ProjectState.PROPOSED: frozenset(
        {ProjectState.DECLINED, ProjectState.PENDING_ADMIN, ProjectState.PROVISIONING}
    ),
    ProjectState.PENDING_ADMIN: frozenset({ProjectState.PROVISIONING, ProjectState.DECLINED}),
    ProjectState.PROVISIONING: frozenset({ProjectState.SANDBOX_CHECK}),
    ProjectState.SANDBOX_CHECK: frozenset(
        {ProjectState.LAB_RUNNING, ProjectState.WAITING_HUMAN, ProjectState.RUNNING}
    ),
    ProjectState.LAB_RUNNING: frozenset(
        {
            ProjectState.SANDBOX_CHECK,
            ProjectState.PLAN_READY,
            ProjectState.LAB_RUNNING,
            ProjectState.WAITING_HUMAN,
        }
    ),
    ProjectState.PLAN_READY: frozenset({ProjectState.RUNNING}),
    ProjectState.RUNNING: frozenset(
        {
            ProjectState.SANDBOX_CHECK,
            ProjectState.WAITING_HUMAN,
            ProjectState.ESCALATED,
            ProjectState.DONE,
            ProjectState.PENDING_PROD_APPROVAL,
            ProjectState.CANCELLED,
        }
    ),
    ProjectState.WAITING_HUMAN: frozenset({ProjectState.RUNNING, ProjectState.PAUSED}),
    ProjectState.PAUSED: frozenset({ProjectState.RUNNING, ProjectState.CANCELLED}),
    ProjectState.ESCALATED: frozenset({ProjectState.RUNNING}),
    ProjectState.PENDING_PROD_APPROVAL: frozenset(
        {ProjectState.DEPLOYING, ProjectState.RUNNING, ProjectState.PAUSED}
    ),
    ProjectState.DEPLOYING: frozenset({ProjectState.DONE, ProjectState.ESCALATED}),
    ProjectState.DONE: frozenset({ProjectState.ARCHIVED}),
    ProjectState.CANCELLED: frozenset(),
    ProjectState.DECLINED: frozenset(),
    ProjectState.ARCHIVED: frozenset(),
}


class IllegalTransition(ValueError):
    """Ese cambio de estado no existe."""


def transition(current: ProjectState, target: ProjectState) -> ProjectState:
    current = ProjectState(current)
    target = ProjectState(target)
    if target not in _ALLOWED[current]:
        raise IllegalTransition(f"{current.value} → {target.value}")
    return target
