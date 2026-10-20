"""Validador de plan: sin evidencia real no se publica, y no pide aprobación."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from universal_bot.code_mode.models import (
    LabEvidence,
    PendingQuestion,
    Plan,
    PlanStep,
    Project,
    ProjectMode,
    ProjectState,
)
from universal_bot.code_mode.plan_validator import PlanRejection, publish_plan, validate_plan

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def evidence(**overrides) -> LabEvidence:
    base = LabEvidence(
        id="LE-1",
        project_id="P-1",
        lab_path=".lab/2026-10-20-reservas/",
        role="lab-runner",
        hypothesis="el slug alcanza",
        commands=("pytest -q",),
        result="1 passed",
        artifacts=(".lab/2026-10-20-reservas/out.txt",),
        verdict="APPROVE",
        evidence_class="running",
        security_check_ref="SC-1",
        started_at=T0,
        finished_at=T0,
        timed_out=False,
    )
    return replace(base, **overrides)


def step(**overrides) -> PlanStep:
    base = PlanStep(
        id="S1",
        workstream="api",
        summary="publicar el slug",
        paths=("src/slug.py",),
        evidence_refs=("LE-1",),
        untested_reason=None,
    )
    return replace(base, **overrides)


def make_plan(steps, lab_evidence=(evidence(),), requires_production=False) -> Plan:
    return Plan("P-1", "O1", tuple(steps), tuple(lab_evidence), "CONSULT: sin cambios", requires_production)


def question() -> PendingQuestion:
    return PendingQuestion(
        id="PQ-1",
        project_id="P-1",
        stage_key="02-lab",
        kind="sandbox_check_failed",
        blocking=True,
        prompt_plain="No pude probar el paso",
        detail_ref=None,
        options=("reintentar",),
        allowed_approvers=(7,),
        message_id=1,
        asked_at=T0,
        remind_at=T0,
        pause_at=T0,
        answer=None,
        answered_by=None,
        answered_at=None,
        resume_token="resume-plan",
    )


def item() -> Project:
    return Project(
        id="P-1",
        guild_id=1,
        requester_id=7,
        origin_message_id=1,
        slug="reservas-api",
        title_plain="Reservas",
        tier="T2",
        work_type="evolving-product",
        mode=ProjectMode.THREAD,
        state=ProjectState.LAB_RUNNING,
        channel_id=10,
        root_thread_id=9,
        run_id="R-1",
        wave="O1",
        sandbox_id="sb",
        last_security_check=None,
        requires_production=False,
        created_at=T0,
        updated_at=T0,
    )


def reasons_of(plan, **kwargs) -> tuple[str, ...]:
    payload = {"lab_was_running": True, "open_questions": ()}
    payload.update(kwargs)
    with pytest.raises(PlanRejection) as caught:
        validate_plan(plan, **payload)
    return caught.value.reasons


def test_plan_without_lab_evidence_is_rejected():
    assert reasons_of(make_plan((step(),), lab_evidence=())) == ("missing_lab_evidence", "invalid_evidence:LE-1")


def test_step_without_refs_or_reason_is_rejected():
    plan = make_plan((step(evidence_refs=(), untested_reason=None),))
    assert reasons_of(plan) == ("step_without_evidence:S1",)


@pytest.mark.parametrize(
    ("verdict", "evidence_class"),
    [
        ("REJECT", "running"),
        ("INCONCLUSIVE", "running"),
        ("APPROVE", "paper"),
        ("REVISE", "running"),
        ("YIELD", "running"),
    ],
)
def test_bad_evidence_is_rejected(verdict, evidence_class):
    plan = make_plan((step(),), (evidence(verdict=verdict, evidence_class=evidence_class),))
    assert reasons_of(plan) == ("invalid_evidence:LE-1",)


def test_untested_step_without_a_question_is_rejected():
    plan = make_plan((step(evidence_refs=(), untested_reason="sin probar: no hay sandbox"),))
    assert reasons_of(plan) == ("untested_without_question:S1",)


def test_untested_step_with_an_open_question_is_accepted():
    plan = make_plan((step(evidence_refs=(), untested_reason="sin probar: no hay sandbox"),))
    validate_plan(plan, lab_was_running=True, open_questions=(question(),))


def test_plan_ready_requires_a_previous_lab_run():
    plan = make_plan((step(),))
    with pytest.raises(PlanRejection) as caught:
        publish_plan(item(), plan, lab_was_running=False, open_questions=(), now=T0)
    assert caught.value.reasons == ("lab_not_run",)


def test_valid_plan_is_published_without_approval():
    plan = make_plan((step(),), requires_production=False)
    published = publish_plan(item(), plan, lab_was_running=True, open_questions=(), now=T0)
    assert published.project.state == ProjectState.PLAN_READY
    assert published.project.requires_production is False
    assert published.approval_requested is False
    assert published.buttons == ()
    assert published.project.updated_at == T0
