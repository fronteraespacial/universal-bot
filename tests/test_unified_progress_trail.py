"""Live trail: edit the same message, and keep concurrent jobs apart."""

from pathlib import Path

from tests.up_fakes import FakeTransport
from universal_bot.unified_progress.config import UnifiedProgressConfig
from universal_bot.unified_progress.trail import (
    LiveTrail,
    events_path,
    format_tool_line,
    marker_path,
    push_event,
)


def _cfg(tmp_path: Path, **kwargs) -> UnifiedProgressConfig:
    data = dict(mode="on", state_dir=tmp_path, min_edit_s=0.0, display_name="Bot", rate_limit_retries=4)
    data.update(kwargs)
    return UnifiedProgressConfig(**data)


def _clock():
    holder = {"t": 1_700_000_000.0}

    def now() -> float:
        return holder["t"]

    return now


def test_edit_in_place_keeps_one_message(tmp_path: Path):
    transport = FakeTransport()
    trail = LiveTrail(
        _cfg(tmp_path),
        transport,
        "chan",
        "job-1",
        "AGY · demo",
        now=_clock(),
        mono=lambda: 0.0,
    )
    trail.start()
    assert len(transport.sent) == 1
    message_id = transport.sent[0]["id"]
    assert transport.sent[0]["channel_id"] == "chan"
    assert trail.add_step("🔧 search") is True
    assert trail.add_step("🔧 search") is False
    assert len(transport.sent) == 1
    assert transport.edits
    assert all(edit["message_id"] == message_id for edit in transport.edits)
    assert "search" in transport.edits[-1]["embeds"][0]["description"]
    assert trail.trail.steps == ["🔧 search"]


def test_concurrent_jobs_do_not_share_steps(tmp_path: Path):
    transport = FakeTransport()
    cfg = _cfg(tmp_path)
    now = _clock()
    first = LiveTrail(cfg, transport, "chan", "job-a", "AGY", now=now, mono=lambda: 0.0)
    second = LiveTrail(cfg, transport, "chan", "job-b", "Codex", now=now, mono=lambda: 0.0)
    first.start()
    second.start()
    assert push_event(tmp_path, "chan", "job-a", "alpha-step") is True
    assert push_event(tmp_path, "chan", "job-b", "beta-step") is True
    assert push_event(tmp_path, "chan", "job-a", "alpha-step") is True
    first.poll_events()
    second.poll_events()
    assert first.trail.steps == ["alpha-step"]
    assert second.trail.steps == ["beta-step"]
    alpha_file = events_path(tmp_path, "chan", "job-a").read_text(encoding="utf-8")
    beta_file = events_path(tmp_path, "chan", "job-b").read_text(encoding="utf-8")
    assert "beta-step" not in alpha_file
    assert "alpha-step" not in beta_file
    assert first.message_id != second.message_id
    first_edits = [edit for edit in transport.edits if edit["message_id"] == first.message_id]
    assert first_edits
    assert all("beta-step" not in (edit["embeds"][0]["description"]) for edit in first_edits)
    first.finish(True)
    assert marker_path(tmp_path, "chan", "job-a").exists() is False
    assert marker_path(tmp_path, "chan", "job-b").exists() is True
    assert second.trail.steps == ["beta-step"]


def test_tool_line_and_start_retries_429(tmp_path: Path):
    line = format_tool_line("search", {"query": "quota windows"})
    assert line is not None and "search" in line and "quota windows" in line
    sleeps: list[float] = []
    transport = FakeTransport()
    transport.fail_send_remaining = 2
    transport.retry_after = 0.2
    trail = LiveTrail(
        _cfg(tmp_path),
        transport,
        "chan",
        "job-9",
        "Codex",
        now=_clock(),
        mono=lambda: 0.0,
        sleep=sleeps.append,
    )
    trail.start()
    assert trail.message_id == "m1"
    assert sleeps == [0.2, 0.2]
    assert len(transport.sent) == 1


def test_exhausted_429_does_not_publish(tmp_path: Path):
    transport = FakeTransport()
    transport.fail_send_remaining = 5
    trail = LiveTrail(
        _cfg(tmp_path, rate_limit_retries=1),
        transport,
        "chan",
        "job-x",
        "AGY",
        now=_clock(),
        sleep=lambda _delay: None,
    )
    trail.start()
    assert trail.message_id is None
    assert transport.sent == []
    assert marker_path(tmp_path, "chan", "job-x").exists() is False
