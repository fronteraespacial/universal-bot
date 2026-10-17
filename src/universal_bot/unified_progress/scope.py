"""off / scoped / on gate for unified progress.

``on`` matches every channel. ``scoped`` matches ``scoped_channel_ids`` and
threads whose ``parent_channel_id`` is in that list. ``off`` matches nothing.
``UB_TRAIL_UNIFIED`` overrides the file mode on each call.
"""

from __future__ import annotations

from typing import Any, Mapping

from universal_bot.unified_progress.config import (
    ENV_MODE,
    UnifiedProgressConfig,
    env_get,
    normalize_mode,
)


def effective_mode(
    cfg: UnifiedProgressConfig,
    env: Mapping[str, str] | None = None,
) -> str:
    """``off``, ``scoped``, or ``on``. Environment wins over the file."""
    override = env_get(env, ENV_MODE)
    if override is None:
        return normalize_mode(cfg.mode)
    return normalize_mode(override)


def in_scope(
    cfg: UnifiedProgressConfig,
    channel_id: Any = None,
    parent_channel_id: Any = None,
    *,
    env: Mapping[str, str] | None = None,
) -> bool:
    """True when this channel (or its parent, for a thread) may use the trail."""
    mode = effective_mode(cfg, env)
    if mode == "on":
        return True
    if mode != "scoped":
        return False
    allowed = set(cfg.scoped_channel_ids)
    channel = str(channel_id or "")
    parent = str(parent_channel_id or "")
    return channel in allowed or parent in allowed


def payload_in_scope(
    cfg: UnifiedProgressConfig,
    payload: Mapping[str, Any] | None,
    *,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Same gate, reading the channel fields a job payload already carries."""
    body = payload or {}
    channel = body.get("reply_in_channel_id") or body.get("channel_id")
    parent = body.get("parent_channel_id")
    return in_scope(cfg, channel, parent, env=env)
