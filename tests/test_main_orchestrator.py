"""Conversar con el MAIN mientras delega: el mensaje nuevo de una sesión con job activo va al MAIN, no crea otro job."""

import json
import sys
import time
from pathlib import Path

import pytest

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.orchestrator import (
    MAIN_SYSTEM_PROMPT,
    Orchestrator,
    ProcessWorker,
    WarmBrain,
    parse_main_reply,
)
from universal_bot.labcode_runtime import run_once
from tests.test_labcode_runtime import make_spool, write_job
from tests.test_warm import fake_command

T0 = __import__("datetime").datetime(2026, 10, 20, 18, 35, 1, tzinfo=__import__("datetime").timezone.utc)
CHANNEL = 100
AUTHOR = 7
START = "pasemos a modo código: transcribí los videos de SpaceX"


class FakeBrain:
    def __init__(self, script=None):
        self.seen = []
        self.out = []
        self.script = script or (lambda text: "Va bien.\nACCION: {\"tipo\": \"ninguna\"}")

    def submit(self, key, text):
        self.seen.append((key, text))
        self.out.append((key, self.script(text)))

    def drain(self):
        out, self.out = self.out, []
        return out

    def close(self):
        pass

    def release(self, key):
        self.released = getattr(self, "released", []) + [key]


class FakeWorker:
    def __init__(self, job_id, prompt):
        self.job_id = job_id
        self.prompt = prompt
        self.status = "running"
        self.steers = []
        self.stopped = False

    def start(self):
        return self

    def progress(self):
        return "procesé 3 de 10 videos"

    def steer(self, text):
        self.steers.append(text)
        return "live"

    def stop(self):
        self.stopped = True
        self.status = "stopped"

    def poll(self):
        return self.status

    def result_text(self):
        return "10 videos transcriptos"


class Workers:
    def __init__(self):
        self.made = []

    def __call__(self, job_id, prompt):
        worker = FakeWorker(job_id, prompt)
        self.made.append(worker)
        return worker


def _config():
    return CodeModeConfig(
        allowed_channels=(CHANNEL,),
        role_map=((str(AUTHOR), ("@dev", "@admin")),),
        main_enabled=True,
    )


def _env(tmp_path, brain=None):
    spool = make_spool(tmp_path / "spool")
    db = tmp_path / "mode.sqlite"
    clock = FakeClock(T0)
    workers = Workers()
    brain = brain or FakeBrain()
    orch = Orchestrator(db, clock=clock, brain=brain, worker_factory=workers)
    return spool, db, clock, workers, brain, orch


def _tick(spool, db, clock, orch, sleeper=None):
    return run_once(spool, db_path=db, clock=clock, config=_config(), orchestrator=orch, sleeper=sleeper)


def _ops(spool):
    found = []
    for folder in (spool / "outbox", spool / "outbox" / "done"):
        for path in sorted(folder.glob("*.json")):
            if not path.name.endswith(".result.json"):
                found.append(json.loads(path.read_text(encoding="utf-8")))
    return found


def _state(job_dir):
    return json.loads((job_dir / "state.json").read_text(encoding="utf-8"))


def _start(tmp_path, brain=None):
    spool, db, clock, workers, brain, orch = _env(tmp_path, brain)
    first = write_job(spool, message_id="601", job_id="job-1", prompt=START)
    _tick(spool, db, clock, orch)
    return spool, db, clock, workers, brain, orch, first


def _custom_ids(ops):
    return [c["custom_id"] for op in ops for row in op.get("components") or [] for c in row.get("components", [])]


def test_long_job_is_delegated_and_the_main_stays_free(tmp_path):
    spool, db, clock, workers, brain, orch, first = _start(tmp_path)
    assert len(workers.made) == 1
    assert "transcribí los videos de SpaceX" in workers.made[0].prompt
    assert "pasemos a modo código" not in workers.made[0].prompt
    assert _state(first)["status"] == "running"
    ids = _custom_ids(_ops(spool))
    assert "ublab:main:job-1:frenar" in ids
    assert any(i.startswith("ublab:exit:") for i in ids)


def test_status_question_goes_to_the_main_and_the_reply_is_threaded(tmp_path):
    spool, db, clock, workers, brain, orch, first = _start(tmp_path)
    second = write_job(spool, message_id="602", job_id="job-2", prompt="¿cómo vas?")
    _tick(spool, db, clock, orch)
    assert len(workers.made) == 1, "no se crea otro job"
    key, text = brain.seen[-1]
    assert key == "job-1"
    assert "¿cómo vas?" in text and "procesé 3 de 10 videos" in text
    replies = [op for op in _ops(spool) if op["op"] == "send" and op.get("reply_to") == 602]
    assert [op["content"] for op in replies] == ["Va bien."]
    assert replies[0]["channel_id"] == CHANNEL
    assert _state(second)["status"] == "done"
    assert _state(second)["active_step"] == "main-msg"
    assert _state(first)["status"] == "running"


