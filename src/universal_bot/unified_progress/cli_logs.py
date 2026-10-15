"""One embed per job in the configured logs channel, plus a text attachment on overflow."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping
from zoneinfo import ZoneInfo

from universal_bot.unified_progress.config import FAIL_COLOR, UnifiedProgressConfig
from universal_bot.unified_progress.quota import cli_kind
from universal_bot.unified_progress.transport import DiscordTransport, retry_on_rate_limit

log = logging.getLogger("universal_bot.unified_progress.cli_logs")

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore

SEP = "━━━━━━━━━━━━━━━━━━━━━━"
DESC_MAX = 3900
DESC_HARD = 4096
ATTACHMENT_NAME = "trail.txt"


def display_zone(name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def message_link(guild_id: str, channel_id: str, message_id: str) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def dur_text(seconds: float) -> str:
    whole = int(max(0, seconds))
    if whole < 60:
        return f"{whole} s"
    return f"{whole // 60}:{whole % 60:02d}"


def _elapsed(trail: Any, now: float | None = None) -> float:
    end = getattr(trail, "ended", None)
    if end is None:
        end = now if now is not None else trail.started
    return float(end) - float(trail.started)


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    """Cross-process lock so two jobs cannot interleave one logs post."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a", encoding="utf-8")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def job_log_embed(
    trail: Any,
    meta: Mapping[str, Any],
    quota_block: str = "",
    *,
    cfg: UnifiedProgressConfig,
    channel_name: str | None = None,
    now: float | None = None,
) -> tuple[dict[str, Any], tuple[str, bytes] | None]:
    """Header, steps, close line, quota. Oversized step lists become ``trail.txt``."""
    kind = cli_kind(getattr(trail, "label", ""), str(meta.get("model") or ""))
    style = cfg.styles.get(kind) or cfg.styles.get("cursor")
    ok = getattr(trail, "state", "") == "done"
    color = (style.color if style else 0x5865F2) if ok else FAIL_COLOR
    emoji = style.emoji if style else "⚙️"
    steps_raw = list(getattr(trail, "steps", []) or [])
    n = len(steps_raw)
    elapsed = _elapsed(trail, now)
    started = datetime.fromtimestamp(float(trail.started), display_zone(cfg.timezone))
    start_label = started.strftime("%d/%m %H:%M:%S %Z")
    who = str(meta.get("author") or "?")[:40]
    request = str(meta.get("request") or "")[:160]
    channel = channel_name or str(meta.get("channel_name") or meta.get("channel_id") or "?")
    link = str(meta.get("origin_link") or "")
    if not link and meta.get("job_id") and meta.get("channel_id") and meta.get("guild_id"):
        link = message_link(str(meta["guild_id"]), str(meta["channel_id"]), str(meta["job_id"]))
    head = [f"📍 {channel}" + (f" · [request]({link})" if link else "")]
    head.append(f"👤 {who} · 🕐 {start_label}")
    head.append(f"🆔 job `{meta.get('job_id') or '?'}`")
    if request:
        head.append(f"💬 “{request}”")
    note = str(getattr(trail, "note", "") or "")
    close_word = "OK" if ok else (note or "ended with error")
    mark = "✅" if ok else "⚠️"
    step_word = "step" if n == 1 else "steps"
    close = f"{mark} **{close_word}** · ⏱️ {dur_text(elapsed)} · {n} {step_word}"
    steps = [f"· {line}" for line in steps_raw] or ["· (no steps recorded)"]
    quota = quota_block.strip()
    quota_part = f"\n{quota}" if quota else ""
    head_txt = "\n".join(head)
    fixed = f"{head_txt}\n{SEP}\n\n{SEP}\n{close}{quota_part}"
    room = DESC_MAX - len(fixed)
    body = "\n".join(steps)
    attachment: tuple[str, bytes] | None = None
    if len(body) > max(0, room):
        full = "\n".join(
            head + ["-" * 30] + [f"- {line}" for line in steps_raw] + ["-" * 30, close]
        )
        if quota:
            full = f"{full}\n{quota}"
        attachment = (ATTACHMENT_NAME, (full + "\n").encode("utf-8"))
        kept: list[str] = []
        for line in reversed(steps):
            used = sum(len(item) + 1 for item in kept) + len(line) + 80
            if used > max(0, room):
                break
            kept.insert(0, line)
        omitted = len(steps) - len(kept)
        body = f"· … {omitted} earlier steps in {ATTACHMENT_NAME}\n" + "\n".join(kept)
    description = f"{head_txt}\n{SEP}\n{body}\n{SEP}\n{close}{quota_part}"
    if len(description) > DESC_HARD:
        description = description[: DESC_HARD - 1] + "…"
    title = f"{emoji} {getattr(trail, 'label', kind)}"[:256]
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "footer": {"text": f"{style.label if style else kind} · job {meta.get('job_id') or '?'}"},
        "timestamp": datetime.fromtimestamp(float(trail.started), timezone.utc).isoformat(),
    }
    return embed, attachment


def post_job_log(
    cfg: UnifiedProgressConfig,
    transport: DiscordTransport,
    trail: Any,
    meta: Mapping[str, Any],
    quota_block: str = "",
    *,
    channel_name: str | None = None,
    sleep: Any = None,
    now: float | None = None,
) -> str | None:
    """Post the job embed under a file lock. Empty logs channel is a no-op."""
    channel_id = str(cfg.cli_logs_channel_id or "").strip()
    if not channel_id:
        return None
    embed, attachment = job_log_embed(
        trail, meta, quota_block, cfg=cfg, channel_name=channel_name, now=now
    )
    files = None
    if attachment:
        files = [{"filename": attachment[0], "data": attachment[1]}]

    def _send() -> str:
        return str(
            transport.send(channel_id, content="", embeds=[embed], files=files) or ""
        )

    lock_path = Path(cfg.state_dir) / "cli_logs_post.lock"
    try:
        with exclusive_file_lock(lock_path):
            message_id = retry_on_rate_limit(
                _send, retries=cfg.rate_limit_retries, sleep=sleep
            )
    except Exception:
        log.exception("job log post failed")
        return None
    return message_id or None
