"""Ask bridge: libera el job, resume con token y sobrevive un reinicio."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from universal_bot.code_mode.ask_bridge import AskBridge
from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.fake_discord import FakeDiscord
from universal_bot.code_mode.models import ProjectState
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.contracts import JobRequest, JobStatus
from universal_bot.store import JobStore

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
APPROVER = 7
STRANGER = 9
FORBIDDEN = "No podés aprobar esto."


def make(tmp_path):
    clock = FakeClock(T0)
    discord = FakeDiscord()
    db = tmp_path / "mode.sqlite"
    ledger = ProjectLedger(db, clock)
    store = JobStore(db)
    config = CodeModeConfig()
    bridge = AskBridge(db, store, discord, clock, ledger, config)
    return SimpleNamespace(
        clock=clock, discord=discord, db=db, ledger=ledger, store=store, config=config, bridge=bridge
    )


def admit(store, message_id, channel_id):
    job, admitted, reason = store.admit_job(
        JobRequest.create(
            instance_name="code-mode",
            message_id=message_id,
            guild_id="42",
            channel_id=channel_id,
            author_id="7",
            prompt="trabajar",
            brain="code",
            workspace_dir=f"/tmp/{channel_id}",
        )
    )
    assert admitted is True
    assert reason == "admitted"
    return job


def buttons(message):
    return tuple((button.custom_id, button.label) for button in message.buttons)


def test_ask_releases_the_job_slot(tmp_path):
    env = make(tmp_path)
    first = admit(env.store, "m1", "c1")
    second = admit(env.store, "m2", "c2")
    claimed = env.store.claim_next_job("worker", max_concurrent=1)
    assert claimed.job_id == first.job_id
    assert env.store.start_job(claimed.job_id) is True
    assert env.store.claim_next_job("worker", max_concurrent=1) is None
    question = env.bridge.ask(
        project_id="P-missing",
        stage_key="02-lab",
        kind="advisor_card",
        prompt_plain="¿Seguimos?",
        options=("seguir", "frenar"),
        allowed_approvers=(APPROVER,),
        job_id=claimed.job_id,
        resume_token="resume-abc",
        channel_id=100,
        thread_id=None,
    )
    assert env.store.get_job_status(claimed.job_id) == JobStatus.WAITING_HUMAN
    nxt = env.store.claim_next_job("worker", max_concurrent=1)
    assert nxt.job_id == second.job_id
    assert question.blocking is False
    assert question.resume_token == "resume-abc"
    assert buttons(env.discord.messages[-1]) == (
        (f"ublab:pq:{question.id}:seguir", "seguir"),
        (f"ublab:pq:{question.id}:frenar", "frenar"),
    )


def test_answer_enqueues_resume_and_is_idempotent(tmp_path):
    env = make(tmp_path)
    job = admit(env.store, "m1", "c1")
    claimed = env.store.claim_next_job("worker", max_concurrent=1)
    env.store.start_job(claimed.job_id)
    question = env.bridge.ask(
        project_id="P-1",
        stage_key="04-impl",
        kind="advisor_card",
        prompt_plain="¿Seguimos?",
        options=("seguir", "frenar"),
        allowed_approvers=(APPROVER,),
        job_id=job.job_id,
        resume_token="resume-abc",
        channel_id=100,
        thread_id=5,
    )
    first = env.bridge.answer(question.id, "seguir", APPROVER)
    second = env.bridge.answer(question.id, "frenar", APPROVER)
    assert first.accepted is True
    assert first.duplicate is False
    assert first.answer == "seguir"
    assert second.duplicate is True
    assert second.answer == "seguir"
    assert second.resume_job_id == first.resume_job_id
    resumed = env.store.get_job(first.resume_job_id)
    assert resumed.prompt == "resume:resume-abc"
    assert env.store.get_job_status(first.resume_job_id) == JobStatus.QUEUED
    assert env.bridge.get(question.id).answered_by == APPROVER


def test_unauthorized_answer_does_not_change_state(tmp_path):
    env = make(tmp_path)
    job = admit(env.store, "m1", "c1")
    question = env.bridge.ask(
        project_id="P-1",
        stage_key="04-impl",
        kind="advisor_card",
        prompt_plain="¿Seguimos?",
        options=("seguir",),
        allowed_approvers=(APPROVER,),
        job_id=job.job_id,
        resume_token="resume-abc",
        channel_id=100,
        thread_id=None,
    )
    result = env.bridge.answer(question.id, "seguir", STRANGER)
    assert result.accepted is False
    assert result.resume_job_id is None
    assert env.bridge.get(question.id).answer is None
    assert env.discord.ephemeral == [(STRANGER, FORBIDDEN)]


def test_reminder_then_pause_with_fake_clock(tmp_path):
    env = make(tmp_path)
    project = env.ledger.create_project(
        guild_id=42, requester_id=APPROVER, state=ProjectState.RUNNING, title_plain="Turnos"
    )
    job = admit(env.store, "m1", "c1")
    env.bridge.ask(
        project_id=project.id,
        stage_key="03-plan",
        kind="sandbox_check_failed",
        prompt_plain="¿Seguimos?",
        options=("reintentar",),
        allowed_approvers=(APPROVER,),
        job_id=job.job_id,
        resume_token="resume-abc",
        channel_id=100,
        thread_id=None,
    )
    assert env.ledger.get_project(project.id).state == ProjectState.WAITING_HUMAN
    env.clock.advance(hours=4)
    assert env.bridge.tick() == ("reminded",)
    assert env.discord.messages[-1].content == "Recordatorio: ¿Seguimos?"
    assert env.ledger.get_project(project.id).state == ProjectState.WAITING_HUMAN
    env.clock.advance(hours=20)
    assert env.bridge.tick() == ("paused",)
    assert env.ledger.get_project(project.id).state == ProjectState.PAUSED


def test_question_survives_restart(tmp_path):
    env = make(tmp_path)
    job = admit(env.store, "m1", "c1")
    question = env.bridge.ask(
        project_id="P-1",
        stage_key="02-lab",
        kind="advisor_card",
        prompt_plain="¿Seguimos?",
        options=("seguir",),
        allowed_approvers=(APPROVER,),
        job_id=job.job_id,
        resume_token="resume-restart",
        channel_id=100,
        thread_id=None,
    )
    revived = AskBridge(env.db, JobStore(env.db), FakeDiscord(), env.clock, env.ledger, env.config)
    result = revived.answer(question.id, "seguir", APPROVER)
    assert result.accepted is True
    assert env.store.get_job(result.resume_job_id).prompt == "resume:resume-restart"


@pytest.mark.parametrize(
    ("kind", "blocking", "expected"),
    [
        ("advisor_card", None, False),
        ("human_brake", None, False),
        ("brief_confirm", None, False),
        ("code_mode_proposal", None, False),
        ("lab_inconclusive", False, False),
        ("prod_approval", None, True),
        ("sandbox_check_failed", None, True),
        ("admin_provision", None, True),
    ],
)
def test_blocking_defaults(tmp_path, kind, blocking, expected):
    env = make(tmp_path)
    question = env.bridge.ask(
        project_id=f"P-{kind}",
        stage_key=kind,
        kind=kind,
        prompt_plain="pregunta",
        options=("ok",),
        allowed_approvers=(APPROVER,),
        job_id=None,
        resume_token=f"resume-{kind}",
        channel_id=100,
        thread_id=None,
        blocking=blocking,
    )
    assert question.blocking is expected


def test_plan_approval_does_not_exist(tmp_path):
    env = make(tmp_path)
    with pytest.raises(ValueError, match="plan_approval"):
        env.bridge.ask(
            project_id="P-1",
            stage_key="03-plan",
            kind="plan_approval",
            prompt_plain="¿Apruebo el plan?",
            options=("sí",),
            allowed_approvers=(APPROVER,),
            job_id=None,
            resume_token="resume-plan",
            channel_id=100,
            thread_id=None,
        )


def test_one_open_question_per_stage(tmp_path):
    env = make(tmp_path)
    first = env.bridge.ask(
        project_id="P-1",
        stage_key="02-lab",
        kind="advisor_card",
        prompt_plain="primera",
        options=("a",),
        allowed_approvers=(APPROVER,),
        job_id=None,
        resume_token="resume-1",
        channel_id=100,
        thread_id=None,
    )
    second = env.bridge.ask(
        project_id="P-1",
        stage_key="02-lab",
        kind="advisor_card",
        prompt_plain="segunda",
        options=("b",),
        allowed_approvers=(APPROVER,),
        job_id=None,
        resume_token="resume-2",
        channel_id=100,
        thread_id=None,
    )
    other = env.bridge.ask(
        project_id="P-1",
        stage_key="03-plan",
        kind="advisor_card",
        prompt_plain="otra etapa",
        options=("c",),
        allowed_approvers=(APPROVER,),
        job_id=None,
        resume_token="resume-3",
        channel_id=100,
        thread_id=None,
    )
    assert first.message_id is not None
    assert second.message_id is None
    assert other.message_id is not None
    posted = [message for message in env.discord.messages if message.buttons]
    assert len(posted) == 2
    env.bridge.answer(first.id, "a", APPROVER)
    revived_buttons = [message for message in env.discord.messages if message.buttons]
    assert len(revived_buttons) == 3
    assert env.bridge.get(second.id).message_id == revived_buttons[-1].message_id