def test_order_change_is_applied_to_the_worker_and_persisted(tmp_path):
    brain = FakeBrain(lambda text: 'Listo, le paso el cambio.\nACCION: {"tipo": "steer", "texto": "solo los de 2026"}' if "solo" in text else "Arranco.")
    spool, db, clock, workers, brain, orch, first = _start(tmp_path, brain)
    write_job(spool, message_id="603", job_id="job-3", prompt="hacé solo los de 2026")
    _tick(spool, db, clock, orch)
    assert workers.made[0].steers == ["solo los de 2026"]
    fresh = Orchestrator(db, clock=clock, brain=FakeBrain(), worker_factory=Workers())
    assert fresh.job("job-1")["instructions"] == ["solo los de 2026"]


def test_relaunch_stops_the_worker_and_starts_one_with_the_new_instruction(tmp_path):
    brain = FakeBrain(lambda text: 'Lo corto y arranco de nuevo.\nACCION: {"tipo": "relanzar", "texto": "usá whisper local"}' if "whisper" in text else "Arranco.")
    spool, db, clock, workers, brain, orch, first = _start(tmp_path, brain)
    write_job(spool, message_id="604", job_id="job-4", prompt="mejor con whisper")
    _tick(spool, db, clock, orch)
    assert workers.made[0].stopped is True
    assert len(workers.made) == 2
    assert "usá whisper local" in workers.made[1].prompt
    assert _state(first)["status"] == "running"


def _click(spool, kind, ident, opt):
    answer = {"version": 1, "kind": kind, "id": ident, "opt": opt, "user_id": str(AUTHOR), "channel_id": str(CHANNEL),
              "message_id": "9", "interaction_id": "ix", "ts": 1.0}
    (spool / "answers" / f"{kind}__{ident}.json").write_text(json.dumps(answer), encoding="utf-8")


def test_stop_button_stops_the_worker(tmp_path):
    spool, db, clock, workers, brain, orch, first = _start(tmp_path)
    _click(spool, "main", "job-1", "frenar")
    _tick(spool, db, clock, orch)
    assert workers.made[0].stopped is True
    assert orch.job("job-1")["status"] == "stopped"
    assert _state(first)["status"] == "done"
    assert _state(first)["active_step"] == "frenado"
    assert any(op.get("content") == "Frené el trabajo." for op in _ops(spool))
    write_job(spool, message_id="605", job_id="job-5", prompt="¿seguís?")
    _tick(spool, db, clock, orch)
    assert [key for key, _ in brain.seen] == ["job-1", "job-5"], "el job frenado no recibe más mensajes; uno nuevo abre otro job"


def test_main_can_stop_by_itself(tmp_path):
    brain = FakeBrain(lambda text: 'Freno.\nACCION: {"tipo": "frenar"}' if "pará" in text else "Arranco.")
    spool, db, clock, workers, brain, orch, first = _start(tmp_path, brain)
    write_job(spool, message_id="606", job_id="job-6", prompt="pará todo")
    _tick(spool, db, clock, orch)
    assert workers.made[0].stopped is True
    assert orch.job("job-1")["status"] == "stopped"


def test_exit_button_ends_the_session_and_stops_the_job(tmp_path):
    spool, db, clock, workers, brain, orch, first = _start(tmp_path)
    exit_id = next(i for i in _custom_ids(_ops(spool)) if i.startswith("ublab:exit:"))
    _, kind, ident, opt = exit_id.split(":")
    _click(spool, kind, ident, opt)
    _tick(spool, db, clock, orch)
    assert workers.made[0].stopped is True
    import sqlite3

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT status FROM code_mode_sessions WHERE id = ?", (ident,)).fetchone()[0] != "ACTIVE"


def test_finished_worker_gets_a_simple_summary_from_the_main(tmp_path):
    brain = FakeBrain(lambda text: "Terminé: transcribí los 10 videos." if "terminó" in text else "Arranco.")
    spool, db, clock, workers, brain, orch, first = _start(tmp_path, brain)
    workers.made[0].status = "done"
    _tick(spool, db, clock, orch)
    _tick(spool, db, clock, orch)
    assert any(op.get("content") == "Terminé: transcribí los 10 videos." for op in _ops(spool))
    assert orch.job("job-1")["status"] == "done"
    assert _state(first)["status"] == "done"


