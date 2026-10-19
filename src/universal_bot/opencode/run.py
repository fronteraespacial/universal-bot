"""Build ``opencode run --server`` argv and child env (all calls via serve)."""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Sequence

from universal_bot.opencode.env import OpenCodeEnv, load_opencode_env
from universal_bot.opencode.models import (
    effort_to_variant,
    format_go_model,
    format_model_arg,
    remap_free_model,
)
from universal_bot.opencode.serve import lookup_serve_password


@dataclass(frozen=True)
class RunPlan:
    argv: tuple[str, ...]
    env: dict[str, str]
    model_arg: str
    serve_url: str | None
    use_auto: bool
    use_pty: bool


def build_run_argv(
    prompt: str,
    *,
    model: str,
    tier: str = "free",
    effort: str | None = None,
    settings: OpenCodeEnv | None = None,
    use_auto: bool = True,
    output_format: str = "json",
) -> list[str]:
    """Assemble ``opencode run -m … [--server URL|--standalone] [--auto] …``.

    When ``settings.use_serve`` is true (default), always pass ``--server``.
    Free tier remaps via :func:`remap_free_model`; Go uses ``opencode-go/``.
    """
    s = settings or load_opencode_env()
    tier_l = (tier or "free").strip().lower()
    variant = effort_to_variant(effort)

    if tier_l in {"go", "opencode-go", "zen-go"}:
        mid = format_go_model(model or s.default_serve_model)
        model_arg = format_model_arg(mid, variant=variant)
    else:
        free_mid = remap_free_model(model or s.free_model, free_model=s.free_model)
        # Free Zen ids are provider ``opencode/<id>`` (not opencode-go).
        model_arg = format_model_arg(free_mid, provider="opencode", variant=variant)

    cmd: list[str] = [
        s.binary,
        "run",
        "-m",
        model_arg,
        "--format",
        output_format,
    ]
    if use_auto:
        cmd.append("--auto")
    if s.use_serve:
        cmd.extend(["--server", s.serve_url])
    else:
        cmd.append("--standalone")
    cmd.append(prompt)
    return cmd


def prepare_run_env(
    settings: OpenCodeEnv | None = None,
    *,
    base: Mapping[str, str] | None = None,
    password: str | None = None,
    lookup_password: bool = True,
) -> dict[str, str]:
    """Child env for ``opencode run --server``.

    Injects ``OPENCODE_PASSWORD`` from lookup when missing (never logs it).
    Sets ``OPENCODE_CONFIG`` / ``OPENCODE_CONFIG_DIR`` from UB_OPENCODE_* when set
    so each bot uses its own config dir, not a shared ``~/.config/opencode``.
    """
    s = settings or load_opencode_env()
    out: dict[str, str] = dict(base) if base is not None else os.environ.copy()
    if s.config_file:
        out["OPENCODE_CONFIG"] = s.config_file
    if s.config_dir:
        out["OPENCODE_CONFIG_DIR"] = s.config_dir
    if not (out.get("OPENCODE_PASSWORD") or "").strip() and not (
        out.get("OPENCODE_SERVER_PASSWORD") or ""
    ).strip():
        pw = password
        if pw is None and lookup_password and s.use_serve:
            pw = lookup_serve_password(binary=s.binary, environ=out)
        if pw:
            out["OPENCODE_PASSWORD"] = pw
    out.setdefault("TERM", "xterm-256color")
    out.setdefault("CI", "1")
    return out


def plan_run(
    prompt: str,
    *,
    model: str,
    tier: str = "free",
    effort: str | None = None,
    settings: OpenCodeEnv | None = None,
    use_auto: bool = True,
    base_env: Mapping[str, str] | None = None,
    lookup_password: bool = True,
) -> RunPlan:
    """Full plan: argv + env + whether a PTY is required for ``--auto``."""
    s = settings or load_opencode_env()
    argv = build_run_argv(
        prompt,
        model=model,
        tier=tier,
        effort=effort,
        settings=s,
        use_auto=use_auto,
    )
    env = prepare_run_env(s, base=base_env, lookup_password=lookup_password)
    model_arg = ""
    try:
        idx = argv.index("-m")
        model_arg = argv[idx + 1]
    except (ValueError, IndexError):
        model_arg = ""
    return RunPlan(
        argv=tuple(argv),
        env=env,
        model_arg=model_arg,
        serve_url=s.serve_url if s.use_serve else None,
        use_auto=use_auto,
        use_pty=bool(use_auto and s.require_pty_for_auto),
    )


# Re-export for callers that only import run
__all__ = [
    "RunPlan",
    "build_run_argv",
    "prepare_run_env",
    "plan_run",
]
