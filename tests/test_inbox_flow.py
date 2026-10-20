"""El inbox pasa por CodeModeApp: triage, sesión, lab y el spool sin esperar results."""

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from universal_bot.code_mode.app import CodeModeApp
from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import CodeModeConfig, load_code_mode_config
from universal_bot.code_mode.custom_id import parse_custom_id
from universal_bot.code_mode.fake_discord import FakeDiscord
from universal_bot.code_mode.file_outbox import FileOutboxDiscordPort
from universal_bot.code_mode.inbox_flow import author_roles, confidence_for, should_propose
from universal_bot.code_mode.lab_runner import LabOutcome
from universal_bot.code_mode.models import LabEvidence, Location, ProjectMode, ProjectState
from universal_bot.code_mode.text_rules import is_manual_trigger
from universal_bot.contracts import Tier, TriageDecision, WorkType
from universal_bot.labcode_runtime import run_once

T0 = datetime(2026, 10, 20, 18, 35, 1, tzinfo=timezone.utc)
CHANNEL = 100
GUILD = 10
JULIAN = 200
EMANUEL = 201
OUTSIDE = "esto lo atiende el bot normal: usá el prefijo de siempre"
INSIDE = "esto lo atiende el bot normal, usá el prefijo"
USER_OK = (
    "Se puede hacer. Lo probé en un directorio aparte y anduvo. "
    "El detalle está en los hilos de cada etapa. "
    "No hace falta una aprobación para seguir con la prueba."
)
JARGON = ("diff", "pr", "prs", "stack", "commit", "merge", "pytest")


class FakeLabs:
    def __init__(self, outcome=None, consult="CONSULT: propone, no decide.\nRecomendación: seguir"):
        self.runs = 0
        self.consults = 0
        self.outcome = outcome
        self.consult = consult

    def run_hypothesis(self, **kwargs):
        self.runs += 1
        if self.outcome is not None:
            return self.outcome
        evidence = LabEvidence(
            id="LE-1",
            project_id=kwargs["project_id"],
            lab_path="/tmp/lab",
            role="lab-runner",
            hypothesis=kwargs["hypothesis"],
            commands=("python probe.py",),
            result="40 segundos",
            artifacts=("probe.txt",),
            verdict="APPROVE",
            evidence_class="running",
            security_check_ref="SC-1",
            started_at=T0,
            finished_at=T0,
            timed_out=False,
        )
        return (LabOutcome(evidence, True, None),)

    def consult_maverick(self, **kwargs):
        self.consults += 1
        return self.consult


def make_spool(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name in ("inbox", "outbox", "answers"):
        (path / name).mkdir()
    return path


def write_job(spool: Path, *, message_id="555", job_id="job-1", prompt="hola", author=str(JULIAN), reply_to=None) -> Path:
    payload = {
        "version": 1,
        "job_id": job_id,
        "instance": "fe-labcode",
        "source": "discord",
        "guild_id": str(GUILD),
        "channel_id": str(CHANNEL),
        "thread_id": None,
        "parent_channel_id": str(CHANNEL),
        "message_id": message_id,
        "author": {"id": str(author), "display_name": "alguien"},
        "author_context": "test",
        "content_raw": prompt,
        "prompt": prompt,
        "attachments": [],
        "audio_transcripts": [],
        "previous_messages": [],
        "location_key": f"{GUILD}:{CHANNEL}",
        "session_key": f"{GUILD}:{CHANNEL}",
        "created_ts": 1000.0,
        "deadline_ts": 2800.0,
        "button_prefix": "ublab:",
        "reply_to_message_id": reply_to,
        "outbox_dir": str(spool / "outbox"),
        "answers_dir": str(spool / "answers"),
    }
    job_dir = spool / "inbox" / f"lc_{message_id}"
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(json.dumps(payload), encoding="utf-8")
    (job_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    return job_dir


def flow_config(**overrides):
    config = CodeModeConfig(
        allowed_channels=(CHANNEL,),
        role_map=(
            (str(JULIAN), ("@dev", "@admin")),
            (str(EMANUEL), ("@dev", "@admin")),
        ),
    )
    return replace(config, **overrides) if overrides else config


def make_app(tmp_path, labs=None, config=None):
    labs = labs or FakeLabs()
    discord = FakeDiscord()
    config = config or flow_config()
    app = CodeModeApp(tmp_path / "mode.sqlite", discord, FakeClock(T0), config, lab_runner=labs)
    app.labs = labs
    return app


def load_job(app, job_dir):
    from universal_bot.code_mode.inbox_job import load_inbox_job

    return load_inbox_job(job_dir)


def state_of(job_dir):
    return json.loads((job_dir / "state.json").read_text(encoding="utf-8"))


def contents(discord):
    return [message.content for message in discord.messages]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("pasemos a modo código", True),
        ("pasemos a modo código: ¿se puede transcribir rápido?", True),
        ("/modo-codigo 1h", True),
        ("no pasemos a modo código", False),
        ("hola", False),
    ],
)
def test_manual_phrase_accepts_a_prefix(text, expected):
    assert is_manual_trigger(text, CodeModeConfig()) is expected


