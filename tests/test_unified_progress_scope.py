"""Scope gate: off, scoped (including thread parents), and on."""

import re
from pathlib import Path

from universal_bot.unified_progress.config import UnifiedProgressConfig, load_unified_progress
from universal_bot.unified_progress.scope import effective_mode, in_scope, payload_in_scope

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config" / "instance.example.toml"


def _cfg(**kwargs) -> UnifiedProgressConfig:
    base = dict(mode="scoped", scoped_channel_ids=("chan-a", "chan-b"))
    base.update(kwargs)
    return UnifiedProgressConfig(**base)


def test_off_matches_nothing():
    cfg = _cfg(mode="off")
    assert in_scope(cfg, "chan-a", env={}) is False
    assert in_scope(cfg, "chan-a", "chan-b", env={}) is False


def test_scoped_channel_and_thread_parent():
    cfg = _cfg()
    assert in_scope(cfg, "chan-a", env={}) is True
    assert in_scope(cfg, "somewhere-else", env={}) is False
    assert in_scope(cfg, "thread-1", "chan-b", env={}) is True
    assert in_scope(cfg, "thread-1", "not-listed", env={}) is False


def test_on_matches_every_channel():
    cfg = _cfg(mode="on", scoped_channel_ids=())
    assert in_scope(cfg, "any-channel", env={}) is True


def test_env_overrides_file_mode():
    cfg = _cfg(mode="off")
    assert effective_mode(cfg, {"UB_TRAIL_UNIFIED": "on"}) == "on"
    assert in_scope(cfg, "other", env={"UB_TRAIL_UNIFIED": "on"}) is True
    wide = _cfg(mode="on")
    assert in_scope(wide, "chan-a", env={"UB_TRAIL_UNIFIED": "off"}) is False
    assert in_scope(cfg, "thread-9", "chan-a", env={"UB_TRAIL_UNIFIED": "scoped"}) is True


def test_payload_uses_parent_channel():
    cfg = _cfg()
    payload = {"channel_id": "thread-9", "parent_channel_id": "chan-a", "reply_in_channel_id": "thread-9"}
    assert payload_in_scope(cfg, payload, env={}) is True
    assert payload_in_scope(cfg, {"channel_id": "nope"}, env={}) is False


def test_example_toml_is_off_and_has_no_live_ids():
    cfg = load_unified_progress(EXAMPLE)
    assert cfg.mode == "off"
    assert cfg.quota_pin_enabled is False
    assert cfg.scoped_channel_ids == ()
    assert cfg.cli_logs_channel_id == ""
    assert cfg.quota_pin_channel_id == ""
    assert cfg.rate_limit_retries == 8
    assert cfg.styles["cursor"].color == 0x5865F2
    assert cfg.styles["agy"].color == 0x4285F4
    text = EXAMPLE.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{17,20}\b", text)


def test_toml_section_round_trip(tmp_path: Path):
    path = tmp_path / "instance.toml"
    path.write_text(
        """
        schema_version = 1
        [paths]
        state_dir = "./var"
        [unified_progress]
        mode = "scoped"
        scoped_channel_ids = ["c1", "c2"]
        cli_logs_channel_id = "logs"
        quota_pin_enabled = false
        quota_pin_channel_id = ""
        timezone = "UTC"
        rate_limit_retries = 3
        display_name = "Site"
        [unified_progress.colors]
        cursor = "112233"
        """,
        encoding="utf-8",
    )
    cfg = load_unified_progress(path)
    assert cfg.mode == "scoped"
    assert cfg.scoped_channel_ids == ("c1", "c2")
    assert cfg.cli_logs_channel_id == "logs"
    assert cfg.quota_pin_enabled is False
    assert cfg.rate_limit_retries == 3
    assert cfg.display_name == "Site"
    assert cfg.styles["cursor"].color == 0x112233
    assert cfg.styles["codex"].color == 0x10A37F
    assert cfg.state_dir == (tmp_path / "var").resolve()


def test_package_sources_omit_live_ids():
    package = ROOT / "src" / "universal_bot" / "unified_progress"
    blob = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
    assert not re.search(r"\b\d{17,20}\b", blob), "hard-coded Discord snowflake"
    assert "Frontera" not in blob
    assert "fe-bot" not in blob.lower()
    assert "lab3" not in blob.lower()
