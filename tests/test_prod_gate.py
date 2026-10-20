"""Pase a producción: sin aprobación no se ejecuta, y en T3 solo un dev."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from universal_bot.code_mode.config import ApprovalPolicy
from universal_bot.code_mode.models import ProductionAction, Project, ProjectMode, ProjectState
from universal_bot.code_mode.prod_gate import (
    NeedsProductionApproval,
    approve,
    can_approve,
    complete_without_production,
    intercept_irreversible,
    may_execute,
    reject_production,
    request_production,
)

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
REQUESTER = 7
DEV = 8
OTHER = 9


def project(**overrides) -> Project:
    base = Project(
        id="P-1",
        guild_id=1,
        requester_id=REQUESTER,
        origin_message_id=1,
        slug="reservas-api",
        title_plain="Reservas",
        tier="T2",
        work_type="evolving-product",
        mode=ProjectMode.THREAD,
        state=ProjectState.RUNNING,
        channel_id=10,
        root_thread_id=9,
        run_id="R-1",
        wave="O1",
        sandbox_id="sb",
        last_security_check=None,
        requires_production=True,
        created_at=T0,
        updated_at=T0,
    )
    return replace(base, **overrides)


def action(kind="deploy") -> ProductionAction:
    return ProductionAction("P-1", kind, "prod", "Subir a producción")


@pytest.mark.parametrize(
    "kind",
    ["deploy", "merge_prod_branch", "env_change", "discord_irreversible", "server_irreversible"],
)
def test_production_kind_without_approval_does_not_execute(kind):
    gated, gated_action = request_production(project(), action(kind), T0)
    assert gated.state == ProjectState.PENDING_PROD_APPROVAL
    assert gated_action.approved_by is None
    assert may_execute(gated, gated_action) is False


@pytest.mark.parametrize(
    ("mode", "user_id", "roles", "accepted"),
    [
        ("requester", REQUESTER, (), True),
        ("requester", DEV, ("@dev",), False),
        ("dev", REQUESTER, (), False),
        ("dev", DEV, ("@dev",), True),
        ("requester|dev", REQUESTER, (), True),
        ("requester|dev", DEV, ("@dev",), True),
        ("requester|dev", OTHER, (), False),
    ],
)
def test_who_can_approve_on_t2(mode, user_id, roles, accepted):
    item = project(tier="T2", state=ProjectState.PENDING_PROD_APPROVAL)
    approvals = ApprovalPolicy(production=mode)
    assert can_approve(item, user_id, roles, approvals) is accepted


def test_t3_rejects_the_requester_without_a_dev_role():
    item = project(tier="T3", state=ProjectState.PENDING_PROD_APPROVAL)
    decision = approve(item, action(), REQUESTER, (), ApprovalPolicy(production="requester|dev"), T0)
    assert decision.accepted is False
    assert decision.reason == "forbidden"
    assert decision.project.state == ProjectState.PENDING_PROD_APPROVAL
    assert may_execute(decision.project, decision.action) is False


def test_t3_dev_moves_the_project_to_deploying():
    item = project(tier="T3", state=ProjectState.PENDING_PROD_APPROVAL)
    decision = approve(item, action(), DEV, ("@dev",), ApprovalPolicy(), T0)
    assert decision.accepted is True
    assert decision.reason == "approved"
    assert decision.project.state == ProjectState.DEPLOYING
    assert decision.action.approved_by == DEV
    assert decision.action.approved_at == T0
    assert may_execute(decision.project, decision.action) is True


def test_reject_returns_to_running_for_a_corrective():
    updated = reject_production(project(state=ProjectState.PENDING_PROD_APPROVAL), T0)
    assert updated.state == ProjectState.RUNNING
    assert updated.updated_at == T0


def test_project_without_production_finishes_done():
    updated = complete_without_production(project(state=ProjectState.RUNNING, requires_production=False), T0)
    assert updated.state == ProjectState.DONE


def test_required_production_cannot_skip_the_gate():
    with pytest.raises(NeedsProductionApproval):
        complete_without_production(project(requires_production=True), T0)


def test_unplanned_irreversible_action_is_intercepted():
    gated, gated_action = intercept_irreversible(
        project(state=ProjectState.RUNNING, requires_production=False),
        action("discord_irreversible"),
        T0,
    )
    assert gated.state == ProjectState.PENDING_PROD_APPROVAL
    assert gated.requires_production is True
    assert gated_action.approved_by is None
    assert may_execute(gated, gated_action) is False
