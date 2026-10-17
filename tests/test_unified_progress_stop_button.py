"""Stop button components on live trail messages."""

from pathlib import Path

from tests.up_fakes import FakeTransport
from universal_bot.unified_progress.config import UnifiedProgressConfig
from universal_bot.unified_progress.stop_control import (
    CANCEL_COLOR,
    IS_COMPONENTS_V2,
    TYPE_CONTAINER,
    parse_stop_button_custom_id,
    stop_button_custom_id,
)
from universal_bot.unified_progress.trail import LiveTrail, read_marker


def test_custom_id_roundtrip():
    cid = stop_button_custom_id("1560336060888780931", "job-20261017-abc")
    assert parse_stop_button_custom_id(cid) == ("1560336060888780931", "job-20261017-abc")
    assert parse_stop_button_custom_id("other:button") is None


def test_live_trail_attaches_button_then_clears_on_finish(tmp_path: Path):
    transport = FakeTransport()
    cfg = UnifiedProgressConfig(
        mode="on",
        state_dir=tmp_path,
        min_edit_s=0.0,
        stop_button_enabled=True,
    )
    trail = LiveTrail(
        cfg,
        transport,
        "chan1",
        "job1",
        "Cursor · demo",
        meta={"author_id": "329811958603972609"},
        mono=lambda: 0.0,
    )
    trail.start()
    assert transport.sent[0]["flags"] == IS_COMPONENTS_V2
    card = transport.sent[0]["components"][0]
    assert card["type"] == TYPE_CONTAINER
    assert card["components"][0]["type"] == 10
    btn = card["components"][1]["components"][0]
    assert btn["label"] == "Detener pedido"
    assert parse_stop_button_custom_id(btn["custom_id"]) == ("chan1", "job1")
    marker = read_marker(tmp_path, "chan1", "job1")
    assert marker and marker.get("author_id") == "329811958603972609"
    trail.add_step("🔧 search")
    assert transport.edits[-1]["components"][0]["components"][1]["type"] == 1
    trail.finish(False, note="Cancelado manualmente.")
    done = transport.edits[-1]["components"][0]
    assert done["type"] == TYPE_CONTAINER
    assert done["accent_color"] == CANCEL_COLOR
    assert all(child["type"] != 1 for child in done["components"])
    assert "Cancelado manualmente" in done["components"][0]["content"]


def test_stop_button_off_when_disabled(tmp_path: Path):
    transport = FakeTransport()
    cfg = UnifiedProgressConfig(mode="on", state_dir=tmp_path, min_edit_s=0.0, stop_button_enabled=False)
    trail = LiveTrail(cfg, transport, "c", "j", "x", mono=lambda: 0.0)
    trail.start()
    assert transport.sent[0]["components"] is None
