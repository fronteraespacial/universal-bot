"""El JSON real del puente recorre el lab una vez y no duplica operaciones."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.custom_id import parse_custom_id
from universal_bot.code_mode.lab_runner import LabOutcome
from universal_bot.code_mode.models import LabEvidence
from universal_bot.labcode_runtime import run_once

T0 = datetime(2026, 10, 20, 18, 35, 1, tzinfo=timezone.utc)
FIXTURE = Path(__file__).resolve().parents[0] / "fixtures" / "labcode" / "lc_1562300000000000001"
MESSAGE = 1562300000000000001
CHANNEL = 1562169649574051942
USER_OK = (
    "Se puede hacer. Lo probé en un directorio aparte y anduvo. "
    "El detalle está en los hilos de cada etapa. "
    "No hace falta una aprobación para seguir con la prueba."
)
JARGON = ("diff", "pr", "prs", "stack", "commit", "merge", "pytest")
MENTIONS = {"parse": [], "replied_user": False}


class FakeLabs:
    def __init__(self):
        self.runs = 0
        self.consults = 0

    def run_hypothesis(self, **kwargs):
        self.runs += 1
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
        del kwargs
        self.consults += 1
        return "CONSULT: propone, no decide.\nRecomendación: seguir"


def _spool_with_fixture(root: Path) -> tuple[Path, Path]:
    spool = root / "spool"
    for name in ("inbox", "outbox", "answers"):
        (spool / name).mkdir(parents=True)
    job_dir = spool / "inbox" / FIXTURE.name
    shutil.copytree(FIXTURE, job_dir)
    payload = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    payload["outbox_dir"] = str(spool / "outbox")
    payload["answers_dir"] = str(spool / "answers")
    (job_dir / "job.json").write_text(json.dumps(payload), encoding="utf-8")
    return spool, job_dir


def _custom_ids(bodies) -> list[str]:
    found = []
    for body in bodies:
        for row in body.get("components") or []:
            for item in row.get("components") or []:
                if "custom_id" in item:
                    found.append(item["custom_id"])
    return found


def test_real_bridge_job_replies_once_and_stays_idempotent(tmp_path):
    spool, job_dir = _spool_with_fixture(tmp_path)
    clock = FakeClock(T0)
    labs = FakeLabs()
    run_once(spool, db_path=tmp_path / "mode.sqlite", clock=clock, lab_runner=labs)
    ops = sorted(path for path in (spool / "outbox").glob("*.json"))
    names = [path.name for path in ops]
    assert names == sorted(names)
    bodies = [json.loads(path.read_text(encoding="utf-8")) for path in ops]
    for body, name in zip(bodies, names):
        assert body["version"] == 1
        assert body["allowed_mentions"] == MENTIONS
        assert name.startswith(body["op_id"])
        assert body["op"] in {"send", "edit", "thread", "pin", "create_channel"}
    threads = [body["name"] for body in bodies if body["op"] == "thread"]
    assert threads == ["02-lab", "03-plan"]
    replied = [body for body in bodies if body.get("reply_to") == MESSAGE and body.get("content") == USER_OK]
    assert replied
    assert replied[0]["channel_id"] == CHANNEL
    for word in JARGON:
        assert word not in replied[0]["content"].lower().split()
    custom_ids = _custom_ids(bodies)
    assert custom_ids
    for custom_id in custom_ids:
        parsed = parse_custom_id(custom_id)
        assert custom_id == f"ublab:{parsed.kind}:{parsed.id}:{parsed.opt}"
        assert len(custom_id) <= 100
    state = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "done"
    assert state["active_step"] == "03-plan"
    assert state["error"] is None
    assert state["session_key"] == "discord:779800770337177652:1562169649574051942"
    assert state["op_ids"]
    assert (spool / "runtime.heartbeat").read_text(encoding="utf-8") == T0.isoformat()
    assert labs.runs == 1
    assert labs.consults == 1
    run_once(spool, db_path=tmp_path / "mode.sqlite", clock=clock, lab_runner=labs)
    assert sorted(path for path in (spool / "outbox").glob("*.json")) == ops
    assert labs.runs == 1
