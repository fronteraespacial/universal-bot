"""El puente no tiene unpin: al terminar la sesión se edita el mensaje fijado (texto de cierre, sin botones).

Los ids locales del modo diferido son negativos y persistentes en el spool, así que no se confunden con ids reales
ni se pierden entre ticks.
"""

import json
from datetime import datetime, timezone

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.discord_port import Button
from universal_bot.code_mode.file_outbox import UNPINNED_TEXT, FileOutboxDiscordPort

T0 = datetime(2026, 10, 20, 18, 35, 1, tzinfo=timezone.utc)
CHANNEL = 100


def _port(spool):
    return FileOutboxDiscordPort(spool, clock=FakeClock(T0), sleeper=lambda s: None, defer_results=True)


def _spool(tmp_path):
    spool = tmp_path / "spool"
    (spool / "outbox").mkdir(parents=True)
    return spool


def _ops(spool, kind):
    found = []
    for folder in (spool / "outbox", spool / "outbox" / "done"):
        for path in sorted(folder.glob("*.json")):
            if not path.name.endswith(".result.json"):
                body = json.loads(path.read_text(encoding="utf-8"))
                if body["op"] == kind:
                    found.append(body)
    return found


def _result(spool, op_id, message_id):
    body = {"version": 1, "op_id": op_id, "ok": True, "ts": 1.0, "message_id": str(message_id)}
    (spool / "outbox" / f"{op_id}.result.json").write_text(json.dumps(body), encoding="utf-8")


def _pin_message(spool):
    return _port(spool).send_buttons(CHANNEL, "Modo programación activo.", (Button("ublab:exit:S1:salir", "Salir"),))


def test_local_ids_are_negative_and_unique_across_ticks(tmp_path):
    spool = _spool(tmp_path)
    first = _pin_message(spool)
    second = _pin_message(spool)
    assert first < 0 and second < 0 and first != second


def test_unpin_in_a_later_tick_edits_the_real_message(tmp_path):
    spool = _spool(tmp_path)
    local = _pin_message(spool)
    _result(spool, _ops(spool, "send")[0]["op_id"], 9001)
    _port(spool).unpin(CHANNEL, local)
    edits = _ops(spool, "edit")
    assert len(edits) == 1
    assert edits[0]["message_id"] == 9001 and edits[0]["channel_id"] == CHANNEL
    assert edits[0]["content"] == UNPINNED_TEXT and edits[0]["components"] == []


def test_unpin_before_the_result_waits_and_flushes_later(tmp_path):
    spool = _spool(tmp_path)
    local = _pin_message(spool)
    _port(spool).unpin(CHANNEL, local)
    assert _ops(spool, "edit") == []
    _result(spool, _ops(spool, "send")[0]["op_id"], 9002)
    assert _port(spool).flush_pins() >= 1
    assert [op["message_id"] for op in _ops(spool, "edit")] == [9002]
    _port(spool).flush_pins()
    assert len(_ops(spool, "edit")) == 1, "no se repite"


def test_pin_in_a_later_tick_resolves_the_local_id(tmp_path):
    spool = _spool(tmp_path)
    local = _pin_message(spool)
    _port(spool).pin(CHANNEL, local)
    _result(spool, _ops(spool, "send")[0]["op_id"], 9003)
    _port(spool).flush_pins()
    assert [op["message_id"] for op in _ops(spool, "pin")] == [9003]
