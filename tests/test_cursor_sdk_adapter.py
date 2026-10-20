"""Adaptador cursor-sdk: request, invocación del sidecar, fallback a cursor-agent y key redactada."""

import json
import stat
import sys
from pathlib import Path

import pytest

from universal_bot.code_mode.cursor_sdk import (
    CursorSdkAdapter,
    SdkOutcome,
    run_with_fallback,
    sdk_request,
    sidecar_argv,
    sidecar_env,
)

FAKE_KEY = "crsr_FAKE_python_0123456789abcdefghijklmnop"


def fake_sidecar(tmp_path: Path, lines: list[dict], *, exit_code: int = 0, stderr: str = "", sleep_s: float = 0.0) -> Path:
    script = tmp_path / "fake-sidecar"
    body = "\n".join(json.dumps(line) for line in lines)
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys, time, json\n"
        "request = json.loads(sys.stdin.read())\n"
        "open(sys.argv[0] + '.request.json', 'w').write(json.dumps({'request': request, 'argv': sys.argv[1:]}))\n"
        f"time.sleep({sleep_s})\n"
        f"sys.stderr.write({stderr!r})\n"
        f"sys.stdout.write({body!r} + '\\n')\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def seen(script: Path) -> dict:
    return json.loads(Path(str(script) + ".request.json").read_text())


OK_LINE = {
    "type": "result", "ok": True, "text": "OK", "duration_ms": 3666, "run_id": "run-1",
    "usage": {"inputTokens": 10, "outputTokens": 2, "cacheReadTokens": 4, "totalTokens": 16},
}


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({}, {"prompt": "hola", "model": "composer-2.5", "cwd": "/w", "timeout_s": 120, "stream": False}),
        ({"model": "composer-2.5-fast", "timeout_s": 30}, {"prompt": "hola", "model": "composer-2.5-fast", "cwd": "/w", "timeout_s": 30, "stream": False}),
        ({"system": "sos breve"}, {"prompt": "hola", "model": "composer-2.5", "cwd": "/w", "timeout_s": 120, "stream": False, "system": "sos breve"}),
        ({"steer_file": "steer.jsonl", "stream": True}, {"prompt": "hola", "model": "composer-2.5", "cwd": "/w", "timeout_s": 120, "stream": True, "steer_file": "steer.jsonl"}),
    ],
)
def test_sdk_request_is_the_contract(kwargs, expected):
    assert sdk_request("hola", cwd="/w", **kwargs) == expected