@pytest.mark.parametrize(
    ("signals", "score"),
    [
        (("refactor",), 0.91),
        (("multi-workstream",), 0.90),
        (("feature",), 0.92),
        (("automation", "vague"), 0.85),
        (("irreversible", "prod-risk"), 0.95),
        (("env-anomaly",), 0.55),
        (("bug", "single-file"), 0.50),
        (("bug", "two-files"), 0.50),
        (("typo",), 0.20),
        (("non-code",), 0.10),
        (("read-only",), 0.10),
        (("empty",), 0.0),
        (("default-cheapest",), 0.40),
        (("desconocido",), 0.0),
    ],
)
def test_confidence_is_exact_per_signal(signals, score):
    decision = TriageDecision(Tier.T2, WorkType.EVOLVING_PRODUCT, True, signals)
    assert confidence_for(decision) == score


@pytest.mark.parametrize(
    ("tier", "confidence", "threshold", "expected"),
    [
        ("T2", 0.8, 0.8, True),
        ("T2", 0.79, 0.8, False),
        ("T3", 0.8, 0.8, True),
        ("T1", 1.0, 0.8, False),
        ("T0", 0.9, 0.8, False),
    ],
)
def test_propose_only_for_high_t2_t3(tier, confidence, threshold, expected):
    assert should_propose(tier, confidence, threshold, ("T2", "T3")) is expected


def test_default_roles_are_closed():
    config = CodeModeConfig()
    assert config.allowed_channels == ()
    assert author_roles(JULIAN, config) == ()
    assert author_roles(EMANUEL, config) == ()
    assert author_roles(1, config) == ()


def test_empty_allowlist_does_not_serve(tmp_path):
    app = make_app(tmp_path, config=CodeModeConfig())
    spool = make_spool(tmp_path / "spool")
    job_dir = write_job(spool, prompt="refactor del store")
    app.handle_job(load_job(app, job_dir), job_dir)
    assert contents(app.discord) == []
    assert app.labs.runs == 0
    assert state_of(job_dir)["status"] == "skipped"


def test_configured_role_map_grants_only_those_ids():
    config = flow_config()
    assert author_roles(JULIAN, config) == ("@dev", "@admin")
    assert author_roles(EMANUEL, config) == ("@dev", "@admin")
    assert author_roles(1, config) == ()


def test_yaml_role_map_replaces_the_defaults(tmp_path):
    path = tmp_path / "guild.yaml"
    path.write_text('code_mode:\n  role_map:\n    "7": ["@dev"]\n', encoding="utf-8")
    config = load_code_mode_config(path)
    assert author_roles(7, config) == ("@dev",)
    assert author_roles(JULIAN, config) == ()


@pytest.mark.parametrize(
    "prompt",
    ["hola", "bug en el lock que no se libera"],
)
def test_outside_without_a_session_gets_the_short_reply(tmp_path, prompt):
    app = make_app(tmp_path)
    spool = make_spool(tmp_path / "spool")
    job_dir = write_job(spool, prompt=prompt)
    app.handle_job(load_job(app, job_dir), job_dir)
    assert OUTSIDE in contents(app.discord)
    assert app.labs.runs == 0
    state = state_of(job_dir)
    assert state["status"] == "done"
    assert state["active_step"] == "charla"
    assert state["summary"] == OUTSIDE
    assert state["error"] is None
    assert state["op_ids"] == []
    assert state["session_key"] == f"{GUILD}:{CHANNEL}"
    assert app.sessions.resolve(Location(GUILD, CHANNEL)) is None


