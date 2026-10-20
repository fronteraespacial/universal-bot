"""El resultado del worker del MAIN pasa por los hilos de etapa (02-lab, 03-plan); el canal solo recibe el resumen simple."""

import json

from tests.test_main_orchestrator import CHANNEL, FakeBrain, _config, _ops, _start
from universal_bot.labcode_runtime import run_once

CONSULT = "CONSULT: propone, no decide.\nPlan: 1) bajar audio 2) transcribir"


class FakeLabs:
    def __init__(self):
        self.consults = []

    def consult_maverick(self, **kw):
        self.consults.append(kw)
        return CONSULT


def _tick(spool, db, clock, orch, labs):
    return run_once(spool, db_path=db, clock=clock, config=_config(), orchestrator=orch, lab_runner=labs)


def _answer_threads(spool, ids):
    for path in sorted((spool / "outbox").glob("*.json")):
        if path.name.endswith(".result.json"):
            continue
        body = json.loads(path.read_text(encoding="utf-8"))
        if body.get("op") == "thread" and body.get("name") in ids:
            result = {"version": 1, "op_id": body["op_id"], "ok": True, "ts": 1.0, "thread_id": str(ids[body["name"]])}
            (spool / "outbox" / f"{body['op_id']}.result.json").write_text(json.dumps(result), encoding="utf-8")


def test_worker_result_goes_to_lab_and_plan_threads(tmp_path):
    brain = FakeBrain(lambda text: "Listo: transcribí los 10 videos." if "terminó" in text else "Arranco.")
    spool, db, clock, workers, brain, orch, first = _start(tmp_path, brain)
    labs = FakeLabs()
    workers.made[0].status = "done"
    _tick(spool, db, clock, orch, labs)
    threads = [op for op in _ops(spool) if op["op"] == "thread"]
    assert [op["name"] for op in threads] == ["02-lab", "03-plan"]
    assert all(op["channel_id"] == CHANNEL for op in threads)
    _answer_threads(spool, {"02-lab": 801, "03-plan": 802})
    _tick(spool, db, clock, orch, labs)
    sends = [op for op in _ops(spool) if op["op"] == "send"]
    lab = [op["content"] for op in sends if op["channel_id"] == 801]
    plan = [op["content"] for op in sends if op["channel_id"] == 802]
    assert lab and "10 videos transcriptos" in lab[0]
    assert plan == [CONSULT]
    assert "transcribí los videos de SpaceX" in labs.consults[0]["context"]
    in_channel = [op["content"] for op in sends if op["channel_id"] == CHANNEL]
    assert "Listo: transcribí los 10 videos." in in_channel
    assert not any("10 videos transcriptos" in text or "CONSULT" in text for text in in_channel), "el detalle no cae al canal"
    assert orch.job("job-1")["project_id"]


def test_without_lab_runner_only_the_lab_thread_is_used(tmp_path):
    spool, db, clock, workers, brain, orch, first = _start(tmp_path)
    workers.made[0].status = "done"
    run_once(spool, db_path=db, clock=clock, config=_config(), orchestrator=orch)
    assert [op["name"] for op in _ops(spool) if op["op"] == "thread"] == ["02-lab"]
