"""Única aprobación obligatoria: el pase a producción."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from universal_bot.code_mode.config import ApprovalPolicy
from universal_bot.code_mode.models import ProductionAction, Project, ProjectState


class NeedsProductionApproval(Exception):
    pass


@dataclass(frozen=True)
class ProdDecision:
    accepted: bool
    project: Project
    action: ProductionAction
    reason: str


def request_production(
    project: Project,
    action: ProductionAction,
    now: datetime,
) -> tuple[Project, ProductionAction]:
    return (
        replace(project, state=ProjectState.PENDING_PROD_APPROVAL, requires_production=True, updated_at=now),
        action,
    )


def may_execute(project: Project, action: ProductionAction) -> bool:
    return project.state == ProjectState.DEPLOYING and action.approved_by is not None


def can_approve(project: Project, user_id: int, roles: tuple[str, ...], approvals: ApprovalPolicy) -> bool:
    is_requester = user_id == project.requester_id
    is_dev = any(role in approvals.dev_roles for role in roles)
    if project.tier == "T3":
        return is_dev
    if approvals.production == "requester":
        return is_requester
    if approvals.production == "dev":
        return is_dev
    if approvals.production == "requester|dev":
        return is_requester or is_dev
    return False


def approve(
    project: Project,
    action: ProductionAction,
    user_id: int,
    roles: tuple[str, ...],
    approvals: ApprovalPolicy,
    now: datetime,
) -> ProdDecision:
    if not can_approve(project, user_id, roles, approvals):
        return ProdDecision(False, project, action, "forbidden")
    updated = replace(
        project,
        state=ProjectState.DEPLOYING,
        updated_at=now,
    )
    approved = replace(action, approved_by=user_id, approved_at=now)
    return ProdDecision(True, updated, approved, "approved")


def reject_production(project: Project, now: datetime) -> Project:
    return replace(project, state=ProjectState.RUNNING, updated_at=now)


def complete_without_production(project: Project, now: datetime) -> Project:
    if project.requires_production:
        raise NeedsProductionApproval("el pase a producción es obligatorio")
    return replace(project, state=ProjectState.DONE, updated_at=now)


def intercept_irreversible(
    project: Project,
    action: ProductionAction,
    now: datetime,
) -> tuple[Project, ProductionAction]:
    return request_production(project, action, now)