def test_argv_passes_the_key_file_and_never_the_key(tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text(FAKE_KEY)
    argv = sidecar_argv("/opt/sidecar/bin/cursor-sdk-sidecar", key_file)
    assert argv == ["/opt/sidecar/bin/cursor-sdk-sidecar", "--key-file", str(key_file)]
    assert FAKE_KEY not in " ".join(argv)


@pytest.mark.parametrize(
    "node_bin,expected",
    [("/opt/node24/bin/node", {"PATH": "/usr/bin", "HOME": "/h", "CURSOR_SDK_NODE": "/opt/node24/bin/node"}),
     (None, {"PATH": "/usr/bin", "HOME": "/h"})],
)
def test_env_is_minimal_and_drops_secrets(node_bin, expected):
    source = {"PATH": "/usr/bin", "HOME": "/h", "CURSOR_API_KEY": FAKE_KEY, "GITHUB_TOKEN": "x", "OTHER": "y"}
    assert sidecar_env(source, node_bin=node_bin) == expected


def test_ok_parses_the_result(tmp_path):
    script = fake_sidecar(tmp_path, [OK_LINE])
    outcome = CursorSdkAdapter(script, key_file=None).run("hola", cwd=str(tmp_path))
    assert outcome == SdkOutcome(ok=True, text="OK", code=None, fallback=False, usage=OK_LINE["usage"], run_id="run-1", duration_ms=3666, events=())
    assert seen(script)["request"]["prompt"] == "hola"


def test_stream_events_are_kept(tmp_path):
    event = {"type": "event", "event": "status", "data": {}}
    steer = {"type": "steer", "ok": True, "outcome": "complete_delivered", "text_len": 3}
    script = fake_sidecar(tmp_path, [event, steer, OK_LINE])
    outcome = CursorSdkAdapter(script, key_file=None).run("hola", cwd=str(tmp_path), stream=True)
    assert outcome.events == (event, steer)


@pytest.mark.parametrize(
    "line,exit_code,code,fallback",
    [
        ({"type": "error", "ok": False, "code": "NO_KEY", "fallback": True}, 3, "NO_KEY", True),
        ({"type": "error", "ok": False, "code": "USAGE_LIMIT", "fallback": True}, 8, "USAGE_LIMIT", True),
        ({"type": "error", "ok": False, "code": "BAD_REQUEST", "fallback": False}, 2, "BAD_REQUEST", False),
        ({"type": "error", "ok": False, "code": "CANCELLED", "fallback": False}, 10, "CANCELLED", False),
    ],
)
def test_errors_keep_code_and_fallback(tmp_path, line, exit_code, code, fallback):
    script = fake_sidecar(tmp_path, [line], exit_code=exit_code)
    outcome = CursorSdkAdapter(script, key_file=None).run("hola", cwd=str(tmp_path))
    assert (outcome.ok, outcome.code, outcome.fallback) == (False, code, fallback)


def test_garbage_output_is_a_fallback_sdk_error(tmp_path):
    script = tmp_path / "broken"
    script.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.write('no json')\nsys.exit(1)\n")
    script.chmod(0o755)
    outcome = CursorSdkAdapter(script, key_file=None).run("hola", cwd=str(tmp_path))
    assert (outcome.ok, outcome.code, outcome.fallback) == (False, "SDK_ERROR", True)


def test_missing_sidecar_is_a_fallback(tmp_path):
    outcome = CursorSdkAdapter(tmp_path / "nope", key_file=None).run("hola", cwd=str(tmp_path))
    assert (outcome.ok, outcome.code, outcome.fallback) == (False, "SDK_MISSING", True)


def test_hard_timeout_kills_a_hung_sidecar(tmp_path):
    script = fake_sidecar(tmp_path, [OK_LINE], sleep_s=5)
    outcome = CursorSdkAdapter(script, key_file=None, grace_s=0.2).run("hola", cwd=str(tmp_path), timeout_s=0.3)
    assert (outcome.ok, outcome.code, outcome.fallback) == (False, "TIMEOUT", True)


def test_key_never_reaches_the_outcome_even_if_the_sidecar_leaks_it(tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text(FAKE_KEY + "\n")
    line = {"type": "error", "ok": False, "code": "SDK_ERROR", "fallback": True, "message": f"boom {FAKE_KEY}"}
    script = fake_sidecar(tmp_path, [line], exit_code=9, stderr=f"leak {FAKE_KEY}\n")
    outcome = CursorSdkAdapter(script, key_file=key_file).run("hola", cwd=str(tmp_path))
    assert FAKE_KEY not in repr(outcome)
    assert "<redacted>" in outcome.message


def test_steer_appends_one_json_line(tmp_path):
    adapter = CursorSdkAdapter(tmp_path / "x", key_file=None)
    inbox = tmp_path / "steer.jsonl"
    adapter.steer(inbox, "cambiá a B")
    adapter.steer(inbox, "y C")
    assert [json.loads(l) for l in inbox.read_text().splitlines()] == [{"text": "cambiá a B"}, {"text": "y C"}]


class FakeSdk:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = 0

    def run(self, prompt, **kwargs):
        self.calls += 1
        return self.outcome


def fake_agent(calls):
    def run(prompt, **kwargs):
        calls.append(prompt)
        return "respuesta de cursor-agent"
    return run


def outcome(ok, code=None, fallback=False, text=""):
    return SdkOutcome(ok=ok, text=text, code=code, fallback=fallback, usage=None, run_id=None, duration_ms=None, events=())


@pytest.mark.parametrize(
    "sdk_outcome,expected_cli,expected_text,agent_calls",
    [
        (outcome(True, text="OK"), "cursor-sdk", "OK", 0),
        (outcome(False, "NO_KEY", True), "cursor-agent", "respuesta de cursor-agent", 1),
        (outcome(False, "USAGE_LIMIT", True), "cursor-agent", "respuesta de cursor-agent", 1),
        (outcome(False, "BAD_REQUEST", False), "cursor-sdk", "", 0),
    ],
)
def test_run_with_fallback(sdk_outcome, expected_cli, expected_text, agent_calls):
    calls = []
    result = run_with_fallback(FakeSdk(sdk_outcome), fake_agent(calls), "hola", cwd="/w")
    assert (result.cli, result.text, len(calls)) == (expected_cli, expected_text, agent_calls)


def test_without_sdk_adapter_goes_straight_to_cursor_agent():
    calls = []
    result = run_with_fallback(None, fake_agent(calls), "hola", cwd="/w")
    assert (result.cli, len(calls)) == ("cursor-agent", 1)
