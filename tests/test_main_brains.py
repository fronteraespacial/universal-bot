"""MAIN con cursor-sdk primero (steer_file/cancel_file), fallback a grok warm y camino cursor-agent (matar y relanzar)."""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.main_brains import FallbackSession, RelaunchSession, SidecarSession, select_main_session
from universal_bot.code_mode.orchestrator import WarmBrain
from universal_bot.code_mode.warm import GrokAcp

FAKES = Path(__file__).parent / "fakes"
SIDECAR = FAKES / "fake_sidecar.py"
AGENT = FAKES / "fake_cursor_agent.py"


def _lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def _sidecar(tmp_path, monkeypatch, mode="ok", **kw):
    monkeypatch.setenv("FAKE_SIDECAR", mode)
    monkeypatch.setenv("FAKE_SIDECAR_LOG", str(tmp_path / "sidecar.log"))
    return SidecarSession(SIDECAR, workdir=tmp_path / "main", model="composer-2.5", key_file=tmp_path / "key", **kw)


def _in_thread(fn):
    box = {}
    thread = threading.Thread(target=lambda: box.update(result=fn()), daemon=True)
    thread.start()
    return thread, box


def _wait_running(session):
    for _ in range(100):
        if session.busy():
            return
        time.sleep(0.02)
    raise AssertionError("el turno no arrancó")


def test_sidecar_turn_sends_steer_and_cancel_files_and_keeps_history(tmp_path, monkeypatch):
    session = _sidecar(tmp_path, monkeypatch)
    session.start()
    first = session.prompt("hola MAIN", timeout_s=10)
    assert first.ok and first.text.startswith("Respuesta a: hola MAIN")
    second = session.prompt("¿cómo vas?", timeout_s=10)
    assert second.ok
    requests = [entry["request"] for entry in _lines(tmp_path / "sidecar.log")]
    assert requests[0]["model"] == "composer-2.5"
    assert requests[0]["steer_file"] and requests[0]["cancel_file"]
    assert requests[0]["steer_file"] != requests[1]["steer_file"], "bandeja nueva por turno"
    assert "hola MAIN" in requests[1]["prompt"] and "Respuesta a: hola MAIN" in requests[1]["prompt"], "historia en el prompt"
    argv = _lines(tmp_path / "sidecar.log")[0]["argv"]
    assert argv == ["--key-file", str(tmp_path / "key")], "la key va por archivo, nunca en el request"
    assert "key" not in json.dumps(requests[0]).replace("steer_file", "").replace("cancel_file", "")


def test_sidecar_steer_is_live_while_a_turn_runs(tmp_path, monkeypatch):
    session = _sidecar(tmp_path, monkeypatch, mode="slow")
    session.start()
    assert session.steer("antes") == "no_turn"
    thread, box = _in_thread(lambda: session.prompt("trabajá", timeout_s=10))
    _wait_running(session)
    assert session.steer("solo 3 videos") == "live"
    thread.join(10)
    assert box["result"].ok and "steered:solo 3 videos" in box["result"].text
    assert box["result"].steered == "live"


def test_sidecar_cancel_file_stops_the_turn(tmp_path, monkeypatch):
    session = _sidecar(tmp_path, monkeypatch, mode="slow")
    session.start()
    thread, box = _in_thread(lambda: session.prompt("trabajá", timeout_s=10))
    _wait_running(session)
    session.cancel()
    thread.join(10)
    assert box["result"].ok is False and box["result"].status == "cancelled"


def test_sidecar_usage_limit_is_reported_as_fallback(tmp_path, monkeypatch):
    session = _sidecar(tmp_path, monkeypatch, mode="rate")
    session.start()
    result = session.prompt("hola", timeout_s=10)
    assert result.ok is False and result.error == "USAGE_LIMIT"
    assert session.last_fallback is True