def test_t2_below_the_threshold_stays_outside(tmp_path):
    app = make_app(tmp_path, config=flow_config(proposal_threshold=0.99))
    spool = make_spool(tmp_path / "spool")
    job_dir = write_job(spool, prompt="refactor del store")
    app.handle_job(load_job(app, job_dir), job_dir)
    assert contents(app.discord) == [OUTSIDE]
    assert app.labs.runs == 0


def test_t2_and_t3_propose_three_part_buttons(tmp_path, prompt="refactor del store"):
    app = make_app(tmp_path)
    spool = make_spool(tmp_path / "spool")
    job_dir = write_job(spool, prompt=prompt, job_id="job-1")
    app.handle_job(load_job(app, job_dir), job_dir)
    state = state_of(job_dir)
    assert state["status"] == "waiting_human"
    assert state["active_step"] == "propose"
    assert app.labs.runs == 0
    buttons = app.discord.messages[-1].buttons
    opts = []
    for button in buttons:
        parsed = parse_custom_id(button.custom_id)
        assert len(button.custom_id) <= 100
        assert parsed.kind == "propose"
        assert parsed.id == "job-1"
        opts.append(parsed.opt)
    assert opts == [
        "create_channel",
        "create_thread",
        "here_1h",
        "here_4h",
        "here_until_exit",
        "decline",
    ]


def test_t3_also_proposes(tmp_path):
    test_t2_and_t3_propose_three_part_buttons(tmp_path, prompt="feature nueva de reservas")


def test_manual_phrase_with_a_role_runs_one_lab_and_one_maverick(tmp_path):
    app = make_app(tmp_path)
    spool = make_spool(tmp_path / "spool")
    prompt = "pasemos a modo código: refactor del store"
    job_dir = write_job(spool, prompt=prompt, author=str(JULIAN))
    app.handle_job(load_job(app, job_dir), job_dir)
    assert app.labs.runs == 1
    assert app.labs.consults == 1
    assert USER_OK in contents(app.discord)
    user = next(message for message in app.discord.messages if message.content == USER_OK)
    assert user.channel_id == CHANNEL
    assert user.thread_id is None
    for word in JARGON:
        assert word not in USER_OK.lower().split()
    session = app.sessions.resolve(Location(GUILD, CHANNEL))
    assert session is not None
    assert session.status == "ACTIVE"
    state = state_of(job_dir)
    assert state["status"] == "done"
    assert state["active_step"] == "03-plan"
    assert state["error"] is None
    assert "02-lab" in [thread.name for thread in app.discord.threads]
    assert "03-plan" in [thread.name for thread in app.discord.threads]


def test_manual_phrase_without_a_role_does_not_enter(tmp_path):
    app = make_app(tmp_path)
    spool = make_spool(tmp_path / "spool")
    job_dir = write_job(spool, prompt="pasemos a modo código", author="999")
    app.handle_job(load_job(app, job_dir), job_dir)
    assert app.sessions.resolve(Location(GUILD, CHANNEL)) is None
    assert OUTSIDE in contents(app.discord)
    assert app.labs.runs == 0
    assert (999, "No tenés permiso para activar el modo código.") in app.discord.ephemeral


def test_trivial_chat_inside_the_session_does_not_leave(tmp_path):
    app = make_app(tmp_path)
    app.sessions.activate(Location(GUILD, CHANNEL), JULIAN, ("@dev",), "4h", "button")
    spool = make_spool(tmp_path / "spool")
    job_dir = write_job(spool, prompt="hola", author=str(JULIAN))
    app.handle_job(load_job(app, job_dir), job_dir)
    assert INSIDE in contents(app.discord)
    assert OUTSIDE not in contents(app.discord)
    assert app.labs.runs == 0
    assert app.sessions.resolve(Location(GUILD, CHANNEL)).status == "ACTIVE"
    assert state_of(job_dir)["summary"] == INSIDE


