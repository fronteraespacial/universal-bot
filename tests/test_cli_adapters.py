"""Flags de cada CLI y el corte de cuota, sin invocar un modelo."""

import json
from pathlib import Path

import pytest

from universal_bot.code_mode.cli_adapters import (
    FileQuotaReader,
    choose_cli,
    cursor_argv,
    grok_argv,
    opencode_argv,
)
from universal_bot.code_mode.lab_runner import ResolvedRoute

LAB = Path("/lab")
POLICY = ResolvedRoute("grok", "grok-4.7", "medium")
CURSOR = ResolvedRoute("cursor-agent", "grok-4.7-high-fast", "high")


def test_grok_argv_is_the_contract():
    assert grok_argv(LAB, "grok-4.7", "medium") == [
        "grok",
        "--prompt-file",
        str(LAB / "prompt.txt"),
        "--always-approve",
        "--output-format",
        "plain",
        "-m",
        "grok-4.7",
        "--effort",
        "medium",
        "--cwd",
        str(LAB),
        "--no-subagents",
        "--deny",
        "Bash(git push*)",
        "--deny",
        "Bash(sudo*)",
        "--deny",
        "mcp__*",
    ]


def test_cursor_argv_puts_effort_in_the_model_slug():
    assert cursor_argv(LAB, "grok-4.7-high-fast", "probá esto") == [
        "cursor-agent",
        "-p",
        "--output-format",
        "text",
        "-m",
        "grok-4.7-high-fast",
        "--force",
        "--trust",
        "--workspace",
        str(LAB),
        "probá esto",
    ]
    assert "--effort" not in cursor_argv(LAB, "grok-4.7-high-fast", "probá esto")
    assert "--approve-mcps" not in cursor_argv(LAB, "grok-4.7-high-fast", "probá esto")


def test_opencode_argv_is_run_with_model_and_cwd_outside():
    assert opencode_argv("flash", "probá esto") == ["opencode", "run", "-m", "flash", "probá esto"]


class Boom:
    def grok_remaining(self) -> float:
        raise RuntimeError("sin cuota")


class Remaining:
    def __init__(self, value: float):
        self.value = value

    def grok_remaining(self) -> float:
        return self.value


@pytest.mark.parametrize(
    ("reader", "expected"),
    (
        (Remaining(0.40), CURSOR),
        (Remaining(0.0), CURSOR),
        (Remaining(0.41), POLICY),
        (Remaining(1.0), POLICY),
        (Boom(), POLICY),
    ),
)
def test_quota_switches_to_cursor_at_forty_percent(reader, expected):
    assert choose_cli(reader, POLICY) == expected


def test_file_reader_uses_the_json_field(tmp_path):
    path = tmp_path / "quota.json"
    path.write_text(json.dumps({"grok_remaining": 0.25}), encoding="utf-8")
    assert FileQuotaReader(path).grok_remaining() == 0.25
    assert choose_cli(FileQuotaReader(path), POLICY) == CURSOR
