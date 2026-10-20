"""Comandos de cada CLI y el corte de cuota. Los tests no invocan un modelo."""

from __future__ import annotations

import json
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
        "-m",
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
        return policy_route
    if remaining <= 0.40:
        return ResolvedRoute("cursor-agent", "grok-4.7-high-fast", "high")
    return policy_route


class FileQuotaReader:
    def __init__(self, path):
        self.path = Path(path)

    def grok_remaining(self) -> float:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return float(raw["grok_remaining"])
