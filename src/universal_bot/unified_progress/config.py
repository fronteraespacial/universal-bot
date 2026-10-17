"""Instance settings for unified progress.

Values come from the ``[unified_progress]`` table. The mode toggle is also
read live from the environment (``UB_TRAIL_UNIFIED``) so a host can narrow
or widen scope without rewriting the file. This module stores no channel
ids, tokens, or installation names.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

ENV_MODE = "UB_TRAIL_UNIFIED"
ENV_QUOTA_PIN = "UB_QUOTA_PIN"
ENV_QUOTA_PIN_CHANNEL = "UB_QUOTA_PIN_CHANNEL"
ENV_STOP_BUTTON = "UB_STOP_BUTTON"

FAIL_COLOR = 0xF0B232
_ON = frozenset({"1", "on", "true", "yes"})
_SCOPED = frozenset({"scoped"})


@dataclass(frozen=True)
class CliStyle:
    """Label, embed color, and emoji for one CLI family."""

    label: str
    color: int
    emoji: str


DEFAULT_CLI_STYLES: dict[str, CliStyle] = {
    "cursor": CliStyle("Cursor", 0x5865F2, "⚡"),
    "agy": CliStyle("AGY", 0x4285F4, "🔷"),
    "claude": CliStyle("Claude", 0x9B59B6, "🟣"),
    "codex": CliStyle("Codex", 0x10A37F, "🌙"),
    "opencode": CliStyle("OpenCode", 0xE67E22, "🧠"),
    "free": CliStyle("Free tier", 0x95A5A6, "🆓"),
    "grok": CliStyle("Grok", 0x23272A, "🖤"),
}


def default_styles() -> dict[str, CliStyle]:
    return dict(DEFAULT_CLI_STYLES)


@dataclass
class UnifiedProgressConfig:
    """Resolved settings. ``mode`` is the file value; callers apply env on read."""

    mode: str = "off"
    scoped_channel_ids: tuple[str, ...] = ()
    cli_logs_channel_id: str = ""
    quota_pin_enabled: bool = False
    quota_pin_channel_id: str = ""
    styles: dict[str, CliStyle] = field(default_factory=default_styles)
    timezone: str = "UTC"
    rate_limit_retries: int = 8
    display_name: str = "Bot"
    stop_button_enabled: bool = False
    state_dir: Path = field(default_factory=lambda: Path("state"))
    min_edit_s: float = 2.0


def parse_color(value: Any) -> int:
    """Accept ``0x5865F2``, ``#5865F2``, ``5865F2``, or an int."""
    if isinstance(value, bool):
        raise ValueError("color must be an integer or hex string")
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    if text.startswith("#"):
        text = text[1:]
    if text.startswith("0x"):
        text = text[2:]
    return int(text, 16)


def normalize_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in _ON:
        return "on"
    if text in _SCOPED:
        return "scoped"
    return "off"


def env_get(env: Mapping[str, str] | None, key: str) -> str | None:
    """Read ``key`` from ``env``. ``None`` means the process environment.

    A mapping that omits the key does not fall through to the process, so
    tests stay isolated.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    if key not in source:
        return None
    return source.get(key)


def _styles_from_table(table: Mapping[str, Any] | None) -> dict[str, CliStyle]:
    styles = default_styles()
    if not isinstance(table, Mapping):
        return styles
    for key, raw in table.items():
        name = str(key)
        base = styles.get(name, CliStyle(name, DEFAULT_CLI_STYLES["cursor"].color, "⚙️"))
        try:
            color = parse_color(raw)
        except (TypeError, ValueError):
            continue
        styles[name] = CliStyle(base.label, color, base.emoji)
    return styles


def _as_id_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return tuple(out)


def _resolve_state_dir(config_path: Path, data: Mapping[str, Any]) -> Path:
    paths = data.get("paths") if isinstance(data.get("paths"), Mapping) else {}
    raw = str((paths or {}).get("state_dir") or "./state")
    state = Path(os.path.expanduser(raw))
    if not state.is_absolute():
        state = config_path.parent / state
    return state


def config_from_mapping(
    section: Mapping[str, Any] | None,
    *,
    state_dir: Path | str = Path("state"),
) -> UnifiedProgressConfig:
    """Build a config from an already-parsed ``[unified_progress]`` table."""
    raw = section if isinstance(section, Mapping) else {}
    retries = raw.get("rate_limit_retries", 8)
    try:
        retries_i = max(0, int(retries))
    except (TypeError, ValueError):
        retries_i = 8
    try:
        min_edit = float(raw.get("min_edit_s", 2.0))
    except (TypeError, ValueError):
        min_edit = 2.0
    return UnifiedProgressConfig(
        mode=normalize_mode(raw.get("mode", "off")),
        scoped_channel_ids=_as_id_tuple(raw.get("scoped_channel_ids")),
        cli_logs_channel_id=str(raw.get("cli_logs_channel_id") or "").strip(),
        quota_pin_enabled=bool(raw.get("quota_pin_enabled", False)),
        quota_pin_channel_id=str(raw.get("quota_pin_channel_id") or "").strip(),
        styles=_styles_from_table(raw.get("colors") if isinstance(raw.get("colors"), Mapping) else None),
        timezone=str(raw.get("timezone") or "UTC").strip() or "UTC",
        rate_limit_retries=retries_i,
        display_name=str(raw.get("display_name") or "Bot").strip() or "Bot",
        stop_button_enabled=bool(raw.get("stop_button_enabled", False)),
        state_dir=Path(state_dir),
        min_edit_s=max(0.0, min_edit),
    )


def stop_button_enabled(
    cfg: UnifiedProgressConfig,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Live toggle: ``UB_STOP_BUTTON=off`` disables even when the file says on."""
    override = env_get(env, ENV_STOP_BUTTON)
    if override is not None:
        text = str(override).strip().lower()
        if text in frozenset({"0", "off", "false", "no"}):
            return False
        if text in _ON:
            return True
    return bool(cfg.stop_button_enabled)


def load_unified_progress(config_path: Path | str) -> UnifiedProgressConfig:
    """Load ``[unified_progress]`` from an instance TOML file.

    A missing table yields defaults (mode off, quota pin off). Other tables
    are ignored except ``[paths].state_dir``, which anchors marker files.
    """
    path = Path(config_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    section = data.get("unified_progress")
    if section is not None and not isinstance(section, Mapping):
        section = {}
    return config_from_mapping(section, state_dir=_resolve_state_dir(path, data))
