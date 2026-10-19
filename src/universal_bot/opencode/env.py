"""UB_OPENCODE_* environment parsing (no FE_ aliases)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


DEFAULT_PORT = 49374
DEFAULT_HOST = "127.0.0.1"
DEFAULT_FREE_MODEL = "deepseek-v4.1-flash-free"
DEFAULT_DEFAULT_SERVE_MODEL = "deepseek-v4.1-flash"


def _truthy(raw: str | None, default: bool = True) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


@dataclass(frozen=True)
class OpenCodeEnv:
    """Resolved OpenCode V2 settings for one bot instance."""

    use_serve: bool = True
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    free_model: str = DEFAULT_FREE_MODEL
    default_serve_model: str = DEFAULT_DEFAULT_SERVE_MODEL
    config_dir: str | None = None
    config_file: str | None = None
    binary: str = "opencode"
    require_pty_for_auto: bool = True

    @property
    def serve_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def load_opencode_env(environ: Mapping[str, str] | None = None) -> OpenCodeEnv:
    """Load settings from UB_OPENCODE_* only (never FE_OPENCODE_*)."""
    env = environ if environ is not None else os.environ
    port_raw = (env.get("UB_OPENCODE_PORT") or str(DEFAULT_PORT)).strip()
    try:
        port = int(port_raw)
    except ValueError:
        port = DEFAULT_PORT
    if port < 1 or port > 65535:
        port = DEFAULT_PORT
    host = (env.get("UB_OPENCODE_HOST") or DEFAULT_HOST).strip() or DEFAULT_HOST
    # Bind loopback only by default policy; refuse wildcard in helpers.
    if host in {"0.0.0.0", "::", "[::]"}:
        host = DEFAULT_HOST
    return OpenCodeEnv(
        use_serve=_truthy(env.get("UB_OPENCODE_USE_SERVE"), default=True),
        host=host,
        port=port,
        free_model=(env.get("UB_OPENCODE_FREE_MODEL") or DEFAULT_FREE_MODEL).strip()
        or DEFAULT_FREE_MODEL,
        default_serve_model=(
            env.get("UB_OPENCODE_DEFAULT_SERVE_MODEL") or DEFAULT_DEFAULT_SERVE_MODEL
        ).strip()
        or DEFAULT_DEFAULT_SERVE_MODEL,
        config_dir=(env.get("UB_OPENCODE_CONFIG_DIR") or "").strip() or None,
        config_file=(env.get("UB_OPENCODE_CONFIG") or "").strip() or None,
        binary=(env.get("UB_OPENCODE_BIN") or "opencode").strip() or "opencode",
        require_pty_for_auto=_truthy(env.get("UB_OPENCODE_REQUIRE_PTY"), default=True),
    )