def test_security_fail_waits_and_resume_does_not_launch_again(tmp_path):
    labs = FakeLabs(outcome=(LabOutcome(None, False, "sin probar: destructive_cmd"),))
    spool = make_spool(tmp_path / "spool")
    db = tmp_path / "mode.sqlite"
    job_dir = write_job(spool, prompt="pasemos a modo código: refactor del store", author=str(JULIAN))
    clock = FakeClock(T0)
    run_once(spool, db_path=db, clock=clock, lab_runner=labs, config=flow_config())
    state = state_of(job_dir)
    assert state["status"] == "waiting_human"
    assert state["active_step"] == "SANDBOX_CHECK"
    assert state["resume_token"].startswith("resume-")
    assert labs.runs == 1
    assert labs.consults == 0
    answer = {
        "version": 1,
        "kind": "pq",
        "id": state["question_id"],
        "opt": "seguir",
        "user_id": str(JULIAN),
        "channel_id": str(CHANNEL),
        "message_id": "9",
        "interaction_id": "ix",
        "ts": 1.0,
    }
    (spool / "answers" / f"pq__{state['question_id']}.json").write_text(json.dumps(answer), encoding="utf-8")
    run_once(spool, db_path=db, clock=clock, lab_runner=labs, config=flow_config())
    resumed = state_of(job_dir)
    assert labs.runs == 1
    assert resumed["status"] == "done"
    assert resumed["active_step"] == "sin-probar"
    assert resumed["summary"] == "sin probar: destructive_cmd"
    assert resumed["resume_token"] == state["resume_token"]


def test_stop_still_pauses_with_a_checkpoint(tmp_path):
    from universal_bot.code_mode.projects import ProjectLedger

    spool = make_spool(tmp_path / "spool")
    clock = FakeClock(T0)
    db = tmp_path / "mode.sqlite"
    ledger = ProjectLedger(db, clock)
    project = ledger.create_project(id="P-stop", guild_id=GUILD, requester_id=JULIAN, state=ProjectState.RUNNING)
    job_dir = spool / "inbox" / "lc_1"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(json.dumps({"job_id": "job-9"}), encoding="utf-8")
    (job_dir / "state.json").write_text(
        json.dumps({"version": 1, "status": "running", "project_id": project.id}),
        encoding="utf-8",
    )
    answer = {
        "version": 1,
        "kind": "stop",
        "id": "job-9",
        "opt": "ahora",
        "user_id": str(JULIAN),
        "channel_id": str(CHANNEL),
        "message_id": "1",
        "interaction_id": "ix",
        "ts": 1.0,
    }
    (spool / "answers" / "stop__job-9.json").write_text(json.dumps(answer), encoding="utf-8")
    run_once(spool, db_path=db, clock=clock, lab_runner=FakeLabs())
    assert state_of(job_dir)["status"] == "paused"
    token = ProjectLedger(db, clock).last_checkpoint(project.id)
    assert token is not None
    assert token.resume_token.startswith("resume-")


def test_run_once_replies_outside_once(tmp_path):
    spool = make_spool(tmp_path / "spool")
    job_dir = write_job(spool, prompt="hola", author=str(JULIAN))
    clock = FakeClock(T0)
    labs = FakeLabs()
    run_once(spool, db_path=tmp_path / "mode.sqlite", clock=clock, lab_runner=labs, config=flow_config())
    ops = sorted((spool / "outbox").glob("*.json"))
    bodies = [json.loads(path.read_text(encoding="utf-8")) for path in ops]
    assert any(body.get("content") == OUTSIDE for body in bodies)
    assert labs.runs == 0
    state = state_of(job_dir)
    assert state["status"] == "done"
    assert state["op_ids"]
    assert (spool / "runtime.heartbeat").is_file()
    run_once(spool, db_path=tmp_path / "mode.sqlite", clock=clock, lab_runner=labs, config=flow_config())
    assert sorted((spool / "outbox").glob("*.json")) == ops


