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
    return SidecarSession(SIDECAR, workdir=tmp_path / "main", model="composer-2.5", key_file=tmp_path / "key", env=dict(__import__("os").environ), **kw)


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
    assert isinstance(session.primary, (SidecarSession, ServeSidecarSession))
    assert isinstance(session.secondary, GrokAcp)


def test_select_low_grok_quota_falls_back_to_cursor_agent(tmp_path):
    session = _select(tmp_path, quota=0.40)()
    assert isinstance(session.secondary, RelaunchSession)
    assert "grok-4.7-high-fast" in session.secondary.argv_for("x")
    direct = _select(tmp_path, cli="grok", quota=0.30)()
    assert isinstance(direct, RelaunchSession)


def test_select_without_sidecar_uses_grok_or_cursor_agent(tmp_path):
    assert isinstance(_select(tmp_path, launcher=tmp_path / "no-hay")(), GrokAcp)
    assert isinstance(_select(tmp_path, cli="grok", quota=RuntimeError("sin dato"))(), RelaunchSession), "sin dato: cursor-agent"
    no_reader = select_main_session(CodeModeConfig(main_enabled=True, main_cli="grok"), cwd=tmp_path, sidecar=None, key_file=None, quota=None)()
    assert isinstance(no_reader, RelaunchSession), "sin lector de cuota: no se asume grok disponible"
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


# --- MAIN por el sidecar en modo --serve (un proceso y un agente por job) ----------------------
from universal_bot.code_mode.main_brains import ServeSidecarSession  # noqa: E402

SERVE = FAKES / "fake_sidecar_serve.py"


def _serve(tmp_path, monkeypatch, mode="ok", **kw):
    monkeypatch.setenv("FAKE_SIDECAR", mode)
    monkeypatch.setenv("FAKE_SIDECAR_LOG", str(tmp_path / "serve.log"))
    return ServeSidecarSession(SERVE, workdir=tmp_path / "main", model="composer-2.5", key_file=tmp_path / "key",
                               env=dict(__import__("os").environ), **kw)


def _runs(tmp_path):
    return [e for e in _lines(tmp_path / "serve.log") if e["msg"].get("op", "run") == "run"]


def test_serve_main_reuses_one_process_and_one_agent_with_the_optimized_config(tmp_path, monkeypatch):
    session = _serve(tmp_path, monkeypatch)
    session.start()
    try:
        first = session.prompt("hola MAIN", timeout_s=10)
        second = session.prompt("¿cómo vas?", timeout_s=10)
    finally:
        session.close()
    assert first.ok and first.text.startswith("Respuesta a: hola MAIN")
    assert second.ok and second.mode == "sidecar-serve"
    runs = _runs(tmp_path)
    assert len({e["pid"] for e in runs}) == 1, "un solo proceso"
    assert runs[0]["argv"] == ["--serve", "--key-file", str(tmp_path / "key")]
    assert runs[0]["msg"]["session_id"] == runs[1]["msg"]["session_id"], "un agente por job"
    req = runs[0]["msg"]
    assert req["setting_sources"] == [] and req["mcp"] is False and req["tools"] == ["read"]
    assert req["model"] == "composer-2.5"
    assert runs[1]["msg"]["prompt"] == "¿cómo vas?", "el agente guarda la charla: no se re-manda la historia"
    assert "key" not in json.dumps(req)


def test_serve_main_steer_is_live_and_cancel_does_not_fall_back(tmp_path, monkeypatch):
    session = _serve(tmp_path, monkeypatch)
    session.start()
    try:
        thread, box = _in_thread(lambda: session.prompt("LONG arrancá", timeout_s=10))
        _wait_running(session)
        time.sleep(0.1)
        assert session.steer("pará") == "live"
        thread.join(5)
        assert box["result"].ok and "steered:pará" in box["result"].text
        assert box["result"].steered == "live"
        thread, box = _in_thread(lambda: session.prompt("LONG otra", timeout_s=10))
        _wait_running(session)
        time.sleep(0.1)
        session.cancel()
        thread.join(5)
        assert box["result"].status == "cancelled" and session.last_fallback is False
        assert session.steer("nada") == "no_turn"
    finally:
        session.close()


def test_serve_main_usage_limit_falls_back_and_crash_restarts_with_history(tmp_path, monkeypatch):
    limited = _serve(tmp_path, monkeypatch, mode="rate")
    limited.start()
    result = limited.prompt("hola", timeout_s=10)
    limited.close()
    assert not result.ok and result.error == "USAGE_LIMIT" and limited.last_fallback is True

    (tmp_path / "serve.log").unlink()
    session = _serve(tmp_path, monkeypatch, mode="ok")
    session.start()
    try:
        assert session.prompt("primero", timeout_s=10).ok
        first_pid = session._proc.pid
        session._proc.kill()  # el proceso murió entre turnos
        session._proc.wait(timeout=5)
        again = session.prompt("segundo", timeout_s=10)
        assert session._proc.pid != first_pid
    finally:
        session.close()
    assert again.ok
    runs = _runs(tmp_path)
    assert "primero" in runs[-1]["msg"]["prompt"], "agente nuevo: la historia viaja en el prompt"


def test_serve_main_close_ends_the_process(tmp_path, monkeypatch):
    session = _serve(tmp_path, monkeypatch)
    session.start()
    assert session.prompt("hola", timeout_s=10).ok
    proc = session._proc
    session.close()
    assert proc.wait(timeout=5) is not None


def test_select_uses_the_serve_sidecar_by_default(tmp_path):
    session = _select(tmp_path)()
    assert isinstance(session.primary, ServeSidecarSession)
    one_shot = select_main_session(CodeModeConfig(main_enabled=True, main_sdk_serve=False), cwd=tmp_path, sidecar=SIDECAR,
                                   key_file=None, quota=Quota(0.9))()
    assert isinstance(one_shot.primary, SidecarSession) and not isinstance(one_shot.primary, ServeSidecarSession)
