"""Per-CLI quota block: before/after snapshots, 20-cell bars, soft failure.

Providers are plain callables. This module does not know how a host reads
usage, and it does not talk to a network.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from universal_bot.unified_progress.config import DEFAULT_CLI_STYLES, CliStyle

log = logging.getLogger("universal_bot.unified_progress.quota")

BAR_CELLS = 20
WIN_ORDER = ("5h", "weekly", "daily", "monthly", "auto", "api")
WIN_LABEL = {
    "5h": "5 h",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "daily": "Daily",
    "auto": "Auto",
    "api": "API",
}
_SKIP_APPEND = frozenset({"cursor", "grok"})
_FREE = frozenset({"free", "zen_free"})

QuotaProvider = Callable[[str], Mapping[str, Any] | None]


def bar(percent: float, *, min_one: bool = False) -> str:
    """Twenty-cell remaining/used bar. ``min_one`` keeps a sliver visible."""
    value = max(0.0, min(100.0, float(percent)))
    filled = int(round(value / 100 * BAR_CELLS))
    if min_one and value >= 0.05 and filled == 0:
        filled = 1
    return "█" * filled + "░" * (BAR_CELLS - filled)


def pct(value: float) -> str:
    return f"{float(value):.1f}"


def cli_kind(label: str, model: str = "") -> str:
    """Map a trail label (and optional model id) to a style key."""
    lab = str(label or "").lower().strip()
    model_l = str(model or "").lower().strip()
    if lab.startswith("cursor") or lab.startswith("composer"):
        return "cursor"
    if lab.startswith("claude") or lab.startswith("agy claude"):
        return "claude"
    if lab.startswith("agy"):
        return "agy"
    if lab.startswith("codex"):
        return "codex"
    if lab.startswith("grok"):
        return "grok"
    free_model = model_l.endswith("-free") or model_l == "free"
    if lab.startswith("free") or (free_model and (lab.startswith("opencode") or lab.startswith("zen") or not lab)):
        return "free"
    if lab.startswith("opencode") or lab.startswith("zen"):
        return "free" if free_model else "opencode"
    if free_model:
        return "free"
    return "cursor"


def normalize_snapshot(record: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Accept either ``{"w": {window: percent}}`` or a provider record with ``windows``."""
    if not isinstance(record, dict):
        return None
    if record.get("ok") is False:
        return None
    if isinstance(record.get("w"), dict):
        windows: dict[str, float] = {}
        for key, raw in record["w"].items():
            if raw is None:
                continue
            try:
                windows[str(key)] = float(raw)
            except (TypeError, ValueError):
                continue
        if not windows:
            return None
        return {"w": windows, "plan": str(record.get("plan") or "")}
    windows = {}
    for window in record.get("windows") or []:
        if not isinstance(window, dict) or window.get("remaining_percent") is None:
            continue
        try:
            windows[str(window.get("name"))] = float(window["remaining_percent"])
        except (TypeError, ValueError):
            continue
    if not windows:
        return None
    return {"w": windows, "plan": str(record.get("plan") or "")}


def take_snapshot(kind: str, provider: QuotaProvider | None) -> dict[str, Any] | None:
    """Run ``provider(kind)`` and normalize. Any failure becomes ``None``."""
    if provider is None:
        return None
    try:
        return normalize_snapshot(provider(kind))
    except Exception:
        log.exception("quota provider failed kind=%s", kind)
        return None


def _style(styles: Mapping[str, CliStyle], kind: str) -> CliStyle:
    if kind in styles:
        return styles[kind]
    if kind in DEFAULT_CLI_STYLES:
        return DEFAULT_CLI_STYLES[kind]
    return CliStyle(kind, DEFAULT_CLI_STYLES["cursor"].color, "⚙️")


def format_quota_block(
    kind: str,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    styles: Mapping[str, CliStyle] | None = None,
) -> str:
    """Code block for one CLI. Missing data yields the quota-unavailable line.

    ``before`` / ``after`` are snapshots (``w`` maps window name to remaining
    percent). The first known window is the headline; the drop between
    snapshots is "This request".
    """
    chosen = styles if styles is not None else DEFAULT_CLI_STYLES
    if kind in _FREE:
        free = _style(chosen, "free")
        return f"`{free.label} · free`"
    style = _style(chosen, kind)
    after_snap = normalize_snapshot(after) if after is not None else None
    if after_snap is None:
        return f"`{style.label}: quota unavailable`"
    before_snap = normalize_snapshot(before) if before is not None else None
    after_w: dict[str, float] = after_snap["w"]
    before_w: dict[str, float] = (before_snap or {}).get("w") or {}
    order = [key for key in WIN_ORDER if key in after_w]
    for key in after_w:
        if key not in order:
            order.append(key)
    main = order[0]
    plan = str(after_snap.get("plan") or "").strip()
    head = f"Quota {style.label}"
    if plan and plan.lower() not in style.label.lower():
        head += f" · {plan}"
    head += f" · {WIN_LABEL.get(main, main)}"
    rows: list[tuple[str, str, str]] = []
    if main in before_w:
        used = max(0.0, float(before_w[main]) - float(after_w[main]))
        used_text = "<0.1%" if used < 0.05 else f"{pct(used)}%"
        rows.append(("This request", bar(used, min_one=used >= 0.05), used_text))
    rows.append(("Remaining", bar(float(after_w[main])), f"{pct(float(after_w[main]))}%"))
    for key in order[1:]:
        rows.append((WIN_LABEL.get(key, key), bar(float(after_w[key])), f"{pct(float(after_w[key]))}%"))
    label_w = max(len(row[0]) for row in rows)
    pct_w = max(len(row[2]) for row in rows)
    body = "\n".join(f"{label.ljust(label_w)} {cells}  {text.rjust(pct_w)}" for label, cells, text in rows)
    return f"```\n{head}\n{body}\n```"


def quota_footer(
    kind: str,
    before: Mapping[str, Any] | None,
    provider: QuotaProvider | None,
    styles: Mapping[str, CliStyle] | None = None,
) -> str:
    """Format the block, taking the after snapshot from ``provider`` when needed."""
    if kind in _FREE:
        return format_quota_block(kind, None, None, styles)
    return format_quota_block(kind, before, take_snapshot(kind, provider), styles)


def append_quota(
    text: str,
    kind: str,
    before: Mapping[str, Any] | None,
    provider: QuotaProvider | None,
    styles: Mapping[str, CliStyle] | None = None,
) -> str:
    """Append a quota block. Cursor and Grok stay unchanged (no remote block)."""
    if kind in _SKIP_APPEND:
        return text
    body = str(text or "").rstrip()
    tail = body[-400:] if body else ""
    if "quota unavailable" in tail or tail.strip().startswith("```") and "Quota " in tail:
        return text
    foot = quota_footer(kind, before, provider, styles)
    return f"{body}\n{foot}" if body else foot