def test_proposal_click_here_runs_the_lab(tmp_path):
    spool = make_spool(tmp_path / "spool")
    db = tmp_path / "mode.sqlite"
    job_dir = write_job(spool, prompt="refactor del store", author=str(JULIAN), job_id="job-1")
    clock = FakeClock(T0)
    labs = FakeLabs()
    run_once(spool, db_path=db, clock=clock, lab_runner=labs, config=flow_config())
    assert state_of(job_dir)["status"] == "waiting_human"
    assert labs.runs == 0
    answer = {
        "version": 1,
        "kind": "propose",
        "id": "job-1",
        "opt": "here_1h",
        "user_id": str(JULIAN),
        "channel_id": str(CHANNEL),
        "message_id": "3",
        "interaction_id": "ix",
        "ts": 1.0,
    }
    (spool / "answers" / "propose__job-1.json").write_text(json.dumps(answer), encoding="utf-8")
    run_once(spool, db_path=db, clock=clock, lab_runner=labs, config=flow_config())
    assert labs.runs == 1
    assert labs.consults == 1
    assert state_of(job_dir)["status"] == "done"
    assert state_of(job_dir)["active_step"] == "03-plan"
    app = CodeModeApp(db, FakeDiscord(), clock, CodeModeConfig())
    session = app.sessions.resolve(Location(GUILD, CHANNEL))
    assert session is not None
    assert session.until == T0 + timedelta(hours=1)


def test_proposal_decline_goes_back_to_the_normal_bot(tmp_path):
    spool = make_spool(tmp_path / "spool")
    db = tmp_path / "mode.sqlite"
    job_dir = write_job(spool, prompt="refactor del store", author=str(JULIAN), job_id="job-2", message_id="556")
    clock = FakeClock(T0)
    labs = FakeLabs()
    run_once(spool, db_path=db, clock=clock, lab_runner=labs, config=flow_config())
    answer = {
        "version": 1,
        "kind": "propose",
        "id": "job-2",
        "opt": "decline",
        "user_id": str(JULIAN),
        "channel_id": str(CHANNEL),
        "message_id": "4",
        "interaction_id": "ix",
        "ts": 1.0,
    }
    (spool / "answers" / "propose__job-2.json").write_text(json.dumps(answer), encoding="utf-8")
    run_once(spool, db_path=db, clock=clock, lab_runner=labs, config=flow_config())
    assert labs.runs == 0
    assert state_of(job_dir)["status"] == "done"
    assert state_of(job_dir)["summary"] == OUTSIDE
    bodies = [json.loads(path.read_text(encoding="utf-8")) for path in (spool / "outbox").glob("*.json")]
    assert any(body.get("content") == OUTSIDE for body in bodies)


def test_deferred_port_enqueues_without_waiting(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "outbox").mkdir()
    calls = []
    port = FileOutboxDiscordPort(
        spool,
        clock=FakeClock(T0),
        sleeper=lambda _seconds: calls.append(_seconds),
        timeout_s=0,
        defer_results=True,
    )
    message_id = port.send(CHANNEL, "hola", reply_to=5)
    thread_id = port.create_thread(CHANNEL, "02-lab")
    port.pin(CHANNEL, message_id)
    assert calls == []
    assert message_id < 0, "id local negativo: nunca se confunde con uno real"
    assert thread_id is None
    ops = sorted((spool / "outbox").glob("*.json"))
    kinds = [json.loads(path.read_text(encoding="utf-8"))["op"] for path in ops]
    assert kinds == ["send", "thread"]
    send = json.loads(ops[0].read_text(encoding="utf-8"))
    assert send["reply_to"] == 5
    assert send["version"] == 1
    assert send["channel_id"] == CHANNEL


def test_missing_thread_id_does_not_post_the_detail_on_the_channel():
    from universal_bot.code_mode.models import Project
    from universal_bot.code_mode.stage_router import StageRouter

    class NullThreads(FakeDiscord):
        def create_thread(self, channel_id, name):
            super().create_thread(channel_id, name)
            return None

    discord = NullThreads()
    project = Project(
        id="P-1",
        guild_id=GUILD,
        requester_id=JULIAN,
        origin_message_id=1,
        slug="eco",
        title_plain="Eco",
        tier="T2",
        work_type="evolving-product",
        mode=ProjectMode.CHANNEL,
        state=ProjectState.LAB_RUNNING,
        channel_id=CHANNEL,
        root_thread_id=None,
        run_id="R-1",
        wave="O1",
        sandbox_id=None,
        last_security_check=None,
        requires_production=False,
        created_at=T0,
        updated_at=T0,
    )
    StageRouter(discord).post(project, "02-lab", "detalle tecnico")
    assert discord.threads[0].name == "02-lab"
    assert discord.messages == []
