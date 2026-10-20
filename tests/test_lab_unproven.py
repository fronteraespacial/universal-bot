"""Un lab que no aprueba no publica plan, pregunta; y un job roto no tira abajo el runtime."""

import json
from dataclasses import replace

import pytest

from universal_bot.code_mode.app import CodeModeApp
from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.lab_runner import LabOutcome
from universal_bot.labcode_runtime import run_once
from tests.test_labcode_e2e_fixture import AUTHOR, CHANNEL, T0, USER_OK, FakeLabs, _spool_with_fixture
from tests.test_labcode_runtime import make_spool, write_job


class UnprovenLabs(FakeLabs):
    def __init__(self, verdict, evidence_class):
        super().__init__()
        self.verdict = verdict
        self.evidence_class = evidence_class

    def run_hypothesis(self, **kwargs):
        (outcome,) = super().run_hypothesis(**kwargs)
        evidence = replace(outcome.evidence, verdict=self.verdict, evidence_class=self.evidence_class)
        return (LabOutcome(evidence, True, None),)


def _config():
    return CodeModeConfig(allowed_channels=(CHANNEL,), role_map=((str(AUTHOR), ("@dev", "@admin")),))


@pytest.mark.parametrize(
    ("verdict", "evidence_class"),
    (("INCONCLUSIVE", "paper"), ("REJECT", "running"), ("APPROVE", "paper")),
)
def test_lab_without_valid_evidence_asks_instead_of_crashing(tmp_path, verdict, evidence_class):
    spool, job_dir = _spool_with_fixture(tmp_path)
    labs = UnprovenLabs(verdict, evidence_class)
    run_once(spool, db_path=tmp_path / "mode.sqlite", clock=FakeClock(T0), lab_runner=labs, config=_config())
    state = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "waiting_human"
    assert state["active_step"] == "SANDBOX_CHECK"
    assert state["question_id"]
    assert verdict in state["summary"]
    assert labs.consults == 0
    bodies = [json.loads(p.read_text(encoding="utf-8")) for p in (spool / "outbox").glob("*.json")]
    assert not [b for b in bodies if b.get("content") == USER_OK]
    assert not [b for b in bodies if b["op"] == "thread" and b.get("name") == "03-plan"]


def test_one_broken_job_is_marked_error_and_the_next_one_runs(tmp_path, monkeypatch):
    spool = make_spool(tmp_path / "spool")
    first = write_job(spool, message_id="551", job_id="job-1")
    second = write_job(spool, message_id="552", job_id="job-2")
    real = CodeModeApp.handle_job

    def flaky(self, job, job_dir):
        if job.job_id == "job-1":
            raise RuntimeError("boom secreto")
        return real(self, job, job_dir)

    monkeypatch.setattr(CodeModeApp, "handle_job", flaky)
    result = run_once(spool, db_path=tmp_path / "mode.sqlite", clock=FakeClock(T0))
    assert result["processed"] == 2
    broken = json.loads((first / "state.json").read_text(encoding="utf-8"))
    assert broken["status"] == "error"
    assert broken["error"] == "RuntimeError"
    assert json.loads((second / "state.json").read_text(encoding="utf-8"))["status"] == "skipped"
    again = run_once(spool, db_path=tmp_path / "mode.sqlite", clock=FakeClock(T0))
    assert again["processed"] == 0
