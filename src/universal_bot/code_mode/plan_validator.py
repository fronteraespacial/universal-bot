"""El plan se publica solo si cada paso tiene evidencia real o un «sin probar» consultado."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from universal_bot.code_mode.models import PendingQuestion, Plan, Project, ProjectState


class PlanRejection(Exception):
    def __init__(self, reasons: tuple[str, ...]):
        super().__init__(", ".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class PublishedPlan:
    project: Project
    approval_requested: bool
    buttons: tuple[str, ...]


def validate_plan(
    plan: Plan,
    *,
    lab_was_running: bool,
    open_questions: tuple[PendingQuestion, ...],
) -> None:
    reasons: list[str] = []
    if not plan.lab_evidence:
        reasons.append("missing_lab_evidence")
    if not lab_was_running:
        reasons.append("lab_not_run")
    known = {item.id: item for item in plan.lab_evidence}
    open_for_project = any(
        question.project_id == plan.project_id and question.answer is None for question in open_questions
    )
    for step in plan.steps:
        if not step.evidence_refs and not step.untested_reason:
            reasons.append(f"step_without_evidence:{step.id}")
        if not step.evidence_refs and step.untested_reason and not open_for_project:
            reasons.append(f"untested_without_question:{step.id}")
        for ref in step.evidence_refs:
            found = known.get(ref)
            if found is None or found.evidence_class != "running" or found.verdict != "APPROVE":
                reasons.append(f"invalid_evidence:{ref}")
    if reasons:
        raise PlanRejection(tuple(reasons))


def publish_plan(
    project: Project,
    plan: Plan,
    *,
    lab_was_running: bool,
    open_questions: tuple[PendingQuestion, ...],
    now: datetime,
) -> PublishedPlan:
    validate_plan(plan, lab_was_running=lab_was_running, open_questions=open_questions)
    updated = replace(
        project,
        state=ProjectState.PLAN_READY,
        requires_production=plan.requires_production,
        updated_at=now,
    )
    return PublishedPlan(updated, False, ())