def _agent(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CA_LOG", str(tmp_path / "agent.log"))
    return RelaunchSession(lambda prompt: [sys.executable, str(AGENT), "--model", "grok-4.7-high-fast", prompt], cwd=tmp_path)


def test_cursor_agent_main_relaunches_on_steer(tmp_path, monkeypatch):
    session = _agent(tmp_path, monkeypatch)
    session.start()
    assert session.steer("nada") == "no_turn"
    thread, box = _in_thread(lambda: session.prompt("LONG pensá", timeout_s=20))
    _wait_running(session)
    started = time.monotonic()
    assert session.steer("frená y contame") == "relaunch"
    thread.join(20)
    assert time.monotonic() - started < 4, "corta al toque, no espera el turno largo"
    result = box["result"]
    assert result.ok and result.text.startswith("Respuesta a: frená y contame")
    assert result.steered == "relaunch"
    prompts = [entry["prompt"] for entry in _lines(tmp_path / "agent.log")]
    assert len(prompts) == 2 and "LONG pensá" in prompts[1] and prompts[1].endswith("frená y contame")
    assert _lines(tmp_path / "agent.log")[0]["argv"][-2:] == ["--model", "grok-4.7-high-fast"]


def test_fallback_session_switches_and_sticks(tmp_path, monkeypatch):
    primary = _sidecar(tmp_path, monkeypatch, mode="rate")
    secondary = _agent(tmp_path, monkeypatch)
    session = FallbackSession(primary, secondary)
    session.start()
    one = session.prompt("hola", timeout_s=10)
    assert one.ok and one.text.startswith("Respuesta a: hola")
    assert session.active is secondary and session.events == ["fallback:USAGE_LIMIT"]
    session.prompt("otra", timeout_s=10)
    assert len(_lines(tmp_path / "sidecar.log")) == 1, "una vez caído, no vuelve a probar el sidecar"


def test_fallback_session_does_not_fall_back_on_cancel(tmp_path, monkeypatch):
    primary = _sidecar(tmp_path, monkeypatch, mode="slow")
    secondary = _agent(tmp_path, monkeypatch)
    session = FallbackSession(primary, secondary)
    session.start()
    thread, box = _in_thread(lambda: session.prompt("trabajá", timeout_s=10))
    _wait_running(primary)
    session.cancel()
    thread.join(10)
    assert box["result"].status == "cancelled"
    assert not (tmp_path / "agent.log").exists()


class Quota:
    def __init__(self, value):
        self.value = value

    def grok_remaining(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def _select(tmp_path, cli="auto", quota=0.42, launcher=SIDECAR):
    config = CodeModeConfig(main_enabled=True, main_cli=cli)
    return select_main_session(config, cwd=tmp_path, sidecar=launcher, key_file=None, quota=Quota(quota))


def test_select_prefers_cursor_sdk_with_grok_warm_fallback(tmp_path):
    session = _select(tmp_path)()
    assert isinstance(session, FallbackSession)
    assert isinstance(session.primary, SidecarSession)
    assert isinstance(session.secondary, GrokAcp)


def test_select_low_grok_quota_falls_back_to_cursor_agent(tmp_path):
    session = _select(tmp_path, quota=0.40)()
    assert isinstance(session.secondary, RelaunchSession)
    assert "grok-4.7-high-fast" in session.secondary.argv_for("x")
    direct = _select(tmp_path, cli="grok", quota=0.30)()
    assert isinstance(direct, RelaunchSession)


def test_select_without_sidecar_uses_grok_or_cursor_agent(tmp_path):
    assert isinstance(_select(tmp_path, launcher=tmp_path / "no-hay")(), GrokAcp)
    assert isinstance(_select(tmp_path, cli="grok", quota=RuntimeError("sin dato"))(), GrokAcp)
    assert isinstance(_select(tmp_path, cli="cursor-agent")(), RelaunchSession)


def test_warm_brain_steers_the_sidecar_main_live(tmp_path, monkeypatch):
    brain = WarmBrain(lambda: _sidecar(tmp_path, monkeypatch, mode="slow"), timeout_s=10)
    brain.submit("job-1", "arrancá")
    time.sleep(0.3)
    brain.submit("job-1", "¿cómo vas?")
    replies = []
    for _ in range(100):
        replies += brain.drain()
        if replies:
            break
        time.sleep(0.05)
    brain.close()
    assert brain.steered == 1
    assert "steered:¿cómo vas?" in replies[0][1]
