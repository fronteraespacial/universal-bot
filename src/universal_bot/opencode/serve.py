"""Shared ``opencode serve`` helpers: URL, healthcheck, password, restart."""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from universal_bot.opencode.env import OpenCodeEnv, load_opencode_env


@dataclass(frozen=True)
class ServeHealth:
    ok: bool
    url: str
    version: str | None = None
    detail: str | None = None


def serve_url(settings: OpenCodeEnv | None = None) -> str:
    s = settings or load_opencode_env()
    return s.serve_url


def healthcheck(
    settings: OpenCodeEnv | None = None,
    *,
    timeout_s: float = 3.0,
    opener: Callable[..., object] | None = None,
) -> ServeHealth:
    """GET ``/global/health`` on the shared serve (loopback only).

    Official OpenCode server API: ``GET /global/health`` →
    ``{ healthy: true, version: string }`` (see opencode.ai/docs/server).
    """
    s = settings or load_opencode_env()
    url = f"{s.serve_url.rstrip('/')}/global/health"
    open_fn = opener or urllib.request.urlopen
    try:
        req = urllib.request.Request(url, method="GET")
        with open_fn(req, timeout=timeout_s) as resp:  # type: ignore[arg-type]
            body = resp.read()  # type: ignore[attr-defined]
            data = json.loads(body.decode("utf-8", errors="replace"))
        healthy = bool(data.get("healthy")) if isinstance(data, dict) else False
        version = None
        if isinstance(data, dict):
            version = str(data.get("version") or "") or None
        return ServeHealth(ok=healthy, url=url, version=version)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return ServeHealth(ok=False, url=url, detail=str(exc)[:200])


def lookup_serve_password(
    *,
    binary: str = "opencode",
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., str] | None = None,
    timeout_s: float = 10.0,
) -> str | None:
    """Resolve the serve basic-auth password without reading credential files.

    Prefer ``OPENCODE_PASSWORD`` / ``OPENCODE_SERVER_PASSWORD`` already in the
    environment. Otherwise call ``opencode service get password`` (password is
    managed by OpenCode itself under the user config dir — never copy it into
    the pack or this repo).
    """
    env = dict(environ) if environ is not None else None
    import os

    src = env if env is not None else os.environ
    for key in ("OPENCODE_PASSWORD", "OPENCODE_SERVER_PASSWORD"):
        val = (src.get(key) or "").strip()
        if val:
            return val

    def _default_runner() -> str:
        return subprocess.check_output(
            [binary, "service", "get", "password"],
            text=True,
            timeout=timeout_s,
            stderr=subprocess.DEVNULL,
            env=env,
        )

    run = runner or _default_runner
    try:
        out = run()
    except Exception:
        return None
    pw = (out or "").strip()
    return pw or None


def restart_serve_hint(settings: OpenCodeEnv | None = None) -> dict[str, Sequence[str]]:
    """Commands a host watchdog can run to restart the shared serve.

    Linux: ``systemctl --user restart`` on the instance unit.
    Also exposes the raw CLI fallback ``opencode service restart``.
    Never embeds passwords.
    """
    s = settings or load_opencode_env()
    unit = "ub-opencode-serve.service"
    return {
        "linux_systemd_user": (
            "systemctl",
            "--user",
            "restart",
            unit,
        ),
        "cli_service": (s.binary, "service", "restart"),
        "cli_serve_foreground": (
            s.binary,
            "serve",
            "--hostname",
            s.host,
            "--port",
            str(s.port),
        ),
        "health_url": (f"{s.serve_url.rstrip('/')}/global/health",),
    }
