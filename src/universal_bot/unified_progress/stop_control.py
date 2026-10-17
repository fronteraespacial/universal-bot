"""Stop button on live progress cards (Discord message components).

The host gateway handles ``INTERACTION_CREATE``, checks ACL, kills the job,
and calls :meth:`LiveTrail.finish` with a cancel note. This module only builds
``custom_id`` values and action-row payloads within Discord limits.
"""

from __future__ import annotations

import re
from typing import Any

STOP_PREFIX = "ub:stop:"
STOP_BUTTON_LABEL = "Detener pedido"
CUSTOM_ID_MAX = 100

# Components V2: a Container is the card. An action row nested in it draws
# inside the card. A row beside an embed always sits underneath.
IS_COMPONENTS_V2 = 1 << 15
TYPE_ACTION_ROW = 1
TYPE_TEXT_DISPLAY = 10
TYPE_CONTAINER = 17

# Manual stop. Distinct from the running blurple and the amber failure color.
CANCEL_COLOR = 0xE74C3C
INACTIVE_COLOR = 0x99AAB5

# Snowflake-style ids from Discord; job ids may be alphanumeric.
_ID_PART = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def stop_button_custom_id(channel_id: Any, job_id: Any) -> str:
    """Stable custom_id for one running job (≤100 chars)."""
    chan = str(channel_id or "").strip()
    job = str(job_id or "").strip()
    if not chan or not job:
        raise ValueError("channel_id and job_id required for stop button")
    if not _ID_PART.match(chan) or not _ID_PART.match(job):
        raise ValueError("channel_id or job_id contains unsupported characters")
    raw = f"{STOP_PREFIX}{chan}:{job}"
    if len(raw) > CUSTOM_ID_MAX:
        raise ValueError("stop button custom_id exceeds Discord limit")
    return raw


def parse_stop_button_custom_id(custom_id: str) -> tuple[str, str] | None:
    """Return ``(channel_id, job_id)`` when ``custom_id`` is a stop button."""
    text = str(custom_id or "").strip()
    if not text.startswith(STOP_PREFIX):
        return None
    rest = text[len(STOP_PREFIX) :]
    if ":" not in rest:
        return None
    chan, job = rest.split(":", 1)
    chan, job = chan.strip(), job.strip()
    if not chan or not job:
        return None
    if not _ID_PART.match(chan) or not _ID_PART.match(job):
        return None
    return chan, job


def is_manual_cancel(note: str) -> bool:
    """True when a finish note is a person stopping the job, not an error."""
    return "cancelad" in (note or "").lower()


def embed_markdown(embed: dict[str, Any]) -> str:
    """Plain-markdown body of a progress embed, for a text display inside a card."""
    parts: list[str] = []
    title = str(embed.get("title") or "").strip()
    if title:
        parts.append(f"**{title}**")
    desc = str(embed.get("description") or "").strip()
    if desc:
        parts.append(desc)
    footer = embed.get("footer") if isinstance(embed.get("footer"), dict) else {}
    foot = str((footer or {}).get("text") or "").strip()
    if foot:
        parts.append(f"-# {foot}")
    text = "\n".join(parts).strip()
    return (text or "…")[:3900]


def progress_card(
    markdown: str,
    *,
    accent: int,
    action_row: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """One Container. The stop button, when present, is a child of that container."""
    text = (markdown or "").strip()[:3900] or "…"
    children: list[dict[str, Any]] = [{"type": TYPE_TEXT_DISPLAY, "content": text}]
    if action_row:
        children.append(action_row)
    return [
        {
            "type": TYPE_CONTAINER,
            "accent_color": int(accent) & 0xFFFFFF,
            "components": children,
        }
    ]


def running_stop_components(channel_id: Any, job_id: Any) -> list[dict[str, Any]]:
    """The action row nested inside the live progress card."""
    return [
        {
            "type": TYPE_ACTION_ROW,
            "components": [
                {
                    "type": 2,
                    "style": 4,
                    "label": STOP_BUTTON_LABEL,
                    "custom_id": stop_button_custom_id(channel_id, job_id),
                }
            ],
        }
    ]
