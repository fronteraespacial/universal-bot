"""Optional pinned quota board. Off unless the instance turns it on.

The message id is stored in ``quota_pin.json`` via an atomic replace. A 404
on edit deletes nothing durable until a new message is sent and pinned.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from universal_bot.unified_progress.config import (
    ENV_QUOTA_PIN,
    ENV_QUOTA_PIN_CHANNEL,
    UnifiedProgressConfig,
    env_get,
)
from universal_bot.unified_progress.cli_logs import exclusive_file_lock
from universal_bot.unified_progress.quota import bar, pct
from universal_bot.unified_progress.transport import (
    DiscordTransport,
    MessageMissing,
    RateLimited,
    retry_on_rate_limit,
)

log = logging.getLogger("universal_bot.unified_progress.quota_pin")

PERIOD_S = 420
_THREAD_LOCK = threading.Lock()
_TRUTHY = frozenset({"1", "on", "true", "yes"})

# Window names shown per CLI, in order. Missing windows are skipped.
PIN_WINDOWS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cursor", ("auto", "api", "monthly")),
    ("agy", ("5h", "weekly")),
    ("claude", ("5h", "weekly")),
    ("codex", ("5h", "weekly", "daily")),
    ("opencode", ("5h", "weekly", "monthly")),
)
WIN_LABEL = {
    "5h": "5 hours",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "daily": "Daily",
    "auto": "Auto",
    "api": "API",
}

Provider = Callable[[], Mapping[str, Any] | None]


def pin_enabled(cfg: UnifiedProgressConfig, env: Mapping[str, str] | None = None) -> bool:
    """File flag, unless ``UB_QUOTA_PIN`` is set. Default is off."""
    override = env_get(env, ENV_QUOTA_PIN)
    if override is None:
        return bool(cfg.quota_pin_enabled)
    return str(override).strip().lower() in _TRUTHY


def pin_channel(cfg: UnifiedProgressConfig, env: Mapping[str, str] | None = None) -> str:
    override = env_get(env, ENV_QUOTA_PIN_CHANNEL)
    if override is not None and str(override).strip():
        return str(override).strip()
    return str(cfg.quota_pin_channel_id or "").strip()


def state_path(cfg: UnifiedProgressConfig) -> Path:
    return Path(cfg.state_dir) / "quota_pin.json"


def _windows_by_name(record: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    found: dict[str, Mapping[str, Any]] = {}
    for window in (record or {}).get("windows") or []:
        if not isinstance(window, dict) or window.get("remaining_percent") is None:
            continue
        found[str(window.get("name"))] = window
    if not found and isinstance((record or {}).get("w"), dict):
        for name, remaining in record["w"].items():  # type: ignore[union-attr]
            if remaining is None:
                continue
            found[str(name)] = {"name": name, "remaining_percent": remaining}
    return found


def _reset_unix(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        stamp = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return int(stamp.timestamp())


def format_status(
    records: Mapping[str, Mapping[str, Any] | None],
    now_ts: float,
    *,
    cfg: UnifiedProgressConfig,
) -> str:
    """Plain-text board. A CLI with no usable windows says quota is unavailable."""
    lines = [f"📊 **CLI quota · {cfg.display_name}**"]
    for key, windows in PIN_WINDOWS:
        style = cfg.styles.get(key)
        title = f"{style.emoji} {style.label}" if style else key
        record = records.get(key)
        by_name = _windows_by_name(record)
        shown = [name for name in windows if name in by_name]
        ok = bool(record) and record.get("ok") is not False and bool(shown)
        if not ok:
            lines.append(f"**{title}**\nQuota unavailable right now.")
            continue
        rows = []
        for name in shown:
            remaining = float(by_name[name]["remaining_percent"])
            label = WIN_LABEL.get(name, name)
            rows.append(f"{label:<14}{bar(remaining)}  {pct(remaining)}%")
        resets = []
        for name in shown:
            stamp = _reset_unix(by_name[name].get("reset_iso_utc"))  # type: ignore[arg-type]
            if stamp is not None:
                resets.append(f"{WIN_LABEL.get(name, name)}: renews <t:{stamp}:R>")
        section = f"**{title}**\n```\n" + "\n".join(rows) + "\n```"
        if resets:
            section += "\n" + " · ".join(resets)
        lines.append(section)
    free = cfg.styles.get("free")
    free_title = f"{free.emoji} {free.label}" if free else "Free tier"
    lines.append(f"**{free_title}** · free (no quota)")
    stamp = int(now_ts)
    minutes = max(1, PERIOD_S // 60)
    lines.append(
        f"-# Updated <t:{stamp}:t> (<t:{stamp}:R>). "
        f"Refreshes after each job and every {minutes} min."
    )
    return "\n".join(lines)[:2000]


def collect(providers: Mapping[str, Provider]) -> dict[str, dict[str, Any] | None]:
    out: dict[str, dict[str, Any] | None] = {}
    for key, fn in providers.items():
        try:
            record = fn()
            out[key] = dict(record) if isinstance(record, Mapping) else None
        except Exception:
            log.exception("quota pin provider failed key=%s", key)
            out[key] = None
    return out


def _load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_save(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(data)), encoding="utf-8")
    os.replace(tmp, path)


def _missing(exc: BaseException) -> bool:
    if isinstance(exc, MessageMissing):
        return True
    text = str(exc).lower()
    return "404" in text or "unknown message" in text


def update(
    cfg: UnifiedProgressConfig,
    transport: DiscordTransport,
    *,
    records: Mapping[str, Mapping[str, Any] | None] | None = None,
    providers: Mapping[str, Provider] | None = None,
    force: bool = False,
    now: Callable[[], float] | None = None,
    env: Mapping[str, str] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> str | None:
    """Edit the pinned message, or send and pin a new one when it is missing.

    Returns ``None`` when the pin is disabled (the default) or no channel is
    configured. ``force`` bypasses the toggle for a one-shot preview.
    """
    if not force and not pin_enabled(cfg, env):
        return None
    channel = pin_channel(cfg, env)
    if not channel:
        return None
    clock = now or time.time
    if records is None:
        records = collect(providers or {})
    content = format_status(records, clock(), cfg=cfg)
    path = state_path(cfg)
    lock_path = Path(cfg.state_dir) / "quota_pin.lock"

    with _THREAD_LOCK:
        with exclusive_file_lock(lock_path):
            stored = _load_state(path)
            message_id = stored.get("message_id") if stored.get("channel_id") == channel else None
            if message_id:
                try:
                    retry_on_rate_limit(
                        lambda: transport.edit(channel, str(message_id), content=content),
                        retries=cfg.rate_limit_retries,
                        sleep=sleep,
                    )
                    return str(message_id)
                except RateLimited:
                    log.exception("quota pin edit stayed rate limited")
                    return None
                except Exception as exc:
                    if not _missing(exc):
                        log.exception("quota pin edit failed")
                        return None
                    log.info("quota pin message missing; recreating")
            try:
                created = retry_on_rate_limit(
                    lambda: str(transport.send(channel, content=content) or ""),
                    retries=cfg.rate_limit_retries,
                    sleep=sleep,
                )
            except Exception:
                log.exception("quota pin send failed")
                return None
            if not created:
                return None
            try:
                retry_on_rate_limit(
                    lambda: transport.pin(channel, created),
                    retries=cfg.rate_limit_retries,
                    sleep=sleep,
                )
            except Exception:
                log.exception("quota pin failed; message still stored")
            _atomic_save(path, {"channel_id": channel, "message_id": created})
            return created
