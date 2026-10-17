"""Quota block: bars, before/after, unavailable fallback, free-tier tag."""

from universal_bot.unified_progress.config import default_styles
from universal_bot.unified_progress.quota import (
    BAR_CELLS,
    bar,
    cli_kind,
    format_quota_block,
    quota_footer,
    take_snapshot,
)


def test_bar_is_twenty_cells():
    assert BAR_CELLS == 20
    assert len(bar(0)) == 20
    assert len(bar(50)) == 20
    assert len(bar(100)) == 20
    assert bar(100) == "█" * 20
    assert bar(0) == "░" * 20
    assert set(bar(50)) <= {"█", "░"}


def test_before_after_block_and_provider():
    styles = default_styles()
    before = {"w": {"5h": 80.0, "weekly": 90.0}, "plan": "Pro"}
    seen: list[str] = []

    def provider(kind: str):
        seen.append(kind)
        return {
            "ok": True,
            "plan": "Pro",
            "windows": [
                {"name": "5h", "remaining_percent": 75.0},
                {"name": "weekly", "remaining_percent": 88.0},
            ],
        }

    after = take_snapshot("agy", provider)
    assert seen == ["agy"]
    text = format_quota_block("agy", before, after, styles)
    assert "Quota AGY · Pro · 5 h" in text
    assert "This request" in text
    assert "Remaining" in text
    assert "Weekly" in text
    assert "75.0%" in text
    assert "88.0%" in text
    for line in text.splitlines():
        if "█" in line or "░" in line:
            cells = "".join(ch for ch in line if ch in "█░")
            assert len(cells) == 20
    footer = quota_footer("agy", before, provider, styles)
    assert "75.0%" in footer


def test_quota_unavailable_and_free_tier():
    styles = default_styles()
    missing = format_quota_block("codex", {"w": {"5h": 10}}, None, styles)
    assert missing == "`Codex: quota unavailable`"
    failed = format_quota_block("agy", None, {"ok": False, "windows": []}, styles)
    assert "quota unavailable" in failed
    calls: list[str] = []

    def provider(kind: str):
        calls.append(kind)
        raise RuntimeError("upstream down")

    assert "quota unavailable" in quota_footer("opencode", None, provider, styles)
    assert calls == ["opencode"]
    free = format_quota_block("free", None, None, styles)
    assert free == "`Free tier · free`"
    assert "unavailable" not in free
    assert cli_kind("OpenCode · demo", "model-free") == "free"
    assert cli_kind("AGY · demo") == "agy"
