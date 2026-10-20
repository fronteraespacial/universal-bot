"""FileOutboxDiscordPort: ops, atomicidad y resultados del puente."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.custom_id import CustomIdError
from universal_bot.code_mode.discord_port import Button
from universal_bot.code_mode.file_outbox import (
    BridgeTimeout,
    FileOutboxDiscordPort,
    OutOfScope,
    ToggleOff,
    UnsupportedBridgeOp,
)

T0 = datetime(2026, 10, 20, 18, 35, 1, tzinfo=timezone.utc)
MENTIONS = {"parse": [], "replied_user": False}
CHANNEL = 1562169649574051942


def make_spool(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name in ("inbox", "outbox", "answers"):
        (path / name).mkdir()
    return path


def completing(spool: Path, clock: FakeClock, *, error: str | None = None):
    def sleep(_seconds: float) -> None:
        clock.advance(seconds=1)
        outbox = spool / "outbox"
        for op_path in list(outbox.glob("*.json")):
            if op_path.name.endswith(".result.json"):
                continue
            op = json.loads(op_path.read_text(encoding="utf-8"))
            result = {"version": 1, "op_id": op["op_id"], "ok": error is None, "ts": 1.0, "error": error}
            if error is None:
                if op["op"] == "thread":
                    result["thread_id"] = 901
                elif op["op"] == "create_channel":
                    result["channel_id"] = 902
                else:
                    result["message_id"] = 900
            (outbox / f"{op['op_id']}.result.json").write_text(json.dumps(result), encoding="utf-8")
            done = outbox / "done"
            done.mkdir(exist_ok=True)
            op_path.rename(done / op_path.name)

    return sleep


def ticking(clock: FakeClock):
    def sleep(_seconds: float) -> None:
        clock.advance(seconds=1)

    return sleep


def port(spool: Path, *, timeout_s: float = 5.0, admin_category_id: int | None = 4242, named_channels=None, error: str | None = None, tick: bool = False):
    clock = FakeClock(T0)
    sleeper = ticking(clock) if tick else completing(spool, clock, error=error)
    return FileOutboxDiscordPort(
        spool,
        clock=clock,
        sleeper=sleeper,
        timeout_s=timeout_s,
        poll_interval_s=1.0,
        admin_category_id=admin_category_id,
        named_channels=named_channels,
    )


def done_ops(spool: Path) -> list[dict]:
    folder = spool / "outbox" / "done"
    if not folder.exists():
        return []
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))]


def test_send_is_atomic_and_returns_the_created_message(tmp_path, monkeypatch):
    spool = make_spool(tmp_path)
    seen = {}
    real_replace = Path.replace

    def spy(self, target):
        if self.name.startswith(".") and str(self).endswith(".tmp"):
            seen["tmp"] = self.name
            seen["body"] = json.loads(self.read_text(encoding="utf-8"))
            seen["final_before"] = Path(target).exists()
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", spy)
    message_id = port(spool).send(CHANNEL, "hola", reply_to=50)
    assert message_id == 900
    assert seen["final_before"] is False
    assert seen["tmp"].startswith(".")
    assert seen["tmp"].endswith(".tmp")
    assert seen["body"]["version"] == 1
    assert seen["body"]["op"] == "send"
    assert seen["body"]["op_id"] == "20261020T183501-0001-send"
    assert seen["body"]["channel_id"] == CHANNEL
    assert seen["body"]["content"] == "hola"
    assert seen["body"]["reply_to"] == 50
    assert seen["body"]["allowed_mentions"] == MENTIONS
    assert isinstance(seen["body"]["channel_id"], int)
    published = done_ops(spool)[0]
    assert published == seen["body"]
    assert list((spool / "outbox").glob(".*.tmp")) == []


def test_thread_target_and_buttons_and_sequence_never_reused(tmp_path):
    spool = make_spool(tmp_path)
    first = port(spool)
    message_id = first.send(CHANNEL, "en el hilo", thread_id=77)
    buttons_id = first.send_buttons(
        CHANNEL,
        "elegí",
        (
            Button("ublab:exit:CMS-1:salir", "Salir de modo programación"),
            Button("ublab:extend:CMS-1:extender", "Extender"),
        ),
    )
    assert message_id == 900
    assert buttons_id == 900
    bodies = done_ops(spool)
    assert bodies[0]["channel_id"] == 77
    assert bodies[0]["op_id"].endswith("-0001-send")
    assert bodies[1]["op_id"] == "20261020T183502-0002-send"
    assert bodies[1]["components"][0]["components"][0]["custom_id"] == "ublab:exit:CMS-1:salir"
    assert bodies[1]["allowed_mentions"] == MENTIONS
    restarted = port(spool)
    restarted.send(CHANNEL, "otra")
    assert done_ops(spool)[2]["op_id"].endswith("-0003-send")


def test_invalid_ops_are_rejected_before_writing(tmp_path):
    spool = make_spool(tmp_path)
    adapter = port(spool)
    with pytest.raises(ValueError):
        adapter.send(CHANNEL, "")
    with pytest.raises(ValueError):
        adapter.send(CHANNEL, "x" * 2001)
    with pytest.raises(ValueError):
        adapter.send(CHANNEL, "x", embeds=[{}] * 11)
    with pytest.raises(CustomIdError):
        adapter.send_buttons(CHANNEL, "no", (Button("ub:stop:job:ahora", "Stop"),))
    with pytest.raises(ValueError):
        adapter.edit(CHANNEL, 5)
    with pytest.raises(ValueError):
        adapter.create_thread(CHANNEL, "")
    with pytest.raises(ValueError):
        adapter.create_thread(CHANNEL, "h" * 101)
    with pytest.raises(ValueError):
        adapter.create_channel(1, "Proyectos", category_name="Proyectos", overwrites=())
    with pytest.raises(ValueError, match="ADMINISTRACIÓN"):
        adapter.create_channel(1, "p-reservas", category_name="Proyectos", overwrites=(), parent_id=7)
    with pytest.raises(ValueError):
        adapter.create_channel(1, "p-reservas", category_name="Proyectos", overwrites=(), topic="t" * 1025)
    assert done_ops(spool) == []
    assert list((spool / "outbox").glob("*.json")) == []


def test_create_channel_thread_pin_and_edit_match_the_contract(tmp_path):
    spool = make_spool(tmp_path)
    adapter = port(spool)
    channel_id = adapter.create_channel(
        1, "p-reservas-api", category_name="Proyectos", overwrites=(), topic="tema"
    )
    thread_id = adapter.create_thread(CHANNEL, "02-lab", from_message_id=12)
    adapter.pin(CHANNEL, 12, thread_id=88)
    adapter.edit(CHANNEL, 12, content="editado")
    adapter.send(CHANNEL, "", embeds=[{"title": "uno"}])
    bodies = done_ops(spool)
    assert channel_id == 902
    assert bodies[0]["op"] == "create_channel"
    assert bodies[0]["name"] == "p-reservas-api"
    assert bodies[0]["topic"] == "tema"
    assert bodies[0]["parent_id"] == 4242
    assert "overwrites" not in bodies[0]
    assert thread_id == 901
    assert bodies[1]["op"] == "thread"
    assert bodies[1]["name"] == "02-lab"
    assert bodies[1]["from_message_id"] == 12
    assert bodies[2]["op"] == "pin"
    assert bodies[2]["channel_id"] == 88
    assert bodies[2]["message_id"] == 12
    assert bodies[3]["op"] == "edit"
    assert bodies[3]["content"] == "editado"
    assert bodies[4]["content"] == ""
    assert bodies[4]["embeds"] == [{"title": "uno"}]
    assert all(body["allowed_mentions"] == MENTIONS for body in bodies)


def test_out_of_scope_and_toggle_off_are_domain_errors(tmp_path):
    spool = make_spool(tmp_path / "a")
    with pytest.raises(OutOfScope, match="out_of_scope"):
        port(spool, error="out_of_scope", timeout_s=3).send(9, "hola")
    other = make_spool(tmp_path / "b")
    with pytest.raises(ToggleOff, match="toggle_off"):
        port(other, error="toggle_off").send(CHANNEL, "hola")


def test_poll_times_out_without_hanging(tmp_path):
    spool = make_spool(tmp_path)
    adapter = port(spool, tick=True, timeout_s=2)
    with pytest.raises(BridgeTimeout):
        adapter.send(CHANNEL, "hola")
    assert (spool / "outbox" / "done").exists() is False or done_ops(spool) == []


def test_unsupported_ops_do_not_write(tmp_path):
    spool = make_spool(tmp_path)
    adapter = port(spool)
    with pytest.raises(UnsupportedBridgeOp):
        adapter.unpin(CHANNEL, 1)
    with pytest.raises(UnsupportedBridgeOp):
        adapter.reply_ephemeral(7, "no")
    assert adapter.check_permissions(1, "manage_channels") is True
    assert adapter.channel_id_by_name(1, "proyectos") is None
    named = port(spool, named_channels={"proyectos": 700})
    assert named.channel_id_by_name(1, "proyectos") == 700
    adapter.register_persistent_view("ublab:exit:CMS-1:salir")
    assert done_ops(spool) == []
