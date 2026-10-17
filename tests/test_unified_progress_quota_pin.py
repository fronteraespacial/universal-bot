"""Pinned quota board stays off unless enabled, and a 404 recreates the pin."""

import json
from pathlib import Path

from tests.up_fakes import FakeTransport
from universal_bot.unified_progress.config import UnifiedProgressConfig
from universal_bot.unified_progress.quota_pin import pin_enabled, state_path, update


def _cfg(tmp_path: Path, **kwargs) -> UnifiedProgressConfig:
    data = dict(state_dir=tmp_path, quota_pin_enabled=False, quota_pin_channel_id="pin-chan", display_name="Bot")
    data.update(kwargs)
    return UnifiedProgressConfig(**data)


def test_pin_is_off_by_default(tmp_path: Path):
    transport = FakeTransport()
    cfg = UnifiedProgressConfig(state_dir=tmp_path)
    assert cfg.quota_pin_enabled is False
    assert pin_enabled(cfg, env={}) is False
    assert update(cfg, transport, records={}, env={}) is None
    assert transport.sent == []
    assert transport.edits == []
    assert transport.pins == []


def test_env_can_turn_pin_on(tmp_path: Path):
    transport = FakeTransport()
    cfg = _cfg(tmp_path, quota_pin_enabled=False)
    message_id = update(
        cfg,
        transport,
        records={"agy": {"ok": False}},
        env={"UB_QUOTA_PIN": "on"},
        now=lambda: 1_700_000_000.0,
    )
    assert message_id == "m1"
    assert transport.pins == [{"channel_id": "pin-chan", "message_id": "m1"}]
    assert "Quota unavailable right now." in transport.sent[0]["content"]
    stored = json.loads(state_path(cfg).read_text(encoding="utf-8"))
    assert stored == {"channel_id": "pin-chan", "message_id": "m1"}
    assert not list(tmp_path.glob("*.tmp"))


def test_edit_existing_then_recreate_on_404(tmp_path: Path):
    transport = FakeTransport()
    cfg = _cfg(tmp_path, quota_pin_enabled=True)
    records = {
        "agy": {
            "ok": True,
            "windows": [{"name": "5h", "remaining_percent": 40.0}],
        }
    }
    first = update(cfg, transport, records=records, env={}, now=lambda: 1_700_000_100.0)
    assert first == "m1"
    assert len(transport.sent) == 1
    assert transport.pins[0]["message_id"] == "m1"
    body = transport.sent[0]["content"]
    assert "40.0%" in body
    cells = "".join(ch for ch in body if ch in "█░")
    assert len(cells) == 20

    second = update(cfg, transport, records=records, env={}, now=lambda: 1_700_000_200.0)
    assert second == "m1"
    assert len(transport.sent) == 1
    assert transport.edits[-1]["message_id"] == "m1"
    assert "40.0%" in transport.edits[-1]["content"]

    transport.missing.add("m1")
    third = update(cfg, transport, records=records, env={}, now=lambda: 1_700_000_300.0)
    assert third == "m2"
    assert transport.pins[-1] == {"channel_id": "pin-chan", "message_id": "m2"}
    stored = json.loads(state_path(cfg).read_text(encoding="utf-8"))
    assert stored["message_id"] == "m2"
    assert stored["channel_id"] == "pin-chan"
    assert not list(tmp_path.glob("quota_pin.json.tmp"))
