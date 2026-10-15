"""Job log embed: header, steps, close, quota, and overflow attachment."""

from pathlib import Path

from tests.up_fakes import FakeTransport
from universal_bot.unified_progress.cli_logs import ATTACHMENT_NAME, job_log_embed, post_job_log
from universal_bot.unified_progress.config import UnifiedProgressConfig
from universal_bot.unified_progress.quota import format_quota_block
from universal_bot.unified_progress.trail import Trail


def _trail(steps: list[str]) -> Trail:
    trail = Trail("AGY · demo", now=lambda: 1_700_000_000.0)
    for step in steps:
        trail.add(step)
    trail.finish(True)
    return trail


def _cfg(tmp_path: Path) -> UnifiedProgressConfig:
    return UnifiedProgressConfig(
        cli_logs_channel_id="logs",
        state_dir=tmp_path,
        timezone="UTC",
        display_name="Bot",
        rate_limit_retries=2,
    )


def test_embed_has_header_steps_close_and_quota(tmp_path: Path):
    cfg = _cfg(tmp_path)
    quota = format_quota_block(
        "agy",
        {"w": {"5h": 80.0}, "plan": "Pro"},
        {"w": {"5h": 79.0}, "plan": "Pro"},
        cfg.styles,
    )
    trail = _trail(["read config", "edit module"])
    meta = {
        "author": "ada",
        "request": "port the trail",
        "channel_id": "chan",
        "channel_name": "#work",
        "guild_id": "g1",
        "job_id": "job-7",
    }
    embed, attachment = job_log_embed(trail, meta, quota, cfg=cfg)
    assert attachment is None
    desc = embed["description"]
    assert "#work" in desc
    assert "ada" in desc
    assert "job-7" in desc
    assert "port the trail" in desc
    assert "read config" in desc
    assert "edit module" in desc
    assert "OK" in desc
    assert "quota unavailable" not in desc
    assert "79.0%" in desc
    assert embed["color"] == cfg.styles["agy"].color
    assert "AGY" in embed["title"]
    transport = FakeTransport()
    message_id = post_job_log(cfg, transport, trail, meta, quota)
    assert message_id == "m1"
    assert transport.sent[0]["channel_id"] == "logs"
    assert transport.sent[0]["embeds"][0]["description"] == desc
    assert (tmp_path / "cli_logs_post.lock").exists()


def test_overflow_becomes_attachment(tmp_path: Path):
    cfg = _cfg(tmp_path)
    steps = [f"step-{index:03d}-" + ("x" * 60) for index in range(80)]
    trail = _trail(steps)
    embed, attachment = job_log_embed(trail, {"job_id": "job-9", "author": "ada"}, "", cfg=cfg)
    assert attachment is not None
    filename, data = attachment
    assert filename == ATTACHMENT_NAME
    text = data.decode("utf-8")
    assert "step-000" in text
    assert "step-079" in text
    assert "step-000" not in embed["description"]
    assert "earlier steps in trail.txt" in embed["description"]
    assert "step-079" in embed["description"]
    assert len(embed["description"]) <= 4096
    transport = FakeTransport()
    post_job_log(cfg, transport, trail, {"job_id": "job-9", "author": "ada"}, "")
    files = transport.sent[0]["files"]
    assert files and files[0]["filename"] == ATTACHMENT_NAME
    assert b"step-000" in files[0]["data"]