def test_a_crash_is_recovered_once_from_sqlite(tmp_path):
    spool, db, clock, workers, brain, orch, first = _start(tmp_path)
    again = Workers()
    revived = Orchestrator(db, clock=clock, brain=FakeBrain(), worker_factory=again)
    _tick(spool, db, clock, revived)
    assert len(again.made) == 1 and "transcribí los videos de SpaceX" in again.made[0].prompt
    assert revived.job("job-1")["restarts"] == 1
    third = Workers()
    dead = Orchestrator(db, clock=clock, brain=FakeBrain(), worker_factory=third)
    _tick(spool, db, clock, dead)
    assert third.made == []
    assert dead.job("job-1")["status"] == "failed"
    assert _state(first)["status"] == "error"


def test_unknown_answer_kind_does_not_crash_the_runtime(tmp_path):
    spool, db, clock, workers, brain, orch, first = _start(tmp_path)
    _click(spool, "rarito", "x1", "y")
    _tick(spool, db, clock, orch)
    _tick(spool, db, clock, orch)


def test_parse_main_reply():
    assert parse_main_reply('Hola.\nACCION: {"tipo": "steer", "texto": "x"}') == ("Hola.", {"tipo": "steer", "texto": "x"})
    assert parse_main_reply("Sin acción") == ("Sin acción", {"tipo": "ninguna"})
    assert parse_main_reply("Algo\nACCION: {roto") == ("Algo", {"tipo": "ninguna"})
    assert "delegá" in MAIN_SYSTEM_PROMPT.lower() and "ACCION" in MAIN_SYSTEM_PROMPT


def test_process_worker_tail_stop_and_relaunch(tmp_path):
    script = "import sys,time\nfor i in range(200):\n    print(sys.argv[1], i, flush=True); time.sleep(0.02)\n"

    def argv(prompt):
        return [sys.executable, "-c", script, prompt.split()[-1]]

    worker = ProcessWorker(argv, "tarea A", cwd=tmp_path).start()
    deadline = time.monotonic() + 5
    while "A 3" not in worker.progress() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert "A" in worker.progress() and worker.poll() == "running"
    assert worker.steer("cambio B") == "relaunch"
    deadline = time.monotonic() + 5
    while "B" not in worker.progress() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert "B" in worker.progress()
    worker.stop()
    assert worker.poll() == "stopped"


def test_warm_brain_steers_the_main_when_a_message_arrives_mid_turn(tmp_path):
    brain = WarmBrain(lambda: __import__("universal_bot.code_mode.warm", fromlist=["make_session"]).make_session(
        "grok", "grok-4.7", cwd=tmp_path, command=fake_command("grok")))
    try:
        brain.submit("job-1", "LONG contá")
        time.sleep(0.3)
        brain.submit("job-1", "CAMBIO: cortá")
        deadline = time.monotonic() + 10
        replies = []
        while not replies and time.monotonic() < deadline:
            replies = brain.drain()
            time.sleep(0.05)
        assert len(replies) == 1 and "STEERED" in replies[0][1]
        assert brain.steered == 1
    finally:
        brain.close()


def test_exit_releases_the_main_session_of_finished_and_running_jobs(tmp_path):
    """Al salir del modo código se cierra el cerebro del MAIN de esa sesión (con --serve es un proceso por job)."""
    brain = FakeBrain(lambda text: "Terminé." if "terminó" in text else "Arranco.")
    spool, db, clock, workers, brain, orch, first = _start(tmp_path, brain)
    workers.made[0].status = "done"
    _tick(spool, db, clock, orch)
    _tick(spool, db, clock, orch)
    assert orch.job("job-1")["status"] == "done"
    exit_id = next(i for i in _custom_ids(_ops(spool)) if i.startswith("ublab:exit:"))
    _, kind, ident, opt = exit_id.split(":")
    _click(spool, kind, ident, opt)
    _tick(spool, db, clock, orch)
    assert getattr(brain, "released", []) == ["job-1"]


def test_warm_brain_release_closes_only_that_session():
    closed = []

    class S:
        def __init__(self):
            self.n = len(closed)

        def start(self):
            return self

        def prompt(self, text, *, timeout_s):
            from universal_bot.code_mode.warm import TurnResult
            return TurnResult(True, "completed", "ok", 1, None)

        def steer(self, text):
            return "no_turn"

        def busy(self):
            return False

        def close(self):
            closed.append(self)

    brain = WarmBrain(S)
    brain.submit("a", "hola")
    brain.submit("b", "hola")
    deadline = time.monotonic() + 5
    while len(brain.drain()) < 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.2)
    brain.release("a")
    assert len(closed) == 1
    brain.release("a")
    assert len(closed) == 1, "idempotente"
    brain.close()
    assert len(closed) == 2
