"""El puente real devuelve los ids como strings de dígitos: el detalle igual llega al hilo, una sola vez."""

import json

import pytest

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.stage_router import StageRouter
from tests.test_stage_delivery import DETAIL, T0, THREAD_ID, make_spool, port, project, sends


def _thread_op(spool):
    return next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (spool / "outbox").glob("*.json")
        if not path.name.endswith(".result.json")
        and json.loads(path.read_text(encoding="utf-8")).get("op") == "thread"
    )


@pytest.mark.parametrize("raw_id", (str(THREAD_ID), THREAD_ID))
def test_string_thread_id_from_the_bridge_flushes_the_detail_once(tmp_path, raw_id):
    spool = make_spool(tmp_path / "spool")
    clock = FakeClock(T0)
    db = tmp_path / "mode.sqlite"

    def sleeper(_seconds):
        clock.advance(seconds=1)

    StageRouter(port(spool, clock, sleeper), db_path=db).post(project(), "02-lab", DETAIL)
    thread = _thread_op(spool)
    result = {"version": 1, "op_id": thread["op_id"], "ok": True, "ts": 1.0, "thread_id": raw_id}
    (spool / "outbox" / f"{thread['op_id']}.result.json").write_text(json.dumps(result), encoding="utf-8")
    StageRouter(port(spool, clock, sleeper), db_path=db).flush_pending()
    StageRouter(port(spool, clock, sleeper), db_path=db).flush_pending()
    delivered = [b for b in sends(spool) if b.get("content") == DETAIL]
    assert [b["channel_id"] for b in delivered] == [THREAD_ID]


@pytest.mark.parametrize("raw_id", ("", "12a", True, None))
def test_malformed_thread_id_keeps_the_post_pending(tmp_path, raw_id):
    spool = make_spool(tmp_path / "spool")
    clock = FakeClock(T0)
    db = tmp_path / "mode.sqlite"

    def sleeper(_seconds):
        clock.advance(seconds=1)

    StageRouter(port(spool, clock, sleeper), db_path=db).post(project(), "02-lab", DETAIL)
    thread = _thread_op(spool)
    result = {"version": 1, "op_id": thread["op_id"], "ok": True, "ts": 1.0, "thread_id": raw_id}
    (spool / "outbox" / f"{thread['op_id']}.result.json").write_text(json.dumps(result), encoding="utf-8")
    StageRouter(port(spool, clock, sleeper), db_path=db).flush_pending()
    assert [b for b in sends(spool) if b.get("content") == DETAIL] == []
