"""Comandos de cada CLI y el corte de cuota. Los tests no invocan un modelo."""

from __future__ import annotations

import json
import time
from pathlib import Path


def grok_argv(labdir, model: str, effort: str) -> list[str]:
    folder = Path(labdir)
    return [
        "grok",
        "--prompt-file",
        str(folder / "prompt.txt"),
        "--always-approve",
        "--output-format",
        "plain",
        "-m",
        model,
        "--effort",
        effort,
        "--cwd",
        str(folder),
        "--no-subagents",
        "--deny",
        "Bash(git push*)",
        "--deny",
        "Bash(sudo*)",
        "--deny",
        "mcp__*",
    ]


def cursor_argv(labdir, model: str, prompt: str) -> list[str]:
    return [
        "cursor-agent",
        "-p",
        "--output-format",
        "text",
        "--model",
        model,
        "--force",
        "--trust",
        "--workspace",
        str(labdir),
        prompt,
    ]


def opencode_argv(model: str, prompt: str) -> list[str]:
    return ["opencode", "run", "-m", model, prompt]


def choose_cli(reader, policy_route):
    from universal_bot.code_mode.lab_runner import ResolvedRoute

    try:
        remaining = float(reader.grok_remaining())
    except Exception:
        # Sin dato de cuota (no hay archivo, vencido o roto): no se asume grok disponible.
        if policy_route.cli == "grok":
            return ResolvedRoute("cursor-agent", "grok-4.7-high-fast", "high")
        return policy_route
    if remaining <= 0.40:
        return ResolvedRoute("cursor-agent", "grok-4.7-high-fast", "high")
    return policy_route


class FileQuotaReader:
    """Lee `grok_remaining` (0..1) del archivo de cuota. Con `as_of` más viejo que `max_age_s` es dato vencido."""

    def __init__(self, path, *, max_age_s: float | None = 3600.0):
        self.path = Path(path)
        self.max_age_s = max_age_s

    def grok_remaining(self) -> float:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        as_of = raw.get("as_of")
        if self.max_age_s is not None and as_of is not None and time.time() - float(as_of) > self.max_age_s:
            raise ValueError("cuota vencida")
        return float(raw["grok_remaining"])
