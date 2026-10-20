"""Answers del puente: ask, producción y stop. El primero gana."""

import json
from datetime import datetime, timezone

from universal_bot.code_mode.answers import consume_answers
from universal_bot.code_mode.ask_bridge import AskBridge
from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import ApprovalPolicy, CodeModeConfig
from universal_bot.code_mode.fake_discord import FakeDiscord
from universal_bot.code_mode.models import ProjectState
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.store import JobStore

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
APPROVER = 7
DEV = 8
REQUESTER = 7


def spool_of(path):
    for name in ("inbox", "outbox", "answers"):
        (path / name).mkdir(parents=True)
    return path


def write_answer(spool, kind, item_id, opt, user_id):
    payload = {
        "version": 1,
        "kind": kind,
        "id": item_id,
        "opt": opt,
        "user_id": str(user_id),
        "channel_id": "100",
        "message_id": "200",
        "interaction_id": f"ix-{kind}-{item_id}",
        "ts": 10.0,
    }
    (spool / "answers" / f"{kind}__{item_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def env(tmp_path):
    clock = FakeClock(T0)
    discord = FakeDiscord()
    db = tmp_path / "mode.sqlite"
    ledger = ProjectLedger(db, clock)
    bridge = AskBridge(db, JobStore(db), discord, clock, ledger, CodeModeConfig())
    return clock, ledger, bridge


def test_pq_click_answers_once_and_ignores_a_later_rewrite(tmp_path):
    clock, ledger, bridge = env(tmp_path)
    question = bridge.ask(
        project_id="P-1",
        stage_key="02-lab",
        kind="advisor_card",
        prompt_plain="¿Seguimos?",
        options=("seguir", "frenar"),
        allowed_approvers=(APPROVER,),
        job_id=None,
        resume_token="resume-1",
        channel_id=100,
        thread_id=None,
    )
    root = spool_of(tmp_path / "spool")
    write_answer(root, "pq", question.id, "seguir", APPROVER)
    first = consume_answers(root, clock=clock, ask_bridge=bridge, projects=ledger)
    assert bridge.get(question.id).answer == "seguir"
    assert len(first) == 1
    write_answer(root, "pq", question.id, "frenar", APPROVER)
    second = consume_answers(root, clock=clock, ask_bridge=bridge, projects=ledger)
    assert second == ()
    assert bridge.get(question.id).answer == "seguir"


def test_prod_click_uses_the_gate(tmp_path):
    clock, ledger, bridge = env(tmp_path)
    project = ledger.create_project(
        id="P-9",
        guild_id=1,
        requester_id=REQUESTER,
        state=ProjectState.PENDING_PROD_APPROVAL,
        tier="T3",
        requires_production=True,
    )
    root = spool_of(tmp_path / "spool")
    write_answer(root, "prod", project.id, "approve", REQUESTER)
    consume_answers(
        root,
        clock=clock,
        ask_bridge=bridge,
        projects=ledger,
        approvals=ApprovalPolicy(),
        role_lookup=lambda user: () if user == REQUESTER else ("@dev",),
    )
    assert ledger.get_project(project.id).state == ProjectState.PENDING_PROD_APPROVAL
    other = ledger.create_project(
        id="P-8",
        guild_id=1,
        requester_id=REQUESTER,
        state=ProjectState.PENDING_PROD_APPROVAL,
        tier="T3",
        requires_production=True,
    )
    write_answer(root, "prod", other.id, "approve", DEV)
    approved = consume_answers(
        root,
        clock=clock,
        projects=ledger,
        approvals=ApprovalPolicy(),
        role_lookup=lambda user: ("@dev",) if user == DEV else (),
    )
    assert ledger.get_project(other.id).state == ProjectState.DEPLOYING
    assert approved[0].action.approved_by == DEV
    rejected = ledger.create_project(
        id="P-7",
        guild_id=1,
        requester_id=REQUESTER,
        state=ProjectState.PENDING_PROD_APPROVAL,
        tier="T2",
    )
    write_answer(root, "prod", rejected.id, "reject", REQUESTER)
    consume_answers(root, clock=clock, projects=ledger, approvals=ApprovalPolicy(), role_lookup=lambda user: ())
    assert ledger.get_project(rejected.id).state == ProjectState.RUNNING


def test_stop_pauses_the_job_and_checkpoints_the_project(tmp_path):
    clock, ledger, _bridge = env(tmp_path)
    project = ledger.create_project(id="P-stop", guild_id=1, requester_id=REQUESTER, state=ProjectState.RUNNING)
    root = spool_of(tmp_path / "spool")
    job_dir = root / "inbox" / "lc_555"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(json.dumps({"job_id": "job-1"}), encoding="utf-8")
    (job_dir / "state.json").write_text(
        json.dumps({"version": 1, "status": "running", "project_id": project.id, "op_ids": ["op-1"]}),
        encoding="utf-8",
    )
    write_answer(root, "stop", "job-1", "ahora", REQUESTER)
    consume_answers(root, clock=clock, projects=ledger)
    state = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "paused"
    assert state["project_id"] == project.id
    assert state["op_ids"] == ["op-1"]
    assert ledger.get_project(project.id).state == ProjectState.PAUSED
    token = ledger.last_checkpoint(project.id).resume_token
    consume_answers(root, clock=clock, projects=ledger)
    assert ledger.last_checkpoint(project.id).resume_token == token
