"""Spike: MAIN de agy manejando la TUI interactiva por tmux (el MAIN queda libre mientras delega)."""

import shutil
import sys
import time
from pathlib import Path

import pytest

from universal_bot.code_mode.agy_tui import AgyTuiSession, agy_tui_argv

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="sin tmux")
FAKE = Path(__file__).parent / "fakes" / "fake_agy_tui.py"


@pytest.fixture()
def session(tmp_path):
    s = AgyTuiSession([sys.executable, str(FAKE)], cwd=tmp_path, settle_s=0.4)
    s.start()
    yield s
    s.close()


def _wait_for(session, needle, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if needle in session.screen():
            return True
        time.sleep(0.1)
    return False


def test_argv_runs_the_interactive_tui_without_stream_json():
    argv = agy_tui_argv("gemini-3.8-flash-medium")
    assert argv[0] == "agy" and "--model" in argv and "gemini-3.8-flash-medium" in argv
    assert "-p" not in argv and "stream-json" not in " ".join(argv)


def test_prompt_returns_the_reply_once_the_tui_is_back_at_the_prompt(session):
    result = session.prompt("hola MAIN", timeout_s=10)
    assert result.ok and result.text == "Respuesta a: hola MAIN"
    second = session.prompt("otra", timeout_s=10)
    assert second.text == "Respuesta a: otra", "solo lo nuevo de este turno"


def test_main_stays_free_while_the_subagent_runs_and_steer_reaches_it(session):
    started = time.monotonic()
    result = session.prompt("LONG contá hasta 200", timeout_s=10)
    assert result.ok and "Spawned 1 subagent" in result.text
    assert time.monotonic() - started < 2.5, "el MAIN no espera al subagente"
    assert session.steer("pará en 20") == "live"
    assert _wait_for(session, "Messaged 1 subagent: pará en 20")
    assert _wait_for(session, "steered:pará en 20")


def test_close_kills_the_tmux_session(tmp_path):
    s = AgyTuiSession([sys.executable, str(FAKE)], cwd=tmp_path, settle_s=0.4)
    s.start()
    assert s.alive()
    s.close()
    assert not s.alive()
